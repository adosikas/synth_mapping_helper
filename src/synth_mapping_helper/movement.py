import numpy as np

# movement
def offset(data: "numpy array (n, 3)", offset_3d: "numpy array (3)") -> "numpy array (n, 3)":
    """translate nodes"""
    return data + offset_3d


def scale(data: "numpy array (n, 3)", scale_3d: "numpy array (3)") -> "numpy array (n, 3)":
    """scale nodes relative to center and start of selection"""
    if scale == 0:
        raise ValueError("Cannot have 0 for time scale")
    output = data * scale_3d
    if scale_3d[2] < 0:
        output = output[::-1]
    return output


def scale_from(
    data: "numpy array (n, 3)", scale_3d: "numpy array (3)", pivot: "numpy array (3)"
) -> "numpy array (n, 3)":
    """scale nodes relative to pivot"""
    return scale(data - pivot, scale_3d) + pivot

def scale_relative(
    data: "numpy array (n, 3)", scale_3d: "numpy array (3)"
) -> "numpy array (n, 3)":
    """scale nodes relative to first node"""
    if data.shape[0] == 1:
        # no effect on single notes
        return data
    return scale(data-data[0], scale_3d) + data[0]

def rotate(data: "numpy array (n, 3)", angle: float) -> "numpy array (n, 3)":
    """rotate nodes anticlockwise around center"""
    rad_ang = np.radians(angle)
    rot_matrix = np.array(
        [
            [np.cos(rad_ang), np.sin(rad_ang), 0],
            [-np.sin(rad_ang), np.cos(rad_ang), 0],
            [0, 0, 1],
        ]
    )
    return data.dot(rot_matrix)

def rotate_around(
    data: "numpy array (n, 3)", angle: float, pivot: "numpy array (3)"
) -> "numpy array (n, 3)":
    """rotate nodes anticlockwise around pivot"""
    return rotate(data - pivot, angle) + pivot

def rotate_relative(
    data: "numpy array (n, 3)", angle: float
) -> "numpy array (n, 3)":
    """rotate nodes anticlockwise around first node"""
    if data.shape[0] == 1:
        # no effect on single notes
        return data
    return rotate(data-data[0], angle) + data[0]
