#! /usr/bin/env python3

# Author: adosikas
#
# Align everything in a map to a fixed divisor, ie 1/64 or 1/48

from pathlib import Path
import numpy as np
import synth_mapping_helper

# CONFIG

divisor = 64  # align everything to 1/64th. Must be a divisor of either 64 or 48

# looks for a "my_map.synth" exists in the current working directory
in_file = Path("my_map.synth")  # this can be None to take a command line argument instead
save_suffix = "_offset"  # output is saved as my_map_offset.synth

# END OF CONFIG

if 64 % divisor and 48 % divisor:
    raise ValueError("Divisor must be a divisor of either 64 or 48, as that is the rounding during final output")

def _round_strict(nodes: "numpy array (n, 3)", direction: int = 1) -> "numpy array (n, 3)":
    out = nodes.copy()  # as we edit the array, we should make a copy first
    out[:,2] = np.round(out[:,2]*divisor) / divisor
    return out

with synth_format.file_data(in_file, save_suffix=save_suffix) as f:
    # loop over all difficulty levels
    for diff_name, data in f.difficulties.items():
        # apply rounding to every wall, note and rail
        data.apply_for_all(_round_strict, offset)
