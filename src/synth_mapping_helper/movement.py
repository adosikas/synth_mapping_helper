import numpy as np

# Note: None of these functions are allowed to *modify* the input array instance. Returning the same array (if nothing needed to be changed) is allowed.

MIRROR_VEC_2D = np.array([-1, 1])
MIRROR_VEC_3D = np.array([-1, 1, 1])

# movement
def offset(
    data: "numpy array (n, m)",
    offset_3d: "numpy array (3)",
    pivot_3d: None = None,
    direction: int = 1,
) -> "numpy array (n, 3+)":
    """translate positions"""
    # pivot is ignored, but exists so this can be used as pivot func aswell
    offset_nd = np.zeros((data.shape[-1]))
    offset_nd[..., :3] = offset_3d if direction == 1 else offset_3d * MIRROR_VEC_3D
    return data + offset_nd


def offset_relative(
    data: "numpy array (n, m)", offset_3d: "numpy array (3)", direction: int = 1
) -> "numpy array (n, 3+)":
    """translate positions, use relative coordinates for walls"""
    if data.shape[-1] == 3:
        return offset(data, offset_3d, direction=direction)
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


def outset_from(
    data: "numpy array (n, m)",
    outset_scalar: float,
    pivot_3d: "numpy array (3)",
    direction: int = 1,
) -> "numpy array (n, 3+)":
    """move positions away from pivot"""
    pivot_nd = np.zeros((data.shape[-1]))
    pivot_nd[..., :3] = pivot_3d
    return outset(data - pivot_nd, outset_scalar, direction=direction) + pivot_nd


def outset_relative(
    data: "numpy array (n, m)", outset_scalar: float, direction: int = 1
) -> "numpy array (n, 3+)":
    """move positions away from pivot"""
    if data.shape[0] == 1:
        # no effect on single notes / walls
        return data
    return outset(data - data[0], outset_scalar, direction=direction) + data[0]


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
    return output


def scale_from(
    data: "numpy array (n, 3+)",
    scale_3d: "numpy array (3)",
    pivot_3d: "numpy array (3)",
    direction: int = 1,
) -> "numpy array (n, 3+)":
    """scale positions relative to pivot"""
    pivot_nd = np.ones((data.shape[-1]))
    pivot_nd[..., :3] = pivot_3d
    return scale(data - pivot_nd, scale_3d, direction=direction) + pivot_nd


def scale_relative(
    data: "numpy array (n, 3+)", scale_3d: "numpy array (3)"
) -> "numpy array (n, 3+)":
    """scale positions relative to first node"""
    if data.shape[0] == 1:
        # no effect on single notes / walls
        return data
    return scale(data - data[0], scale_3d) + data[0]


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
        # just add to wall rotation
        out[..., 4] += angle * direction
    return out

def rotate_around(
    data: "numpy array (n, 3+)",
    angle: float,
    pivot_3d: "numpy array (3)",
    direction: int = 1,
) -> "numpy array (n, 3+)":
    """rotate positions anticlockwise around pivot"""
    pivot_nd = np.zeros((data.shape[-1]))
    pivot_nd[..., :3] = pivot_3d
    return rotate(data - pivot_nd, angle, direction=direction) + pivot_nd


def rotate_relative(
    data: "numpy array (n, 3+)", angle: float, direction: int = 1
) -> "numpy array (n, 3+)":
    """rotate positions anticlockwise around first node/wall center"""
    if data.shape[0] == 1:
        if data.shape[-1] >= 5:
            # just add to wall rotation
            wall_rot = np.zeros((data.shape[-1]))
            wall_rot[4] = angle * direction
            return data + wall_rot
        else:
            # no effect on single notes
            return data
    return rotate(data - data[0], angle, direction=direction) + data[0]
