#! /usr/bin/env python3

# Author: adosikas
# Idea: Artanis
#
# Rotate existing walls in clipboard

import numpy as np
from synth_mapping_helper import synth_format, movement

full_rotation_b: float = 16.0  # in beats for a full cycle. Can be negative to reverse direction
relative_rotation: bool = False  # when this is True, walls rotate around themselves, else rotate walls around center

first_b: float|None = None  # start rotation of 0 degrees on this beat. When None, detects position of first wall

def _do_rotate(wall: "numpy array (1, 5)", direction: int = 1) -> "numpy array (1, 5)":
    global first_b
    t = wall[0,2]
    if first_b is None:
        first_b = t
    angle_offset = (t-first_b) / full_rotation_b * 360 
    return movement.rotate(wall, angle_offset, relative=relative_rotation)

with synth_format.clipboard_data(realign_start=False) as data:
    data.apply_for_walls(_do_rotate)  # apply for all walls
