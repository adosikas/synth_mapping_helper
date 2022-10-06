from argparse import ArgumentParser

from . import synth_format, rails, pattern_generation, movement

def _parse_3d_vector(val: str) -> list[int]:
    split = val.split(",")
    if len(split) != 3:
        raise ValueError("Must be in the form x,y,t")
    try:
        x = float(split[0])
    except ValueError:
        raise ValueError("Error parsing x")
    try:
        y = float(split[1])
    except ValueError:
        raise ValueError("Error parsing y")
    try:
        t = float(split[2])
    except ValueError:
        raise ValueError("Error parsing t")
    return [x,y,t]    

def get_parser():
    parser = ArgumentParser()

    parser.add_argument("--use-original", action="store_true", help="When calling this multiple times, start over with orignal copied json")
    parser.add_argument("-f", "--filter-types", nargs="+", choices=synth_format.TYPES, default=synth_format.TYPES, help="Only affect notes of this type. Multiple types can be specified seperated by spaces, defaults to all")

    preproc_group = parser.add_argument_group("pre-processing")
    preproc_group.add_argument("--merge-rails", action="store_true", help="Merge sequential rails")
    preproc_group.add_argument("-t", "--change-type", choices=synth_format.TYPES, help="Change the type/color of notes")

    movement_group = parser.add_argument_group("movement", description="X and Y are in edtor grid positions (+x=right, +y=up), Time is in beats. Operation order is scale, rotate, offset.")
    movement_group.add_argument("-p", "--pivot", type=_parse_3d_vector, help="Pivot for scale and rotate as x,y,t")
    movement_group.add_argument("--relative", action="store_true", help="Use first node of rails as pivot for scale/rotate")
    movement_group.add_argument("-s", "--scale", type=_parse_3d_vector, help="Scale by x,y,t. Use negative values to mirror across axis")
    movement_group.add_argument("-r", "--rotate", type=float, help="Rotate counterclockwise by degrees (can also be negative)")
    movement_group.add_argument("-o", "--offset", type=_parse_3d_vector, help="Move/Translate by x,y,t")

    postprocessing_group = parser.add_argument_group("post-processing")
    postprocessing_group.add_argument("--split-rails", action="store_true", help="Split rails at single notes")
    postprocessing_group.add_argument("--keep-alignment", action="store_true", help="Do NOT shift the start of selection to first element")

    return parser

def main(options):
    data = synth_format.import_clipboard(options.use_original)
    # preprocessing
    if options.merge_rails:
        data.apply_for_note_types(rails.merge_rails, types=options.filter_types)

    if options.change_type:
        changed = {}
        for t in (("right", "left", "single", "both") if not options.filter_types else options.filter_types):
            if t != options.change_type:
                changed |= getattr(data, t)
                setattr(data, t, {})
        # existing notes always have priority
        changed |= getattr(data, options.change_type)
        setattr(data, options.change_type, changed)

    # movement
    if options.scale:
        if options.relative:
            data.apply_for_notes(movement.scale_relative, options.scale, types=options.filter_types)
        elif options.pivot:
            data.apply_for_notes(movement.scale_from, options.scale, options.pivot, types=options.filter_types)
        else:
            data.apply_for_notes(movement.scale, options.scale, types=options.filter_types)
    if options.rotate:
        if options.relative:
            data.apply_for_notes(movement.rotate_relative, options.rotate, types=options.filter_types)
        elif options.pivot:
            data.apply_for_notes(movement.rotate_around, options.rotate, options.pivot, types=options.filter_types)
        else:
            data.apply_for_notes(movement.rotate, options.rotate, types=options.filter_types)
    if options.offset:
        data.apply_for_notes(movement.offset, options.offset, types=options.filter_types)

    # postprocessing
    if options.split_rails:
        data.apply_for_note_types(rails.split_rails, types=options.filter_types)
    synth_format.export_clipboard(data, not options.keep_alignment)

if __name__ == "__main__":
    main(get_parser().parse_args())