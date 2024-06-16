from argparse import ArgumentParser, RawDescriptionHelpFormatter
import itertools
from json import JSONDecodeError
from pathlib import Path

import numpy as np

from . import synth_format, rails, pattern_generation, movement, utils, __version__

_filter_groups = {
    "notes": synth_format.NOTE_TYPES,
    "walls": list(synth_format.WALL_TYPES),
    "slides": synth_format.SLIDE_TYPES,
}

def _movement_helper(data: synth_format.DataContainer, mirror_left: bool, base_func, relative_func, pivot_func, relative: bool, pivot: list[int], *args, **kwargs) -> None:
    """pick the right function depending on relative or pivot being set"""
    if relative:
        data.apply_for_all(relative_func, *args, mirror_left=mirror_left,  **kwargs)
    elif pivot is not None:
        data.apply_for_all(pivot_func, *args, mirror_left=mirror_left, pivot_3d=pivot, **kwargs)
    else:
        data.apply_for_all(base_func, *args, mirror_left=mirror_left, **kwargs)

def do_movement(options, data: synth_format.DataContainer, filter_types: tuple[str, ...] = synth_format.ALL_TYPES) -> None:
    common_args = dict(relative=options.relative, pivot=np.array(options.pivot), mirror_left=options.mirror_left, types=filter_types)
    if options.scale is not None:
        data.apply_for_all(movement.scale, scale_3d=options.scale, **common_args)
    if options.rotate is not None:
        data.apply_for_all(movement.rotate, angle=options.rotate, **common_args)
    if options.wall_rotate is not None:
        data.apply_for_walls(movement.rotate, angle=options.wall_rotate, relative=True, mirror_left=options.mirror_left, types=filter_types)
    if options.offset is not None:
        data.apply_for_all(movement.offset, offset_3d=options.offset, **common_args)
    if options.outset is not None:
        data.apply_for_all(movement.outset, outset_scalar=options.outset, **common_args)

def do_random_movement(options, data: synth_format.DataContainer, filter_types: tuple[str, ...] = synth_format.ALL_TYPES) -> None:
    if options.rotate_random is not None:
        if len(options.rotate_random) == 1:
            area = options.rotate_random[0]
        else:
            areas = np.array([
                max(a[1]-a[1], 0.01)  # area, where 0-width areas are counted as 0.01 for numerical stability
                for a in options.rotate_random
            ])
            area = options.rotate_random[np.random.choice(len(areas), p=areas/sum(areas))]
        random_angle = np.random.random_sample() * (area[1]-area[0]) + area[0]
        data.apply_for_all(movement.rotate, angle=random_angle, relative=options.relative, pivot=np.array(options.pivot), mirror_left=options.mirror_left, types=filter_types)

    if options.offset_random is not None:
        if len(options.offset_random) == 1:
            area = options.offset_random[0]
        else:
            areas = np.array([
                max(a[1,0]-a[0,0], 0.01)*max(a[1,1]-a[0,1], 0.01)  # area, where 0-width axes are counted as 0.01 for numerical stability
                for a in options.offset_random
            ])
            area = options.offset_random[np.random.choice(len(areas), p=areas/sum(areas))]
        random_offset = pattern_generation.random_xy(1, area[0], area[1])[0]
        data.apply_for_all(movement.offset, [random_offset[0], random_offset[1], 0], mirror_left=options.mirror_left, types=filter_types)
    
def get_parser():
    parser = ArgumentParser(
        formatter_class=RawDescriptionHelpFormatter,
        prog=f"python3 -m {__package__}.{Path(__file__).stem}",
        description='\n'.join([
            f"Note types:\n\t{', '.join(synth_format.NOTE_TYPES)}",
            f"Wall types:\n\t{', '.join(synth_format.WALL_TYPES)}",
            "",
            "Most number values accept decimals, percentages and fractions (ie '0.25', '25%' or '1/4')",
            "\tTime inputs may also be given in seconds (ie '81.5s' or '1:21.5'), which will be converted into beats",
            "If your value starts with a '-', you must add a = between option and value, ie '--rotate=-45' or '--offset=-1,0,0'",
            "For most options, only the last occurence is considered (exception: '--offset-random' and '--rotate-random')",
            "",
            "Angles are in degrees",
            "Vectors are specified as 'x,y,time':",
            "\tX/Y is measured in editor grid squares, where +x is right and +y is up",
            "\tTime is measured in measures/beats from the start of the selection",
            "",
            "Also see the wiki on GitHub, which contains more detailed explainations, as well as some examples and images: https://github.com/adosikas/synth_mapping_helper/wiki",
        ]),
        epilog=f"Version: {__version__}",
    )

    parser.add_argument("-E", "--start-empty", type=utils.parse_number, metavar="BPM", help="Start with empty data instead of reading the clipboard. Requires specifing BPM. Use with --spawn.")
    parser.add_argument("--use-original", action="store_true", help="When calling this multiple times, start over with orignal copied json")
    parser.add_argument("-f", "--filter-types", nargs="+", metavar="FILTER_TYPE", choices=synth_format.ALL_TYPES + tuple(_filter_groups), default=synth_format.ALL_TYPES, help=f"Only affect notes and walls of these types. Multiple types can be specified seperated by spaces, defaults to all")
    parser.add_argument("--invert-filter", action="store_true", help="Invert filter so everything *but* the filter is affected")
    parser.add_argument("--mirror-left", action="store_true", help="Mirror operations for the LEFT hand")

    preproc_group = parser.add_argument_group("pre-processing")
    preproc_group.add_argument("-b", "--bpm", type=utils.parse_number, help="Change BPM without changing timing")
    preproc_group.add_argument("--delete-others", action="store_true", help="Delete everything that doesn't match the filter")
    preproc_group.add_argument("--connect-singles", type=utils.parse_time, metavar="MAX_INTERVAL", help="Replace strings of single notes with rails if they are . Use with'--rails-to-singles=1' if you want to keep the singles")
    preproc_group.add_argument("--merge-rails", type=utils.parse_time, nargs="?", action="append", metavar="MAX_INTERVAL", help="Merge sequential rails. By default only joins rails that start close to where another ends (in X, Y AND time), but with MAX_INTERVAL only the time interval counts")
    preproc_group.add_argument("--swap-hands", action="store_true", help="Swap left and right hand notes.")
    preproc_group.add_argument("-n", "--change-notes", metavar="NEW_NOTE_TYPE", nargs="+", choices=synth_format.NOTE_TYPES, help=f"Change the type/color of notes. Specify multiple to loop over them.")
    preproc_group.add_argument("-w", "--change-walls", metavar="NEW_WALL_TYPE", nargs="+", choices=synth_format.WALL_TYPES, help=f"Change the type of walls. Specify multiple to loop over them.")
    preproc_group.add_argument("--spawn", metavar="OBJECT_TYPE", choices=synth_format.ALL_TYPES, help="Spawn an objects of the given type. Can only spawn one object per call.")
    preproc_group.add_argument("--spawn-location", type=utils.parse_position, help="Location for the spawned object (defaults to 0,0,0)")

    rail_pattern_group = parser.add_argument_group("rail patterns")
    interp_group = rail_pattern_group.add_mutually_exclusive_group()
    interp_group.add_argument("--interpolate", type=utils.parse_time, metavar="INTERVAL", help="Subdivide rail into segments of this length in beats, interpolating using splines close to the editor. Supports fractions. When used with --spiral or --spikes, this is the distance between each nodes")
    interp_group.add_argument("--interpolate-linear", type=utils.parse_time, metavar="INTERVAL", help="Subdivide rail into segments of this length in beats, interpolating linearly. Supports fractions. When used with --spiral or --spikes, this is the distance between each nodes")
    rail_pattern_group.add_argument("--shorten-rails", type=utils.parse_time, metavar="DISTANCE", help="Cut some distance from every rail. Supports fractions. When negative, cuts from the start instead of the end")
    rail_pattern_group.add_argument("--start-angle", type=utils.parse_number, default=0.0, metavar="DEGREES", help="Angle of the first node of the spiral in degrees. Default: 0/right")
    rail_pattern_group.add_argument("--radius", type=utils.parse_number, default=1.0, help="Radius of spiral or length of spikes")
    rail_op_group = rail_pattern_group.add_mutually_exclusive_group()
    rail_op_group.add_argument("--spiral", type=utils.parse_number, metavar="NODES_PER_ROT", help="Generate counterclockwise spiral around rails with this number of nodes per full rotation. Supports fractions. 2=zigzag, negative=clockwise")
    rail_op_group.add_argument("--spikes", type=utils.parse_number, metavar="NODES_PER_ROT", help="Generate spikes from rail, either spiraling (see --spiral) or random (when set to 0)")
    rail_pattern_group.add_argument("--spike-width", type=utils.parse_time, default=1/32, help="Width of spike 'base' in beats. Supports fractions. Should not be lower than 1/32 (the default) and should be lower than chosen interpolation interval")

    movement_group = parser.add_argument_group("movement", description="Operation order is always: scale, rotate, offset, outset")
    pivot_group = movement_group.add_mutually_exclusive_group()
    pivot_group.add_argument("-p", "--pivot", type=utils.parse_position, help="Pivot for outset, scale and rotate as x,y,t")
    pivot_group.add_argument("--note-pivot", choices=synth_format.NOTE_TYPES, help="Use position of first matching note as pivot (determined before any operations)")
    pivot_group.add_argument("--relative", action="store_true", help="Use first node of rails as pivot for outset, scale and rotate, and for walls offset because relative based on rotation")
    movement_group.add_argument("-s", "--scale", type=utils.parse_position, help="Scale positions by x,y,t. Use negative values to mirror across axis. Does NOT change the size of walls. Time-Scale of 2 means twice as long, not twice as fast.")
    movement_group.add_argument("-r", "--rotate", type=utils.parse_number, metavar="DEGREES", help="Rotate everything counterclockwise by this many degrees (negative for clockwise)")
    movement_group.add_argument("--wall-rotate", type=utils.parse_number, metavar="DEGREES", help="Rotate walls counterclockwise around themselves by this many degrees (negative for clockwise)")
    movement_group.add_argument("-o", "--offset", type=utils.parse_position, help="Move/Translate by x,y,t")
    movement_group.add_argument("--outset", type=utils.parse_number, metavar="DISTANCE", help="Move outwards (negative for inwards, can move 'across' pivot)")
    rail_stack_group = movement_group.add_mutually_exclusive_group()
    rail_stack_group.add_argument("--offset-along", choices=synth_format.NOTE_TYPES, help="While stacking: Offset objects to follow notes/rails of the specified type")
    rail_stack_group.add_argument("--rotate-with", choices=synth_format.NOTE_TYPES, help="While stacking: Rotate and outset the objects to follow notes/rails of the specified type")
    movement_group.add_argument("--offset-random", nargs="+", action="extend", type=utils.parse_xy_range, metavar="[MIN_X:]MAX_X,[MIN_Y:]MAX_Y", help="Offset by a random amount in the X and Y axis (ignoring relative & pivot). When no MIN is given, uses negative MAX. Multiple ranges can be specified, separated via space or as separate options (required when starting with '-').")
    movement_group.add_argument("--rotate-random", nargs="+", action="extend", type=utils.parse_range, metavar="[MIN_ANG:]MAX_ANG", help="Rotate by a random angle (obeying relative & pivot if given). When no MIN is given, uses negative MAX. Multiple ranges can be specified, separated via space or as separate options (required when starting with '-').")

    movement_group.add_argument("-c", "--stack-count", type=int, help="Instead of moving, create copies. Must have time offset set.")
    movement_group.add_argument("--stack-duration", type=utils.parse_time, help="Like --stack-count, but you can give it during in beats ('4') or seconds ('2s').")
    movement_group.add_argument("--autostack", nargs="?", choices=("OFFSET", "SPIRAL", "OUTSET", "SCALE"), action="append", metavar="OFFSET/SPIRAL/OUTSET/SCALE", help="Find the first pair of matching objects and continue the pattern. For continuing the positions, the following modes are supported: OFFSET (default, absolute xy), SPIRAL (rotate around implied pivot), OUTSET (distance from pivot) and SCALE (xy ratio).")

    postproc_group = parser.add_argument_group("post-processing")
    postproc_group.add_argument("--parallels", type=utils.parse_number, metavar="DISTANCE", help="Create parallel left/right handed patterns with given spacing from input. Negative numbers result in crossovers.")
    postproc_group.add_argument("--split-rails", action="store_true", help="Split rails at single notes")
    postproc_group.add_argument("--rails-to-singles", type=int, nargs="?", action="append", metavar="KEEP_RAIL", help="Replace rails with single notes at all nodes. KEEP_RAIL is optional and can be '1' if you want to keep the rail instead of replacing it")
    postproc_group.add_argument("--snap-singles-to-rail", action="store_true", help="Snap single notes to rail of the same color")
    postproc_group.add_argument("--keep-alignment", action="store_true", help="Do NOT shift the start of selection to first element")

    return parser

def abort(reason: str):
    if __name__ == "__main__":
        print("ERROR: " + reason)
        exit(1)
    else:
        raise RuntimeError(reason)

def main(options):
    if options.start_empty is not None:
        if options.start_empty <= 0:
            abort("BPM must be positive")
        data = synth_format.DataContainer(options.start_empty, {}, {}, {}, {}, {})
    else:
        try:
            data = synth_format.import_clipboard(options.use_original)
        except (JSONDecodeError, KeyError) as err:
            abort(f"Could not decode clipboard, did you copy somethinge else?\n\t{err!r}")
        except synth_format.JSONParseError as jpe:
            abort(
                "Detected invalid map data. The editor or your map may be corrupted.\n"
                "\tYou can try repairing the file using 'File Utils' tab of the GUI, or restoring from a backup.\n"
                "\tIf you know how to fix the json manually, the following should help (otherwise you may find help on the discord):\n"
                f"\t{jpe!r}\n"
                f"\tCaused by {jpe.__cause__!r}"
            )

    # argument post-parsing
    # convert time parsed in seconds to beats
    for pos_val in "spawn-location", "pivot", "offset", "scale":
        v = getattr(options, pos_val, None)
        if v is not None and isinstance(v[2], utils.SecondFloat):
            setattr(options, pos_val[:2] + (v[2].to_beat(data.bpm),))
    for time_val in "connect_singles", "merge_rails", "interpolate", "interpolate_linear", "shorten_rails", "spike_width", "stack_duration":
        v = getattr(options, time_val, None)
        if isinstance(v, utils.SecondFloat):
            setattr(options, time_val, v.to_beat(data.bpm))
    # expand filter groupts
    if any(name in options.filter_types for name in _filter_groups):
        out_filters = []
        for inp in options.filter_types:
            if inp in _filter_groups:
                out_filters.extend(_filter_groups[inp])
            else:
                out_filters.append(inp)
        options.filter_types = out_filters
    # normalize/invert filter
    if not options.invert_filter:
        # only have each entry once
        filter_types = list(set(options.filter_types))
    else:
        filter_types = list(
            t for t in synth_format.ALL_TYPES
            if t not in options.filter_types
        )
    # get note pivot (before filtering)
    if options.note_pivot:
        notes = getattr(data, options.note_pivot)
        if not notes:
            abort(f"Could not find any {options.note_pivot} notes")
        options.pivot = notes[sorted(notes)[0]][:3]

    # stacking
    if options.autostack is not None:
        if not options.stack_count and not options.stack_duration:
            abort("Cannot --autostack without count/duration")
        obj_type = None
        first = None
        second = None
        for t in synth_format.ALL_TYPES[::-1]:  # start with walls (for SPIRAL mode)
            obj_dict = data.get_object_dict(t)
            if len(obj_dict) >= 2:
                ty_objs = sorted(obj_dict.items())
                _, ty_first = ty_objs[0]
                if first is None or ty_first[0,2] < first[2]:
                    first = ty_first[0]  # rail head only
                    _, ty_second = ty_objs[1]
                    second = ty_second[0]
                    obj_type = t
        if first is None:
            abort("Could not find object pair for autostack")

        if options.autostack[0] == "SPIRAL":
            if first.shape[0] != 5:
                abort("Can only spiral-autostack based on walls")
            # rotation from point 'a' to point 'b', around pivot 'p' by angle 'ang':
            #   x_b = (x_a - x_p) * cos(ang) - (y_a - y_p) * sin(ang) + x_p
            #   y_b = (x_a - x_p) * sin(ang) + (y_a - y_p) * cos(ang) + y_p
            # I couldn't find a good way to solve that for x_p and y_p, so lets do it the geometric way:
            #   p must be an equal distance from both points, so together with p they form an isosceles triangle
            #   In this triangle we want the the angle at p (alpha) to match wall rotation, allowing us to calculate p using basic trigonometry
            #   In particular, the first point, the point halfway between both points and the pivot form a right triangle with an angle of alpha/2 at the pivot and an opposite of (b-a)/2
            #   Therefore, the hypotenuse will be ((b-a)/2) / sin(alpha/2) long and face the direction of (b-a)/2 rotated by 90-alpha/2
            options.rotate = second[4] - first[4]
            options.pivot = first[:3] + movement.rotate((second - first)[:3]/2, 90 - options.rotate/2) / np.sin(np.radians(options.rotate/2))
            options.offset = (0, 0, second[2] - first[2])
        else:
            if options.pivot is not None:
                first[:2] -= options.pivot[:2]
                second[:2] -= options.pivot[:2]

            if options.autostack[0] is None or options.autostack[0] == "OFFSET":
                options.offset = (second - first)[:3]
            elif options.autostack[0] == "OUTSET":
                # this is equivalent to the "rotate-with" calculations below
                options.rotate = np.degrees(np.arctan2(first[0], first[1])) - np.degrees(np.arctan2(second[0], second[1]))
                options.outset = np.sqrt(second[:2].dot(second[:2])) - np.sqrt(first[:2].dot(first[:2]))
                options.offset = (0, 0, second[2] - first[2])
            elif options.autostack[0] == "SCALE":
                options.scale = (second[0] / first[0], second[1] / first[1], 1)
                options.offset = (0, 0, second[2] - first[2])

            if first.shape[0] == 5:
                options.wall_rotate = ((second[4] - first[4]) - (options.rotate or 0)) or None  # see if we need to correct wall rotation

        # remove second object so it doesn't get stacked
        if obj_type in synth_format.NOTE_TYPES:
            del getattr(data, obj_type)[second[2]]
        else:
            del data.walls[second[2]]

    if options.stack_duration:
        if options.stack_count:
            abort("Cannot use --stack-count and --stack-duration at the same time")
        options.stack_count = int(options.stack_duration / options.offset[2])

    if options.stack_count and (options.offset is None or not options.offset[2]):
        abort("Cannot stack with time offset of 0")

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

    if options.swap_hands:
        data.left, data.right = data.right, data.left

    if options.change_notes:
        if len(options.change_notes) == 1:
            # to single type: just merge all dicts
            changed = {}
            for t in filter_types:
                if t in synth_format.NOTE_TYPES and t != options.change_notes[0]:
                    changed |= getattr(data, t)
                    setattr(data, t, {})
            # existing notes always have priority
            setattr(data, options.change_notes[0], changed | getattr(data, options.change_notes[0]))
        else:
            # to multiple types: cycle
            outputs = {}
            for t in options.change_notes:
                outputs[t] = {}
            for t in filter_types:
                if t in synth_format.NOTE_TYPES:
                    notes = getattr(data, t)
                    # note: looping happens independently for each note type
                    for time, new_type in zip(sorted(notes), itertools.cycle(options.change_notes)):
                        nodes = notes[time]
                        outputs[new_type][nodes[0,2]] = nodes
                    setattr(data, t, {})  # clear existing notes
            for t, notes in outputs.items():
                # existing notes (that did not get changed) always have priority
                setattr(data, t, notes | getattr(data, t))

    if options.change_walls:
        if len(options.change_walls) == 1:
            # to single type: just merge all arrays the same way
            new_type = synth_format.WALL_TYPES[options.change_walls[0]][0]
            data.apply_for_walls(pattern_generation.change_wall_type, types=filter_types, new_type=new_type)
        else:
            # to multiple types: cycle
            generator = itertools.cycle(synth_format.WALL_TYPES[t][0] for t in options.change_walls)
            def _change_wall_type(wall: "numpy array (1, 5)", direction: int=1) -> "numpy array (1, 5)":
                new_wall = wall.copy()
                new_wall[..., 3] = next(generator)
                return new_wall
            data.apply_for_walls(_change_wall_type, types=filter_types)

    if options.spawn:
        loc = options.spawn_location or (0.0,0.0,0.0)
        if options.spawn in synth_format.NOTE_TYPES:
            getattr(data, options.spawn)[loc[2]] = np.array([loc])
        elif options.spawn in synth_format.WALL_TYPES:
            data.walls[loc[2]] = np.array([loc + (synth_format.WALL_TYPES[options.spawn][0],0)])

    # rail patterns
    if options.interpolate:
        data.apply_for_notes(rails.interpolate_nodes, "spline", options.interpolate, types=filter_types)
    elif options.interpolate_linear:
        data.apply_for_notes(rails.interpolate_nodes, "linear", options.interpolate_linear, types=filter_types)
    if options.shorten_rails:
        data.apply_for_notes(rails.shorten_rail, options.shorten_rails, types=filter_types)
    if options.spiral:
        if (1 / options.spiral) % 1 == 0:
            abort("Chosen spiral factor divides 1 and would result in a straight rail. Refusing action!")
        data.apply_for_notes(
            pattern_generation.add_spiral,
            fidelity=options.spiral,
            radius=options.radius,
            start_angle=options.start_angle,
            types=filter_types,
            mirror_left=options.mirror_left,
        )
    if options.spikes is not None:
        data.apply_for_notes(
            pattern_generation.add_spikes,
            fidelity=options.spikes,
            radius=options.radius,
            spike_duration=options.spike_width,
            start_angle=options.start_angle,
            types=filter_types,
            mirror_left=options.mirror_left,
        )

    # movement
    if options.stack_count:
        stacking = data.filtered(types=filter_types)  # pre-filter
        if options.offset_along or options.rotate_with:
            if options.offset_along and options.rotate_with:
                abort("Cannot use offset-along and rotate-with at the same time")
            if options.relative:
                abort("Cannot use offset-along or rotate-with in relative mode")
            start_pos = rails.get_position_at(getattr(data, options.offset_along or options.rotate_with), 0)
            if start_pos is None:
                abort(f"No start position of {options.offset_along or options.rotate_with} notes found")
            if options.pivot is not None:
                start_pos -= options.pivot[:2]
        for i in range(options.stack_count):
            do_movement(options, stacking)
            tmp = stacking.filtered()  # deep copy
            if options.offset_along:
                cur_pos = rails.get_position_at(getattr(data, options.offset_along), (i+1) * options.offset[2])
                if cur_pos is None:
                    abort(f"No intermediate position of {options.offset_along} notes found at {(i+1) * options.offset[2]}")
                delta = cur_pos - start_pos
                tmp.apply_for_all(movement.offset, [delta[0], delta[1], 0], mirror_left=options.mirror_left)
            if options.rotate_with:
                cur_pos = rails.get_position_at(getattr(data, options.rotate_with), (i+1) * options.offset[2])
                if cur_pos is None:
                    abort(f"No intermediate position of {options.rotate_with} notes found at {(i+1) * options.offset[2]}")
                if options.pivot is not None:
                    cur_pos -= options.pivot[:2]
                angle_diff = np.degrees(np.arctan2(start_pos[0], start_pos[1])) - np.degrees(np.arctan2(cur_pos[0], cur_pos[1]))
                distance_diff = np.sqrt(cur_pos.dot(cur_pos)) - np.sqrt(start_pos.dot(start_pos))
                tmp.apply_for_all(movement.rotate, angle=angle_diff, pivot=np.array(options.pivot), mirror_left=options.mirror_left)
                # outset all objects together by precalculating the offset based on rail position
                group_outset_offset = [cur_pos[0], cur_pos[1], 0] / np.sqrt(cur_pos.dot(cur_pos)) * distance_diff
                tmp.apply_for_all(movement.offset, offset_3d=group_outset_offset) 
            do_random_movement(options, tmp)
            data.merge(tmp)
    else:
        if options.offset_along or options.rotate_with:
            abort("Cannot use offset-along or rotate-with without stacking")
        do_movement(options, data, filter_types=filter_types)
        do_random_movement(options, data, filter_types=filter_types)

    # postprocessing
    if options.parallels:
        pattern_generation.create_parallel(data, options.parallels)
    if options.split_rails:
        data.apply_for_note_types(rails.split_rails, types=filter_types)
    if options.rails_to_singles:
        data.apply_for_note_types(rails.rails_to_singles, keep_rail=bool(options.rails_to_singles[0]), types=filter_types)
    if options.snap_singles_to_rail:
        data.apply_for_note_types(rails.snap_singles_to_rail, types=filter_types)
    synth_format.export_clipboard(data, not options.keep_alignment)

def entrypoint():
    main(get_parser().parse_args())

if __name__ == "__main__":
    entrypoint()
