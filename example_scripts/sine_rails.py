#! /usr/bin/env python3

# Author: adosikas
#
# Makes zigzag rails where the amplitude is controlled by a sine wave

import numpy as np
from synth_mapping_helper import synth_format, movement, rails, pattern_generation

max_amplitude = 2  # in squares. Note that this is both left and right of the center, ie distance between left and right is double this.
angle = 0  # in degrees, where 0 is right, and 90 is up
peak_count = 1  # number of peaks in the amplitude
interval = 1/64  # in beats

data = synth_format.import_clipboard()

def _rail_sines(nodes: "numpy array (n, 3+)", direction: int = 1) -> "numpy array (n, 3+)":
    if nodes.shape[0] == 1:
        return nodes
    l = nodes[-1,2] - nodes[0,2]
    interp_nodes = rails.interpolate_nodes(nodes, "spline", interval, direction=direction)
    offsets = (
        # pattern_generation.angle_to_xy((interp_nodes[:,2]-interp_nodes[0,2])/l*270)  # rotating zigzag
        pattern_generation.angle_to_xy([angle for _ in interp_nodes])  # basic zigzag
        * np.sin(np.radians((interp_nodes[:,2]-interp_nodes[0,2])/l*180*peak_count))[...,np.newaxis]
        * max_amplitude
    )

    interp_nodes[::2,:2] += offsets[::2]  # add to XY axis (positive for 0,2,4...)
    interp_nodes[1::2,:2] -= offsets[1::2]  # add to XY axis (negative for 1,3,5,...)
    return interp_nodes

data.apply_for_notes(_rail_sines)  # apply for all notes/rails

synth_format.export_clipboard(data)