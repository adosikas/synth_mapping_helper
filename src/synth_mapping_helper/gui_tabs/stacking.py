from typing import Any, Optional

from nicegui import app, ui, elements
import numpy as np
import pyperclip

from .utils import *
from .map_render import SettingsPanel, MapScene
from ..utils import parse_number, pretty_fraction
from .. import synth_format, movement

def _negate(val: str|None) -> str|None:
    if not val:
        return val
    if val.startswith("-"):
        return val[1:]
    return "-" + val

def _icon(val: str|None, icons: dict) -> str:
    try:
        v = parse_number(val)
    except ValueError:
        return "error"
    if v > 0:
        return icons.get(1, "add")
    if v < 0:
        return icons.get(-1, "remove")
    return icons.get(0, "close")

def _icon_scale(val: str|None, icons: dict) -> str:
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
    bt = ui.button("Reset", icon="delete", color="negative", on_click=lambda _: [o.set_value(getattr(o, "default_value", "0")) for o in inp])
    bt.props("outline size=sm align=left").classes("w-full")
    _register_marking(bt, *inp)
    return bt

def _find_first_pair(types: list[str] = synth_format.ALL_TYPES) -> Optional[tuple[str, "numpy array (3)", "numpy array (3)"]]:
    clipboard = pyperclip.paste()
    try:
        d = synth_format.import_clipboard_json(clipboard, use_original=False)
    except ValueError as ve:
        error(f"Error reading data from clipboard", ve, data=clipboard)
        return None
    first_t: Optional[str] = None
    first: Optional["numpy array (3+)"] = None
    second: Optional["numpy array (3+)"] = None
    for t in types:
        n = sorted(d.get_object_dict(t).items())
        if len(n) >= 2 and (second is None or n[0][2][0,2] < second[2]):
            first_t = t
            first = n[0][1][0]
            second = n[1][1][0]
    if first_t is None:
        return None
    return first_t, first, second

def _stack(d: synth_format.DataContainer, count: int, pivot: tuple[float, float, float], offset: tuple[float, float, float], scale: tuple[float, float, float], rotation: float, wall_rotation: float, outset: float):
    stacking = d.filtered()  # deep copy
    for _ in range(count):
        if scale != [1,1,1]:
            stacking.apply_for_all(movement.scale_from, scale_3d=scale, pivot_3d=pivot)
        if rotation:
            stacking.apply_for_all(movement.rotate_around, angle=rotation, pivot_3d=pivot)
        if wall_rotation:
            stacking.apply_for_walls(movement.rotate_relative, wall_rotation)
        stacking.apply_for_all(movement.offset, offset_3d=offset)
        if outset:
            stacking.apply_for_all(movement.outset_from, outset_scalar=outset, pivot_3d=pivot)
        d.merge(stacking)

class SMHInput(ui.input):
    def __init__(self, label: str, value: str|float, storage_id: str, tooltip: Optional[str]=None, suffix: Optional[str] = None, icons: dict[int, str]|None = None,**kwargs):
        super().__init__(label=label, value=str(value), **kwargs)
        self.bind_value(app.storage.user, f"stacking_{storage_id}")
        self.classes("w-24 h-10")
        self.props('dense input-style="text-align: right" no-error-icon')
        self.storage_id = storage_id
        self.default_value = value
        if suffix:
            self.props(f'suffix="{suffix}"')
        with self:
            if tooltip is not None:
                ui.tooltip(tooltip)
        if icons is not None:
            with self.add_slot("prepend"):
                self.icon = ui.icon("", color="primary").classes("border-2 rounded cursor-pointer").on(
                    "click", lambda e: self.set_value(_negate(self.value))
                ).bind_name_from(self, "value", lambda v: _icon(v, icons))
                ui.tooltip("Click to negate")
        with self.add_slot("error"):
            ui.element().style("visiblity: hidden")

    def _handle_value_change(self, value: Any) -> None:
        super()._handle_value_change(value)
        try:
            parse_number(value)
            self.props(remove="error")
        except ValueError:
            self.props(add="error")

    @property
    def parsed_value(self) -> float:
        try:
            return parse_number(self.value)
        except ValueError as ve:
            raise ParseInputError(self.storage_id, self.value) from ve

def stacking_tab():
    preview_scene: MapScene|None = None
    with ui.row():
        with ui.card():
            ui.label("Pivot")
            pivot_x = SMHInput("X", "0", "pivot_x", suffix="sq", icons={1: "east", -1: "west"})
            pivot_y = SMHInput("Y", "0", "pivot_y", suffix="sq", icons={1: "north", -1: "south"})

            def _pick_pivot():
                clipboard = pyperclip.paste()
                try:
                    d = synth_format.import_clipboard_json(clipboard, use_original=False)
                except ValueError as ve:
                    error(f"Error reading data from clipboard", ve, data=clipboard)
                    return
                first_t: Optional[str] = None
                first: Optional["numpy array (3)"] = None
                for t in synth_format.NOTE_TYPES:
                    n = sorted(d.get_object_dict(t).items())
                    if n and (first is None or n[0][1][0,2] < first[2]):
                        first_t = t
                        first = n[0][1][0]
                if first_t is None:
                    error("No note found!")
                pivot_x.set_value(pretty_fraction(first[0]))
                pivot_y.set_value(pretty_fraction(first[1]))
                info(f"Set pivot to first note ({first_t} hand{'s' if first_t == 'both' else ''})")
            with _register_marking(ui.button("Pivot", icon="colorize", on_click=_pick_pivot).props("outline size=sm align=left").classes("w-full"), pivot_x, pivot_y):
                ui.tooltip("Place pivot at first note")
            _clear_button(pivot_x, pivot_y)
        with ui.card():
            ui.label("Offset")
            offset_x = SMHInput("X", "0", "offset_x", suffix="sq", icons={1: "east", -1: "west"})
            offset_y = SMHInput("Y", "0", "offset_y", suffix="sq", icons={1: "north", -1: "south"})
            def _pick_offset():
                tfs = _find_first_pair()
                if tfs is not None:
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
            scale_x = SMHInput("X", "100%", "scale_x", tooltip="Can be given as % or ratio")
            with scale_x.add_slot("prepend"):
                ui.icon("close").classes("rotate-90").bind_name_from(scale_x, "value", lambda v: _icon_scale(v, {1: "unfold_more", -1: "unfold_less"}))
            scale_y = SMHInput("Y", "100%", "scale_y", tooltip="Can be given as % or ratio")
            with scale_y.add_slot("prepend"):
                ui.icon("close").bind_name_from(scale_y, "value", lambda v: _icon_scale(v, {1: "unfold_more", -1: "unfold_less"}))
            def _pick_scale():
                tfs = _find_first_pair()
                if tfs is None:
                    error("No object pairs found!")
                    return
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
                s_xy = (second[:2] - p) / (first[:2] - p)
                scale_x.set_value(pretty_fraction(s_xy[0]))
                scale_y.set_value(pretty_fraction(s_xy[1]))
                offset_t.set_value(pretty_fraction(delta[2]))
                if len(delta) >= 5:
                    walls_angle.set_value(str(round((delta[4]+180)%360-180, 4)))
                info(f"Set offset from {t} object pair")
            with ui.button("Scale", icon="colorize", on_click=_pick_scale).props("outline size=sm align=left").classes("w-full mt-auto") as pick_scale:
                ui.tooltip("Calculate scale (XY) between first two objects of the same type")
            _clear_button(scale_x, scale_y)
        with ui.card():
            ui.label("Rotation")
            pattern_angle = SMHInput("Pattern", "0", "pattern_angle", suffix="°", icons={1: "rotate_left", -1: "rotate_right"})
            outset_amount = SMHInput("Outset", "0", "outset", suffix="sq", icons={1: "open_in_full", -1: "close_fullscreen"})
            def _pick_rot():
                tfs = _find_first_pair()
                if tfs is None:
                    error("No object pairs found!")
                    return
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
                info(f"Set offset from {t} object pair")
            with ui.button("Rotate", icon="colorize", on_click=_pick_rot).props("outline size=sm align=left").classes("w-full") as pick_rot:
                ui.tooltip("Calculate Rotation and Outset between first two objects of the same type")
            _clear_button(pattern_angle, outset_amount)
        with ui.card():
            ui.label("All")
            offset_t = SMHInput("Time", "1/16", "offset_t", suffix="b", icons={1: "fast_forward", -1: "fast_rewind"})
            walls_angle = SMHInput("Walls", "0", "walls_angle", suffix="°", icons={1: "rotate_left", -1: "rotate_right"})
            def _pick_spiral():
                tfs = _find_first_pair(list(synth_format.WALL_TYPES))
                if tfs is None:
                    error("No wall pairs found!")
                    return
                t, first, second = tfs
                ang = (second[4] - first[4])
                p = first[:3] + movement.rotate((second - first)[:3]/2, 90 - ang/2) / np.sin(np.radians(ang/2))

                pivot_x.set_value(pretty_fraction(p[0]))
                pivot_y.set_value(pretty_fraction(p[1]))

                offset_x.set_value(offset_x.default_value)
                offset_y.set_value(offset_y.default_value)

                scale_x.set_value(scale_x.default_value)
                scale_y.set_value(scale_y.default_value)

                pattern_angle.set_value(str(round((ang+180)%360-180, 4)))
                outset_amount.set_value(outset_amount.default_value)

                walls_angle.set_value("0")
                offset_t.set_value(pretty_fraction(second[2] - first[2]))

                info(f"Set offset from {t} object pair")
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

        def _do_stack(count_mode: str):
            clipboard = pyperclip.paste()
            try:
                d = synth_format.import_clipboard_json(clipboard, use_original=True)
            except ValueError as ve:
                error(f"Error reading data from clipboard", ve, data=clipboard)
                return None
            try:
                o_t = offset_t.parsed_value
                if not o_t:
                    error("Time offset must not be 0", data=offset_t.value)
                    return
                if count_mode == "count":
                    c = int(count.parsed_value)
                elif count_mode == "duration":
                    c = int(duration.parsed_value / o_t)
                elif count_mode == "fill":
                    c = int(d.selection_length / o_t)
                p = [pivot_x.parsed_value, pivot_y.parsed_value, 0]
                o = [offset_x.parsed_value, offset_y.parsed_value, o_t]
                s = [scale_x.parsed_value, scale_y.parsed_value, 1]
                r = pattern_angle.parsed_value
                wr = walls_angle.parsed_value
                outset = outset_amount.parsed_value
            except ParseInputError as pie:
                error(f"Error parsing value: {pie.input_id}", pie, data=pie.value)
                return
            try:
                _stack(d, c, p, o, s, r, wr, outset)
            except Exception as exc:
                error(f"Error executing stack", exc, settings={"count": c, "pivot": p, "offset": o, "scale": s, "rotation": r, "wall_rotation": wr, "outset": outset}, data=clipboard)
                return
            counts = d.get_counts()
            info(
                f"Completed stack",
                caption=", ".join(f"{counts[t]['total']} {t if counts[t]['total'] != 1 else t.rstrip('s')}" for t in ("notes", "rails", "rail_nodes", "walls")),
            )
            synth_format.export_clipboard(d, realign_start=False)
            if preview_scene is not None:
                try:
                    preview_settings = sp.parse_settings()
                except ParseInputError as pie:
                    error(f"Error parsing preview setting: {pie.input_id}", pie, data=pie.value)
                    return
                preview_scene.render(d, preview_settings)

        with ui.card():
            ui.label("Execute stack")
            with ui.button("Fill", icon="format_color_fill", on_click=lambda _: _do_stack("fill")).props("rounded").classes("w-full"):
                ui.tooltip("Stack until end of selection")
            ui.separator()
            with ui.row():
                count = SMHInput("Count", 15, "count", suffix="x").classes("w-12", remove="w-24")
                ui.button(icon="play_arrow", on_click=lambda _: _do_stack("count")).props("rounded").classes("w-10 mt-auto")
            ui.separator()
            with ui.row():
                duration = SMHInput("Duration", 1, "duration", suffix="b").classes("w-12", remove="w-24")
                ui.button(icon="play_arrow", on_click=lambda _: _do_stack("duration")).props("rounded").classes("w-10 mt-auto")

    with ui.card():
        def _soft_refresh():
            try:
                data = synth_format.import_clipboard()
            except:
                data = synth_format.DataContainer()
            try:
                preview_settings = sp.parse_settings()
            except ParseInputError as pie:
                error(f"Error parsing preview setting: {pie.input_id}", pie, data=pie.value)
                return
            if preview_scene is None:
                draw_preview_scene.refresh()
            if preview_scene is not None:
                preview_scene.render(data, preview_settings)
        with ui.row():
            with ui.row():
                ui.label("Clipboard Preview").classes("my-auto")
                with ui.button(icon="sync", on_click=_soft_refresh):
                    ui.tooltip("Preview current clipboard")
            with ui.expansion("Settings", icon="settings").props("dense"):
                with ui.row():
                    scene_width = SMHInput("Width", "800", "preview_width", suffix="px", tooltip="Width of the preview in px")
                    scene_height = SMHInput("Height", "600", "preview_height", suffix="px", tooltip="Height of the preview in px")
                with ui.row():
                    time_scale = SMHInput("Time Scale", "64", "preview_time_scale", tooltip="Ratio between XY and time")
                    frame_length = SMHInput("Frame Length", "16", "preview_frame_length", suffix="b", tooltip="Number of beats to draw frames for")
                apply_button = ui.button("Apply")
            with ui.expansion("Colors & Sizes", icon="palette").props("dense"):
                sp = SettingsPanel()
        @ui.refreshable
        def draw_preview_scene():
            nonlocal preview_scene
            try:
                w = int(scene_width.parsed_value)
                h = int(scene_height.parsed_value)
                l = int(frame_length.parsed_value)
                t = time_scale.parsed_value
            except ParseInputError as pie:
                error(f"Error parsing preview setting: {pie.input_id}", pie, data=pie.value)
                return
            preview_scene = MapScene(width=w, height=h, frame_length=l, time_scale=t)
            _soft_refresh()
        draw_preview_scene()
        apply_button.on("click", draw_preview_scene.refresh)