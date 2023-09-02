#! /usr/bin/env python3

# Moves walls and notes by configured amount

from pathlib import Path
import synth_mapping_helper

# CONFIG

offset = [0, 1, 1/16]  # move everything up by one square and back by 1/16 of a beat
# if you want to offset by time in seconds (eg. 250ms), you can use: 0.25/60*bpm

# looks for a "my_map.synth" exists in the current working directory
in_file = Path("my_map.synth").absolute()  # make absolute to show what the above means
out_file = Path("my_map_offset.synth").absolute()

# END OF CONFIG

# load file
print(f"Loading {in_file}")
f = synth_mapping_helper.synth_format.import_file(in_file)

# loop over all difficulty levels
for diff_name, data in f.difficulties:
    # apply offset to every wall, note and rail
    data.apply_for_all(synth_mapping_helper.movement.offset, offset)

# save to output file
f.save_as(out_file)
print(f"Saved output to {out_file}")