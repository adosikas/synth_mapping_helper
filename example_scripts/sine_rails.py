#! /usr/bin/env python3

# Author: adosikas
#
# Makes zigzag rails where the amplitude is controlled by a sine wave

import numpy as np
from synth_mapping_helper import synth_format, movement, rails, pattern_generation

max_amplitude = 2  # in squares. Note that this is both left and right of the center, ie distance between left and right is double this.
angle = 0  # in degrees, where 0 is right, and 90 is up

peak_count = 1  # number of "full" peaks in the amplitude, for every rail. This corresponds to 180 degrees of the sine wave
phase_offset = 0  # start of the sine in degrees, where 0 and 180 start at the center, 90 and 270 start at the max amplitude
# some examples:
#   peak_count=1 and phase_offset=0  results in eye shaped rails (default)
#   peak_count=2 and phase_offset=0  results in "double eye" shaped rails (full 360 degrees of sine wave)
#   peak_count=1 and phase_offset=90 results in hourglass shapes

interval = 1/64  # in beats

def _rail_sines(nodes: "numpy array (n, 3+)", direction: int = 1) -> "numpy array (n, 3+)":
    if nodes.shape[0] == 1:
        return nodes
    l = nodes[-1,2] - nodes[0,2]
    interp_nodes = rails.interpolate_nodes(nodes, "spline", interval, direction=direction)
    offsets = (
        # pattern_generation.angle_to_xy((interp_nodes[:,2]-interp_nodes[0,2])/l*270)  # rotating zigzag
        pattern_generation.angle_to_xy([angle for _ in interp_nodes])  # basic zigzag
        * np.sin(np.radians((interp_nodes[:,2]-interp_nodes[0,2])/l*180*peak_count+phase_offset))[...,np.newaxis]
        * max_amplitude
    )

    interp_nodes[::2,:2] += offsets[::2]  # add to XY axis (positive for 0,2,4...)
    interp_nodes[1::2,:2] -= offsets[1::2]  # add to XY axis (negative for 1,3,5,...)
    return interp_nodes

with synth_format.clipboard_data() as data:
    data.apply_for_notes(_rail_sines)  # apply for all notes/rails
