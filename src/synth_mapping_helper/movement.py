import numpy as np

# movement
def move(data: "numpy array (n, 3)", offset: "numpy array (3)") -> "numpy array (n, 3)":
    """translate nodes"""
    return data + offset


def scale(data: "numpy array (n, 3)", scale: "numpy array (3)") -> "numpy array (n, 3)":
    """scale nodes relative to center and start of selection"""
    return data * scale


def scale_from(
    data: "numpy array (n, 3)", scale: "numpy array (3)", pivot: "numpy array (2)"
) -> "numpy array (n, 3)":
    """scale nodes relative to pivot"""
    return (data - pivot) * scale + pivot


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
    data: "numpy array (n, 3)", angle: float, pivot: "numpy array (2)"
) -> "numpy array (n, 3)":
    """rotate nodes anticlockwise around a pivot point"""
    pivot = np.array([pivot[0], pivot[1], 0])
    return rotate(data - pivot, angle) + pivot
