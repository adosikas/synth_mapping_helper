#! /usr/bin/env python3

# Author: adosikas
# Idea: Donjuannelly
#
# Creates a sphere of square walls in clipboard

import numpy as np
from synth_mapping_helper import synth_format

grid_size = 16  # squares size
time_scale = 64  # smaller: more streched
time_step = 1/64  # shift walls that land on the same time
radius = 150  # radius of the sphere
back = False  # set to False to only render front half

walls_front = []
walls_back = []

grid_limit = int(radius/grid_size)

# for each grid position, find optimal time to place the wall at to make a perfect sphere
for x in range(-grid_limit, grid_limit):
    for y in range(-grid_limit, grid_limit):
        if x&1 == y&1: # checkerboard: x and y must both be even or both be odd
            diff = radius**2 - (x*grid_size)**2 - (y*grid_size)**2
            if diff >= 0:  # don't attempt to calculate positions outside of the sphere
                t = round((radius-np.sqrt(diff))/time_scale/time_step)*time_step
                walls_front.append([x*grid_size,y*grid_size, t])
                t = round((radius+np.sqrt(diff))/time_scale/time_step)*time_step
                walls_back.append([x*grid_size,y*grid_size, t])

out = synth_format.ClipboardDataContainer()

# sorted by time (ascending), add them to the output
for w in sorted(walls_front, key=lambda w: w[2]):
    new_t = w[2]
    while new_t in out.walls:
        # shift time back until we find a free spot
        new_t = round((new_t+time_step)/time_step)*time_step
    out.walls[new_t] = np.array([[
        w[0], w[1], new_t,
        synth_format.WALL_TYPES["square"][0],
        # angle, may be based on wall position (matching rotation)
        0  # np.degrees(np.arctan2(w[1],w[0]))
    ]])
if back:
    # sorted by time (now descending), add them to the output
    for w in sorted(walls_back, key=lambda w: w[2], reverse=True):
        new_t = w[2]
        # shift time back until we find a free spot
        while new_t in out.walls:
            new_t = round((new_t-time_step)/time_step)*time_step
        out.walls[new_t] = np.array([[
            w[0], w[1], new_t,
            synth_format.WALL_TYPES["square"][0],
            # angle, may be based on wall position (matching rotation)
            0  # np.degrees(np.arctan2(w[1],w[0]))
        ]])

synth_format.export_clipboard(out)
