#! /usr/bin/env python3

# rescale the whole map to a new BPM
# do this BEFORE changing the BPM in the file, which has to be done manually

# note: this snaps everything to the closest 1/192. Use with caution.

from pathlib import Path
import synth_mapping_helper

# CONFIG

new_bpm = 120
# looks for a "my_map.synth" exists in the current working directory
in_file = Path("my_map.synth").absolute()  # make absolute to show what the above means
out_file = Path("my_map_fixed.synth").absolute()

# END OF CONFIG

# load file
f = synth_mapping_helper.synth_format.import_file(in_file)

# loop over all difficulty levels
for diff in f.difficulties:
	# apply time scaling to every wall, note and rail
	f.difficulties[diff].apply_for_all(synth_mapping_helper.movement.scale, [1,1,new_bpm/data.bpm])
# save to output file
f.save_as(out_file)

print(f"Saved output to {out_file}")