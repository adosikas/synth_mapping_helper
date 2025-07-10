#! /usr/bin/env python3

# Author: adosikas
#
# Offset everything in a map by configured amount

from pathlib import Path
from synth_mapping_helper import synth_format, movement

# CONFIG

offset = [0, 1, 1/16]  # move everything up by one square and back by 1/16 of a beat
# if you want to offset by time in seconds (eg. 250ms), you can use: 0.25/60*bpm

# looks for a "my_map.synth" exists in the current working directory
in_file = Path("my_map.synth")  # this can be None to take a command line argument instead
save_suffix = "_offset"  # output is saved as my_map_offset.synth

# END OF CONFIG

# load file
with synth_format.file_data(in_file, save_suffix=save_suffix) as f:
    # loop over all difficulty levels
    for diff_name, data in f.difficulties.items():
        # apply offset to every wall, note and rail
        data.apply_for_all(movement.offset, offset)

