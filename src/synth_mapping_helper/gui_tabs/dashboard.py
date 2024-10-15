from typing import Any, Callable, Optional, List

import numpy as np
from nicegui import app, events, ui
import pyperclip

from .utils import *
from .. import movement, pattern_generation, rails, synth_format
from ..utils import parse_number, pretty_list

def _safe_inverse(v: float) -> float:
    return 0.0 if v == 0 else 1/v

def _safe_parse_number(v: Any) -> float:
    try:
        return parse_number(v)
    except ValueError:
        return 0.0

def _swap_hands(data: synth_format.DataContainer, **kwargs) -> None:
    data.left, data.right = data.right, data.left

def _change_color(data: synth_format.DataContainer, types: List[str], new_type: str, **kwargs) -> None:
    # to single type: just merge all dicts
    changed: synth_format.SINGLE_COLOR_NOTES = {}
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

def make_input(label: str, value: str|float, storage_id: str, **kwargs) -> SMHInput:
    default_kwargs = {"tab_id": "dashboard"}
    return SMHInput(storage_id=storage_id, label=label, default_value=value, **(default_kwargs|kwargs))

def offset_card(action_btn_cls: Any) -> None:
    with ui.card():
        with ui.label("Offset"):
            wiki_reference("Movement-Options#offset")
        with ui.grid(columns=3):
            for y in (1, 0, -1):
                for x in (-1, 0, 1):
                    if x or y:
                        action_btn_cls(
                            tooltip=f'Offset {("down", "", "up")[y+1]}{" and " if x and y else ""}{("left", "", "right")[x+1]}',
                            icon=f'{("south", "", "north")[y+1]}{"_" if x and y else ""}{("west", "", "east")[x+1]}',
                            apply_func=movement.offset,
                            apply_args=lambda x=x, y=y: dict(offset_3d=np.array([x,y,0])*offset_xy.parsed_value),
                        )
                    else:
                        offset_xy = make_input("X/Y", 1, "offset_xy", suffix="sq")
        ui.separator()
        with ui.grid(columns=3):
            action_btn_cls(
                tooltip="Offset earlier in time",
                icon="remove",
                apply_func=movement.offset,
                apply_args=lambda: dict(offset_3d=np.array([0,0,-offset_t.parsed_value])),
                color="secondary",
            )
            offset_t = make_input("Time", 1, "dashboard_offset_t", suffix="b")
            action_btn_cls(
                tooltip="Offset later in time",
                icon="add",
                apply_func=movement.offset,
                apply_args=lambda: dict(offset_3d=np.array([0,0,offset_t.parsed_value])),
            )

def scaling_card(action_btn_cls: Any) -> None:
    with ui.card():
        with ui.label("Scaling"):
            wiki_reference("Movement-Options#scaling")
        with ui.grid(columns=3):
            scaleup_label = ui.label("110%").classes("ml-auto h-min bg-primary")
            action_btn_cls(
                tooltip="Scale Y up (taller)",
                icon="unfold_more",
                apply_func=movement.scale,
                apply_args=lambda: dict(scale_3d=np.array([1,scale_xy.parsed_value,1])),
            )
            action_btn_cls(
                tooltip="Scale XY up (larger)",
                icon="zoom_out_map",
                apply_func=movement.scale,
                apply_args=lambda: dict(scale_3d=np.array([scale_xy.parsed_value,scale_xy.parsed_value,1])),
            )
            action_btn_cls(
                tooltip="Scale X down (less wide)",
                icon="unfold_less", icon_angle=90,
                apply_func=movement.scale,
                apply_args=lambda: dict(scale_3d=np.array([_safe_inverse(scale_xy.parsed_value),1,1])),
                color="secondary",
            )
            scale_xy = make_input("X/Y", "110%", "scale_xy", tooltip="Can be given as % or ratio. If less than 1 (100%), scale up/down are inverted")
            action_btn_cls(
                tooltip="Scale X up (wider)",
                icon="unfold_more", icon_angle=90,
                apply_func=movement.scale,
                apply_args=lambda: dict(scale_3d=np.array([scale_xy.parsed_value,1,1])),
            )
            action_btn_cls(
                tooltip="Scale XY down (smaller)",
                icon="zoom_in_map",
                apply_func=movement.scale,
                apply_args=lambda: dict(scale_3d=np.array([_safe_inverse(scale_xy.parsed_value),_safe_inverse(scale_xy.parsed_value),1])),
                color="secondary",
            )
            action_btn_cls(
                tooltip="Scale Y down (less tall)",
                icon="unfold_less",
                apply_func=movement.scale,
                apply_args=lambda: dict(scale_3d=np.array([1,_safe_inverse(scale_xy.parsed_value),1])),
                color="secondary",
            )
            with ui.label().classes("mt-auto w-min bg-secondary").bind_text_from(scale_xy, "value", backward=lambda v: f"{_safe_inverse(_safe_parse_number(v)):.1%}"):
                ui.tooltip("This is the exact inverse of the scale up. Percent calculations are weird like that.")
            scaleup_label.bind_text_from(scale_xy, "value", backward=lambda v: f"{_safe_parse_number(v):.1%}")
        ui.separator()
        with ui.grid(columns=3):
            action_btn_cls(
                tooltip="Scale time down (shorter)",
                icon="compress",
                apply_func=movement.scale,
                apply_args=lambda: dict(scale_3d=np.array([1,1,_safe_inverse(scale_t.parsed_value)])),
                color="secondary",
            )
            scale_t = make_input("Time", 2, "scale_t", tooltip="Can be given as % or ratio. If less than 1 (100%), scale up/down are inverted")
            action_btn_cls(
                tooltip="Scale time up (longer)",
                icon="expand",
                apply_func=movement.scale,
                apply_args=lambda: dict(scale_3d=np.array([1,1,scale_t.parsed_value])),
            )
            
            action_btn_cls(
                tooltip="Read BPM from clipboard",
                icon="colorize",
                func=lambda data, **kwargs: setattr(scale_bpm, "value", str(data.bpm)),
            ).props("outline")
            scale_bpm = make_input("New BPM", 120, "scale_bpm")
            action_btn_cls(
                tooltip="Change BPM of clipboard (keeps timing)",
                icon="straighten",
                func=lambda data, **kwargs: data.change_bpm(scale_bpm.parsed_value),
                wiki_ref="Pre--and-Post-Processing-Options#change-bpm",
            )

def flatten_mirror_card(action_btn_cls: Any) -> None:
    with ui.card():
        ui.label("Flatten").tooltip("Just scaling, but with 0")
        with ui.grid(columns=3):
            action_btn_cls(
                tooltip="Flatten to Y axis (X=0)",
                icon="vertical_align_center", icon_angle=90,
                apply_func=movement.scale, 
                apply_args=dict(scale_3d=np.array([0,1,1])),
            )
            action_btn_cls(
                tooltip="Flatten to X axis (Y=0)",
                icon="vertical_align_center",
                apply_func=movement.scale, 
                apply_args=dict(scale_3d=np.array([1,0,1])),
            )
            action_btn_cls(
                tooltip="Move to pivot (X=Y=0)",
                icon="adjust",
                apply_func=movement.scale, 
                apply_args=dict(scale_3d=np.array([0,0,1])),
            )
        ui.separator()
        ui.label("Mirror").tooltip("Just scaling, but with -1")
        with ui.grid(columns=3):
            action_btn_cls(
                tooltip="Mirror X (left<->right)",
                icon="align_horizontal_center",
                apply_func=movement.scale, 
                apply_args=dict(scale_3d=np.array([-1,1,1])),
            )
            action_btn_cls(
                tooltip="Mirror Y (up<->down)",
                icon="align_vertical_center",
                apply_func=movement.scale, 
                apply_args=dict(scale_3d=np.array([1,-1,1])),
            )
            action_btn_cls(
                tooltip="Mirror time (reverse)",
                icon="fast_rewind",
                apply_func=movement.scale, 
                apply_args=dict(scale_3d=np.array([1,1,-1])),
            )
        ui.separator()
        with ui.grid(columns=3):
            mirror_angle = make_input("Angle", 45, "mirror_angle", suffix="°", tooltip="Angle of the mirror line. 0=-, ±90=|, +45=/, -45=\\")
            def _do_mirror(data: synth_format.DataContainer, **kwargs):
                    # work on copy when stacking, else directly on data
                    tmp = data.filtered() if mirror_stack.parsed_value else data
                    # subtract rotation, mirror, add back rotation
                    tmp.apply_for_all(movement.rotate, angle=-mirror_angle.parsed_value, **kwargs)
                    tmp.apply_for_all(movement.scale, scale_3d=np.array([1,-1,1]), **kwargs)
                    tmp.apply_for_all(movement.rotate, angle=mirror_angle.parsed_value, **kwargs)
                    if mirror_stack.parsed_value:
                        tmp.apply_for_all(movement.offset, [0,0,mirror_stack.parsed_value])
                        data.merge(tmp)
                        
            with action_btn_cls(
                tooltip="Mirror with custom angle. Depending on coordinate mode, the mirror line passes through grid center, object center or pivot",
                icon=None,
                func=_do_mirror,
            ).add_slot("default"):
                mirror_icon = ui.icon("flip").style(f"rotate: {90-mirror_angle.parsed_value}deg")
            @handle_errors
            def _rotate_mirror_icon() -> None:
                mirror_icon.style(f"rotate: {90-mirror_angle.parsed_value}deg")
            mirror_angle.on_value_change(_rotate_mirror_icon)
            mirror_stack = make_input("Stack time", 0, "mirror_stack", suffix="b", tooltip="Instead of just mirroring, stack a mirrored copy onto the input using this as interval. 0=disabled.")

def rotate_outset_card(action_btn_cls: Any) -> None:
    with ui.card():
        with ui.label("Rotation"):
            wiki_reference("Movement-Options#rotate")
        with ui.grid(columns=3):
            action_btn_cls(
                tooltip="Rotate counterclockwise",
                icon="rotate_left",
                apply_func=movement.rotate,
                apply_args=lambda: dict(angle=rotate_angle.parsed_value),
            )
            rotate_angle = make_input("Angle", 45, "angle", suffix="°")
            action_btn_cls(
                tooltip="Rotate clockwise",
                icon="rotate_right",
                apply_func=movement.rotate,
                apply_args=lambda: dict(angle=-rotate_angle.parsed_value),
            )
        ui.separator()

        with ui.label("Outset"):
            wiki_reference("Movement-Options#outset")
        with ui.grid(columns=3):
            action_btn_cls(
                tooltip="Inset (towards center/pivot)",
                icon="close_fullscreen",
                apply_func=movement.outset,
                apply_args=lambda: dict(outset_scalar=-outset_amount.parsed_value),
                color="secondary",
            )
            outset_amount = make_input("Amount", 1, "outset", suffix="sq")
            action_btn_cls(
                tooltip="Outset (away from center/pivot)",
                icon="open_in_full",
                apply_func=movement.outset,
                apply_args=lambda: dict(outset_scalar=outset_amount.parsed_value),
            )

        ui.separator()
        with ui.label("Create parallel"):
            wiki_reference("Pre--and-Post-Processing-Options#create-parallel-patterns")
        with ui.grid(columns=3):
            action_btn_cls(
                tooltip="Create parallel crossovers",
                icon="shuffle",
                func=lambda data, **kwargs: pattern_generation.create_parallel(data, -parallel_distance.parsed_value),
                color="secondary",
            )
            parallel_distance = make_input("Spacing", 2, "parallel", suffix="sq")
            action_btn_cls(
                tooltip="Create parallel pattern",
                icon="stacked_line_chart",
                func=lambda data, **kwargs: pattern_generation.create_parallel(data, parallel_distance.parsed_value),
            )

def rails_card(action_btn_cls: Any) -> None:
    with ui.card():
        ui.label("Rails and Notes")
        with ui.grid(columns=3):
            action_btn_cls(
                tooltip="Merge sequential rails",
                icon="link",
                func=lambda data, types, **kwargs: data.apply_for_note_types(rails.merge_sequential_rails, types=types),
                wiki_ref="Pre--and-Post-Processing-Options#merge-rails",
            )
            action_btn_cls(
                tooltip="Split rails at single notes",
                icon="link_off",
                func=lambda data, types, **kwargs: data.apply_for_note_types(rails.split_rails, types=types),
                wiki_ref="Pre--and-Post-Processing-Options#split-rails",
            )
            action_btn_cls(
                tooltip="Snap notes to rail",
                icon="insights",
                func=lambda data, types, **kwargs: data.apply_for_note_types(rails.snap_singles_to_rail, types=types),
                wiki_ref="Pre--and-Post-Processing-Options#snap-single-notes-to-rails",
            )

            action_btn_cls(
                tooltip="Rail nodes to notes (delete rail)",
                icon="more_vert",
                func=lambda data, types, **kwargs: data.apply_for_note_types(rails.rails_to_singles, keep_rail=False, types=types),
                wiki_ref="Pre--and-Post-Processing-Options#convert-rails-into-single-notes",
            )
            action_btn_cls(
                tooltip="Rail nodes to notes (keep rail)",
                icon="more_vert"+"show_chart",
                func=lambda data, types, **kwargs: data.apply_for_note_types(rails.rails_to_singles, keep_rail=True, types=types),
                wiki_ref="Pre--and-Post-Processing-Options#convert-rails-into-single-notes",
            )
        ui.separator()
        with ui.grid(columns=3):
            rail_distance = make_input("Max-Dist", 1, "rail_distance", suffix="b", tooltip="Maximum distance")
            action_btn_cls(
                tooltip="Connect notes",
                icon="linear_scale", icon_angle=90,
                func=lambda data, types, **kwargs: data.apply_for_note_types(rails.connect_singles, max_interval=rail_distance.parsed_value, types=types),
                wiki_ref="Pre--and-Post-Processing-Options#connect-single-notes-into-rails",
            )
            action_btn_cls(
                tooltip="Connect rails",
                icon="add_link",
                func=lambda data, types, **kwargs: data.apply_for_note_types(rails.merge_rails, max_interval=rail_distance.parsed_value, types=types),
                wiki_ref="Pre--and-Post-Processing-Options#merge-rails",
            )
        ui.separator()
        with ui.grid(columns=3):
            rail_interval = make_input("Interval", "1/16", "rail_interval", suffix="b", tooltip="Can be negative to start from end")
            action_btn_cls(
                tooltip="Split rail into intervals",
                icon="format_line_spacing"+"link_off",
                func=lambda data, types, **kwargs: data.apply_for_note_types(rails.segment_rail, max_length=rail_interval.parsed_value, types=types),
            )
            action_btn_cls(
                tooltip="Interpolate rail nodes",
                icon="format_line_spacing"+"commit",
                func=lambda data, types, **kwargs: data.apply_for_notes(rails.interpolate_nodes, mode="spline", interval=rail_interval.parsed_value, types=types),
                wiki_ref="Rail-Options#interpolate",
            )

            action_btn_cls(
                tooltip="Rail to notestack (delete rail)",
                icon="animation",
                func=lambda data, types, **kwargs: data.apply_for_note_types(rails.rails_to_notestacks, interval=rail_interval.parsed_value, keep_rail=False, types=types),
            )
            action_btn_cls(
                tooltip="Rail to notestack (keep rail)",
                icon="animation"+"show_chart",
                func=lambda data, types, **kwargs: data.apply_for_note_types(rails.rails_to_notestacks, interval=rail_interval.parsed_value, keep_rail=True, types=types),
            )
            action_btn_cls(
                tooltip="Shorten rail (cuts from start if negative)",
                icon="content_cut",
                func=lambda data, types, **kwargs: data.apply_for_notes(rails.shorten_rail, distance=rail_interval.parsed_value, types=types),
                wiki_ref="Rail-Options#shorten-rails",
            )

            action_btn_cls(
                tooltip="Extend level",
                icon="swipe_right_alt" + "horizontal_rule",
                func=lambda data, types, **kwargs: data.apply_for_notes(rails.extend_level, distance=rail_interval.parsed_value, types=types),
            )
            action_btn_cls(
                tooltip="Extend directional / straight",
                icon="swipe_right_alt" + "double_arrow",
                func=lambda data, types, **kwargs: data.apply_for_notes(rails.extend_straight, distance=rail_interval.parsed_value, types=types),
            )
            action_btn_cls(
                tooltip="Extend pointing to next",
                icon="swipe_right_alt" + "swipe_right_alt",
                func=lambda data, types, **kwargs: data.apply_for_note_types(rails.extend_to_next, distance=rail_interval.parsed_value, types=types),
            )

def color_card(action_btn_cls: Any) -> None:
    with ui.card():
        with ui.label("Color"):
            wiki_reference("Pre--and-Post-Processing-Options#change-note-type")

        action_btn_cls(
            tooltip="Swap Hands",
            icon="swap_horizontal_circle",
            func=_swap_hands,
            wiki_ref="Pre--and-Post-Processing-Options#swap-hands",
        ).props("outline")
        action_btn_cls(
            tooltip="Change to left hand",
            icon="change_circle",
            func=lambda **kwargs: _change_color(new_type="left", **kwargs),
            color="#009BAA",
        )
        action_btn_cls(
            tooltip="Change to right hand",
            icon="change_circle",
            func=lambda **kwargs: _change_color(new_type="right", **kwargs),
            color="#E32862",
        )
        action_btn_cls(
            tooltip="Change to single hand",
            icon="change_circle",
            func=lambda **kwargs: _change_color(new_type="single", **kwargs),
            color="#49BB08",
        )
        action_btn_cls(
            tooltip="Change to both hands",
            icon="change_circle",
            func=lambda **kwargs: _change_color(new_type="both", **kwargs),
            color="#FB9D10",
        )

def spiral_spike_card(action_btn_cls: Any) -> None:
    with ui.card():
        with ui.row():
            spiral_angle = make_input("Angle", 45, "spiral_angle", suffix="°", tooltip="Angle between nodes. Choose 180 for zigzag.")
            spiral_start = make_input("Start", 0, "spiral_start", suffix="°", tooltip="Angle of first node: 0=right, 90=up, 180=left, 270/-90=down")
            spiral_radius = make_input("Radius", 1, "spiral_radius", suffix="sq", tooltip="Radius of spiral / Length of spikes")
        with ui.row():
            with ui.switch("Interpolate", value=True).classes("w-28").bind_value(app.storage.user, "dashboard_spiral_do_interpolate") as spiral_do_interpolate:
                ui.tooltip("Interpolate rail before adding spiral/spikes. Enable this for consistent spacing.")
            spiral_interpolation = make_input("Interval", "1/16", "spiral_interpolation", suffix="b", tooltip="Time between spiral nodes/spikes").bind_enabled(spiral_do_interpolate, "value")
        with ui.label("Spiral"):
            wiki_reference("Rail-Options#spiral")
        with ui.row():
            @handle_errors
            def _add_spiral(nodes: "numpy array (n, 3)", fid_dir: int, direction: int = 1) -> "numpy array (n, 3)":
                if spiral_do_interpolate.value:
                    nodes = rails.interpolate_nodes(nodes, mode="spline", interval=spiral_interpolation.parsed_value)
                return pattern_generation.add_spiral(
                    nodes,
                    fidelity=fid_dir*360*_safe_inverse(spiral_angle.parsed_value),
                    radius=spiral_radius.parsed_value,
                    start_angle=spiral_start.parsed_value,
                    direction=direction,
                )
            action_btn_cls(
                tooltip="Spiral (counter-clockwise)",
                icon="rotate_left",
                func=lambda data, types, mirror_left, **kwargs: data.apply_for_notes(_add_spiral, fid_dir=1, types=types, mirror_left=mirror_left),
            ).props("rounded")
            action_btn_cls(
                tooltip="Spiral (clockwise)",
                icon="rotate_right",
                func=lambda data, types, mirror_left, **kwargs: data.apply_for_notes(_add_spiral, fid_dir=-1, types=types, mirror_left=mirror_left),
            ).props("rounded")
            action_btn_cls(
                tooltip="Random nodes",
                icon="casino",
                func=lambda data, types, mirror_left, **kwargs: data.apply_for_notes(_add_spiral, fid_dir=0, types=types, mirror_left=mirror_left),
            ).props("rounded outline")
        with ui.row():
            with ui.label("Spikes"):
                wiki_reference("Rail-Options#spikes")
            spike_duration = make_input("Duration", 0, "spike_duration", suffix="b", tooltip="Duration of spikes.")
        with ui.row():
            @handle_errors
            def _add_spikes(nodes: "numpy array (n, 3)", fid_dir: int, direction: int = 1) -> "numpy array (n, 3)":
                if spiral_do_interpolate.value:
                    nodes = rails.interpolate_nodes(nodes, mode="spline", interval=spiral_interpolation.parsed_value)
                return pattern_generation.add_spikes(
                    nodes,
                    fidelity=fid_dir*360*_safe_inverse(spiral_angle.parsed_value),
                    radius=spiral_radius.parsed_value,
                    spike_duration=spike_duration.parsed_value,
                    start_angle=spiral_start.parsed_value,
                    direction=direction,
                )
            action_btn_cls(
                tooltip="Spikes (counter-clockwise)",
                icon="rotate_left",
                func=lambda data, types, mirror_left, **kwargs: data.apply_for_notes(_add_spikes, fid_dir=1, types=types, mirror_left=mirror_left),
            ).props("square")
            action_btn_cls(
                tooltip="Spikes (clockwise)",
                icon="rotate_right",
                func=lambda data, types, mirror_left, **kwargs: data.apply_for_notes(_add_spikes, fid_dir=-1, types=types, mirror_left=mirror_left),
            ).props("square")
            action_btn_cls(
                tooltip="Spikes (random)",
                icon="casino",
                func=lambda data, types, mirror_left, **kwargs: data.apply_for_notes(_add_spikes, fid_dir=0, types=types, mirror_left=mirror_left),
            ).props("square")

def wall_spacing_card(action_btn_cls: Any) -> None:
    with ui.card():
        ui.label("Wall spacing")
        with ui.row():
            compress_interval = make_input("Spacing", "1/64", "compress_interval", suffix="b", tooltip="Space between walls")
            action_btn_cls(
                tooltip="Compress",
                icon="compress",
                icon_angle=90,
                func=lambda data, **kwargs: _space_walls(data, interval=compress_interval.parsed_value),
            )
        with ui.row():
            wall_limit = make_input("Walls/4s", 195, "spawn_limit", tooltip="200=wireframe limit, 500=spawn limit")
            action_btn_cls(
                tooltip="Distribute walls to configured density",
                icon="expand",
                icon_angle=90,
                func=lambda data, **kwargs: _space_walls(data, interval=(4*data.bpm/60)/wall_limit.parsed_value),
            )

card_funcs: list[Callable[[Any], None]] = [
    offset_card,
    scaling_card,
    flatten_mirror_card,
    rotate_outset_card,
    rails_card,
    color_card,
    spiral_spike_card,
    wall_spacing_card,
]

def _dashboard_tab():
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
                pivot_x = make_input("X", 0, "pivot_x", suffix="sq")
                pivot_y = make_input("Y", 0, "pivot_y", suffix="sq")
                pivot_t = make_input("Time", 0, "pivot_t", suffix="b")
                pivot_settings.bind_visibility_from(coordinate_mode, "value", backward=lambda v: v=="pivot")        

    class ActionButton(ui.button):
        def __init__(self,
            tooltip: str, wiki_ref: Optional[str] = None,
            icon: str="play_arrow", icon_angle: int=0, 
            func: Callable|None=None,
            apply_func: Callable|None=None,
            apply_args: Callable[[], dict[str, ...]]|dict[str, ...]|None=None,
            **kwargs
        ):
            super().__init__(icon=icon if not icon_angle else None, on_click=self.do_action, **kwargs)
            self._tooltip = tooltip
            if (func is not None) == (apply_func is not None):
                raise TypeError("Specify either func OR apply_func")
            if func is not None:
                self._func = func
            else: # apply_func
                if apply_args is None:
                    apply_args = {}
                self._func = lambda data, **kwargs: data.apply_for_all(apply_func, **kwargs, **(apply_args() if callable(apply_args) else apply_args))

            self.classes("w-12 h-10")
            with self:
                ui.tooltip(tooltip)
                if wiki_ref is not None:
                    wiki_reference(wiki_ref, True).props("floating")
            if icon_angle:
                with self.add_slot("default"):
                    # create dedicated object, which can rotate independently from button
                    ui.icon(icon).style(f"rotate: {icon_angle}deg")

        @handle_errors
        def do_action(self):
            settings = {
                k.removeprefix("dashboard_"): v for k, v in app.storage.user.items()
                if k.startswith("dashboard_")
            }
            try:
                with safe_clipboard_data(use_original=sw_use_orig.value, realign_start=sw_realign.value) as data:
                    self._func(
                        data=data,
                        types=synth_format.ALL_TYPES,  # placeholder
                        mirror_left=sw_mirror_left.value,
                        relative=(coordinate_mode.value == "relative"),
                        pivot=np.array([pivot_x.parsed_value, pivot_y.parsed_value, pivot_t.parsed_value]) if (coordinate_mode.value=="pivot") else None
                    )
            except (PrettyError, ParseInputError):
                raise
            except Exception as exc:
                raise PrettyError(
                    msg=f"Error executing '{self._tooltip}'",
                    exc=exc,
                    context={"settings": settings},
                ) from exc
            counts = data.get_counts()
            info(
                f"Completed: '{self._tooltip}'",
                caption=pretty_list([f"{counts[t]['total']} {t if counts[t]['total'] != 1 else t.rstrip('s')}" for t in ("notes", "rails", "rail_nodes", "walls")]),
            )


    with ui.row():
        for card_func in card_funcs:
            card_func(ActionButton)

dashboard_tab = GUITab(
    name = "dashboard",
    label = "Dashboard",
    icon = "dashboard",
    content_func=_dashboard_tab,
)