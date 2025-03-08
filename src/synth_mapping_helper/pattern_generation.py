import dataclasses
from typing import Literal, Union

import numpy as np

from .synth_format import RailFilter, DataContainer, WALLS, WALL_LOOKUP, WALL_SYMMETRY, WALL_TYPES, NOTE_TYPES
from .utils import bounded_arange
from . import movement, rails

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
        rot = np.concatenate((rot, np.array([(length / fidelity)])))
    return angle_to_xy(rot * 360 + start_angle)

def add_spiral(nodes: "numpy array (n, 3)", fidelity: float, radius: float, start_angle: float = 0.0, direction: int = 1) -> "numpy array (n, 3)":
    nodes = nodes.copy()
    nodes[:, :2] += spiral(
        fidelity=fidelity * direction,
        length=nodes.shape[0],
        start_angle=start_angle if direction == 1 else 180 - start_angle
    ) * radius
    return nodes

def spikes(
    fidelity: float, length: float, start_angle: float = 0
) -> "numpy array (n, 2)":
    """spikes with radius 1, uses random when fidelity is 0"""
    output = np.zeros((int(length) * 3, 2))
    output[1::3] = (
        spiral(fidelity, length, start_angle) 
    )
    return output

def add_spikes(nodes: "numpy array (n, 3)", fidelity: float, radius: float, spike_duration: float, start_angle: float = 0.0, direction: int = 1) -> "numpy array (n, 3)":
    node_count = nodes.shape[0]  # backup count before repeat
    nodes = np.repeat(nodes, 3, axis=0)
    nodes[::3] -= spike_duration
    nodes[1::3] -= spike_duration/2
    nodes[:, :2] += spikes(
        fidelity=fidelity * direction,
        length=node_count,
        start_angle=start_angle if direction == 1 else 180 - start_angle
    ) * radius
    return nodes

def create_lightning(data: DataContainer, interval: float, rail_filter: RailFilter|None=None) -> None:
    """create a zigzag between left hand and right hand notes and rails

    It picks the first rail (or longer if starting simultaneous) from either left and right as primary.
    Then it interpolates that, picking every other node from the secondary color if there is a rail/note there
    """
    new_filter = RailFilter(single=False) if rail_filter is None else dataclasses.replace(rail_filter, single=False)
    d = data.filtered(rail_filter=new_filter)
    if not d.left:
        raise ValueError("Input does not contain any left rails")
    if not d.right:
        raise ValueError("Input does not contain any right rails")
    first_l = sorted(d.left)[0]
    first_r = sorted(d.right)[0]
    end_l = d.left[first_l][-1,2]
    end_r = d.right[first_r][-1,2]

    primary = "right"
    if first_l < first_r or ((first_l == first_r) and (end_l > end_r)):
        # use left as primary if it starts first OR starts at the same time and ends later
        primary = "left"
    primary_nodes = d.left[first_l] if primary == "left" else d.right[first_r]
    secondary_notes = d.right if primary == "left" else d.left

    out = rails.interpolate_nodes(primary_nodes, "spline", interval=interval)
    for i in range(1, len(out), 2):
        new_pos = rails.get_position_at(secondary_notes, out[i,2], interpolate_gaps=False)
        if new_pos is not None:
            out[i, :2] = new_pos
    data.both = data.both | {out[0,2]: out}

def create_parallel(data: DataContainer, distance: float, types: tuple[str, ...] = NOTE_TYPES, rail_filter: RailFilter|None=None) -> None:
    """create parallel patterns by splitting specials, or adding the other hand
    
    when splitting specials, both will be moved by half the distance left and right.
    otherwise, the existing color stays, while the new hand is moved by distance in the "natural" direction.

    distance can be negative to create crossovers.
    """
    left_orig, right_orig = data.left, data.right  # create a backup of the input
    data.left = (
        left_orig
        | ({} if "right" not in types else {t: nodes - [distance,0,0] for t, nodes in sorted(right_orig.items()) if not rail_filter or rail_filter.matches(nodes)})  # shift over right hand by <distance>
        | ({} if "single" not in types else {t: nodes - [distance/2,0,0] for t, nodes in sorted(data.single.items()) if not rail_filter or rail_filter.matches(nodes)})  # shift over single & both by <distance>/2
        | ({} if "both" not in types else {t: nodes - [distance/2,0,0] for t, nodes in sorted(data.both.items()) if not rail_filter or rail_filter.matches(nodes)})
    )
    # vice versa for right hand
    data.right = (
        right_orig 
        | ({} if "left" not in types else {t: nodes + [distance,0,0] for t, nodes in sorted(left_orig.items()) if not rail_filter or rail_filter.matches(nodes)})
        | ({} if "single" not in types else {t: nodes + [distance/2,0,0] for t, nodes in sorted(data.single.items()) if not rail_filter or rail_filter.matches(nodes)})
        | ({} if "both" not in types else {t: nodes + [distance/2,0,0] for t, nodes in sorted(data.both.items()) if not rail_filter or rail_filter.matches(nodes)})
    )
    # wipe single & both (leaving only those NOT affected)
    if "single" in types:
        data.single = {} if not rail_filter else {t: nodes for t, nodes in sorted(data.single.items()) if not rail_filter.matches(nodes)}
    if "both" in types:
        data.both = {} if not rail_filter else {t: nodes for t, nodes in sorted(data.both.items()) if not rail_filter.matches(nodes)}

def find_wall_patterns(walls: WALLS) -> list[tuple[int, int, float]]:
    """try to find repeating "patterns" with identical wall type and timing, returns wall count per pattern, pattern count and pattern length for all possible candidates"""
    wall_count = len(walls)
    if wall_count < 2:
        raise ValueError("Need at least two walls to find repeating patterns")
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
    out = []
    for walls_per_pattern in reversed(matching_types):  # start with the largest candidate
        reshaped = wall_times.reshape((-1, walls_per_pattern)).copy()
        reshaped -= reshaped[:,0,np.newaxis]
        if np.allclose(reshaped[0], reshaped):
            out.append((walls_per_pattern, wall_count//walls_per_pattern, reshaped[0,-1]-reshaped[0,0]))
    if out:
        return out
    raise ValueError(f"Could not find any pattern of type AND timing that repeats consistently")

def blend_wall_single(first: "numpy array (n, 5)", second: "numpy array (n, 5)", interval: float, with_symmetry: bool=True) -> dict[float, "numpy array (1, 5)"]:
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

    out_walls: dict[float, "numpy array (1, 5)"] = {}

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
                new = movement.rotate(f[np.newaxis], angle=ang * (i/delta_t), pivot=piv)
                new[:,2] += i
                out_walls[new[0,2]] = new
    return out_walls

def blend_walls_multiple(patterns: "numpy array (m,n,5)", interval: float, with_symmetry: bool=True) -> dict[float, "numpy array (1, 5)"]:
    """calls blend_wall_single to blending between multiple patterns, each with n walls"""
    out_walls: dict[float, "numpy array (x*n, 5)"] = {}
    for first, second in zip(patterns[:-1], patterns[1:]):
        out_walls |= blend_wall_single(first, second, interval=interval, with_symmetry=with_symmetry)
    return out_walls

def generate_symmetry(source: dict[float, "numpy array (n, 5)"], operations: list[Literal["mirror_x", "mirror_y"]|int], interval: float, pivot_3d: "numpy_array (3)" = np.zeros((3,))) -> dict[float, "numpy array (n, 5)"]:
    out = source.copy()
    offset = np.array([0.0,0.0,interval,0.0,0.0])
    counter = 1
    for o in operations:
        new_out = out.copy()
        if o in ("mirror_x", "mirror_y"):
            scale = np.array([-1.0,1.0,1.0]) if o=="mirror_x" else np.array([1.0,-1.0,1.0])
            for _, v in sorted(out.items()):
                v = movement.scale(v, scale, pivot=pivot_3d) + offset*counter
                new_out[v[0,2]] = v
            counter += 1
        elif isinstance(o, int):
            for _, v in sorted(out.items()):
                ang = 360 / o
                for r in range(1,abs(o)):
                    vrot = movement.rotate(v, ang*r, pivot=pivot_3d) + offset*counter*r
                    new_out[vrot[0,2]] = vrot
            counter += (abs(o)-1)
        else:
            raise ValueError(f"Unknown symmetry operation {o!r}")
        out = new_out
    return out

def change_wall_type(walls: "numpy array (n, 5)", new_type: str|int, direction: int = 1) -> "numpy array (n, 5)":
    if isinstance(new_type, str):
        new_type = WALL_TYPES[new_type][0]
    out = walls.copy()
    out[..., 3] = new_type
    if new_type == WALL_TYPES["crouch"][0]:
        out[..., 4] = 0
    return out
