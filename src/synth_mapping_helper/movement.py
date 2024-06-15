from functools import wraps
import numpy as np

from .synth_format import WALL_MIRROR_ID, WALL_TYPES

# Note: None of these functions are allowed to *modify* the input array instance. Returning the same array (if nothing needed to be changed) is allowed.

MIRROR_VEC_3D = np.array([-1, 1, 1])

def add_basic_pivot_wrapper(func):
    @wraps(func)
    def _pivot_wrapper(
        data: "numpy array (n, 3+)",
        *args,
        relative: bool = False,
        pivot: "optional numpy array (2+)"=None,
        **kwargs
    ) ->  "numpy array (n, 3+)":
        if relative:
            pivot = data[0,:3]
        if pivot is not None and pivot.any():
            pivot_nd = np.zeros(data.shape[-1])
            pivot_nd[:pivot.shape[0]] = pivot
            return func(data-pivot_nd, *args, **kwargs) + pivot_nd
        return func(data, *args, **kwargs)
    return _pivot_wrapper

# movement
def _offset(data: "numpy array (n, m)", offset_3d: "numpy array (3)", direction: int = 1) -> "numpy array (n, 3+)":
    """translate positions"""
    offset_nd = np.zeros((data.shape[-1]))
    offset_nd[..., :3] = offset_3d if direction == 1 else offset_3d * MIRROR_VEC_3D
    return data + offset_nd


def _offset_relative(
    data: "numpy array (n, m)", offset_3d: "numpy array (3)", direction: int = 1
) -> "numpy array (n, 3+)":
    """translate positions, use relative coordinates for walls"""
    if data.shape[-1] == 3:
        return _offset(data, offset_3d, direction=direction)
    # calculate rot matrix for angle of every wall
    rad_ang = np.radians(np.atleast_1d(data[:, 4]))
    rot_matrix = np.rollaxis(
        np.array(
            (
                (np.cos(rad_ang), np.sin(rad_ang)),
                (-np.sin(rad_ang), np.cos(rad_ang)),
            )
        ),
        -1,
    )
    offset_nd = np.zeros((data.shape[-1]))
    offset_nd[..., :2] = (
        np.array(offset_3d[:2]) if direction == 1 else offset_3d[:2] * MIRROR_VEC_3D
    ).dot(
        rot_matrix
    )  # offset is rotated for each wall
    offset_nd[..., 2] = offset_3d[2]  # t stays as-is
    return data + offset_nd

def offset(
    data: "numpy array (n, 3+)",
    offset_3d: "numpy array (3)",
    pivot: None = None,  # ignored, for compatibility with other movement funcs
    relative: bool = False,
    direction: int = 1,
) -> "numpy array (n, 3+)":
    if relative:
        return _offset_relative(data, offset_3d=offset_3d, direction=direction)
    else:
        return _offset(data, offset_3d=offset_3d, direction=direction)

@add_basic_pivot_wrapper
def outset(
    data: "numpy array (n, m)", outset_scalar: float, direction: int = 1
) -> "numpy array (n, 3+)":
    """move positions outwards"""
    zero_mask = np.logical_and(np.isclose(data[..., 0], 0, atol=1e-5), np.isclose(data[..., 1], 0, atol=1e-5))  # ignore xy close to 0,0
    angles = np.arctan2(data[~zero_mask, 1], data[~zero_mask, 0])
    normalized = np.zeros(data.shape)
    normalized[~zero_mask, 0] = np.cos(angles)
    normalized[~zero_mask, 1] = np.sin(angles)
    return data + normalized * outset_scalar

@add_basic_pivot_wrapper
def scale(
    data: "numpy array (n, 3+)", scale_3d: "numpy array (3)", direction: int = 1
) -> "numpy array (n, 3+)":
    """scale positions relative to center and start of selection"""
    if scale_3d[2] == 0:
        raise ValueError("Cannot have 0 for time scale")
    scale_nd = np.ones((data.shape[-1]))
    scale_nd[..., :3] = scale_3d
    output = data * scale_nd
    if scale_nd[2] < 0:  # reverse order of elements
        output = output[::-1]
    if data.shape[-1] == 5: # walls
        if (scale_nd[0] < 0) != (scale_nd[1] < 0):  # mirror X *or* Y: swap type and invert angle (both: do nothing)
            output[:,3] = [WALL_MIRROR_ID[i] for i in output[:,3]]
            output[:,4] = -output[:,4]
        if (scale_nd[1] < 0):  # mirror Y: add 180
            output[:,4] += 180

    return output


@add_basic_pivot_wrapper
def rotate(
    data: "numpy array (n, 3+)", angle: float, direction: int = 1
) -> "numpy array (n, 3+)":
    """rotate positions anticlockwise around center"""
    rad_ang = np.radians(angle * direction)
    rot_matrix = np.identity(data.shape[-1])
    rot_matrix[:2, :2] = [
        [np.cos(rad_ang), np.sin(rad_ang)],
        [-np.sin(rad_ang), np.cos(rad_ang)],
    ]
    out = data.dot(rot_matrix)
    if data.shape[-1] >= 5:
        # just add to wall rotation (unless it is a crouch wall)
        not_crouch = (out[..., 3] != WALL_TYPES["crouch"][0])
        out[not_crouch, 4] += angle * direction
    return out
