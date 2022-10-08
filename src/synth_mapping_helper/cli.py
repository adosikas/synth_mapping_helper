from argparse import ArgumentParser, RawDescriptionHelpFormatter
from json import JSONDecodeError

import numpy as np

from . import synth_format, rails, pattern_generation, movement

def _parse_fraction(val: str) -> float:
    if "/" in val:
        a, b = val.split("/",1)
        return float(a) / float(b)
    return float(val)

def _parse_range(val: str) -> tuple[float, float]:
    if ":" not in val:
        return (0, _parse_fraction(val))
    split = val.split(":")
    if len(split) != 2:
        raise ValueError("Must be in the form 'max' or 'min:max'")
    try:
        min = _parse_fraction(split[0])
    except ValueError:
        raise ValueError("Error parsing minimum")
    try:
        max = _parse_fraction(split[1])
    except ValueError:
        raise ValueError("Error parsing maximum")
    return (min, max)

def _parse_xy_range(val: str) -> tuple[tuple[float, float], tuple[float, float]]:
    split = val.split(",")
    if len(split) != 2:
        raise ValueError("Must be in the form X_RANGE,Y_RANGE")
    try:
        x = _parse_range(split[0])
    except ValueError:
        raise ValueError("Error parsing x range")
    try:
        y = _parse_range(split[1])
    except ValueError:
        raise ValueError("Error parsing y range")
    return np.array((x, y)).transpose()


def _parse_position(val: str) -> tuple[float, float, float]:
    split = val.split(",")
    if len(split) != 3:
        raise ValueError("Must be in the form x,y,t")
    try:
        x = _parse_fraction(split[0])
    except ValueError:
        raise ValueError("Error parsing x")
    try:
        y = _parse_fraction(split[1])
    except ValueError:
        raise ValueError("Error parsing y")
    try:
        t = _parse_fraction(split[2])
    except ValueError:
        raise ValueError("Error parsing t")
    return (x,y,t)

def _movement_helper(data: synth_format.DataContainer, base_func, relative_func, pivot_func, relative: bool, pivot: list[int], *args, **kwargs) -> None:
    """pick the right function depending on relative or pivot being set"""
    if relative:
        data.apply_for_all(relative_func, *args, **kwargs)
    elif pivot:
        data.apply_for_all(pivot_func, *args, pivot=pivot, **kwargs)
    else:
        data.apply_for_all(base_func, *args, **kwargs)

def do_movement(options, data: synth_format.DataContainer, filter_types: list = synth_format.ALL_TYPES) -> None:
    if options.scale:
        _movement_helper(data, movement.scale, movement.scale_relative, movement.scale_from, options.relative, options.pivot, options.scale, types=filter_types)
    if options.rotate:
        _movement_helper(data, movement.rotate, movement.rotate_relative, movement.rotate_around, options.relative, options.pivot, options.rotate, types=filter_types)
    if options.offset:
        data.apply_for_all(movement.offset, options.offset, types=filter_types)
    if options.outset:
        _movement_helper(data, movement.outset, movement.outset_relative, movement.outset_from, options.relative, options.pivot, options.outset, types=filter_types)

def get_parser():
    parser = ArgumentParser(
        formatter_class=RawDescriptionHelpFormatter,
        description='\n'.join([
            f"Note types:\n\t{', '.join(synth_format.NOTE_TYPES)}",
            f"Wall types:\n\t{', '.join(synth_format.WALL_TYPES)}",
            "",
            "Most number values accept both numbers and fractions (ie '0.25' or '1/4')",
            "If your value starts with a '-', you must add a = between option and value, ie '--rotate=-45' or '--offset=-1,0,0'",
            "",
            "Angles are in degrees",
            "Vectors are specified as 'x,y,time:'",
            "\tX/Y is measured in editor grid squares, where +x is right and +y is up",
            "\tTime is measured in measures/beats",
        ])
    )

    parser.add_argument("--use-original", action="store_true", help="When calling this multiple times, start over with orignal copied json")
    parser.add_argument("-f", "--filter-types", nargs="+", metavar="FILTER_TYPE", choices=synth_format.ALL_TYPES, default=synth_format.ALL_TYPES, help=f"Only affect notes and walls of these types. Multiple types can be specified seperated by spaces, defaults to all")
    parser.add_argument("--invert-filter", action="store_true", help="Invert filter so everything *but* the filter is affected")

    preproc_group = parser.add_argument_group("pre-processing")
    preproc_group.add_argument("-b", "--bpm", type=_parse_fraction, help="Change BPM without changing timing")
    preproc_group.add_argument("--delete-others", action="store_true", help="Delete everything that doesn't match the filter")
    preproc_group.add_argument("--connect-singles", type=_parse_fraction, metavar="MAX_INTERVAL", help="Replace strings of single notes with rails if they are . Use with'--rails-to-singles=1' if you want to keep the singles")
    preproc_group.add_argument("--merge-rails", type=_parse_fraction, nargs="?", action="append", metavar="MAX_INTERVAL", help="Merge sequential rails. By default only joins rails that start close to where another ends (in X, Y AND time), but with MAX_INTERVAL only the time interval counts")
    preproc_group.add_argument("-n", "--change-notes", metavar="NEW_NOTE_TYPE", choices=synth_format.NOTE_TYPES, help=f"Change the type/color of notes")
    preproc_group.add_argument("-w", "--change-walls", metavar="NEW_WALL_TYPE", choices=synth_format.WALL_TYPES, help=f"Change the type/color of walls")

    rail_pattern_group = parser.add_argument_group("rail patterns")
    rail_pattern_group.add_argument("--interpolate", type=_parse_fraction, metavar="INTERVAL", help="Subdivide rail into segments of this length in beats, interpolating linearly. Supports fractions. When used with --spiral or --spikes, this is the distance between each nodes")
    rail_pattern_group.add_argument("--start-angle", type=_parse_fraction, default=0.0, metavar="DEGREES", help="Angle of the first node of the spiral in degrees. Default: 0/right")
    rail_pattern_group.add_argument("--radius", type=_parse_fraction, default=1.0, help="Radius of spiral or length of spikes")
    rail_pattern_group.add_argument("--spiral", type=_parse_fraction, metavar="NODES_PER_ROT", help="Generate counterclockwise spiral around rails with this number of nodes per full rotation. Supports fractions. 2=zigzag, negative=clockwise")
    rail_pattern_group.add_argument("--spikes", type=_parse_fraction, metavar="NODES_PER_ROT", help="Generate spikes from rail, either spiraling (see --spiral) or random (when set to 0)")
    rail_pattern_group.add_argument("--spike-width", type=_parse_fraction, default=1/32, help="Width of spike 'base' in beats. Supports fractions. Should not be lower than 1/32 (the default) and should be lower than chosen interpolation interval")

    movement_group = parser.add_argument_group("movement", description="Operation order is always: scale, rotate, offset, outset")
    movement_group.add_argument("-p", "--pivot", type=_parse_position, help="Pivot for outset, scale and rotate as x,y,t")
    movement_group.add_argument("--relative", action="store_true", help="Use first node of rails as pivot for scale/rotate")
    movement_group.add_argument("-s", "--scale", type=_parse_position, help="Scale positions by x,y,t. Use negative values to mirror across axis. Does NOT change the size of walls")
    movement_group.add_argument("-r", "--rotate", type=_parse_fraction, metavar="DEGREES", help="Rotate counterclockwise by this many degrees (negative for clockwise)")
    movement_group.add_argument("-o", "--offset", type=_parse_position, help="Move/Translate by x,y,t")
    movement_group.add_argument("--outset", type=_parse_fraction, metavar="DISTANCE", help="Move outwards")

    movement_group.add_argument("-c", "--stack-count", type=int, help="Instead of moving, create copies. Must have time offset set.")
    movement_group.add_argument("--offset-random", type=_parse_xy_range, metavar="[MIN_X:]MAX_X,[MIN_Y:]MAX_Y", help="Offset by a random amount in the X axis")

    postproc_group = parser.add_argument_group("post-processing")
    postproc_group.add_argument("--split-rails", action="store_true", help="Split rails at single notes")
    postproc_group.add_argument("--rails-to-singles", type=int, nargs="?", action="append", metavar="KEEP_RAIL", help="Replace rails with single notes at all nodes. KEEP_RAIL is optional and can be '1' if you want to keep the rail instead of replacing it")
    postproc_group.add_argument("--keep-alignment", action="store_true", help="Do NOT shift the start of selection to first element")

    return parser

def abort(reason: str):
    print("ERROR: " + reason)
    exit(1)

def main(options):
    if not options.invert_filter:
        # only have each entry once
        filter_types = list(set(options.filter_types))
    else:
        filter_types = list(
            t for t in synth_format.ALL_TYPES
            if t not in options.filter_types
        )
    try:
        data = synth_format.import_clipboard(options.use_original)
    except (JSONDecodeError, KeyError) as err:
        abort(f"Could not decode clipboard, did you copy somethinge else?\n\t{err!r}")

    # preprocessing
    if options.bpm:
        bpm_scale = [1, 1, options.bpm / data.bpm]
        data.apply_for_all(movement.scale, bpm_scale, types=filter_types)

    if options.delete_others:
        data = data.filtered(types=filter_types)
    if options.connect_singles:
        data.apply_for_note_types(rails.connect_singles, max_interval=options.connect_singles, types=filter_types)
    if options.merge_rails:
        if options.merge_rails[0] is None:
            data.apply_for_note_types(rails.merge_sequential_rails, types=filter_types)
        else:
            data.apply_for_note_types(rails.merge_rails, max_interval=options.merge_rails[0], types=filter_types)

    if options.change_notes:
        changed = {}
        for t in filter_types:
            if t in synth_format.NOTE_TYPES and t != options.change_notes:
                changed |= getattr(data, t)
                setattr(data, t, {})
        # existing notes always have priority
        changed |= getattr(data, options.change_notes)
        setattr(data, options.change_notes, changed)

    if options.change_walls:
        new_type = synth_format.WALL_TYPES[options.change_walls][0]
        def _change_wall_type(wall: "numpy array (1, 5)") -> "numpy array (1, 5)":
            new_wall = wall.copy()
            new_wall[..., 3] = new_type
            return new_wall
        data.apply_for_walls(_change_wall_type, types=filter_types)

    # rail patterns
    if options.interpolate:
        data.apply_for_notes(rails.interpolate_nodes_linear, options.interpolate, types=filter_types)
    if options.spiral:
        if (1 / options.spiral) % 1 == 0:
            abort("Chosen spiral factor divides 1 and would result in a straight rail. Refusing action!")
        def _add_spiral(nodes: "numpy array (n, 3)") -> "numpy array (n, 3)":
            nodes[:, :2] += pattern_generation.spiral(options.spiral, nodes.shape[0], options.start_angle) * options.radius
            return nodes
        data.apply_for_notes(_add_spiral, types=filter_types)
    if options.spikes is not None:
        def _add_spikes(nodes: "numpy array (n, 3)") -> "numpy array (n, 3)":
            count = nodes.shape[0]
            nodes = np.repeat(nodes, 3, axis=0)
            nodes[::3] -= options.spike_width
            nodes[1::3] -= options.spike_width/2
            nodes[:, :2] += pattern_generation.spikes(options.spikes, count, options.start_angle) * options.radius
            return nodes
        data.apply_for_notes(_add_spikes, types=filter_types)

    # movement
    if options.stack_count:
        if not options.offset or options.offset[2] == 0:
            abort("Cannot stack with time offset of 0")
        stacking = data.filtered(types=filter_types)
        for i in range(options.stack_count):
            do_movement(options, stacking)
            if options.offset_random is not None:
                tmp = stacking.filtered()  # deep copy
                random_offset = pattern_generation.random_xy(1, options.offset_random[0], options.offset_random[1])[0]
                tmp.apply_for_all(movement.offset, [random_offset[0], random_offset[1], 0])
                data.merge(tmp)
            else:
                data.merge(stacking)
    else:
        do_movement(options, data, filter_types=filter_types)
        if options.offset_random is not None:
            random_offset = pattern_generation.random_xy(1, options.offset_random[0], options.offset_random[1])[0]
            data.apply_for_all(movement.offset, [random_offset[0], random_offset[1], 0])

    # postprocessing
    if options.split_rails:
        data.apply_for_note_types(rails.split_rails, types=filter_types)
    if options.rails_to_singles:
        data.apply_for_note_types(rails.rails_to_singles, keep_rail=bool(options.rails_to_singles[0]), types=filter_types)
    synth_format.export_clipboard(data, not options.keep_alignment)

if __name__ == "__main__":
    main(get_parser().parse_args())