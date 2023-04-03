import numpy as np
from scipy.interpolate import pchip_interpolate

from .synth_format import DataContainer, SINGLE_COLOR_NOTES
from .utils import bounded_arange

# How far last node and start note can be spaced for two rails to be merged
MERGE_ACCURACY_GRID = 1 / 8
MERGE_ACCURACY_BEAT = 1 / 64

def interpolate_linear(data: "numpy array (n, m)", new_z: "numpy array (x)", *, direction: bool = 1) -> "numpy array (x, 3)":
    return np.stack((
        np.interp(new_z, data[:, 2], data[:, 0]),
        np.interp(new_z, data[:, 2], data[:, 1]),
        new_z,
    ), axis=-1)

def interpolate_spline(data: "numpy array (n, m)", new_z: "numpy array (x)", *, direction: bool = 1) -> "numpy array (x, 3)":
    if data.shape[0] == 1:
        return data
    # add points in straight line from start and end to match shape more closely
    padded_data = np.concatenate(([2*data[0]-data[1]], data, [2*data[-1]-data[-2]]))
    return np.stack((
        pchip_interpolate(padded_data[:, 2], padded_data[:, 0], new_z),
        pchip_interpolate(padded_data[:, 2], padded_data[:, 1], new_z),
        new_z,
    ), axis=-1)

def get_position_at(notes: SINGLE_COLOR_NOTES, beat: float, interpolate_gaps: bool = True) -> "numpy array (2)":
    # single note
    if beat in notes:
        return notes[beat][0, 0:2].copy()
    last_before = None
    # on rail, or between notes: interpolate
    for time in sorted(notes):
        nodes = notes[time]
        if time > beat:  # passed by target beat: interpolate between last and this
            if interpolate_gaps and last_before is not None:
                return interpolate_spline(np.concatenate((last_before, nodes)), beat)[0:2]
            break
        last_before = nodes
        if nodes.shape[0] == 1:  # ignore single nodes
            continue
        if nodes[-1, 2] >= beat:  # on rail: interpolate between nodes
            return interpolate_spline(nodes, beat)[0:2]

    # neither
    return None

# Note: None of these functions are allowed to *modify* the input dict instance. Returning the same dict (if nothing needed to be changed) is allowed.

def split_rails(notes: SINGLE_COLOR_NOTES, *, direction: bool = 1) -> SINGLE_COLOR_NOTES:
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


def merge_sequential_rails(notes: SINGLE_COLOR_NOTES, *, direction: bool = 1) -> SINGLE_COLOR_NOTES:
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

def merge_rails(notes: SINGLE_COLOR_NOTES, max_interval: float, *, direction: bool = 1) -> SINGLE_COLOR_NOTES:
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

def connect_singles(notes: SINGLE_COLOR_NOTES, max_interval: float, *, direction: bool = 1) -> SINGLE_COLOR_NOTES:
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

def interpolate_nodes(
    data: "numpy array (n, 3)", mode: "'spline' or 'linear'", interval: float, *, direction: bool = 1
) -> "numpy array (n, 3)":
    """places nodes at defined interval along the rail, interpolating between existing nodes"""
    if data.shape[0] == 1:  # ignore single nodes
        return data
    new_z = bounded_arange(data[0, 2], data[-1, 2], interval)

    if mode == "spline":
        return interpolate_spline(data, new_z)
    elif mode == "linear":
        return interpolate_linear(data, new_z)
    else:
        raise RuntimeError("Invalid iterpolation mode")


def rails_to_singles(notes: SINGLE_COLOR_NOTES, keep_rail: bool, *, direction: bool = 1) -> SINGLE_COLOR_NOTES:
    """Turn all rails into single notes"""
    out: SINGLE_COLOR_NOTES = {}
    for time in sorted(notes):
        nodes = notes[time]
        if nodes.shape[0] == 1:  # ignore single nodes
            out[time] = nodes
            continue
        if keep_rail:
            out[nodes[0,2]] = nodes
        for node in nodes[int(keep_rail):]:  # when keeping the rail, don't overwrite the start with a single note
            out[node[2]] = node[np.newaxis]

    return out

def shorten_rail(
    data: "numpy array (n, 3)", distance: float, *, direction: bool = 1
) -> "numpy array (n, 3)":
    """Cut a bit of the end or start of the rail"""
    if data.shape[0] == 1:  # ignore single nodes
        return data
    if distance > 0:  # cut at the end
        new_z = data[-1,2] - distance
        last_index = np.argwhere(data[:, 2] < new_z)[-1][0]  # last node before new end
        return np.concatenate((data[:last_index+1], interpolate_spline(data, [new_z])))
    else:  # cut at the start
        new_z = data[0,2] - distance  # distance is negative to minus is correct here
        first_index = np.argwhere(data[:, 2] > new_z)[0][0]  # first node after new start
        return np.concatenate((interpolate_spline(data, [new_z]), data[first_index:]))
