import numpy as np

from .synth_format import DataContainer, WALLS, WALL_LOOKUP, WALL_SYMMETRY
from .utils import bounded_arange
from . import movement

# generic helpers
def angle_to_xy(angles: "numpy array like") -> "numpy array like":
    """convert a angles in degrees to x and y coordinates"""
    rad_angles = np.radians(angles)
    return np.stack((np.cos(rad_angles), np.sin(rad_angles)), -1)

def random_ring(count: int) -> "numpy array (n, 2)":
    """random positons along a ring of radius 1"""
    return angle_to_xy(np.random.random_sample((count,)) * 360)

def random_xy(count: int, min: "numpy array (2)", max: "numpy array (2)") -> "numpy array (n, 2)":
    """random positions in a rectangle"""
    return np.random.random_sample((count, 2)) * (max - min) + min

# pattern generation
def spiral(
    fidelity: float, length: float, start_angle: float = 0
) -> "numpy array (n, 2)":
    """spiral with radius 1, uses random when fidelity is 0"""
    if not fidelity: 
        return random_ring(int(length))
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
        spiral(fidelity, length, start_angle) 
    )
    return output

def create_parallel(data: DataContainer, distance: float) -> None:
    """create parallel patterns by splitting specials, or adding the other hand
    
    when splitting specials, both will be moved by half the distance left and right.
    otherwise, the existing color stays, while the new hand is moved by distance in the "natural" direction.

    distance can be negative to create crossovers.
    """
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

def find_wall_patterns(walls: WALLS) -> tuple[int, int]:
    """try to find repeating "patterns" with identical wall type and timing"""
    wall_count = len(walls)
    if wall_count < 2:
        raise ValueError("At least two walls must be selected")
    wall_types = [w[0,3] for _, w in sorted(walls.items())]

    # find candidates for patterns, by looking where the first wall type is repeated
    matching_first = [i for i, t in enumerate(wall_types) if i and t == wall_types[0]]
    if not matching_first:
        raise ValueError(f"Could not find any repeats of first wall ({WALL_LOOKUP[wall_types[0]]})")
    # now ensure it is an divisor of the wall count
    matching_count = [i for i in matching_first if wall_count % i == 0]
    if not matching_count:
        raise ValueError(f"Could not find any repeats of first wall that are divisors of total wall count ({wall_count})")
    # now check if types match
    matching_types = [i for i in matching_count if wall_types == wall_types[:i] * (wall_count//i)]
    if not matching_types:
        raise ValueError(f"Could not find any wall type pattern that repeats consistently")
    # finally check times
    wall_times = np.array([w[0,2] for _, w in sorted(walls.items())])
    for walls_per_pattern in reversed(matching_types):  # start with the largest candidate
        reshaped = wall_times.reshape((-1, walls_per_pattern)).copy()
        reshaped -= reshaped[:,0,np.newaxis]
        if np.allclose(reshaped[0], reshaped):
            return walls_per_pattern, wall_count // walls_per_pattern
    raise ValueError(f"Could not find any pattern of type AND timing that repeats consistently")

def blend_wall_single(first: "numpy array (n, 5)", second: "numpy array (n, 5)", interval: float, with_symmetry: bool=True) -> dict[str, "numpy array (1, 5)"]:
    """create blending substeps between two patterns
    
    first and second must be numpy arrays of the patterns (each with n walls)
    with_symmetry can be set to false to disregard that symetrical walls (like squares) look the same in multiple orientations
    """
    delta_t = second[0,2] - first[0,2]
    if not np.allclose(first[:,3], second[:,3]):
        raise ValueError("Patterns have mismatched wall types")
    if not np.allclose(first[:,2], second[:,2] - delta_t):
        raise ValueError("Patterns have mismatched timing")
    time_offsets = bounded_arange(0, delta_t, interval)

    out_walls = {}

    for f, s in zip(first, second):
        sym = WALL_SYMMETRY[WALL_LOOKUP[f[3]]] if with_symmetry else 360
        f_ang = f[4] % sym
        s_ang = s[4] % sym

        if f_ang == s_ang:  # equal angle => shift
            delta_xyttr = np.zeros_like(f) 
            delta_xyttr[:2] = (s[:2] - f[:2]) / delta_t
            delta_xyttr[2] = 1
            # x and y: delta for t=1, t: 1, type and rotation: 0
            for i in time_offsets:
                new = (f + delta_xyttr * i)
                out_walls[new[2]] = new[np.newaxis]
        else:  # spiral stack logic
            ang = ((s_ang - f_ang)+sym/2)%sym-sym/2  # angle difference, between -(sym/2) and +(sym/2), ie -180 to 180 for non-symetrical walls
            piv = f[:3] + movement.rotate((s - f)[:3]/2, 90 - ang/2) / np.sin(np.radians(ang/2))  # pivot location matching rotation with translation

            for i in time_offsets:
                new = movement.rotate_around(f[np.newaxis], angle=ang * (i/delta_t), pivot_3d=piv)
                new[:,2] += i
                out_walls[new[0,2]] = new
    return out_walls

def blend_walls_multiple(patterns: list["numpy array (n, 5)"], interval: float, with_symmetry: bool=True) -> dict[str, "numpy array (1, 5)"]:
    """calls blend_wall_single to blending between multiple patterns, each with n walls"""
    out_walls = {}
    for first, second in zip(patterns[:-1], patterns[1:]):
        out_walls |= blend_wall_single(first, second, interval=interval, with_symmetry=with_symmetry)
    return out_walls
