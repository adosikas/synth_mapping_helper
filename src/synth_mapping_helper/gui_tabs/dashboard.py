from contextlib import contextmanager
from functools import partial
from typing import Any, Callable, Optional, List

import numpy as np
from nicegui import app, events, ui
import pyperclip

from .utils import *
from .. import movement, pattern_generation, rails, synth_format
from ..utils import parse_number, pretty_list, pretty_fraction

def _safe_inverse(v: float) -> float:
    return 0.0 if v == 0 else 1/v

def _safe_parse_number(v: Any) -> float:
    try:
        return parse_number(v)
    except ValueError:
        return 0.0

def _swap_hands(data: synth_format.DataContainer, **kwargs) -> None:
    data.left, data.right = data.right, data.left

def _change_color(data: synth_format.DataContainer, types: List[str], rail_filter: synth_format.RailFilter|None, new_type: str, **kwargs) -> None:
    # to single type: just merge all dicts
    changed: synth_format.SINGLE_COLOR_NOTES = {}
    for t in types:
        if t in synth_format.NOTE_TYPES and t != new_type:
            if not rail_filter:
                changed |= getattr(data, t)
                setattr(data, t, {})
            else:
                unchanged = {}
                for ti, nodes in getattr(data, t).items():
                    if rail_filter.matches(nodes):
                        changed[ti] = nodes
                    else:
                        unchanged[ti] = nodes
                setattr(data, t, unchanged)
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
                apply_func=partial(movement.scale, scale_3d=np.array([0,1,1])),
            )
            action_btn_cls(
                tooltip="Flatten to X axis (Y=0)",
                icon="vertical_align_center",
                apply_func=partial(movement.scale, scale_3d=np.array([1,0,1])),
            )
            action_btn_cls(
                tooltip="Move to pivot (X=Y=0)",
                icon="adjust",
                apply_func=partial(movement.scale, scale_3d=np.array([0,0,1])),
            )
        ui.separator()
        ui.label("Mirror").tooltip("Just scaling, but with -1")
        with ui.row():
            def _do_mirror_axis(data: synth_format.DataContainer, axis: int, **kwargs):
                # work on copy when stacking, else directly on data
                tmp = data.filtered() if mirror_do_stack.value else data
                scale_3d = np.ones((3,))
                scale_3d[axis] = -1
                tmp.apply_for_all(movement.scale, scale_3d=scale_3d, **kwargs)
                if mirror_do_stack.value:
                    interval = mirror_stack_interval.parsed_value
                    if axis != 2 and not interval:
                        raise PrettyError("Stacked copy with interval 0 would just override input.")
                    tmp.apply_for_all(movement.offset, [0,0,interval])
                    data.merge(tmp)
            action_btn_cls(
                tooltip="Mirror X (left<->right)",
                icon="align_horizontal_center",
                func=partial(_do_mirror_axis, axis=0),
            )
            action_btn_cls(
                tooltip="Mirror Y (up<->down)",
                icon="align_vertical_center",
                func=partial(_do_mirror_axis, axis=1),
            )
            action_btn_cls(
                tooltip="Mirror time (reverse). Enabling 'Realign Start' at the top is recommended.",
                icon="fast_rewind",
                func=partial(_do_mirror_axis, axis=2),
            )
        with ui.row():
            mirror_angle = make_input("Custom Mirror Angle", 45, "mirror_angle", suffix="°", tooltip="Angle of the mirror line. 0: --, ±90: |, +45: /, -45: \\", width=28)
            def _do_mirror_custom(data: synth_format.DataContainer, **kwargs):
                    # work on copy when stacking, else directly on data
                    tmp = data.filtered() if mirror_do_stack.value else data
                    # subtract rotation, mirror, add back rotation
                    tmp.apply_for_all(movement.rotate, angle=-mirror_angle.parsed_value, **kwargs)
                    tmp.apply_for_all(movement.scale, scale_3d=np.array([1,-1,1]), **kwargs)
                    tmp.apply_for_all(movement.rotate, angle=mirror_angle.parsed_value, **kwargs)
                    if mirror_do_stack.value:
                        tmp.apply_for_all(movement.offset, [0,0,mirror_stack_interval.parsed_value])
                        data.merge(tmp)
            custom_mirror_btn = action_btn_cls(
                tooltip="",
                icon=None,
                func=_do_mirror_custom,
            )
            @handle_errors
            def _rotate_mirror_icon() -> None:
                try:
                    ang = mirror_angle.parsed_value
                except ParseInputError:
                    ang = 0
                mirror_icon.style(f"rotate: {90-ang}deg")
            with custom_mirror_btn.add_slot("default"):
                ui.tooltip("Mirror with custom angle. Depending on coordinate mode, the mirror line passes through grid center, object center or pivot")
                mirror_icon = ui.icon("flip")
                _rotate_mirror_icon()
            mirror_angle.on_value_change(_rotate_mirror_icon)
        with ui.row():
            with ui.switch("Stacking", value=False).props('size="xs"').classes("w-28 my-auto").bind_value(app.storage.user, "dashboard_mirror_do_stack") as mirror_do_stack:
                ui.tooltip("Instead of simply mirroring the input, stack the mirrored copy behind it.")
            mirror_stack_interval = make_input("Interval", 0, "mirror_stack_interval", suffix="b", tooltip="Interval for stacked copy. When reversing time, this should either be 0 (to mirror across cursor) or double the pattern length (to mirror from back).").bind_enabled_from(mirror_do_stack, "value")

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
                func=lambda data, types, rail_filter, **kwargs: pattern_generation.create_parallel(data, distance=-parallel_distance.parsed_value, types=types, rail_filter=rail_filter),
                color="secondary",
            )
            parallel_distance = make_input("Spacing", 2, "parallel", suffix="sq")
            action_btn_cls(
                tooltip="Create parallel pattern",
                icon="stacked_line_chart",
                func=lambda data, types, rail_filter, **kwargs: pattern_generation.create_parallel(data, distance=parallel_distance.parsed_value, types=types, rail_filter=rail_filter),
            )

def rails_card(action_btn_cls: Any) -> None:
    with ui.card():
        ui.label("Rails and Notes")
        with ui.grid(columns=3):
            action_btn_cls(
                tooltip="Merge sequential rails",
                icon="link",
                func=lambda data, types, rail_filter, **kwargs: data.apply_for_note_types(rails.merge_sequential_rails, types=types, rail_filter=rail_filter),
                wiki_ref="Pre--and-Post-Processing-Options#merge-rails",
            )
            action_btn_cls(
                tooltip="Split rails at single notes",
                icon="link_off",
                func=lambda data, types, rail_filter, **kwargs: data.apply_for_note_types(rails.split_rails, types=types, rail_filter=rail_filter),
                wiki_ref="Pre--and-Post-Processing-Options#split-rails",
            )
            action_btn_cls(
                tooltip="Snap notes to rail",
                icon="insights",
                func=lambda data, types, rail_filter, **kwargs: data.apply_for_note_types(rails.snap_singles_to_rail, types=types, rail_filter=rail_filter),
                wiki_ref="Pre--and-Post-Processing-Options#snap-single-notes-to-rails",
            )

            action_btn_cls(
                tooltip="Rail nodes to notes (delete rail)",
                icon="more_vert",
                func=lambda data, types, rail_filter, **kwargs: data.apply_for_note_types(rails.rails_to_singles, keep_rail=False, types=types, rail_filter=rail_filter),
                wiki_ref="Pre--and-Post-Processing-Options#convert-rails-into-single-notes",
            )
            action_btn_cls(
                tooltip="Rail nodes to notes (keep rail)",
                icon="more_vert"+"show_chart",
                func=lambda data, types, rail_filter, **kwargs: data.apply_for_note_types(rails.rails_to_singles, keep_rail=True, types=types, rail_filter=rail_filter),
                wiki_ref="Pre--and-Post-Processing-Options#convert-rails-into-single-notes",
            )
        ui.separator()
        with ui.grid(columns=3):
            rail_distance = make_input("Max-Dist", 1, "rail_distance", suffix="b", tooltip="Maximum distance")
            action_btn_cls(
                tooltip="Connect notes",
                icon="linear_scale", icon_angle=90,
                func=lambda data, types, rail_filter, **kwargs: data.apply_for_note_types(rails.connect_singles, max_interval=rail_distance.parsed_value, types=types, rail_filter=rail_filter),
                wiki_ref="Pre--and-Post-Processing-Options#connect-single-notes-into-rails",
            )
            action_btn_cls(
                tooltip="Connect rails",
                icon="add_link",
                func=lambda data, types, rail_filter, **kwargs: data.apply_for_note_types(rails.merge_rails, max_interval=rail_distance.parsed_value, types=types, rail_filter=rail_filter),
                wiki_ref="Pre--and-Post-Processing-Options#merge-rails",
            )
        ui.separator()
        with ui.row():
            rail_interval = make_input("Interval", "1/16", "rail_interval", suffix="b")
            with ui.switch("From end", value=False).props('dense size="xs"').classes("my-auto").bind_value(app.storage.user, "dashboard_rail_from_back") as rail_from_back:
                ui.tooltip("Start operation from the end instead of the start, so e.g. shorten would cut from start instead of end and extending looks at previous instead of next.")
        with ui.grid(columns=3):
            action_btn_cls(
                tooltip="Split rail at time intervals",
                icon="format_line_spacing"+"link_off",
                func=lambda data, types, rail_filter, **kwargs: data.apply_for_note_types(rails.segment_rail, max_length=rail_interval.parsed_value*(1-rail_from_back.value*2), types=types, rail_filter=rail_filter),
            )
            action_btn_cls(
                tooltip="Interpolate rail nodes",
                icon="format_line_spacing"+"commit",
                apply_func=partial(rails.interpolate_nodes, mode="spline"),
                apply_args=lambda: dict(interval=rail_interval.parsed_value*(1-rail_from_back.value*2)),
                wiki_ref="Rail-Options#interpolate",
            )
            action_btn_cls(
                tooltip="Extend level",
                icon="swipe_right_alt" + "horizontal_rule",
                apply_func=rails.extend_level,
                apply_args=lambda: dict(distance=rail_interval.parsed_value*(1-rail_from_back.value*2)),
            )

            action_btn_cls(
                tooltip="Rail to notestack (delete rail)",
                icon="animation",
                func=lambda data, types, rail_filter, **kwargs: data.apply_for_note_types(rails.rails_to_notestacks, interval=rail_interval.parsed_value*(1-rail_from_back.value*2), keep_rail=False, types=types, rail_filter=rail_filter),
            )
            action_btn_cls(
                tooltip="Rail to notestack (keep rail)",
                icon="animation"+"show_chart",
                func=lambda data, types, rail_filter, **kwargs: data.apply_for_note_types(rails.rails_to_notestacks, interval=rail_interval.parsed_value*(1-rail_from_back.value*2), keep_rail=True, types=types, rail_filter=rail_filter),
            )
            action_btn_cls(
                tooltip="Extend directional / straight",
                icon="swipe_right_alt" + "double_arrow",
                apply_func=rails.extend_straight,
                apply_args=lambda: dict(distance=rail_interval.parsed_value*(1-rail_from_back.value*2)),
            )

            action_btn_cls(
                tooltip="Shorten rail by amount from the end",
                icon="content_cut"+"straighten",
                apply_func=rails.shorten_rail_by,
                apply_args=lambda: dict(distance=rail_interval.parsed_value*(1-rail_from_back.value*2)),
                wiki_ref="Rail-Options#shorten-rails",
            )
            action_btn_cls(
                tooltip="Shorten rail to given length",
                icon="straighten"+"content_cut",
                apply_func=rails.shorten_rail_to,
                apply_args=lambda: dict(distance=rail_interval.parsed_value*(1-rail_from_back.value*2)),
            )
            action_btn_cls(
                tooltip="Extend pointing to next",
                icon="swipe_right_alt" + "swipe_right_alt",
                func=lambda data, types, rail_filter, **kwargs: data.apply_for_note_types(rails.extend_to_next, distance=rail_interval.parsed_value*(1-rail_from_back.value*2), types=types, rail_filter=rail_filter),
            )

            action_btn_cls(
                tooltip="Create a both-hands lightning rail that zig-zags between the first rail of one hand and rails of the other hand",
                icon="graphic_eq",
                icon_angle=-45,
                func=lambda data, types, rail_filter, **kwargs: pattern_generation.create_lightning(data=data, interval=rail_interval.parsed_value*(1-rail_from_back.value*2), rail_filter=rail_filter),
            ).classes("text-yellow")

def smoothing_card(action_btn_cls: Any) -> None:
    with ui.card():
        ui.label("Smoothing")
        with ui.row():
            smooth_iterations = make_input("Iterations", "3", "smooth_interations", tooltip="Number of smoothing iterations. Higher number leads to more smoothing.")
            smooth_resistance = make_input("Resist", "1", "smooth_resistance", tooltip="Resistance of original rail against smoothing. Higher values results in smaller changes.")
            action_btn_cls(
                tooltip="Smooth rail nodes",
                icon="switch_access_shortcut",
                icon_angle=90,
                func=lambda data, types, rail_filter, **kwargs: data.apply_for_note_types(rails.reinterpolation_smoothing, 
                    iterations=int(smooth_iterations.parsed_value),
                    resistance=smooth_resistance.parsed_value,
                    singles_mode=smooth_singlesmode.value,
                    types=types,
                    rail_filter=rail_filter,
                ),
            )
        with ui.row().classes("w-full"):
            smooth_singlesmode = ui.radio({"snap":"", "anchor":"", "temp_anchor":""}, value="anchor").props("dense inline").bind_value(app.storage.user, "dashboard_smooth_singlesmode")
            with ui.teleport(f"#c{smooth_singlesmode.id} > div:nth-child(1)"):
                ui.tooltip("Snap single notes to smoothed rail")
                ui.icon("moving", size="sm")
            with ui.teleport(f"#c{smooth_singlesmode.id} > div:nth-child(2)"):
                ui.tooltip("Single notes anchor rail for smoothing")
                ui.icon("anchor", size="sm")
            with ui.teleport(f"#c{smooth_singlesmode.id} > div:nth-child(3)"):
                ui.tooltip("Remove anchors notes after smoothing (if you placed them as tempoary anchors)")
                ui.icon("delete", size="sm")


def color_card(action_btn_cls: Any) -> None:
    with ui.card():
        with ui.label("Color"):
            wiki_reference("Pre--and-Post-Processing-Options#change-note-type")

        action_btn_cls(
            tooltip="Swap Hands (ignores filters)",
            icon="swap_horizontal_circle",
            func=_swap_hands,
            wiki_ref="Pre--and-Post-Processing-Options#swap-hands",
        ).props("outline")
        action_btn_cls(
            tooltip="Change to left hand",
            icon="change_circle",
            func=partial(_change_color, new_type="left"),
            color="cyan",
        )
        action_btn_cls(
            tooltip="Change to right hand",
            icon="change_circle",
            func=partial(_change_color, new_type="right"),
            color="pink",
        )
        action_btn_cls(
            tooltip="Change to single hand",
            icon="change_circle",
            func=partial(_change_color, new_type="single"),
            color="green",
        )
        action_btn_cls(
            tooltip="Change to both hands",
            icon="change_circle",
            func=partial(_change_color, new_type="both"),
            color="amber",
        )

def spiral_spike_card(action_btn_cls: Any) -> None:
    with ui.card():
        ui.label("Spiralize and Spikify")
        with ui.row():
            spiral_angle = make_input("Angle", 45, "spiral_angle", suffix="°", tooltip="Angle between nodes. Choose 180 for zigzag.")
            spiral_start = make_input("Start", 0, "spiral_start", suffix="°", tooltip="Angle of first node: 0=right, 90=up, 180=left, 270/-90=down")
            spiral_radius = make_input("Radius", 1, "spiral_radius", suffix="sq", tooltip="Radius of spiral / Length of spikes")
        with ui.row():
            with ui.switch("Interpolate", value=True).props('size="xs"').classes("my-auto").bind_value(app.storage.user, "dashboard_spiral_do_interpolate") as spiral_do_interpolate:
                ui.tooltip("Interpolate rail before adding spiral/spikes. Enable this for consistent spacing.")
            spiral_interpolation = make_input("Interval", "1/16", "spiral_interpolation", suffix="b", tooltip="Time between spiral nodes/spikes").bind_enabled(spiral_do_interpolate, "value")
        with ui.label("Spiral"):
            wiki_reference("Rail-Options#spiral")
        with ui.row():
            def _add_spiral(nodes: "numpy array (n, 3)", fid_dir: int, direction: int = 1, relative: bool = False, pivot: "optional numpy array (2+)"=None,) -> "numpy array (n, 3)":
                if spiral_do_interpolate.value:
                    nodes = rails.interpolate_nodes(nodes, mode="spline", interval=spiral_interpolation.parsed_value)
                return pattern_generation.add_spiral(
                    nodes,
                    fidelity=fid_dir*(360*_safe_inverse(spiral_angle.parsed_value) or 1),  # if angle=0, default to 1
                    radius=spiral_radius.parsed_value,
                    start_angle=spiral_start.parsed_value,
                    direction=direction,
                )
            action_btn_cls(
                tooltip="Spiral (counter-clockwise)",
                icon="rotate_left",
                apply_func=partial(_add_spiral, fid_dir=1),
            ).props("rounded")
            action_btn_cls(
                tooltip="Spiral (clockwise)",
                icon="rotate_right",
                apply_func=partial(_add_spiral, fid_dir=-1),
            ).props("rounded")
            action_btn_cls(
                tooltip="Random nodes",
                icon="casino",
                apply_func=partial(_add_spiral, fid_dir=0),
            ).props("rounded outline")
        with ui.row():
            with ui.label("Spikes"):
                wiki_reference("Rail-Options#spikes")
            spike_duration = make_input("Duration", 0, "spike_duration", suffix="b", tooltip="Duration of spikes.")
        with ui.row():
            def _add_spikes(nodes: "numpy array (n, 3)", fid_dir: int, direction: int = 1, relative: bool = False, pivot: "optional numpy array (2+)"=None,) -> "numpy array (n, 3)":
                if spiral_do_interpolate.value:
                    nodes = rails.interpolate_nodes(nodes, mode="spline", interval=spiral_interpolation.parsed_value)
                return pattern_generation.add_spikes(
                    nodes,
                    fidelity=fid_dir*(360*_safe_inverse(spiral_angle.parsed_value) or 1),  # if angle=0, default to 1
                    radius=spiral_radius.parsed_value,
                    spike_duration=spike_duration.parsed_value,
                    start_angle=spiral_start.parsed_value,
                    direction=direction,
                )
            action_btn_cls(
                tooltip="Spikes (counter-clockwise)",
                icon="rotate_left",
                apply_func=partial(_add_spikes, fid_dir=1),
            ).props("square")
            action_btn_cls(
                tooltip="Spikes (clockwise)",
                icon="rotate_right",
                apply_func=partial(_add_spikes, fid_dir=-1),
            ).props("square")
            action_btn_cls(
                tooltip="Spikes (random)",
                icon="casino",
                apply_func=partial(_add_spikes, fid_dir=0),
            ).props("square")

def wall_spacing_card(action_btn_cls: Any) -> None:
    with ui.card():
        ui.label("Wall spacing")
        with ui.row():
            compress_interval = make_input("Spacing", "1/64", "compress_interval", suffix="b", tooltip="Space between walls")
            action_btn_cls(
                tooltip="Compress (ignores filters)",
                icon="compress",
                icon_angle=90,
                func=lambda data, **kwargs: _space_walls(data, interval=compress_interval.parsed_value),
            )
        with ui.row():
            wall_limit = make_input("Walls/4s", 195, "spawn_limit", tooltip="200=wireframe limit, 500=spawn limit")
            action_btn_cls(
                tooltip="Distribute walls to configured densit (ignores filters)",
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
    smoothing_card,
    color_card,
    spiral_spike_card,
    wall_spacing_card,
]

def _dashboard_tab() -> None:
    with ui.row():
        with ui.card().classes("h-14 bg-grey-9").props("dark"), ui.row():
            sw_use_orig = ui.switch("", value=False).props('dense size="xl" icon="restore" color="accent" keep-color').bind_value(app.storage.user, "dashboard_use_orig")
            sw_use_orig.tooltip("Restore original data copied from editor, to quickly try different settings.")
            sw_mirror_left = ui.switch("", value=False).props('dense size="xl" icon="flip" color="secondary" keep-color').bind_value(app.storage.user, "dashboard_mirror_left")
            sw_mirror_left.tooltip("Mirror operations for left notes and left walls, e.g. offseting right will move those left instead")
            sw_realign = ui.switch("", value=True).props('dense size="xl" icon="align_horizontal_left" color="orange" keep-color').bind_value(app.storage.user, "dashboard_realign")
            sw_realign.tooltip("After completion, align the start of the selection to the very first object. Not recommended when shifting in time or shortening rails.")

            ui.separator().props("vertical")

            with ui.button(icon="filter_alt", color="info").props("dense").classes("w-10 h-8 -my-1") as filter_menu_btn:
                ui.tooltip("Open filter settings")
                filter_types: dict[str, bool] = app.storage.user.get("dashboard_filter", {ty: True for ty in synth_format.ALL_TYPES})

                filter_badge = ui.badge(str(sum(filter_types.values())), color="green").props("floating")
                def _bdg_color(invert_filter: bool) -> None:
                    filter_badge.props(f'color="{"red" if invert_filter else "green"}"')

                filter_chk: dict[str, ui.checkbox] = {}
                filter_cats: dict[str, ui.checkbox] = {}
                ty_lookup = {"notes": synth_format.NOTE_TYPES, "walls": synth_format.WALL_TYPES, "effects": ("lights", "effects")}

                _chk_update = False
                @contextmanager
                def _chk_change():
                    nonlocal _chk_update
                    if _chk_update:
                        yield True
                    else:
                        _chk_update = True
                        yield False
                        _chk_update = False
                    filter_badge.set_text(str(sum(filter_types.values())))
                    app.storage.user["dashboard_filter"] = filter_types

                def _cat_change(ev: events.ValueChangeEventArguments) -> None:
                    with _chk_change() as recurse:
                        if recurse:
                            return
                        for g, chk in filter_cats.items():
                            if chk != ev.sender:
                                continue
                            for ty in ty_lookup[g]:
                                filter_chk[ty].set_value(ev.value)

                def _ty_change(group: str) -> None:
                    with _chk_change() as recurse:
                        if recurse:
                            return
                        vals = [filter_chk[ty].value for ty in ty_lookup[group]]
                        if all(val == True for val in vals):
                            filter_cats[group].set_value(True)
                        elif all(val == False for val in vals):
                            filter_cats[group].set_value(False)
                        else:
                            filter_cats[group].set_value(None)

                with ui.menu().classes("p-2") as filter_menu:
                    filter_enable = ui.switch("Enable Filter", value=False).props('dense icon="filter_alt" color="info"').classes("p-2").tooltip("Enable filter").bind_value(app.storage.user, "dashboard_filter_enable")
                    filter_menu_btn.bind_icon_from(filter_enable, "value", backward=lambda v: "filter_alt" if v else "filter_alt_off")
                    ui.separator()
                    with ui.element().bind_visibility_from(filter_enable, "value"):
                        with ui.row().classes("bg-grey-9").props("dark"):
                            filter_enable_type = ui.switch("Filter type", value=True).props('dense icon="filter_alt" color="info"').classes("p-2").tooltip("Enable type filter").bind_value(app.storage.user, "dashboard_filter_enable_type")
                            filter_invert = ui.switch("Invert type", value=False).props('dense icon="flaky" color="black"').classes("p-2").tooltip("Invert type filter (ignore selected type)").bind_value(app.storage.user, "dashboard_filter_invert")
                            filter_invert.on_value_change(lambda ev: _bdg_color(ev.value))
                            _bdg_color(filter_invert.value)
                        with ui.element().bind_visibility_from(filter_enable_type, "value"):
                            with ui.row().classes("py-2"):
                                filter_cats["notes"] = ui.checkbox(text="Notes", value=True).props('dense keep-color').classes("w-16").tooltip("Toggle all notes")
                                ui.separator().props("vertical").classes("m-0 p-0")
                                filter_chk["left"] = ui.checkbox(value=True).props('dense color="cyan" keep-color').tooltip("Left notes/rails")
                                filter_chk["right"] = ui.checkbox(value=True).props('dense color="pink" keep-color').tooltip("Right notes/rails")
                                filter_chk["single"] = ui.checkbox(value=True).props('dense color="green" keep-color').tooltip("Single handed notes/rails")
                                filter_chk["both"] = ui.checkbox(value=True).props('dense color="amber" keep-color').tooltip("Two-handed notes/rails")
                            with ui.row().classes("py-2"):
                                filter_cats["walls"] = ui.checkbox(text="Walls", value=True).props('dense keep-color').classes("w-16").tooltip("Toggle all walls")
                                ui.separator().props("vertical").classes("m-0 p-0")
                                with ui.grid(rows=2, columns=4):
                                    filter_chk["wall_left"] = ui.checkbox(value=True).props('dense checked-icon="flip" unchecked-icon="flip" color="cyan"').tooltip("Left walls")
                                    filter_chk["wall_right"] = ui.checkbox(value=True).props('dense checked-icon="flip" unchecked-icon="flip" color="pink"').classes("rotate-180 w-5").tooltip("Right walls")
                                    filter_chk["crouch"] = ui.checkbox(value=True).props('dense checked-icon="flip" unchecked-icon="flip" color="green"').classes("rotate-90 w-5").tooltip("Crouch walls")
                                    filter_chk["square"] = ui.checkbox(value=True).props('dense checked-icon="check_box_outline_blank" unchecked-icon="check_box_outline_blank" color="amber"').tooltip("Square walls")
                                    
                                    filter_chk["angle_left"] = ui.checkbox(value=True).props('dense checked-icon="switch_right" unchecked-icon="switch_right" color="cyan"').tooltip("Left angled walls")
                                    filter_chk["angle_right"] = ui.checkbox(value=True).props('dense checked-icon="switch_left" unchecked-icon="switch_left" color="pink"').tooltip("Right angled walls")
                                    filter_chk["center"] = ui.checkbox(value=True).props('dense checked-icon="unfold_more_double" unchecked-icon="unfold_more_double" color="green"').tooltip("Center walls")
                                    filter_chk["triangle"] = ui.checkbox(value=True).props('dense checked-icon="change_history" unchecked-icon="change_history" color="amber"').tooltip("Triangle walls")
                            with ui.row().classes("py-2"):
                                filter_cats["effects"] = ui.checkbox(text="Effects", value=True).props('dense keep-color').classes("w-16").tooltip("Toggle all effects")
                                ui.separator().props("vertical").classes("m-0 p-0")
                                filter_chk["lights"] = ui.checkbox(value=True).props('dense checked-icon="lightbulb" unchecked-icon="lightbulb" color="yellow"').tooltip("Light effects")
                                filter_chk["effects"] = ui.checkbox(value=True).props('dense checked-icon="bolt" unchecked-icon="bolt" color="yellow"').tooltip("Flash effects")
                            for g, tys in ty_lookup.items():
                                filter_cats[g].on_value_change(_cat_change)
                                for t in tys:
                                    chk = filter_chk[t]
                                    chk.bind_value(filter_types, t)
                                    chk.on_value_change(partial(_ty_change, g))
                                _ty_change(g)  # update group checkbox state
                        ui.separator()
                        with ui.row().classes("bg-grey-9").props("dark"):
                            filter_enable_rails = ui.switch("Filter notes/rails", value=True).props('dense icon="filter_alt" color="info"').classes("p-2").tooltip("Enable notes/rails filter").bind_value(app.storage.user, "dashboard_filter_enable_rail")
                        with ui.element().bind_visibility_from(filter_enable_rails, "value"):
                            with ui.row().classes("bg-grey-9").props("dark"):
                                filter_single = ui.switch("Single notes", value=True).props('dense icon="sports_baseball" color="info"').classes("p-2").tooltip("Allow single notes. Note that some functions need single nodes to work (e.g. split rails).").bind_value(app.storage.user, "dashboard_filter_allow_single")
                                filter_rails = ui.switch("Rails", value=True).props('dense icon="show_chart" color="info"').classes("p-2").tooltip("Allow rails. Length and node spacing can be constrainted below.").bind_value(app.storage.user, "dashboard_filter_allow_rails")
                            with ui.element().bind_visibility_from(filter_rails, "value"):
                                with ui.row():
                                    ui.label("Rail length").classes("my-auto w-24")
                                    ui.separator().props("vertical")
                                    filter_raillen_min = make_input("Min", "", "raillen_min", suffix="b", allow_empty=True)
                                    ui.label("to").classes("my-auto")
                                    filter_raillen_max = make_input("Max", "", "raillen_max", suffix="b", allow_empty=True)
                                    ui.tooltip("Only affect rails with this length").props('max-width="20%"')
                                with ui.row():
                                    ui.label("Node spacing").classes("my-auto w-24")
                                    ui.separator().props("vertical")
                                    filter_railspace_min = make_input("Min", "", "railspace_min", suffix="b", allow_empty=True)
                                    ui.label("to").classes("my-auto")
                                    filter_railspace_max = make_input("Max", "", "railspace_max", suffix="b", allow_empty=True)
                                    ui.tooltip("Only affect rails where all nodes have a time spacing between min and max")
                                with ui.row():
                                    ui.label("Node count").classes("my-auto w-24")
                                    ui.separator().props("vertical")
                                    filter_railnodes_min = make_input("Min", "", "railnodes_min", allow_empty=True)
                                    ui.label("to").classes("my-auto")
                                    filter_railnodes_max = make_input("Max", "", "railnodes_max", allow_empty=True)
                                    ui.tooltip("Only affect rails with a node count between min and max")
                                def _fix_inputs() -> None:
                                    for inp in (filter_raillen_min, filter_raillen_max, filter_railspace_min, filter_railspace_max, filter_railnodes_min, filter_railnodes_max):
                                        inp.update()
                                filter_menu.on_value_change(_fix_inputs)
            ui.separator().props("vertical")

            with ui.label("Coordinates"):
                wiki_reference("Movement-Options#pivot-and-relative")
            coordinate_mode = ui.radio({"absolute":"", "relative":"", "pivot":""}, value="absolute").props("dense inline dark").bind_value(app.storage.user, "dashboard_coord_mode")
            with ui.teleport(f"#c{coordinate_mode.id} > div:nth-child(1)"):
                ui.tooltip("Absolute (grid center)")
                ui.icon("grid_4x4", size="sm")
            with ui.teleport(f"#c{coordinate_mode.id} > div:nth-child(2)"):
                ui.tooltip("Relative (rail head & wall angle)")
                ui.icon("start", size="sm").classes("rotate-315")
            with ui.teleport(f"#c{coordinate_mode.id} > div:nth-child(3)"):
                ui.tooltip("Pivot (custom position)")
                ui.icon("tune", size="sm")
            with ui.row().classes("-my-2") as pivot_settings:
                pivot_settings.bind_visibility_from(coordinate_mode, "value", backward=lambda v: v=="pivot")
                with ui.row():
                    ui.tooltip("Pivot position")
                    pivot_x = make_input("X", 0, "pivot_x", suffix="sq").props("dark")
                    pivot_y = make_input("Y", 0, "pivot_y", suffix="sq").props("dark")
                    pivot_t = make_input("Time", 0, "pivot_t", suffix="b").props("dark")

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
            with (self.add_slot("default") if icon_angle else self):
                ui.tooltip(tooltip)
                if wiki_ref is not None:
                    wiki_reference(wiki_ref, True).props("floating")
                if icon_angle:
                    # create dedicated object, which can rotate independently from button
                    ui.icon(icon).style(f"rotate: {icon_angle}deg")


        @handle_errors
        def do_action(self):
            settings = {
                k.removeprefix("dashboard_"): v
                for k, v in app.storage.user.items()
                if k.startswith("dashboard_")
            }
            try:
                rail_filter = None
                types = synth_format.ALL_TYPES
                if filter_enable.value and filter_enable_rails.value:
                    rail_filter = synth_format.RailFilter(
                        single=filter_single.value,
                        rails=filter_rails.value,
                        min_len=filter_raillen_min.parsed_value,
                        max_len=filter_raillen_max.parsed_value,
                        min_count=filter_railnodes_min.parsed_value,
                        max_count=filter_railnodes_max.parsed_value,
                        min_spacing=filter_railspace_min.parsed_value,
                        max_spacing=filter_railspace_max.parsed_value,
                    )
                if filter_enable.value and filter_enable_type.value:
                    types = tuple(ty for ty, ty_enabled in filter_types.items() if ty_enabled != filter_invert.value)
                with safe_clipboard_data(use_original=sw_use_orig.value, realign_start=sw_realign.value) as data:
                    self._func(
                        data=data,
                        types=types,
                        rail_filter=rail_filter or None,  # if rail-filter is false-ish (nothing set), pass None
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
                caption=pretty_list(
                    [f"{counts[t]['total']} {t if counts[t]['total'] != 1 else t.rstrip('s')}" for t in ("notes", "rails", "rail_nodes", "walls")]
                    +([f"{len(types)} types filtered"]  if set(types) != set(synth_format.ALL_TYPES) else [])
                    +(["note/rail filter active"] if rail_filter else [])
                ),
            )

    with pivot_settings:
        def _pick_pivot(data: synth_format.DataContainer, types, rail_filter, **kwargs) -> None:
            first = data.find_first()
            if first is None:
                raise PrettyError("No object found matching the filter")
            x, y, t = first[1][:3]
            pivot_x.value = pretty_fraction(x)
            pivot_y.value = pretty_fraction(y)
            pivot_t.value = pretty_fraction(t)
        ActionButton(
            tooltip="Pick position of first object",
            icon="colorize",
            func=_pick_pivot,
        ).props("outline").classes(replace="w-10 h-8 my-1")

    with ui.row():
        for card_func in card_funcs:
            card_func(ActionButton)

dashboard_tab = GUITab(
    name = "dashboard",
    label = "Dashboard",
    icon = "dashboard",
    content_func=_dashboard_tab,
)