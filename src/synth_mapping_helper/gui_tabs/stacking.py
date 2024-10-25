from typing import Any, Optional

from nicegui import app, ui, elements
import numpy as np
import pyperclip

from .utils import *
from .map_render import SettingsPanel, MapScene
from ..utils import parse_number, parse_range, parse_xy_range, pretty_fraction, pretty_list
from .. import synth_format, movement, pattern_generation

def _icon_scale(val: str|None, icons: dict) -> str:
    if not val:
        return icons.get(0, "close")
    try:
        v = parse_number(val)
    except ValueError:
        return "error"
    if v > 1:
        return icons.get(1, "add")
    if v < 1:
        return icons.get(-1, "remove")
    return icons.get(0, "close")

def _mark_inputs(on: bool, *inp: ui.input) -> None:
    for i in inp:
        if on:
            i.props('bg-color="grey-6"')
        else:
            i.props(remove='bg-color="grey-6"')

def _register_marking(bt: ui.button, *inp: ui.input) -> ui.button:
    bt.on("pointerenter", lambda _: _mark_inputs(True, *inp))
    bt.on("pointerleave", lambda _: _mark_inputs(False, *inp))
    return bt

def _clear_button(*inp: ui.input) -> ui.button:
    def _clear_all() -> None:
        for o in inp:
            o.set_value(getattr(o, "default_value", "0"))
    bt = ui.button("Reset", icon="delete", color="negative", on_click=_clear_all)
    bt.props("outline size=sm align=left").classes("w-full")
    _register_marking(bt, *inp)
    return bt

def _find_first(types: tuple[str, ...] = synth_format.ALL_TYPES) -> Optional[tuple[str, "numpy array (3)"]]:
    with safe_clipboard_data(use_original=False, write=False) as d:
        first_t: Optional[str] = None
        first: Optional["numpy array (3+)"] = None
        for t in types:
            ty_objs = sorted(d.get_object_dict(t).items())
            if not ty_objs:
                continue
            _, ty_first = ty_objs[0]
            if first is None or ty_first[0,2] < first[2]:
                first_t = t
                first = ty_first[0]
        if first_t is None:
            return None
        return first_t, first


def _find_first_pair(types: tuple[str, ...] = synth_format.ALL_TYPES) -> Optional[tuple[str, "numpy array (3)", "numpy array (3)"]]:
    with safe_clipboard_data(use_original=False, write=False) as d:
        first_t: Optional[str] = None
        first: Optional["numpy array (3+)"] = None
        second: Optional["numpy array (3+)"] = None
        for t in types:
            ty_objs = sorted(d.get_object_dict(t).items())
            if len(ty_objs) < 2:
                continue
            _, ty_first = ty_objs[0]
            if second is None or ty_first[0,2] < second[2]:
                first_t = t
                first = ty_first[0]
                _, ty_second = ty_objs[1]
                second = ty_second[0]
        if first_t is None:
            return None
        return first_t, first, second

def _stack(
    d: synth_format.DataContainer, count: int, pivot: tuple[float, float, float],
    offset: tuple[float, float, float], scale: tuple[float, float, float], rotation: float, wall_rotation: float, outset: float,
    random_ranges_offset: list[tuple[tuple[float, float], tuple[float, float]]]|None, random_step_offset: tuple[float, float]|None, random_ranges_angle: list[tuple[float, float]]|None, random_step_angle: float|None
):
    pivot_np = np.array(pivot)
    stacking = d.filtered()  # deep copy
    rng = np.random.default_rng()
    for _ in range(count):
        if scale != [1,1,1]:
            stacking.apply_for_all(movement.scale, scale_3d=scale, pivot=pivot_np)
        if rotation:
            stacking.apply_for_all(movement.rotate, angle=rotation, pivot=pivot_np)
        if wall_rotation:
            stacking.apply_for_walls(movement.rotate, angle=wall_rotation, relative=True)
        stacking.apply_for_all(movement.offset, offset_3d=offset)
        if outset:
            stacking.apply_for_all(movement.outset, outset_scalar=outset, pivot=pivot_np)
        if random_ranges_offset is not None or random_ranges_angle is not None:
            tmp = stacking.filtered()  # deep copy
            if random_ranges_offset is not None:
                if len(random_ranges_offset) == 1:
                    area = random_ranges_offset[0]
                else:
                    areas = np.array([
                        max(x_max-x_min, 0.01)*max(y_max-y_min, 0.01)  # area, where 0-width axes are counted as 0.01 for numerical stability
                        for (x_min, y_min), (x_max, y_max) in random_ranges_offset
                    ])
                    area = rng.choice(random_ranges_offset, p=areas/sum(areas))
                if random_step_offset is not None:
                    xy_min, xy_max = area
                    random_offset = [random_step_offset[axis] * rng.integers(round(xy_min[axis]/random_step_offset[axis]), round(xy_max[axis]/random_step_offset[axis]), endpoint=True) for axis in (0,1)]
                else:
                    random_offset = pattern_generation.random_xy(1, area[0], area[1])[0]
                tmp.apply_for_all(movement.offset, offset_3d=[random_offset[0], random_offset[1], 0])
            if random_ranges_angle is not None:
                if len(random_ranges_angle) == 1:
                    ang_area = random_ranges_angle[0]
                else:
                    ang_areas = np.array([
                        max(a_max-a_min, 0.01)  # ang_area, where 0-width axes are counted as 0.01 for numerical stability
                        for a_max, a_min in random_ranges_angle
                    ])
                    ang_area = rng.choice(random_ranges_angle, p=ang_areas/sum(ang_areas))
                if random_step_angle is not None:
                    random_rotation = random_step_angle * rng.integers(round(ang_area[0]/random_step_angle), round(ang_area[1]//random_step_angle), endpoint=True)
                else:
                    random_rotation = rng.uniform(ang_area[0], ang_area[1])
                tmp.apply_for_all(movement.rotate, angle=random_rotation, pivot=pivot_np)
            d.merge(tmp)
        else:
            d.merge(stacking)

def make_input(label: str, value: str|float, storage_id: str, **kwargs) -> SMHInput:
    default_kwargs: dict[str, str|int] = {"tab_id": "stacking", "width": 24}
    return SMHInput(storage_id=storage_id, label=label, default_value=value, **(default_kwargs|kwargs))


def _stacking_tab() -> None:
    preview_scene: MapScene|None = None
    with ui.row():
        with ui.card():
            ui.label("Pivot")
            pivot_x = make_input("X", "0", "pivot_x", suffix="sq", negate_icons={1: "east", -1: "west"})
            pivot_y = make_input("Y", "0", "pivot_y", suffix="sq", negate_icons={1: "north", -1: "south"})

            @handle_errors
            def _pick_pivot():
                result = _find_first(types=synth_format.NOTE_TYPES)
                if result is None:
                    raise PrettyError(msg="No note found!")
                first_t, first = result
                pivot_x.set_value(pretty_fraction(first[0]))
                pivot_y.set_value(pretty_fraction(first[1]))
                info(f"Set pivot to first note ({first_t} hand{'s' if first_t == 'both' else ''})")
            with _register_marking(ui.button("Pivot", icon="colorize", on_click=_pick_pivot).props("outline size=sm align=left").classes("w-full"), pivot_x, pivot_y):
                ui.tooltip("Place pivot at first note")
            _clear_button(pivot_x, pivot_y)
        with ui.card():
            ui.label("Offset")
            offset_x = make_input("X", "0", "offset_x", suffix="sq", negate_icons={1: "east", -1: "west"})
            offset_y = make_input("Y", "0", "offset_y", suffix="sq", negate_icons={1: "north", -1: "south"})
            @handle_errors
            def _pick_offset():
                tfs = _find_first_pair()
                if tfs is None:
                    raise PrettyError(msg="No object pair found!")
                t, first, second = tfs
                delta = second - first
                offset_x.set_value(pretty_fraction(delta[0]))
                offset_y.set_value(pretty_fraction(delta[1]))
                offset_t.set_value(pretty_fraction(delta[2]))
                if len(delta) >= 5:
                    walls_angle.set_value(str(round((delta[4]+180)%360-180, 4)))
                info(f"Set offset from {t} object pair")
            with ui.button("Offset", icon="colorize", on_click=_pick_offset).props("outline size=sm align=left").classes("w-full") as pick_offset:
                ui.tooltip("Calculate offset between first two objects of the same type")
            _clear_button(offset_x, offset_y)
        with ui.card():
            ui.label("Scale")
            scale_x = make_input("X", "100%", "scale_x", tooltip="Can be given as % or ratio")
            with scale_x.add_slot("prepend"):
                ui.icon("close").classes("rotate-90").bind_name_from(scale_x, "value", lambda v: _icon_scale(v, {1: "unfold_more", -1: "unfold_less"}))
            scale_y = make_input("Y", "100%", "scale_y", tooltip="Can be given as % or ratio")
            with scale_y.add_slot("prepend"):
                ui.icon("close").bind_name_from(scale_y, "value", lambda v: _icon_scale(v, {1: "unfold_more", -1: "unfold_less"}))
            @handle_errors
            def _pick_scale():
                tfs = _find_first_pair()
                if tfs is None:
                    raise PrettyError(msg="No object pair found!")
                t, first, second = tfs
                delta = second - first
                try:
                    p = [pivot_x.parsed_value, pivot_y.parsed_value]
                except ParseInputError as pie:
                    error(f"Error parsing value: {pie.input_id}", pie, data=pie.value)
                    return
                if any(np.isclose(first[:2], p)):
                    error(f"{t} object pair too close to pivot", data={"type": t, "first": first.tolist(), "second": second.tolist(), "pivot": p})
                    return
                s_xy = (second[:2] - p) / (first[:2] - p)
                scale_x.set_value(pretty_fraction(s_xy[0]))
                scale_y.set_value(pretty_fraction(s_xy[1]))
                offset_t.set_value(pretty_fraction(delta[2]))
                if len(delta) >= 5:
                    walls_angle.set_value(str(round((delta[4]+180)%360-180, 4)))
                info(f"Set scale from {t} object pair")
            with ui.button("Scale", icon="colorize", on_click=_pick_scale).props("outline size=sm align=left").classes("w-full mt-auto") as pick_scale:
                ui.tooltip("Calculate scale (XY) between first two objects of the same type")
            _clear_button(scale_x, scale_y)
        with ui.card():
            ui.label("Rotation")
            pattern_angle = make_input("Pattern", "0", "pattern_angle", suffix="°", negate_icons={1: "rotate_left", -1: "rotate_right"})
            outset_amount = make_input("Outset", "0", "outset", suffix="sq", negate_icons={1: "open_in_full", -1: "close_fullscreen"})
            @handle_errors
            def _pick_rot():
                tfs = _find_first_pair()
                if tfs is None:
                    raise PrettyError(msg="No object pair found!")
                t, first, second = tfs
                delta = second - first
                try:
                    p = [pivot_x.parsed_value, pivot_y.parsed_value]
                except ParseInputError as pie:
                    error(f"Error parsing value: {pie.input_id}", pie, data=pie.value)
                    return
                if any(np.isclose(first[:2], p)):
                    error(f"{t} object pair too close to pivot", settings={"pivot": p}, data={"type": t, "first": first.tolist(), "second": second.tolist()})
                    return
                first = first[:2] - p
                second = second[:2] - p
                ang = np.degrees(np.arctan2(first[0], first[1])) - np.degrees(np.arctan2(second[0], second[1]))
                pattern_angle.set_value(pretty_fraction(ang))
                outset_amount.set_value(pretty_fraction(np.sqrt(second.dot(second)) - np.sqrt(first.dot(first))))
                offset_t.set_value(pretty_fraction(delta[2]))
                if len(delta) >= 5:
                    walls_angle.set_value(str(round((delta[4]+360-ang+180)%360-180, 4)))
                info(f"Set rotation and outset from {t} object pair")
            with ui.button("Rotate", icon="colorize", on_click=_pick_rot).props("outline size=sm align=left").classes("w-full") as pick_rot:
                ui.tooltip("Calculate Rotation and Outset between first two objects of the same type")
            _clear_button(pattern_angle, outset_amount)
        with ui.card():
            ui.label("All")
            walls_angle = make_input("Wall rotation", "0", "walls_angle", suffix="°", negate_icons={1: "rotate_left", -1: "rotate_right"})
            offset_t = make_input("Time", "1/16", "offset_t", suffix="b", negate_icons={1: "fast_forward", -1: "fast_rewind"})
            @handle_errors
            def _pick_spiral():
                tfs = _find_first_pair(synth_format.WALL_TYPES)
                if tfs is None:
                    raise PrettyError(msg="No object pair found!")
                t, first, second = tfs
                ang = (second[4] - first[4])
                divisor = np.sin(np.radians(ang/2))
                if divisor == 0:  # avoid division by 0 when angles match
                    error(f"Wall pair ({t}) have matching angle, cannot determine spiral", data={"first": first.tolist(), "second": second.tolist()})
                    return
                # calculate pivot naively
                p = first[:3] + movement.rotate((second - first)[:3]/2, 90 - ang/2) / divisor
                pivot_x.set_value(pretty_fraction(p[0]))
                pivot_y.set_value(pretty_fraction(p[1]))

                pattern_angle.set_value(str(round((ang+180)%360-180, 4)))
                offset_t.set_value(pretty_fraction(second[2] - first[2]))
            
                # reset the rest
                offset_x.set_value(offset_x.default_value)
                offset_y.set_value(offset_y.default_value)
                scale_x.set_value(scale_x.default_value)
                scale_y.set_value(scale_y.default_value)
                outset_amount.set_value(outset_amount.default_value)
                walls_angle.set_value(walls_angle.default_value)

                info(f"Calculated spiral from {t} wall pair")
            all_values = (
                pivot_x, pivot_y,
                offset_x, offset_y,
                scale_x, scale_y,
                pattern_angle, walls_angle,
                offset_t, outset_amount,
            )
            with _register_marking(ui.button("Spiral", icon="colorize", on_click=_pick_spiral).props("outline size=sm align=left").classes("w-full"), *all_values) as pick_spiral:
                ui.tooltip('Calculates "intuitive" spiral using two walls of the same type')
            _clear_button(*all_values)
        _register_marking(pick_offset, offset_x, offset_y, offset_t, walls_angle)
        _register_marking(pick_scale, scale_x, scale_y, offset_t, walls_angle)
        _register_marking(pick_rot, pattern_angle, outset_amount, offset_t, walls_angle)

        @handle_errors
        def _do_stack(count_mode: str):
            o_t = offset_t.parsed_value
            if not o_t:
                raise PrettyError("Time offset must not be 0", data=offset_t.value)
            p = (pivot_x.parsed_value, pivot_y.parsed_value, 0)
            o = (offset_x.parsed_value, offset_y.parsed_value, o_t)
            s = (scale_x.parsed_value, scale_y.parsed_value, 1)
            r = pattern_angle.parsed_value
            wr = walls_angle.parsed_value
            outset = outset_amount.parsed_value
            try:
                if not random_offset.value:  # empty string or None
                    random_ranges_offset = random_step_offset = None
                elif "@" in random_offset.value:
                    ranges, step = random_offset.value.rsplit("@", 1)
                    random_ranges_offset = [parse_xy_range(r) for r in ranges.split(";")]
                    if "," in step:
                        x, y = step.split(",",1)
                        random_step_offset = (parse_number(x), parse_number(y))
                    else:
                        xy = parse_number(step)
                        random_step_offset = (xy, xy)
                else:
                    random_ranges_offset = [parse_xy_range(r) for r in random_offset.value.split(";")]
                    random_step_offset = None
            except ValueError as ve:
                raise PrettyError(msg="Error parsing random XY ranges", exc=ve, data=random_offset.value) from ve
            try:
                if not random_angle.value:  # empty string or None
                    random_ranges_angle = random_step_angle = None
                elif "@" in random_angle.value:
                    ranges, step = random_angle.value.rsplit("@", 1)
                    random_ranges_angle = [parse_range(r) for r in ranges.split(";")]
                    random_step_angle = parse_number(step)
                else:
                    random_ranges_angle = [parse_range(r) for r in random_angle.value.split(";")]
                    random_step_angle = None
            except ValueError as ve:
                raise PrettyError(msg="Error parsing random angle ranges", exc=ve, data=random_angle.value) from ve
            try:
                with safe_clipboard_data(use_original=True, realign_start=False) as d:  # type: synth_format.ClipboardDataContainer
                    if count_mode == "count":
                        c = int(count.parsed_value)
                    elif count_mode == "duration":
                        c = int(duration.parsed_value / o_t)
                    elif count_mode == "fill":
                        c = int(d.selection_length / o_t)
                    _stack(
                        d=d, count=c, pivot=p,
                        offset=o, scale=s, rotation=r, wall_rotation=wr, outset=outset,
                        random_ranges_offset=random_ranges_offset, random_step_offset=random_step_offset,
                        random_ranges_angle=random_ranges_angle, random_step_angle=random_step_angle,
                    )
            except PrettyError:
                raise
            except Exception as exc:
                raise PrettyError(
                    msg=f"Error executing stack",
                    exc=exc,
                    context={"count": c, "pivot": p, "offset": o, "scale": s, "rotation": r, "wall_rotation": wr, "outset": outset},
                ) from exc
            counts = d.get_counts()
            info(
                f"Completed stack",
                caption=pretty_list([f"{counts[t]['total']} {t if counts[t]['total'] != 1 else t.rstrip('s')}" for t in ("notes", "rails", "rail_nodes", "walls")]),
            )
            if preview_scene is not None:
                preview_settings = sp.parse_settings()
                preview_scene.render(d, preview_settings)

        with ui.card():
            ui.label("Execute stack")
            with ui.button("Fill", icon="format_color_fill", on_click=lambda _: _do_stack("fill")).props("rounded").classes("w-full"):
                ui.tooltip("Stack until end of selection")
            ui.separator()
            with ui.row():
                count = make_input("Count", 15, "count", suffix="x", width=12)
                ui.button(icon="play_arrow", on_click=lambda _: _do_stack("count")).props("rounded").classes("w-10 mt-auto")
            ui.separator()
            with ui.row():
                duration = make_input("Duration", 1, "duration", suffix="b", width=12)
                ui.button(icon="play_arrow", on_click=lambda _: _do_stack("duration")).props("rounded").classes("w-10 mt-auto")
        with ui.card():
            ui.label("Substeps")
            subdiv_values = (
                offset_x, offset_y,
                scale_x, scale_y,
                pattern_angle, walls_angle,
                offset_t, outset_amount,
            )
            @handle_errors
            def _subdivide(substeps: float) -> None:
                for v in (offset_x, offset_y, pattern_angle, walls_angle,offset_t, outset_amount):
                    v.set_value(pretty_fraction(v.parsed_value/substeps))
                for v in (scale_x, scale_y):
                    v.set_value(f"{v.parsed_value**(1/substeps):.1%}")
            subdiv = make_input("Substeps", "2", "subdiv", tooltip="Number of substeps (should be >1)", suffix="x")
            with subdiv.add_slot("prepend"):
                ui.icon("density_medium")
            _register_marking(ui.button("Subdivide", on_click=lambda _: _subdivide(subdiv.parsed_value if subdiv.parsed_value else 1)).props("outline size=sm").classes("w-full"), *subdiv_values).tooltip("Divide current step into substeps")
            _register_marking(ui.button("Combine", on_click=lambda _: _subdivide((1/subdiv.parsed_value) if subdiv.parsed_value else 1)).props("outline size=sm").classes("w-full"), *subdiv_values).tooltip("Combine multiple steps into one")

        with ui.card():
            with ui.dialog() as random_dialog, ui.card():
                ui.markdown("""
                    This is applied on each copy individually, so the random range will stay centered on the unrandomized stack and not "drift".

                    Ranges are always uniformly distributed. To get non-uniform distributions, you can overlap ranges.

                    |Input|Example|Description|
                    |-|-|-|
                    |`<x>,<y>` |`5,3` |X is chosen randomly between -5 to +5 and Y between -3 and +3, equivalent to "-5:5,-3:3"|
                    |`<min_x>:<max_x>, <min_y>:<max_y>` |`-3:5, -1:1` |X is chosen randomly between -3 to +5 and Y between -1 and +1|
                    |`<range A>; <range B>` |`-10:-5, 1;5:10,1` |Multiple ranges (weighted based on size): Any offset in the two rectangles from -10,-1 to -5,+1 and +5,-1 to +10,+1|
                    |`... @<step_x>,<step_y>` |`-5,0:-3,0; 1,0:2,0 @1,1` |Must be at the end: Random values are always a multiple of the step (1sq here), so ie X will be chosen randomly from -5,-4,-3,+1,+2, while Y is always 0. When just step_x is given, that step is also used for Y|

                    Rotation works the same, except there is only a single value, not X and Y (ie `5;-2:1@0.5`)
                """)
            with ui.label("Random"):
                with ui.button(icon="help", on_click=random_dialog.open).props('flat text-color=info').classes("w-4 h-4 text-xs cursor-help"):
                    ui.tooltip("Show range input format help")
            # custom input format, don't use SMHInput
            random_offset = ui.input("XY Offset Range", value="").props('dense suffix="sq"').classes("w-24").bind_value(app.storage.user, "stacking_random_offset")
            random_offset.default_value = ""
            random_angle = ui.input("Rotation Range", value="").props('dense suffix="°"').classes("w-24").bind_value(app.storage.user, "stacking_random_angle")
            random_angle.default_value = ""
            _clear_button(random_offset, random_angle)

    with ui.card():
        @handle_errors
        def _soft_refresh():
            try:
                data = synth_format.ClipboardDataContainer.from_json(read_clipboard())
            except:
                # fall back to empty data on error
                data = synth_format.DataContainer()
            preview_settings = sp.parse_settings()
            if preview_scene is None:
                draw_preview_scene.refresh()
            if preview_scene is not None:
                preview_scene.render(data, preview_settings)
        with ui.row():
            with ui.row():
                ui.label("Clipboard Preview").classes("my-auto")
                with ui.button(icon="sync", on_click=_soft_refresh, color="positive").props("outline"):
                    ui.tooltip("Preview current clipboard")
            with ui.expansion("Preview Settings", icon="palette").props("dense"):
                sp = SettingsPanel()
                ui.separator()
                with ui.row():
                    ui.icon("preview", size="3em").tooltip("Change size and scaling of preview")
                    scene_width = make_input("Width", "800", "width", tab_id="preview", suffix="px", tooltip="Width of the preview in px", width=20)
                    scene_height = make_input("Height", "600", "height", tab_id="preview", suffix="px", tooltip="Height of the preview in px", width=20)
                    time_scale = make_input("Time Scale", "64", "time_scale", tab_id="preview", tooltip="Ratio between XY and time", width=20)
                    frame_length = make_input("Frame Length", "16", "frame_length", tab_id="preview", suffix="b", tooltip="Number of beats to draw frames for", width=20)
                apply_button = ui.button("Apply").props("outline")

        @ui.refreshable
        @handle_errors
        def draw_preview_scene():
            nonlocal preview_scene
            w = int(scene_width.parsed_value)
            h = int(scene_height.parsed_value)
            l = int(frame_length.parsed_value)
            t = time_scale.parsed_value
            preview_scene = MapScene(width=w, height=h, frame_length=l, time_scale=t)
            _soft_refresh()
        draw_preview_scene()
        apply_button.on("click", draw_preview_scene.refresh)

stacking_tab = GUITab(
    name="stacking",
    label="Stacking",
    icon="layers",
    content_func=_stacking_tab,
)
