#! /usr/bin/env python3

# Author: adosikas
#
# Spiral existing pattern in clipboard
# Note: Interpolate rails fist

import numpy as np
from synth_mapping_helper import synth_format, movement

cycle = 3  # in beats, for a full cycle. Can be negative to reverse direction

def _do_spiral(nodes: "numpy array (n, 3+)", direction: int = 1) -> "numpy array (n, 3+)":
    return np.concatenate([
        # for every rail node, determine angle based on time, and rotate position by that
        movement.rotate(np.array([n]), n[2]*360/cycle)
        for n in nodes
    ])

with synth_format.clipboard_data() as data:
    data.apply_for_all(_do_spiral)  # apply for all notes and walls