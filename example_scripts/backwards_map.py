#! /usr/bin/env python3

# Author: adosikas
#
# Creates a "backwards" copy of a difficulty with helper walls to guide players

from pathlib import Path

import numpy as np
from synth_mapping_helper import synth_format, utils, movement, rails

# CONFIG

wall_offset_s = 0.3  # time that walls appear ahead of the note
source_difficulty = "Normal"  # difficulty to copy

rail_interpolation = 1/4  # distance between marker walls on rails
finalize = True  # finalize walls such that they appear in game as in the editor (for all difficulties)

turn_around_s = 3.0  # add "TURN AROUND" text at this second. Can be None to disable
# "TURN AROUND" in wall art letters
turn_around_json = """
{"BPM":67.5,"startMeasure":144.0,"startTime":2000.0,"lenght":666.666748,"notes":{},"effects":[],"jumps":[],"crouchs":[],"squares":[{"time":168.0,"position":[0.00199997425,3.0042,46.6666641],"zRotation":45.0,"initialized":true}],"triangles":[],"slides":[{"time":160.0,"slideType":2,"position":[-5.185,2.8677,44.4444427],"zRotation":352.5,"initialized":true},{"time":161.0,"slideType":3,"position":[-5.458,2.5947,44.72222],"zRotation":270.0,"initialized":true},{"time":162.0,"slideType":4,"position":[-5.735,2.8677,45.0],"zRotation":7.5,"initialized":true},{"time":164.0,"slideType":3,"position":[-3.4105,2.8677,45.5555573],"zRotation":0.0,"initialized":true},{"time":165.0,"slideType":1,"position":[-2.182,3.6867,45.8333359],"zRotation":270.0,"initialized":true},{"time":166.0,"slideType":4,"position":[-2.3185,2.5947,46.1111145],"zRotation":82.5,"initialized":true},{"time":172.0,"slideType":1,"position":[3.278,2.0487,47.77778],"zRotation":270.0,"initialized":true},{"time":173.0,"slideType":4,"position":[2.186,2.8677,48.0555573],"zRotation":37.5,"initialized":true},{"time":174.0,"slideType":2,"position":[3.278,2.8677,48.3333359],"zRotation":322.5,"initialized":true},{"time":176.0,"slideType":3,"position":[4.643,2.7312,48.8888855],"zRotation":0.0,"initialized":true},{"time":177.0,"slideType":4,"position":[6.827,2.8677,49.1666641],"zRotation":37.5,"initialized":true},{"time":178.0,"slideType":2,"position":[5.3255,2.7312,49.4444427],"zRotation":7.5,"initialized":true},{"time":180.0,"slideType":3,"position":[7.373,2.8677,50.0],"zRotation":0.0,"initialized":true},{"time":181.0,"slideType":2,"position":[7.915,2.4582,50.27778],"zRotation":270.0,"initialized":true},{"time":182.0,"slideType":4,"position":[8.5975,3.5502,50.5555573],"zRotation":270.0,"initialized":true},{"time":144.0,"slideType":3,"position":[-6.823,7.9182,40.0],"zRotation":270.0,"initialized":true},{"time":145.0,"slideType":3,"position":[-6.825,6.825,40.27778],"zRotation":0.0,"initialized":true},{"time":148.0,"slideType":1,"position":[-3.547,6.1437,41.1111145],"zRotation":270.0,"initialized":true},{"time":149.0,"slideType":4,"position":[-4.639,6.9627,41.3888855],"zRotation":37.5,"initialized":true},{"time":150.0,"slideType":2,"position":[-3.547,6.9627,41.6666641],"zRotation":322.5,"initialized":true},{"time":152.0,"slideType":3,"position":[-2.0455,6.9627,42.22222],"zRotation":0.0,"initialized":true},{"time":153.0,"slideType":1,"position":[-0.817,7.7817,42.5],"zRotation":270.0,"initialized":true},{"time":154.0,"slideType":4,"position":[-0.953500032,6.6897,42.77778],"zRotation":82.5,"initialized":true},{"time":156.0,"slideType":3,"position":[0.548,6.8262,43.3333359],"zRotation":0.0,"initialized":true},{"time":157.0,"slideType":4,"position":[2.732,6.9627,43.6111145],"zRotation":37.5,"initialized":true},{"time":158.0,"slideType":2,"position":[1.2305,6.8262,43.8888855],"zRotation":7.5,"initialized":true}],"lights":[]}
"""

# looks for a "my_map.synth" exists in the current working directory
in_file = None  # this can be None to take a command line argument instead
save_suffix = "_backwards"  # output is saved as my_map_backwards.synth. Can be an empty string to overwrite input file.

# you could edit this to 
marker_templates = {
    "left": np.array([[ 7.5, -6.8, 0.0, synth_format.WALL_TYPES["angle_right"][0], 0.0]]),
    "right": np.array([[-7.5, -6.8, 0.0, synth_format.WALL_TYPES["angle_left"][0], 0.0]]),
    "single": np.array([[ 0.0, -11.0, 0.0, synth_format.WALL_TYPES["center"][0], 0.0]]),
    "both": np.array([[ 0.0, -11.0, 0.0, synth_format.WALL_TYPES["center"][0], 0.0]]),
}


# END OF CONFIG

with synth_format.file_data(in_file, save_suffix=save_suffix) as f:
    wall_offset_b = utils.second_to_beat(wall_offset_s, f.bpm)

    # copy difficulty (notes and effects only)
    c_diff = f.difficulties[source_difficulty].filtered(types=synth_format.NOTE_TYPES + ("lights", "effects"))
    # mirror everything (without changing colors)
    c_diff.apply_for_notes(movement.scale, scale_3d=[-1,1,1])

    walls: synth_format.WALLS = {}

    if turn_around_s is not None:
        turn_around = synth_format.import_clipboard_json(turn_around_json)
        turn_around.bpm = f.bpm
        turn_around.apply_for_walls(movement.offset, offset_3d=[0,0,utils.second_to_beat(turn_around_s, f.bpm)])
        walls |= turn_around.walls

    for note_type, marker_template in marker_templates.items():
        def _create_marker(nodes: "numpy array (n, 3)", direction: int = 1) -> "numpy array (n, 3)":
            # single marker for singles, interpolate rails
            marker_positions = nodes if nodes.shape[0] == 1 else rails.interpolate_nodes(nodes, mode="spline", interval=rail_interpolation)
            for n in marker_positions:
                new_wall = marker_template.copy()
                if n[1] > 2:  # if above head, mirror Y, so the walls come down from top instead
                    new_wall = movement.scale(new_wall, [1,-1,1])
                # offset by note position, and move forward in time
                new_wall[0,:3] += n + [0, 0, -wall_offset_b]
                # if time slot is already used, fall back to next one
                while new_wall[0,2] in walls:
                    new_wall[0,2] += 1/64
                walls[new_wall[0,2]] = new_wall  # add wall
            return nodes  # don't acutally change input
        c_diff.apply_for_notes(_create_marker, types=(note_type))
    c_diff.walls = walls

    f.difficulties["Custom"] = c_diff
    f.meta.custom_difficulty_name = "Backward"
    f.meta.custom_difficulty_speed = 3

    if finalize:
        finalized = (f.bookmarks.get(0.0) == "#smh_finalized")
        if not finalized:
            f.bookmarks[0.0] = "#smh_finalized"
            for _, diff_data in f.difficulties.items():
                diff_data.apply_for_walls(movement.offset, offset_3d=(0,-2.1,0), types=synth_format.SLIDE_TYPES)
        else:
            # only finalize custom difficulty
            f.difficulties["Custom"].apply_for_walls(movement.offset, offset_3d=(0,-2.1,0), types=synth_format.SLIDE_TYPES)
