import numpy as np

# generic helpers
def angle_to_xy(angles: "numpy array like") -> "numpy array like":
    """convert a angles in degrees to x and y coordinates"""
    rad_angles = np.radians(angles)
    return np.stack((np.cos(angles), np.sin(angles)), -1)


# pattern generation
def random_ring(count: int) -> "numpy array (n, 2)":
    """random positons along a ring of radius 1"""
    return angle_to_xy(np.random.rand(count) * 360)


def spiral(
    fidelity: float, length: float, start_angle: float = 0
) -> "numpy array (n, 2)":
    """spiral with radius 1"""
    rot = np.arange(length) / fidelity  # 1 = 360°
    if length % 1:
        # add a partial angle at the end
        rot = np.concatenate((rot, [(length / fidelity)]))
    return angle_to_xy(rot * 360 + start_angle)


def spikes(
    fidelity: float, length: float, start_angle: float = 0
) -> "numpy array (n, 2)":
    """spikes with radius 1, uses random when fidelity is 0"""
    output = np.zeros((int(length) * 3, 2))
    output[1::3] = (
        spiral(fidelity, length, start_angle) if fidelity else random_ring(int(length))
    )
    return output
