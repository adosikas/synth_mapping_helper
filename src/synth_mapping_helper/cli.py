from argparse import ArgumentParser

import numpy as np

from . import synth_format, rails, pattern_generation, movement

def _parse_fraction(val: str) -> float:
    if "/" in val:
        a, b = val.split("/",1)
        return float(a) / float(b)
    return float(val)

def _parse_position(val: str) -> list[int]:
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
    return [x,y,t]   

def do_movement(options, data: synth_format.DataContainer, filter_types: list = synth_format.ALL_TYPES) -> None:
    if options.scale:
        if options.relative:
            data.apply_for_all(movement.scale_relative, options.scale, types=filter_types)
        elif options.pivot:
            data.apply_for_all(movement.scale_from, options.scale, options.pivot, types=filter_types)
        else:
            data.apply_for_all(movement.scale, options.scale, types=filter_types)
    if options.rotate:
        if options.relative:
            data.apply_for_all(movement.rotate_relative, options.rotate, types=filter_types)
        elif options.pivot:
            data.apply_for_all(movement.rotate_around, options.rotate, options.pivot, types=filter_types)
        else:
            data.apply_for_all(movement.rotate, options.rotate, types=filter_types)
    if options.offset:
        data.apply_for_all(movement.offset, options.offset, types=filter_types)
    if options.outset:
        if options.relative:
            data.apply_for_all(movement.outset_relative, options.outset, types=filter_types)
        elif options.pivot:
            data.apply_for_all(movement.outset_from, options.outset, options.pivot, types=filter_types)
        else:
            data.apply_for_all(movement.outset, options.outset, types=filter_types)

def get_parser():
    parser = ArgumentParser()

    parser.add_argument("--use-original", action="store_true", help="When calling this multiple times, start over with orignal copied json")
    parser.add_argument("-f", "--filter-types", nargs="+", choices=synth_format.ALL_TYPES, default=synth_format.ALL_TYPES, help="Only affect notes/walls of these types. Multiple types can be specified seperated by spaces, defaults to all")

    preproc_group = parser.add_argument_group("pre-processing")
    preproc_group.add_argument("--merge-rails", action="store_true", help="Merge sequential rails")
    preproc_group.add_argument("-n", "--change-notes", choices=synth_format.NOTE_TYPES, help="Change the type/color of notes")
    preproc_group.add_argument("-w", "--change-walls", choices=synth_format.WALL_TYPES, help="Change the type/color of walls")

    rail_pattern_group = parser.add_argument_group("rail patterns")
    rail_pattern_group.add_argument("--interpolate", type=_parse_fraction, metavar="float_or_fraction", help="Subdivide rail into segments of this length in beats, interpolating linearly. Supports fractions. When used with --spiral or --spikes, this is the distance between each nodes")
    rail_pattern_group.add_argument("--start-angle", type=float, default=0.0, help="Angle of the first node of the spiral in degrees. Default: 0/right")
    rail_pattern_group.add_argument("--radius", type=_parse_fraction, default=1.0, help="Radius of spiral or length of spikes")
    rail_pattern_group.add_argument("--spiral", type=_parse_fraction, help="Generate counterclockwise spiral around rails with this number of nodes per full rotation. Supports fractions. 2=zigzag, negative=clockwise")
    rail_pattern_group.add_argument("--spikes", type=_parse_fraction, help="Generate spikes from rail, either spiraling (see --spiral) or random (when set to 0)")
    rail_pattern_group.add_argument("--spike-width", type=_parse_fraction, default=1/32, help="Width of spike 'base' in beats. Supports fractions. Should not be lower than 1/32 (the default) and should be lower than chosen interpolation interval")

    movement_group = parser.add_argument_group("movement", description="X and Y are in edtor grid positions (+x=right, +y=up), Time is in beats. Operation order is scale, rotate, offset, outset.")
    movement_group.add_argument("-p", "--pivot", type=_parse_position, help="Pivot for outset, scale and rotate as x,y,t")
    movement_group.add_argument("--relative", action="store_true", help="Use first node of rails as pivot for scale/rotate")
    movement_group.add_argument("-s", "--scale", type=_parse_position, help="Scale positions by x,y,t. Use negative values to mirror across axis. Does NOT change the size of walls")
    movement_group.add_argument("-r", "--rotate", type=float, help="Rotate counterclockwise by this many degrees (negative for clockwise)")
    movement_group.add_argument("-o", "--offset", type=_parse_position, help="Move/Translate by x,y,t")
    movement_group.add_argument("--outset", type=_parse_fraction, help="Move outwards")

    movement_group.add_argument("-c", "--stack-count", type=int, help="Instead of moving, create copies. Must have time offset set.")


    postproc_group = parser.add_argument_group("post-processing")
    postproc_group.add_argument("--split-rails", action="store_true", help="Split rails at single notes")
    postproc_group.add_argument("--keep-alignment", action="store_true", help="Do NOT shift the start of selection to first element")

    return parser

def main(options):
    filter_types = list(set(options.filter_types))
    data = synth_format.import_clipboard(options.use_original)
    # preprocessing
    if options.merge_rails:
        data.apply_for_note_types(rails.merge_rails, types=filter_types)

    if options.change_notes:
        changed = {}
        for t in filter_types:
            if t in synth_format.NOTE_TYPES and t != options.change_notes:
                changed |= getattr(data, t)
                setattr(data, t, {})
        # existing notes always have priority
        changed |= getattr(data, options.change_notes)
        setattr(data, options.change_notes, changed)

    # rail patterns
    if options.interpolate:
        data.apply_for_notes(rails.interpolate_nodes_linear, options.interpolate, types=filter_types)
    if options.spiral:
        if (1 / options.spiral) % 1 == 0:
            raise ValueError("Chosen spiral factor divides 1 and would result in a straight rail. Refusing action!")
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
            raise ValueError("Cannot stack with time offset of 0")
        stacking = data.filtered(types=filter_types)
        for i in range(options.stack_count):
            do_movement(options, stacking)
            data.merge(stacking)
    else:
        do_movement(options, data, types=filter_types)

    # postprocessing
    if options.split_rails:
        data.apply_for_note_types(rails.split_rails, types=filter_types)
    synth_format.export_clipboard(data, not options.keep_alignment)

if __name__ == "__main__":
    main(get_parser().parse_args())