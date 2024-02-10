#! /usr/bin/env python3

# Author: adosikas
# Idea: Melon4dinner
#
# Creates a box of square walls in clipboard

import numpy as np
from synth_mapping_helper import synth_format

size = np.array([200, 200, 4])  # size of the box
min_spacing = np.array([40, 40, 1/2])  # minimal spacing, automatically rounded up to fit size
fill_sides = True
fill_front_back = True
time_step = 1/64  # shift walls that land on the same time

grid_size = size // min_spacing
spacing = size / grid_size

walls = [
    spacing * [x,y,z] - size/2  # position (should the condition below be true)
    # loop over all combinations of x, y and z
    for x in range(int(grid_size[0])+1)
    for y in range(int(grid_size[1])+1)
    for z in range(int(grid_size[2])+1)
    # only put a wall when at least two values are at min or max (meaning any edge) ...
    if ((x in (0, int(grid_size[0]))) + (y in (0, int(grid_size[1]))) + (z in (0, int(grid_size[2])))) >= 2
        # or (if filling sides): x or y are at min/max
        or fill_sides and (x in (0, int(grid_size[0])) or y in (0, int(grid_size[1])))
        # or (if filling front/back): z is at min/max
        or fill_front_back and (z in (0, int(grid_size[2])))
]

out = synth_format.ClipboardDataContainer()  # start with empty data

# sort walls by distance from center, results in best perspective
for w in sorted(walls, key=lambda w: w[0]**2+w[1]**2):
    new_t = w[2]
    # shift time back until we find a free spot
    while new_t in out.walls: 
        new_t = round((new_t+time_step)/time_step)*time_step
    # add wall in [X,Y,T,type,rotation] format
    out.walls[new_t] = np.array([[w[0], w[1], new_t, synth_format.WALL_TYPES["square"][0],0]])

# export to clipboard
synth_format.export_clipboard(out)