#! /usr/bin/env python3

# Author: adosikas
# Idea: Sodapie
#
# Creates a spike rail from the clipboard where the spikes rotate with the movement of the rail
# Note: interpolation must be done beforehand

import numpy as np
from synth_mapping_helper import synth_format, pattern_generation

spike_radius = 2  # in squares
spike_length = 1/32  # in beats
spike_angle = 90  # 0 means in direction of movement, 90 is to the left of direction, -90 is to the right
mirror_left = False  # mirror angle for left hand

data = synth_format.import_clipboard()

def _add_directional_spikes(nodes: "numpy array (n, 3)", direction: int = 1) -> "numpy array (n, 3)":
    # calculate "angle" at each rail node by looking at the direction to previous and upcoming node
    tangents = np.diff(nodes[:,:2], axis=0, prepend=nodes[0,:2][np.newaxis], append=nodes[-1,:2][np.newaxis])
    smoothed_tangents = (tangents[:-1] + tangents[1:]) / 2
    angles = np.degrees(np.arctan2(smoothed_tangents[:,1], smoothed_tangents[:,0])) + spike_angle * direction

    count = nodes.shape[0]
    nodes = np.repeat(nodes, 3, axis=0)  # turn each rail node into triplets
    nodes[0::3, 2] -= spike_length/2  # move first node of each triplet earlier in time
    nodes[1::3, :2] += pattern_generation.angle_to_xy(angles) * spike_radius  # add xy-offset to second node of each triplet 
    nodes[2::3, 2] += spike_length  # move third node of each triplet earlier in time
    return nodes

data.apply_for_notes(_add_directional_spikes, mirror_left=mirror_left)

synth_format.export_clipboard(data)
