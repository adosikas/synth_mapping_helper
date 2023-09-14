import numpy as np

from .synth_format import DataContainer

# generic helpers
def angle_to_xy(angles: "numpy array like") -> "numpy array like":
    """convert a angles in degrees to x and y coordinates"""
    rad_angles = np.radians(angles)
    return np.stack((np.cos(rad_angles), np.sin(rad_angles)), -1)

def random_ring(count: int) -> "numpy array (n, 2)":
    """random positons along a ring of radius 1"""
    return angle_to_xy(np.random.random_sample((count,)) * 360)

def random_xy(count: int, min: "numpy array (2)", max: "numpy array (2)") -> "numpy array (n, 2)":
    return np.random.random_sample((count, 2)) * (max - min) + min

# pattern generation
def spiral(
    fidelity: float, length: float, start_angle: float = 0
) -> "numpy array (n, 2)":
    """spiral with radius 1"""
    rot = np.arange(length) / fidelity  # in rotations, ie 1.0 = 360°
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

def create_parallel(data: DataContainer, distance: float) -> None:
    left_orig, right_orig = data.left, data.right  # create a backup of the input
    data.left = (
        left_orig
        | {t: nodes - [distance,0,0] for t, nodes in sorted(right_orig.items())}  # shift over right hand by <distance>
        | {t: nodes - [distance/2,0,0] for t, nodes in sorted(data.single.items())}  # shift over single & both by <distance>/2
        | {t: nodes - [distance/2,0,0] for t, nodes in sorted(data.both.items())}
    )
    # vice versa for right hand
    data.right = (
        right_orig 
        | {t: nodes + [distance,0,0] for t, nodes in sorted(left_orig.items())}
        | {t: nodes + [distance/2,0,0] for t, nodes in sorted(data.single.items())}
        | {t: nodes + [distance/2,0,0] for t, nodes in sorted(data.both.items())}
    )
    # wipe single & both
    data.single = {}
    data.both = {}