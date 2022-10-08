import numpy as np

from .synth_format import DataContainer, SINGLE_COLOR_NOTES

# How far last node and start note can be spaced for two rails to be merged
MERGE_ACCURACY_GRID = 1 / 8
MERGE_ACCURACY_BEAT = 1 / 64

# Note: None of these functions are allowed to *modify* the input dict instance. Returning the same dict (if nothing needed to be changed) is allowed.

def split_rails(notes: SINGLE_COLOR_NOTES) -> SINGLE_COLOR_NOTES:
    """splits rails at single notes"""
    current_rail_start = None
    current_rail_end = None
    out: SINGLE_COLOR_NOTES = {}

    for time in sorted(notes):
        if current_rail_start is not None and time >= current_rail_end:
            current_rail_start = None
            current_rail_end = None
        nodes = notes[time]
        if nodes.shape[0] > 1:
            current_rail_start = nodes[0, 2]
            current_rail_end = nodes[-1, 2]
            out[time] = nodes
        elif current_rail_start is not None:
            previous_nodes = out[current_rail_start]
            # last index that is *before* or *at* the note
            last_index = np.argwhere(previous_nodes[:, 2] <= nodes[0, 2])[-1][0]

            # use the remainder of current rail for new rail
            # includes [last_index] that gets replaced by note to avoid concatenating
            remainder = previous_nodes[last_index:].copy()
            remainder[0] = nodes[0]
            out[time] = remainder

            if previous_nodes[last_index, 2] == time:
                # when there is a existing node at the current time, leave it be
                out[current_rail_start] = previous_nodes[: last_index + 1]
            else:
                # else replace the next one with note to finish the rail and include it
                previous_nodes[last_index + 1] = nodes[0]
                out[current_rail_start] = previous_nodes[: last_index + 2]

            current_rail_start = remainder[0, 2]
            current_rail_end = remainder[-1, 2]

    return out


def merge_sequential_rails(notes: SINGLE_COLOR_NOTES) -> SINGLE_COLOR_NOTES:
    """merges rails where end and start a very close"""
    current_rail_start = None
    current_rail_end = None
    out: SINGLE_COLOR_NOTES = {}

    for time in sorted(notes):
        nodes = notes[time]
        if nodes.shape[0] == 1:  # ignore single nodes
            out[time] = nodes
            continue

        if (
            current_rail_end is not None
            and time <= current_rail_end + MERGE_ACCURACY_BEAT
        ):
            previous_nodes = out[current_rail_start]
            if np.isclose(
                previous_nodes[-1, 2], nodes[0, 2], atol=MERGE_ACCURACY_BEAT
            ) and np.allclose(
                previous_nodes[-1, :2], nodes[0, :2], atol=MERGE_ACCURACY_GRID
            ):
                # add to rail
                out[current_rail_start] = np.concatenate((previous_nodes[:-1], nodes))
                current_rail_end = nodes[-1, 2]
                # add single note where rail started
                out[time] = nodes[:1]
                continue
    
        current_rail_start = time
        current_rail_end = nodes[-1, 2]
        out[time] = nodes

    return out

def merge_rails(notes: SINGLE_COLOR_NOTES, max_interval: float) -> SINGLE_COLOR_NOTES:
    """merges rails"""
    current_rail_start = None
    current_rail_end = None
    out: SINGLE_COLOR_NOTES = {}

    for time in sorted(notes):
        nodes = notes[time]
        if nodes.shape[0] == 1:  # ignore single nodes
            out[time] = nodes
            continue

        if (
            current_rail_end is None
            or time > current_rail_end + max_interval
        ):
            current_rail_start = time
            current_rail_end = nodes[-1, 2]
            out[time] = nodes
        else:
            previous_nodes = out[current_rail_start]
            # when start and end are close, remove end node of previous rail before joining
            if np.isclose(
                previous_nodes[-1, 2], nodes[0, 2], atol=MERGE_ACCURACY_BEAT
            ) and np.allclose(
                previous_nodes[-1, :2], nodes[0, :2], atol=MERGE_ACCURACY_GRID
            ):
                previous_nodes = previous_nodes[:-1]

            # add to rail
            out[current_rail_start] = np.concatenate((previous_nodes, nodes))
            current_rail_end = nodes[-1, 2]
            # add single note where rail started
            out[time] = nodes[:1]

    return out

def connect_singles(notes: SINGLE_COLOR_NOTES, max_interval: float) -> SINGLE_COLOR_NOTES:
    """Turn single notes into rails"""
    current_rail_start = None
    current_rail_end = None
    out: SINGLE_COLOR_NOTES = {}
    for time in sorted(notes):
        nodes = notes[time]

        if nodes.shape[0] != 1:  # existing rails are ignored and reset 
            current_rail_start = None
            current_rail_end = None
            out[time] = nodes
            continue

        if (
            current_rail_end is None
            or time > current_rail_end + max_interval + MERGE_ACCURACY_BEAT
        ):
            current_rail_start = time
            current_rail_end = nodes[-1, 2]
            out[time] = nodes
        else:
            out[current_rail_start] = np.concatenate((out[current_rail_start], nodes))
            current_rail_end = nodes[-1, 2]
            # note: does not readd the single notes to the output dict

    return out

def interpolate_nodes_linear(
    data: "numpy array (n, 3)", interval: float
) -> "numpy array (n, 3)":
    """places nodes at defined interval along the rail, interpolating linearly between existing nodes"""
    if data.shape[0] == 1:  # ignore single nodes
        return data
    new_z = np.arange(data[0, 2], data[-1, 2], interval)
    # when it does not distribute evenly, append end
    if not np.isclose(new_z[-1], data[-1, 2]):
        new_z = np.append(new_z, [data[-1, 2]])

    new_x = np.interp(new_z, data[:, 2], data[:, 0])
    new_y = np.interp(new_z, data[:, 2], data[:, 1])
    return np.stack((new_x, new_y, new_z), -1)


def rails_to_singles(notes: SINGLE_COLOR_NOTES, keep_rail: bool) -> SINGLE_COLOR_NOTES:
    """Turn all rails into single notes"""
    out: SINGLE_COLOR_NOTES = {}
    for time in sorted(notes):
        nodes = notes[time]
        if nodes.shape[0] == 1:  # ignore single nodes
            out[time] = nodes
            continue
        for node in nodes[int(keep_rail):]:  # when keeping the rail, don't overwrite the start with a single note
            out[node[2]] = node[np.newaxis]

    return out