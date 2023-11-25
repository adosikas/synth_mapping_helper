from typing import Any, Callable, Optional, List

import numpy as np
from nicegui import app, events, ui
import pyperclip

from .utils import *
from .. import movement, pattern_generation, rails, synth_format
from ..utils import parse_number

def _movement_helper(data: synth_format.DataContainer, mirror_left: bool, base_func, relative_func, pivot_func, relative: bool, pivot: Optional[list[int]], *args, **kwargs) -> None:
    """pick the right function depending on relative or pivot being set"""
    if relative:
        data.apply_for_all(relative_func, *args, mirror_left=mirror_left, **kwargs)
    elif pivot is not None:
        data.apply_for_all(pivot_func, *args, mirror_left=mirror_left, pivot_3d=pivot, **kwargs)
    else:
        data.apply_for_all(base_func, *args, mirror_left=mirror_left, **kwargs)

def _safe_inverse(v: float) -> float:
    return 0.0 if v == 0 else 1/v

def _safe_parse_number(v: Any) -> float:
    try:
        return parse_number(v)
    except ValueError:
        return 0.0

def _swap_hands(data: synth_format.DataContainer, **kwargs):
    data.left, data.right = data.right, data.left

def _change_color(data: synth_format.DataContainer, types: List[str], new_type: str, **kwargs):
    # to single type: just merge all dicts
    changed = {}
    for t in types:
        if t in synth_format.NOTE_TYPES and t != new_type:
            changed |= getattr(data, t)
            setattr(data, t, {})
    # existing notes always have priority
    setattr(data, new_type, changed | getattr(data, new_type))

def _space_walls(data: synth_format.DataContainer, interval: float) -> None:
    out: synth_format.WALLS = {}
    for i, (_, w) in enumerate(sorted(data.walls.items())):
        out[i*interval] = (w*[1,1,0,1,1]) + [0,0,i*interval,0,0]
    data.walls = out

def dashboard_tab():
    class SMHInput(ui.input):
        def __init__(self, label: str, value: str|float, storage_id: str, tooltip: Optional[str]=None, suffix: Optional[str] = None, **kwargs):
            self.on_parsed_value_change: Callable|None = None
            super().__init__(label=label, value=str(value), **kwargs)
            self.bind_value(app.storage.user, f"dashboard_{storage_id}")
            self.classes("w-12 h-10")
            self.props('dense input-style="text-align: right" no-error-icon')
            self.storage_id = storage_id
            if suffix:
                self.props(f'suffix="{suffix}"')
            with self:
                if tooltip is not None:
                    ui.tooltip(tooltip)
            with self.add_slot("error"):
                ui.element().style("visiblity: hidden")

        def _handle_value_change(self, value: Any) -> None:
            super()._handle_value_change(value)
            try:
                v = parse_number(value)
                if self.on_parsed_value_change:
                    self.on_parsed_value_change(v)
                self.props(remove="error")
            except ValueError:
                self.props(add="error")

        @property
        def parsed_value(self) -> float:
            try:
                return parse_number(self.value)
            except ValueError as ve:
                raise ParseInputError(self.storage_id, self.value) from ve

    with ui.row().classes("mb-4"):
        # with ui.card().classes("h-16"), ui.row():
        #     with ui.label("Filter").classes("my-auto"):
        #         wiki_reference("Miscellaneous-Options#filtering")
        #     with ui.button(icon="filter_alt"):
        #         ui.badge("0", color="red").props("floating")
        #     with ui.switch("Delete other"):
        #         wiki_reference("Pre--and-Post-Processing-Options#delete-everything-not-matching-filter")
        with ui.card().classes("h-16"), ui.row():
            with ui.switch("Use original", value=False).bind_value(app.storage.user, "dashboard_use_orig") as sw_use_orig:
                ui.tooltip("Enable this to quickly try different settings without having to undo and copy the input again")
                wiki_reference("Miscellaneous-Options#use-original-json")
            with ui.switch("Mirror for left", value=False).bind_value(app.storage.user, "dashboard_mirror_left") as sw_mirror_left:
                ui.tooltip("Mirrors the operations for left notes and walls, e.g. offseting right will move those left instead")
                wiki_reference("Miscellaneous-Options#mirror-operations-for-left-hand")
            with ui.switch("Realign start", value=False).bind_value(app.storage.user, "dashboard_realign") as sw_realign:
                ui.tooltip("This will realign the start of the selection to the very first object AFTER the operation")
                wiki_reference("Pre--and-Post-Processing-Options#keep-selection-alignment")
        with ui.card().classes("h-16"), ui.row():
            with ui.label("Coordinates").classes("my-2"):
                wiki_reference("Movement-Options#pivot-and-relative")
            coordinate_mode = ui.toggle(["absolute", "relative", "pivot"], value="absolute").props('color="grey-7" rounded').bind_value(app.storage.user, "dashboard_coord_mode")
            with ui.row() as pivot_settings:
                pivot_x = SMHInput("X", 0, "pivot_x", suffix="sq")
                pivot_y = SMHInput("Y", 0, "pivot_y", suffix="sq")
                pivot_t = SMHInput("Time", 0, "pivot_t", suffix="b")
                pivot_settings.bind_visibility_from(coordinate_mode, "value", backward=lambda v: v=="pivot")        

    class SMHActionButton(ui.button):
        def __init__(self, func: Callable, tooltip: str, icon: str="play_arrow", icon_angle: int=0, wiki_ref: Optional[str] = None, **kwargs):
            super().__init__(icon=icon if not icon_angle else "", on_click=self.do_action, **kwargs)
            self._tooltip = tooltip
            self._func = func
            self.classes("w-12 h-10")
            with self:
                ui.tooltip(tooltip)
                if icon_angle:
                    # create dedicated object, which can rotate independently from button
                    ui.icon(icon).style(f"rotate: {icon_angle}deg")
                if wiki_ref is not None:
                    wiki_reference(wiki_ref, True).props("floating")

        def do_action(self, e: events.ClickEventArguments):
            clipboard = pyperclip.paste()
            settings = {
                k.removeprefix("dashboard_"): v for k, v in app.storage.user.items()
                if k.startswith("dashboard_")
            }
            try:
                d = synth_format.import_clipboard_json(clipboard, use_original=sw_use_orig.value)
            except ValueError as ve:
                error(f"Error reading data from clipboard", ve, settings=settings, data=clipboard)
                return
            try:
                self._func(
                    data=d,
                    types=synth_format.ALL_TYPES,  # placeholder
                    mirror_left=sw_mirror_left.value,
                    relative=(coordinate_mode.value=="relative"),
                    pivot=[pivot_x.parsed_value, pivot_y.parsed_value, pivot_t.parsed_value] if (coordinate_mode.value=="pivot") else None
                )
            except ParseInputError as pie:
                error(f"Error parsing value: {pie.input_id}", pie, settings=settings, data=pie.value)
                return
            except Exception as exc:
                error(f"Error executing '{self._tooltip}'", exc, settings=settings, data=clipboard)
                return
            counts = d.get_counts()
            info(
                f"Completed: '{self._tooltip}'",
                caption=", ".join(f"{counts[t]['total']} {t if counts[t]['total'] != 1 else t.rstrip('s')}" for t in ("notes", "rails", "rail_nodes", "walls")),
            )
            synth_format.export_clipboard(d, realign_start=sw_realign.value)

    with ui.row():
        with ui.card():
            with ui.label("Offset"):
                wiki_reference("Movement-Options#offset")
            with ui.grid(columns=3):
                for y in (1, 0, -1):
                    for x in (-1, 0, 1):
                        if x or y:
                            SMHActionButton(
                                tooltip=f'Offset {("down", "", "up")[y+1]}{" and " if x and y else ""}{("left", "", "right")[x+1]}',
                                icon=f'{("south", "", "north")[y+1]}{"_" if x and y else ""}{("west", "", "east")[x+1]}',
                                func=lambda x=x, y=y, **kwargs: _movement_helper(**kwargs,
                                    base_func=movement.offset, relative_func=movement.offset_relative, pivot_func=movement.offset,
                                    offset_3d=np.array([x,y,0])*offset_xy.parsed_value,
                                ),
                            )
                        else:
                            offset_xy = SMHInput("X/Y", 1, "offset_xy", suffix="sq")
            ui.separator()
            with ui.row():
                SMHActionButton(
                    tooltip="Offset earlier in time",
                    icon="remove",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.offset, relative_func=movement.offset_relative, pivot_func=movement.offset,
                        offset_3d=np.array([0,0,-offset_t.parsed_value]),
                    ),
                    color="secondary",
                )
                offset_t = SMHInput("Time", 1, "dashboard_offset_t", suffix="b")
                SMHActionButton(
                    tooltip="Offset later in time",
                    icon="add",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.offset, relative_func=movement.offset_relative, pivot_func=movement.offset,
                        offset_3d=np.array([0,0,offset_t.parsed_value]),
                    ),
                )

        with ui.card():
            with ui.label("Scaling"):
                wiki_reference("Movement-Options#scaling")
            with ui.grid(columns=3):
                scaleup_label = ui.label("110%").classes("ml-auto h-min bg-primary")
                SMHActionButton(
                    tooltip="Scale Y up (taller)",
                    icon="unfold_more",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.scale, relative_func=movement.scale_relative, pivot_func=movement.scale_from,
                        scale_3d=np.array([1,scale_xy.parsed_value,1]),
                    ),
                )
                SMHActionButton(
                    tooltip="Scale XY up (larger)",
                    icon="zoom_out_map",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.scale, relative_func=movement.scale_relative, pivot_func=movement.scale_from,
                        scale_3d=np.array([scale_xy.parsed_value,scale_xy.parsed_value,1]),
                    ),
                )
                SMHActionButton(
                    tooltip="Scale X down (less wide)",
                    icon="unfold_less", icon_angle=90,
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.scale, relative_func=movement.scale_relative, pivot_func=movement.scale_from,
                        scale_3d=np.array([_safe_inverse(scale_xy.parsed_value),1,1]),
                    ),
                    color="secondary",
                )
                scale_xy = SMHInput("X/Y", "110%", "scale_xy", tooltip="Can be given as % or ratio. If less than 1 (100%), scale up/down are inverted")
                SMHActionButton(
                    tooltip="Scale X up (wider)",
                    icon="unfold_more", icon_angle=90,
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.scale, relative_func=movement.scale_relative, pivot_func=movement.scale_from,
                        scale_3d=np.array([scale_xy.parsed_value,1,1]),
                    ),
                )
                SMHActionButton(
                    tooltip="Scale XY down (smaller)",
                    icon="zoom_in_map",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.scale, relative_func=movement.scale_relative, pivot_func=movement.scale_from,
                        scale_3d=np.array([_safe_inverse(scale_xy.parsed_value),_safe_inverse(scale_xy.parsed_value),1]),
                    ),
                    color="secondary",
                )
                SMHActionButton(
                    tooltip="Scale Y down (less tall)",
                    icon="unfold_less",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.scale, relative_func=movement.scale_relative, pivot_func=movement.scale_from,
                        scale_3d=np.array([1,_safe_inverse(scale_xy.parsed_value),1]),
                    ),
                    color="secondary",
                )
                with ui.label().classes("mt-auto w-min bg-secondary").bind_text_from(scale_xy, "value", backward=lambda v: f"{_safe_inverse(_safe_parse_number(v)):.1%}"):
                    ui.tooltip("This is the exact inverse of the scale up. Percent calculations are weird like that.")
                scaleup_label.bind_text_from(scale_xy, "value", backward=lambda v: f"{_safe_parse_number(v):.1%}")
            ui.separator()
            with ui.row():
                SMHActionButton(
                    tooltip="Scale time down (shorter)",
                    icon="compress",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.scale, relative_func=movement.scale_relative, pivot_func=movement.scale_from,
                        scale_3d=np.array([1,1,_safe_inverse(scale_t.parsed_value)]),
                    ),
                    color="secondary",
                )
                scale_t = SMHInput("Time", 2, "scale_t", tooltip="Can be given as % or ratio. If less than 1 (100%), scale up/down are inverted")
                SMHActionButton(
                    tooltip="Scale time up (longer)",
                    icon="expand",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.scale, relative_func=movement.scale_relative, pivot_func=movement.scale_from,
                        scale_3d=np.array([1,1,scale_t.parsed_value]),
                    ),
                )
            with ui.row():
                SMHActionButton(
                    tooltip="Read BPM from clipboard",
                    icon="colorize",
                    func=lambda data, **kwargs: setattr(scale_bpm, "value", str(data.bpm)),
                ).props("outline")
                scale_bpm = SMHInput("New BPM", 120, "scale_bpm")
                SMHActionButton(
                    tooltip="Change BPM of clipboard (keeps timing)",
                    icon="straighten",
                    func=lambda data, **kwargs: (
                        _movement_helper(data, **kwargs,
                            base_func=movement.scale, relative_func=movement.scale_relative, pivot_func=movement.scale_from,
                            scale_3d=np.array([1,1,scale_bpm.parsed_value / data.bpm])
                        ),
                        setattr(data, "bpm", scale_bpm.parsed_value),
                    ),
                    wiki_ref="Pre--and-Post-Processing-Options#change-bpm",
                )

            ui.separator()
            with ui.label("Flatten and Mirror"):
                ui.tooltip("Just scaling, but with -1 or 0")
            with ui.row():
                SMHActionButton(
                    tooltip="Flatten to Y axis (X=0)",
                    icon="vertical_align_center", icon_angle=90,
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.scale, relative_func=movement.scale_relative, pivot_func=movement.scale_from,
                        scale_3d=np.array([0,1,1]),
                    ),
                )
                SMHActionButton(
                    tooltip="Flatten to X axis (Y=0)",
                    icon="vertical_align_center",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.scale, relative_func=movement.scale_relative, pivot_func=movement.scale_from,
                        scale_3d=np.array([1,0,1]),
                    ),
                )
                SMHActionButton(
                    tooltip="Move to pivot (X=Y=0)",
                    icon="adjust",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.scale, relative_func=movement.scale_relative, pivot_func=movement.scale_from,
                        scale_3d=np.array([0,0,1]),
                    ),
                )
            with ui.row():
                SMHActionButton(
                    tooltip="Mirror X (left<->right)",
                    icon="align_horizontal_center",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.scale, relative_func=movement.scale_relative, pivot_func=movement.scale_from,
                        scale_3d=np.array([-1,1,1]),
                    ),
                )
                SMHActionButton(
                    tooltip="Mirror Y (up<->down)",
                    icon="align_vertical_center",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.scale, relative_func=movement.scale_relative, pivot_func=movement.scale_from,
                        scale_3d=np.array([1,-1,1]),
                    ),
                )
                SMHActionButton(
                    tooltip="Mirror time (reverse)",
                    icon="fast_rewind",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.scale, relative_func=movement.scale_relative, pivot_func=movement.scale_from,
                        scale_3d=np.array([1,1,-1]),
                    ),
                )
            ui.separator()
            with ui.row():
                mirror_angle = SMHInput("Angle", 45, "mirror_angle", suffix="°", tooltip="Angle of the mirror line. 0=horizontal, ±90=vertical, +45=/, -45=\\")
                mirror_stack = SMHInput("Stack", 0, "mirror_stack", suffix="b", tooltip="Instead of just mirroring, stack a mirrored copy onto the input. 0=disabled.")
                def _do_mirror(data: synth_format.DataContainer, **kwargs):
                        # work on copy when stacking, else directly on data
                        tmp = data.filtered() if mirror_stack.parsed_value else data
                        # subtract rotation, mirror, add back rotation
                        _movement_helper(tmp, **kwargs,
                            base_func=movement.rotate, relative_func=movement.rotate_relative, pivot_func=movement.rotate_around,
                            angle=-mirror_angle.parsed_value,
                        )
                        _movement_helper(tmp, **kwargs,
                            base_func=movement.scale, relative_func=movement.scale_relative, pivot_func=movement.scale_from,
                            scale_3d=np.array([1,-1,1]),
                        )
                        _movement_helper(tmp, **kwargs,
                            base_func=movement.rotate, relative_func=movement.rotate_relative, pivot_func=movement.rotate_around,
                            angle=mirror_angle.parsed_value,
                        )
                        if mirror_stack.parsed_value:
                            tmp.apply_for_all(movement.offset, [0,0,mirror_stack.parsed_value])
                            data.merge(tmp)
                            
                with SMHActionButton(
                    tooltip="Mirror with custom angle (passing through origin/pivot/object depending on coordinate mode)",
                    icon="",
                    func=_do_mirror
                ):
                    mirror_icon = ui.icon("flip").style(f"rotate: {90-mirror_angle.parsed_value}deg")
                mirror_angle.on_parsed_value_change = lambda v: mirror_icon.style(f"rotate: {90-v}deg")

        with ui.card():
            with ui.label("Rotation"):
                wiki_reference("Movement-Options#rotate")
            with ui.row():
                SMHActionButton(
                    tooltip="Rotate counterclockwise",
                    icon="rotate_left",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.rotate, relative_func=movement.rotate_relative, pivot_func=movement.rotate_around,
                        angle=rotate_angle.parsed_value,
                    ),
                )
                rotate_angle = SMHInput("Angle", 45, "angle", suffix="°")
                SMHActionButton(
                    tooltip="Rotate clockwise",
                    icon="rotate_right",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.rotate, relative_func=movement.rotate_relative, pivot_func=movement.rotate_around,
                        angle=-rotate_angle.parsed_value,
                    ),
                )
            ui.separator()

            with ui.label("Outset"):
                wiki_reference("Movement-Options#outset")
            with ui.row():
                SMHActionButton(
                    tooltip="Inset (towards center/pivot)",
                    icon="close_fullscreen",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.outset, relative_func=movement.outset_relative, pivot_func=movement.outset_from,
                        outset_scalar=-outset_amount.parsed_value,
                    ),
                    color="secondary",
                )
                outset_amount = SMHInput("Amount", 1, "outset", suffix="sq")
                SMHActionButton(
                    tooltip="Outset (away from center/pivot)",
                    icon="open_in_full",
                    func=lambda **kwargs: _movement_helper(**kwargs,
                        base_func=movement.outset, relative_func=movement.outset_relative, pivot_func=movement.outset_from,
                        outset_scalar=outset_amount.parsed_value,
                    ),
                )

            ui.separator()
            with ui.label("Create parallel"):
                wiki_reference("Pre--and-Post-Processing-Options#create-parallel-patterns")
            with ui.row():
                SMHActionButton(
                    tooltip="Create parallel crossovers",
                    icon="shuffle",
                    func=lambda data, **kwargs: pattern_generation.create_parallel(data, -parallel_distance.parsed_value),
                    color="secondary",
                )
                parallel_distance = SMHInput("Spacing", 2, "parallel", suffix="sq")
                SMHActionButton(
                    tooltip="Create parallel pattern",
                    icon="stacked_line_chart",
                    func=lambda data, **kwargs: pattern_generation.create_parallel(data, parallel_distance.parsed_value),
                )

        with ui.card():
            ui.label("Rails and Notes")
            with ui.row():
                SMHActionButton(
                    tooltip="Merge sequential rails",
                    icon="link",
                    func=lambda data, types, **kwargs: data.apply_for_note_types(rails.merge_sequential_rails, types=types),
                    wiki_ref="Pre--and-Post-Processing-Options#merge-rails",
                )
                SMHActionButton(
                    tooltip="Split rails at single notes",
                    icon="link_off",
                    func=lambda data, types, **kwargs: data.apply_for_note_types(rails.split_rails, types=types),
                    wiki_ref="Pre--and-Post-Processing-Options#split-rails",
                )
                SMHActionButton(
                    tooltip="Snap notes to rail",
                    icon="insights",
                    func=lambda data, types, **kwargs: data.apply_for_note_types(rails.snap_singles_to_rail, types=types),
                    wiki_ref="Pre--and-Post-Processing-Options#snap-single-notes-to-rails",
                )
            with ui.row():
                SMHActionButton(
                    tooltip="Rail nodes to notes (delete rail)",
                    icon="more_vert",
                    func=lambda data, types, **kwargs: data.apply_for_note_types(rails.rails_to_singles, keep_rail=False, types=types),
                    wiki_ref="Pre--and-Post-Processing-Options#convert-rails-into-single-notes",
                )
                SMHActionButton(
                    tooltip="Rail nodes to notes (keep rail)",
                    icon="more_vert"+"show_chart",
                    func=lambda data, types, **kwargs: data.apply_for_note_types(rails.rails_to_singles, keep_rail=True, types=types),
                    wiki_ref="Pre--and-Post-Processing-Options#convert-rails-into-single-notes",
                )
            ui.separator()
            with ui.row():
                rail_distance = SMHInput("Max-Dist", 1, "rail_distance", suffix="b", tooltip="Maximum distance")
                SMHActionButton(
                    tooltip="Connect notes",
                    icon="linear_scale", icon_angle=90,
                    func=lambda data, types, **kwargs: data.apply_for_note_types(rails.connect_singles, max_interval=rail_distance.parsed_value, types=types),
                    wiki_ref="Pre--and-Post-Processing-Options#connect-single-notes-into-rails",
                )
                SMHActionButton(
                    tooltip="Connect rails",
                    icon="add_link",
                    func=lambda data, types, **kwargs: data.apply_for_note_types(rails.merge_rails, max_interval=rail_distance.parsed_value, types=types),
                    wiki_ref="Pre--and-Post-Processing-Options#merge-rails",
                )
            ui.separator()
            with ui.row():
                rail_interval = SMHInput("Interval", "1/16", "rail_interval", suffix="b", tooltip="Can be negative to start from end")
                SMHActionButton(
                    tooltip="Split rail into intervals",
                    icon="format_line_spacing"+"link_off",
                    func=lambda data, types, **kwargs: data.apply_for_note_types(rails.segment_rail, max_length=rail_interval.parsed_value, types=types),
                )
                SMHActionButton(
                    tooltip="Interpolate rail nodes",
                    icon="format_line_spacing"+"commit",
                    func=lambda data, types, **kwargs: data.apply_for_all(rails.interpolate_nodes, mode="spline", interval=rail_interval.parsed_value, types=types),
                    wiki_ref="Rail-Options#interpolate",
                )
            with ui.row():
                SMHActionButton(
                    tooltip="Rail to notestack (delete rail)",
                    icon="animation",
                    func=lambda data, types, **kwargs: data.apply_for_note_types(rails.rails_to_notestacks, interval=rail_interval.parsed_value, keep_rail=False, types=types),
                )
                SMHActionButton(
                    tooltip="Rail to notestack (keep rail)",
                    icon="animation"+"show_chart",
                    func=lambda data, types, **kwargs: data.apply_for_note_types(rails.rails_to_notestacks, interval=rail_interval.parsed_value, keep_rail=True, types=types),
                )
                SMHActionButton(
                    tooltip="Shorten rail (cuts from start if negative)",
                    icon="content_cut",
                    func=lambda data, types, **kwargs: data.apply_for_all(rails.shorten_rail, distance=rail_interval.parsed_value, types=types),
                    wiki_ref="Rail-Options#shorten-rails",
                )
            with ui.row():
                SMHActionButton(
                    tooltip="Extend level",
                    icon="swipe_right_alt" + "horizontal_rule",
                    func=lambda data, types, **kwargs: data.apply_for_all(rails.extend_level, distance=rail_interval.parsed_value, types=types),
                )
                SMHActionButton(
                    tooltip="Extend directional / straight",
                    icon="swipe_right_alt" + "double_arrow",
                    func=lambda data, types, **kwargs: data.apply_for_all(rails.extend_straight, distance=rail_interval.parsed_value, types=types),
                )
                SMHActionButton(
                    tooltip="Extend pointing to next",
                    icon="swipe_right_alt" + "swipe_right_alt",
                    func=lambda data, types, **kwargs: data.apply_for_note_types(rails.extend_to_next, distance=rail_interval.parsed_value, types=types),
                )

        with ui.card():
            with ui.label("Color"):
                wiki_reference("Pre--and-Post-Processing-Options#change-note-type")

            SMHActionButton(
                tooltip="Swap Hands",
                icon="swap_horizontal_circle",
                func=_swap_hands,
                wiki_ref="Pre--and-Post-Processing-Options#swap-hands",
            ).props("outline")
            SMHActionButton(
                tooltip="Change to left hand",
                icon="change_circle",
                func=lambda **kwargs: _change_color(new_type="left", **kwargs),
                color="#009BAA",
            )
            SMHActionButton(
                tooltip="Change to right hand",
                icon="change_circle",
                func=lambda **kwargs: _change_color(new_type="right", **kwargs),
                color="#E32862",
            )
            SMHActionButton(
                tooltip="Change to single hand",
                icon="change_circle",
                func=lambda **kwargs: _change_color(new_type="single", **kwargs),
                color="#49BB08",
            )
            SMHActionButton(
                tooltip="Change to both hands",
                icon="change_circle",
                func=lambda **kwargs: _change_color(new_type="both", **kwargs),
                color="#FB9D10",
            )

        with ui.card():
            with ui.row():
                spiral_angle = SMHInput("Angle", 45, "spiral_angle", suffix="°", tooltip="Angle between nodes. Choose 180 for zigzag.")
                spiral_start = SMHInput("Start", 0, "spiral_start", suffix="°", tooltip="Angle of first node: 0=right, 90=up, 180=left, 270/-90=down")
                spiral_radius = SMHInput("Radius", 1, "spiral_radius", suffix="sq", tooltip="Radius of spiral / Length of spikes")
            with ui.label("Spiral"):
                wiki_reference("Rail-Options#spiral")
            with ui.row():
                def _add_spiral(nodes: "numpy array (n, 3)", fidelity: float, direction: int = 1) -> "numpy array (n, 3)":
                    nodes[:, :2] += pattern_generation.spiral(
                        fidelity * direction,
                        nodes.shape[0],
                        spiral_start.parsed_value if direction == 1 else 180 - spiral_start.parsed_value
                    ) * spiral_radius.parsed_value
                    return nodes
                SMHActionButton(
                    tooltip="Spiral (counter-clockwise)",
                    icon="rotate_left",
                    func=lambda data, types, mirror_left, **kwargs: data.apply_for_notes(_add_spiral, fidelity=360*_safe_inverse(spiral_angle.parsed_value), types=types, mirror_left=mirror_left),
                ).props("rounded")
                SMHActionButton(
                    tooltip="Spiral (clockwise)",
                    icon="rotate_right",
                    func=lambda data, types, mirror_left, **kwargs: data.apply_for_notes(_add_spiral, fidelity=360*_safe_inverse(-spiral_angle.parsed_value), types=types, mirror_left=mirror_left),
                ).props("rounded")
                SMHActionButton(
                    tooltip="Random nodes",
                    icon="casino",
                    func=lambda data, types, mirror_left, **kwargs: data.apply_for_notes(_add_spiral, fidelity=0, types=types, mirror_left=mirror_left),
                ).props("rounded outline")
            with ui.row():
                with ui.label("Spikes"):
                    wiki_reference("Rail-Options#spikes")
                spike_duration = SMHInput("Duration", 0, "spike_duration", suffix="b", tooltip="Duration of spikes.")
            with ui.row():
                def _add_spikes(nodes: "numpy array (n, 3)", fidelity: float, direction: int = 1) -> "numpy array (n, 3)":
                    node_count = nodes.shape[0]  # backup count before repeat
                    nodes = np.repeat(nodes, 3, axis=0)
                    nodes[::3] -= spike_duration.parsed_value
                    nodes[1::3] -= spike_duration.parsed_value/2
                    nodes[:, :2] += pattern_generation.spikes(
                        fidelity * direction,
                        node_count,
                        spiral_start.parsed_value if direction == 1 else 180 - spiral_start.parsed_value
                    ) * spiral_radius.parsed_value
                    return nodes
                SMHActionButton(
                    tooltip="Spikes (counter-clockwise)",
                    icon="rotate_left",
                    func=lambda data, types, mirror_left, **kwargs: data.apply_for_notes(_add_spikes, fidelity=360*_safe_inverse(spiral_angle.parsed_value), types=types, mirror_left=mirror_left),
                )
                SMHActionButton(
                    tooltip="Spikes (clockwise)",
                    icon="rotate_right",
                    func=lambda data, types, mirror_left, **kwargs: data.apply_for_notes(_add_spikes, fidelity=360*_safe_inverse(-spiral_angle.parsed_value), types=types, mirror_left=mirror_left),
                )
                SMHActionButton(
                    tooltip="Spikes (random)",
                    icon="casino",
                    func=lambda data, types, mirror_left, **kwargs: data.apply_for_notes(_add_spikes, fidelity=0, types=types, mirror_left=mirror_left),
                )

        with ui.card():
            ui.label("Wall spacing")
            with ui.row():
                compress_interval = SMHInput("Spacing", "1/64", "compress_interval", suffix="b", tooltip="Space between walls")
                SMHActionButton(
                    tooltip="Compress",
                    icon="compress",
                    icon_angle=90,
                    func=lambda data, **kwargs: _space_walls(data, interval=compress_interval.parsed_value),
                )
            with ui.row():
                wall_limit = SMHInput("Walls/4s", 195, "spawn_limit", tooltip="200=wireframe limit, 500=spawn limit")
                SMHActionButton(
                    tooltip="Distribute walls to configured density",
                    icon="expand",
                    icon_angle=90,
                    func=lambda data, **kwargs: _space_walls(data, interval=(4*data.bpm/60)/wall_limit.parsed_value),
                )
