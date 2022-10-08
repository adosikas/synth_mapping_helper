import numpy as np

# Note: None of these functions are allowed to *modify* the input array instance. Returning the same array (if nothing needed to be changed) is allowed.

# movement
def offset(data: "numpy array (n, m)", offset_3d: "numpy array (3)") -> "numpy array (n, 3+)":
    """translate positions"""
    offset_nd = np.zeros((data.shape[-1]))
    offset_nd[...,:3] = offset_3d
    return data + offset_nd

def outset(data: "numpy array (n, m)", outset: float) -> "numpy array (n, 3+)":
    """move positions outwards"""
    angles = np.arctan2(data[..., 1], data[..., 0])
    normalized = np.zeros(data.shape)
    normalized[..., 0] = np.cos(angles)
    normalized[..., 1] = np.sin(angles)
    return data + normalized * outset

def outset_from(data: "numpy array (n, m)", outset: float, pivot_3d: "numpy array (3)") -> "numpy array (n, 3+)":
    """move positions away from pivot"""
    pivot_nd = np.zeros((data.shape[-1]))
    pivot_nd[...,:3] = pivot_3d
    return outset(data - pivot_nd) + pivot_nd

def outset_relative(data: "numpy array (n, m)", outset: float) -> "numpy array (n, 3+)":
    """move positions away from pivot"""
    if data.shape[0] == 1:
        # no effect on single notes / walls
        return data
    return outset(data - data[0]) + data[0]


def scale(data: "numpy array (n, 3+)", scale_3d: "numpy array (3)") -> "numpy array (n, 3+)":
    """scale positions relative to center and start of selection"""
    if scale_3d[2] == 0:
        raise ValueError("Cannot have 0 for time scale")
    scale_nd = np.ones((data.shape[-1]))
    scale_nd[...,:3] = scale_3d
    output = data * scale_nd
    if scale_nd[2] < 0:  # reverse order of elements
        output = output[::-1]
    return output


def scale_from(
    data: "numpy array (n, 3+)", scale_3d: "numpy array (3)", pivot_3d: "numpy array (3)"
) -> "numpy array (n, 3+)":
    """scale positions relative to pivot"""
    pivot_nd = np.ones((data.shape[-1]))
    pivot_nd[...,:3] = pivot_3d
    return scale(data - pivot_nd, scale_3d) + pivot_nd

def scale_relative(
    data: "numpy array (n, 3+)", scale_3d: "numpy array (3)"
) -> "numpy array (n, 3+)":
    """scale positions relative to first node"""
    if data.shape[0] == 1:
        # no effect on single notes / walls
        return data
    return scale(data - data[0], scale_3d) + data[0]

def rotate(data: "numpy array (n, 3+)", angle: float) -> "numpy array (n, 3+)":
    """rotate positions anticlockwise around center"""
    rad_ang = np.radians(angle)
    rot_matrix = np.identity(data.shape[-1])
    rot_matrix[:2,:2] = [
        [np.cos(rad_ang), np.sin(rad_ang)],
        [-np.sin(rad_ang), np.cos(rad_ang)],
    ]
    out = data.dot(rot_matrix)
    if data.shape[-1] >= 5:
        # just add to wall rotation
        out[..., 4] += angle
    return out

def rotate_around(
    data: "numpy array (n, 3+)", angle: float, pivot_3d: "numpy array (3)"
) -> "numpy array (n, 3+)":
    """rotate positions anticlockwise around pivot"""
    pivot_nd = np.zeros((data.shape[-1]))
    pivot_nd[...,:3] = pivot_3d
    return rotate(data - pivot_nd, angle) + pivot_nd

def rotate_relative(
    data: "numpy array (n, 3+)", angle: float
) -> "numpy array (n, 3+)":
    """rotate positions anticlockwise around first node/wall center"""
    if data.shape[0] == 1:
        if data.shape[-1] >= 5:
            # just add to wall rotation
            wall_rot = np.zeros((data.shape[-1]))
            wall_rot[4] = angle
            return data + wall_rot
        else:
            # no effect on single notes
            return data
    return rotate(data - data[0], angle) + data[0]
