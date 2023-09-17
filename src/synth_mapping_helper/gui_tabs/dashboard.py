from typing import Callable, Optional, List

import numpy as np
from nicegui import app, events, ui

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
    return 0 if v == 0 else 1/v

def dashboard_tab():
    class SMHInput(ui.input):
        def __init__(self, label: str, value: str|float, storage_id: str, tooltip: Optional[str]=None, suffix: Optional[str] = None, **kwargs):
            super().__init__(label=label, value=str(value), **kwargs)
            self.bind_value(self, f"dashboard_{storage_id}")
            self.classes("w-12 h-10")
            self.props('dense input-style="text-align: right"')
            if suffix:
                self.props(f'suffix="{suffix}"')
            with self:
                if tooltip is not None:
                    ui.tooltip(tooltip)
        @property
        def parsed_value(self) -> float:
            return self.parsed_value

    with ui.row():
        # with ui.card().classes("h-16"), ui.row():
        #     with ui.label("Filter").classes("my-auto"):
        #         wiki_reference("Miscellaneous-Options#filtering")
        #     with ui.button(icon="filter_alt"):
        #         ui.badge("0", color="red").props("floating")
        #     with ui.switch("Delete other"):
        #         wiki_reference("Pre--and-Post-Processing-Options#delete-everything-not-matching-filter")
        with ui.card().classes("h-16"), ui.row():
            with ui.switch("Use original", value=False).bind_value(app.storage.user, "dashboard_use_orig") as sw_use_orig:
                wiki_reference("Miscellaneous-Options#use-original-json")
            with ui.switch("Mirror left hand", value=False).bind_value(app.storage.user, "dashboard_mirror_left") as sw_mirror_left:
                wiki_reference("Miscellaneous-Options#mirror-operations-for-left-hand")
            with ui.switch("Realign start", value=False).bind_value(app.storage.user, "dashboard_realign") as sw_realign:
                wiki_reference("Pre--and-Post-Processing-Options#keep-selection-alignment")
        with ui.card().classes("h-16"), ui.row():
            with ui.label("Coordinates").classes("my-auto"):
                wiki_reference("Movement-Options#pivot-and-relative")
            coordinate_mode = ui.toggle(["absolute", "relative", "pivot"], value="absolute").classes("my-auto").bind_value(app.storage.user, "dashboard_coord_mode")
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
                    ui.icon(icon).classes(f"rotate-{icon_angle}")
                if wiki_ref is not None:
                    wiki_reference(wiki_ref, True).props("floating")

        def do_action(self, e: events.ClickEventArguments):
            try:
                d = synth_format.import_clipboard(use_original=sw_use_orig.value)
            except ValueError as ve:
                error(f"Error reading data from clipboard", ve)
                return
            try:
                self._func(
                    data=d,
                    types=synth_format.ALL_TYPES,  # placeholder
                    mirror_left=sw_mirror_left.value,
                    relative=(coordinate_mode.value=="relative"),
                    pivot=[pivot_x.parsed_value, pivot_y.parsed_value, pivot_t.parsed_value] if (coordinate_mode.value=="pivot") else None
                )
            except Exception as exc:
                error(f"Error executing action", exc)
                return
            info(
                f"Completed: '{self._tooltip}'",
                caption=f"{d.notecount} note{'s' if d.notecount != 1 else ''}, {d.wallcount} wall{'s' if d.wallcount != 1 else ''}",
            )
            synth_format.export_clipboard(d, realign_start=sw_realign.value)

    ui.separator().classes("my-1")
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
                offset_t = ui.input("Time", value="1").props("dense suffix=b").classes("w-12 h-10").bind_value(app.storage.user, "dashboard_offset_t")
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
                with ui.label().classes("mt-auto w-min bg-secondary").bind_text_from(scale_xy, "value", backward=lambda v: f"{_safe_inverse(parse_number(v)):.1%}"):
                    ui.tooltip("This is the exact inverse of the scale up. Percent calculations are weird like that.")
                scaleup_label.bind_text_from(scale_xy, "value", backward=lambda v: f"{parse_number(v):.1%}")
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
            ui.separator()
            with ui.label("Mirror & Flatten"):
                ui.tooltip("Just scaling, but with -1 or 0")
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
                    tooltip="To notestack (delete rail)",
                    icon="animation",
                    func=lambda data, types, **kwargs: data.apply_for_note_types(rails.rails_to_notestacks, interval=rail_interval.parsed_value, keep_rail=False, types=types),
                )
                SMHActionButton(
                    tooltip="To notestack (keep rail)",
                    icon="animation"+"show_chart",
                    func=lambda data, types, **kwargs: data.apply_for_note_types(rails.rails_to_notestacks, interval=rail_interval.parsed_value, keep_rail=True, types=types),
                )
                SMHActionButton(
                    tooltip="Shorten rail (cuts from start if negative)",
                    icon="content_cut",
                    func=lambda data, types, **kwargs: data.apply_for_all(rails.shorten_rail, distance=rail_interval.parsed_value, types=types),
                    wiki_ref="Rail-Options#shorten-rails",
                )

        # with ui.card():
        #     with ui.label("Change Notes"):
        #         wiki_reference("Pre--and-Post-Processing-Options#change-note-type")
        #     with ui.row():
        #         ui.button(icon="change_circle", color="#009BAA").classes("w-12 h-10")
        #         ui.button(icon="change_circle", color="#E32862").classes("w-12 h-10")
        #     with ui.row():
        #         ui.button(icon="change_circle", color="#49BB08").classes("w-12 h-10")
        #         ui.button(icon="change_circle", color="#FB9D10").classes("w-12 h-10")
        #     with ui.row():
        #         with ui.button(icon="swap_horizontal_circle").classes("w-12 h-10"):
        #             wiki_reference("Pre--and-Post-Processing-Options#swap-hands", True).props("floating")