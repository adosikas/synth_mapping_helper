#! /usr/bin/env python3

# Author: adosikas
# Idea: Little Asi
#
# Shifts pattern in clipboard left and right based on a sine wave
# Note: Interpolate rails fist

import numpy as np
from synth_mapping_helper import synth_format, movement

amplitude = 4  # in squares. Note that this is both left and right of the center, ie distance between left and right is double this.
cycle = 2  # in beats, for a full cycle
phase_offset = 0  # 0 or 180: start in center, go in right or left first, +/-90: start at right(+) or left(-), move across center first

data = synth_format.import_clipboard()

def _shift_sine(nodes: "numpy array (n, 3+)", direction: int = 1) -> "numpy array (n, 3+)":
    amplitide_array = np.sin(np.radians(nodes[:,2]*360/cycle) + phase_offset) * amplitude
    out = nodes.copy()
    out[:,0] += amplitide_array  # add to X axis
    return out

data.apply_for_all(_shift_sine)  # apply for all notes and walls

synth_format.export_clipboard(data)
