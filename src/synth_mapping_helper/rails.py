from typing import Literal

import numpy as np
from scipy.interpolate import CubicHermiteSpline, pchip_interpolate

from .synth_format import DataContainer, SINGLE_COLOR_NOTES
from .utils import bounded_arange_plusminus

# How far last node and start note can be spaced for two rails to be merged
MERGE_ACCURACY_GRID = 1 / 8
MERGE_ACCURACY_BEAT = 1 / 64

def interpolate_linear(data: "numpy array (n, m)", new_z: "numpy array (x)", *, direction: int = 1) -> "numpy array (x, 3)":
    return np.stack((
        np.interp(new_z, data[:, 2], data[:, 0]),
        np.interp(new_z, data[:, 2], data[:, 1]),
        new_z,
    ), axis=-1)

def interpolate_hermite(data: "numpy array (n, m)", new_z: "numpy array (x)", *, direction: int = 1) -> "numpy array (x, 3)":
    return np.stack((
        pchip_interpolate(data[:, 2], data[:, 0], new_z),
        pchip_interpolate(data[:, 2], data[:, 1], new_z),
        new_z,
    ), axis=-1)

def synth_curve(data: "numpy array (n, m)", *, direction: int = 1):
    # based on https://github.com/LittleAsi/synth-riders-editor,
    # which uses LineSmoother.cs from https://forum.unity.com/threads/easy-curved-line-renderer-free-utility.391219
    if data.shape[0] == 1:
        return data

    # equivalent of Unity's AnimationCurve when doing smoothTangents(0)
    tangents = np.diff(data, axis=0, prepend=data[0][np.newaxis], append=data[-1][np.newaxis])
    smoothed_tangents = (tangents[:-1] + tangents[1:]) / 2

    # this interpolates not only x and y, but also time
    curve = CubicHermiteSpline(range(data.shape[0]), data, smoothed_tangents)
    curve_points = []
    for i in range(data.shape[0]-1):
        curve_points.append(data[i])
        # interpolate a number of points which is based on distance between nodes
        # intermediates = int(np.linalg.norm(coord_to_synth(240, data[i+1]-data[i])) / 0.15)

        # we use a different formula, which doesn't rely on BPM but produces very similar results
        intermediates = int(np.linalg.norm((data[i+1]-data[i])*(0.1,0.1,16)))
        curve_points.extend(curve(i + np.arange(1, intermediates)/intermediates))
    curve_points.append(data[-1])
    return np.array(curve_points)

def interpolate_spline(data: "numpy array (n, m)", new_z: "numpy array (x)", *, direction: int = 1) -> "numpy array (x, 3)":
    return interpolate_linear(synth_curve(data), new_z, direction=direction)

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

def split_rails(notes: SINGLE_COLOR_NOTES, *, direction: int = 1) -> SINGLE_COLOR_NOTES:
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
        else:
            # ignore freestanding single note
            out[time] = nodes
    return out

def snap_singles_to_rail(notes: SINGLE_COLOR_NOTES, *, direction: int = 1) -> SINGLE_COLOR_NOTES:
    """snap single notes to rail"""
    current_rail_start = None
    current_rail_end = None
    out: SINGLE_COLOR_NOTES = {}

    for time in sorted(notes):
        if current_rail_start is not None and time > current_rail_end:  # current time is past end of stored rail -> forget stored rail
            current_rail_start = None
            current_rail_end = None
        nodes = notes[time]
        if nodes.shape[0] > 1:  # rail: store start/end and keep as-is
            current_rail_start = nodes[0, 2]
            current_rail_end = nodes[-1, 2]
            out[time] = nodes
        elif current_rail_start is not None:  # single next to rail -> snap to it
            out[time] = interpolate_spline(out[current_rail_start], [time])
        else:  # single without rail next to it: keep as-is
            out[time] = nodes
    return out

def merge_sequential_rails(notes: SINGLE_COLOR_NOTES, *, direction: int = 1) -> SINGLE_COLOR_NOTES:
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

def merge_rails(notes: SINGLE_COLOR_NOTES, max_interval: float, *, direction: int = 1) -> SINGLE_COLOR_NOTES:
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

def connect_singles(notes: SINGLE_COLOR_NOTES, max_interval: float, *, direction: int = 1) -> SINGLE_COLOR_NOTES:
    """Turn single notes into rails"""
    current_rail_start = None
    current_rail_end = None
    out: SINGLE_COLOR_NOTES = {}
    for time in sorted(notes):
        nodes = notes[time]

        if nodes.shape[0] != 1:  # existing rails are added unchanged and stops notes from connecting past it
            current_rail_start = None
            current_rail_end = None
            out[time] = nodes
            continue

        if (
            current_rail_end is None
            or time > current_rail_end + max_interval + MERGE_ACCURACY_BEAT
        ):
            # start a new rail (but only 1 node for now)
            current_rail_start = time
            current_rail_end = nodes[-1, 2]
            out[time] = nodes
        else:
            # extend the current rail inplace
            out[current_rail_start] = np.concatenate((out[current_rail_start], nodes))
            current_rail_end = nodes[-1, 2]
            # note: does not readd the single notes to the output dict

    return out

def interpolate_nodes(
    data: "numpy array (n, 3)", mode: Literal["spline", "hermite", "linear"], interval: float, *, direction: int = 1
) -> "numpy array (n, 3)":
    """places nodes at defined interval along the rail, interpolating between existing nodes. Can be negative to start from end."""
    if data.shape[0] == 1:  # ignore single nodes
        return data
    new_z = bounded_arange_plusminus(data[0, 2], data[-1, 2], interval)

    if mode == "spline":
        return interpolate_spline(data, new_z)
    elif mode == "hermite":
        return interpolate_hermite(data, new_z)
    elif mode == "linear":
        return interpolate_linear(data, new_z)
    else:
        raise RuntimeError("Invalid iterpolation mode")

def rails_to_singles(notes: SINGLE_COLOR_NOTES, keep_rail: bool, *, direction: int = 1) -> SINGLE_COLOR_NOTES:
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

def rails_to_notestacks(notes: SINGLE_COLOR_NOTES, interval: float, keep_rail: bool, *, direction: int = 1) -> SINGLE_COLOR_NOTES:
    """Turn all rails into notestacks. Can be negative to start from wnd"""
    out: SINGLE_COLOR_NOTES = {}
    for time in sorted(notes):
        nodes = notes[time]
        if nodes.shape[0] == 1:  # ignore single nodes
            out[time] = nodes
            continue
        i_nodes = interpolate_nodes(nodes, "spline", interval=interval)
        if keep_rail:
            out[nodes[0,2]] = nodes
        for node in i_nodes[int(keep_rail):]:  # when keeping the rail, don't overwrite the start with a single note
            out[node[2]] = node[np.newaxis]

    return out

def shorten_rail(
    data: "numpy array (n, 3)", distance: float, *, direction: int = 1
) -> "numpy array (n, 3)":
    """Cut a bit of the end or start (if negative) of the rail"""
    if data.shape[0] == 1 or not distance:  # ignore single nodes or shorter rails
        return data
    if distance > 0:  # cut at the end
        if (data[-1,2] - data[0,2]) <= distance:  # shorter -> return rail start only
            return data[0][np.newaxis]
        new_z = data[-1,2] - distance
        last_index = np.argwhere(data[:, 2] < new_z)[-1][0]  # last node before new end
        return np.concatenate((data[:last_index+1], interpolate_spline(data, [new_z])))
    else:  # cut at the start
        if (data[-1,2] - data[0,2]) <= -distance:  # shorter -> return rail end only
            return data[-1][np.newaxis]
        new_z = data[0,2] - distance  # distance is negative, so "- distance" is correct here
        first_index = np.argwhere(data[:, 2] > new_z)[0][0]  # first node after new start
        return np.concatenate((interpolate_spline(data, [new_z]), data[first_index:]))

def extend_level(
    data: "numpy array (n, 3)", distance: float, *, direction: int = 1
) -> "numpy array (n, 3)":
    """Add a level rail section at the end or start (if negative). Turns single notes into rails"""
    if not distance:
        return data
    elif distance > 0:
        return np.concatenate((data, data[np.newaxis,-1]+[0,0,distance]))
    else:
        return np.concatenate((data[np.newaxis,0]+[0,0,distance], data))

def extend_straight(
    data: "numpy array (n, 3)", distance: float, *, direction: int = 1
) -> "numpy array (n, 3)":
    """Add a straight rail section at the end or start (if negative) which keeps the same direction of the previous segment"""
    if data.shape[0] == 1 or not distance:  # ignore single nodes or shorter rails
        return data
    elif distance > 0:
        delta = data[-1] - data[-2]
        return np.concatenate((data, data[np.newaxis,-1]+delta*(distance/delta[2])))
    else:
        delta = data[0] - data[1]
        return np.concatenate((data[np.newaxis,0]+delta*(distance/delta[2]), data))

def extend_to_next(
    notes: SINGLE_COLOR_NOTES, distance: float, *, direction: int = 1
) -> "numpy array (n, 3)":
    """Add a rail section at the end pointing to next note/rail. Vice-versa for negative. Turns single notes into rails."""
    if len(notes) < 2 or not distance:  # ignore when there is nothing to work with
        return notes
    out: SINGLE_COLOR_NOTES = {}
    last_nodes: "numpy array (n, 3)" = None
    if distance > 0:
        for time in sorted(notes):
            nodes = notes[time]
            if last_nodes is not None:
                delta = nodes[0] - last_nodes[-1]
                out[last_nodes[0,2]] = np.concatenate((last_nodes, last_nodes[np.newaxis,-1]+delta*(distance/delta[2])))
            last_nodes = nodes
        out[last_nodes[0,2]] = last_nodes
    else:
        for time in sorted(notes):
            nodes = notes[time]
            if last_nodes is not None:
                delta = nodes[0] - last_nodes[-1]
                new = np.concatenate((nodes[np.newaxis,0]+delta*(distance/delta[2]), nodes))
                out[new[0,2]] = new
            else:
                out[nodes[0,2]] = nodes
            last_nodes = nodes
    return out

def segment_rail(
    notes: SINGLE_COLOR_NOTES, max_length: float, *, direction: int = 1
) -> "numpy array (n, 3)":
    """Segment rails into multiple range of maximum length. Can be negative to segment from end"""
    out: SINGLE_COLOR_NOTES = {}
    for time in sorted(notes):
        nodes = notes[time]
        if nodes.shape[0] == 1 or (nodes[-1,2]-nodes[0,2]) <= max_length:  # ignore single nodes or short rails
            out[time] = nodes
            continue

        steps = bounded_arange_plusminus(nodes[0,2], nodes[-1,2], max_length)
        new_z = np.union1d(nodes[:,2], steps)
        for start in steps[:-1]:
            out[start] = interpolate_spline(nodes, new_z=new_z[np.logical_and(new_z>=start, new_z<=(start+abs(max_length)))])
    return out
