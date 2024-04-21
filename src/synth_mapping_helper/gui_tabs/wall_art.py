from dataclasses import dataclass, field
from io import BytesIO
from time import time
from typing import Literal

from fastapi.responses import Response
from nicegui import ui, app, events
from nicegui.elements.scene_objects import Extrusion, Texture
import numpy as np
import pyperclip
import requests

from .map_render import MapScene, SettingsPanel
from .utils import ParseInputError, info, error
from ..utils import parse_number, pretty_time_delta, pretty_fraction, pretty_list
from .. import synth_format, movement, pattern_generation

class SMHInput(ui.input):
    def __init__(self, label: str, value: str|float, storage_id: str, tooltip: str|None=None, suffix: str|None = None, **kwargs):
        super().__init__(label=label, value=str(value), **kwargs)
        self.bind_value(app.storage.user, f"wall_art_{storage_id}")
        self.classes("w-16 h-10")
        self.props('dense input-style="text-align: right" no-error-icon')
        self.storage_id = storage_id
        if suffix:
            self.props(f'suffix="{suffix}"')
        with self:
            if tooltip is not None:
                ui.tooltip(tooltip)
        with self.add_slot("error"):
            ui.element().style("visiblity: hidden")

    def _handle_value_change(self, value: str) -> None:
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

class LargeSwitch(ui.switch):
    def __init__(self, storage_id: str, tooltip: str|None=None, color: str="primary", icon_unchecked: str|None=None, icon_checked: str|None=None):
        super().__init__()
        self.bind_value(app.storage.user, f"wall_art_{storage_id}")
        self.classes("my-auto")
        self.props(f'dense size="xl" color="{color}" keep-color' + (f' unchecked-icon="{icon_unchecked}"' if icon_unchecked is not None else '') + (f' checked-icon="{icon_checked}"' if icon_checked is not None else ''))
        self.tooltip(tooltip)

@app.get("/image_proxy")
def image_proxy(url:str):
    r = requests.get(url)
    return Response(content=r.content)

def wall_art_tab():
    preview_scene: MapScene|None = None
    refimg_obj: Texture|None = None
    walls: synth_format.WALLS = {}
    is_dragging: bool = False

    @dataclass
    class Undo:
        undo_stack: list[str, float, tuple[synth_format.WALLS], set[float]] = field(default_factory=list)
        redo_stack: list[str, float, tuple[synth_format.WALLS], set[float]] = field(default_factory=list)
        max_steps: int = 50

        def reset(self):
            self.undo_stack.clear()
            self.redo_stack.clear()

        def push_undo(self, label: str):
            self.undo_stack.append((label, time(), walls.copy(), selection.sources.copy()))
            if len(self.undo_stack) > self.max_steps:
                del self.undo_stack[0]
            self.redo_stack.clear()
        
        def undo(self):
            nonlocal walls
            if not self.undo_stack:
                ui.notify("Nothing to undo", type="info", timeout=1000)
                return
            label, timestamp, undo_walls, undo_selection = self.undo_stack.pop()
            self.redo_stack.append((label, timestamp, walls.copy(), selection.sources.copy()))
            selection.clear()
            walls.clear()
            walls |= undo_walls
            selection.select(undo_selection, mode="set")
            _soft_refresh()
            ui.notify(f"Undo: {label} ({pretty_time_delta(time() - timestamp)} ago)", type="info", timeout=1000)

        def redo(self):
            nonlocal walls
            if not self.redo_stack:
                ui.notify("Nothing to redo", type="info", timeout=1000)
                return
            label, timestamp, redo_walls, redo_selection = self.redo_stack.pop()
            self.undo_stack.append((label, timestamp, walls.copy(), selection.sources.copy()))
            selection.clear()
            walls.clear()
            walls |= redo_walls
            selection.select(redo_selection, mode="set")
            _soft_refresh()
            ui.notify(f"Redo: {label} ({pretty_time_delta(time() - timestamp)} ago)", type="info", timeout=1000)

    undo = Undo()

    @dataclass
    class Selection:
        sources: set[float] = field(default_factory=set)
        cursors: dict[float, Extrusion] = field(default_factory=dict)
        drag_time: float = None
        offset: "np.array (3)" = field(default_factory=lambda: np.array([0.0, 0.0, 0.0]))
        mirrored: bool = False
        rotation: float = 0.0
        copy: bool = False

        def clear(self):
            self.sources = set()
            if self.drag_time is not None:
                # everything is parented to this one
                self.cursors[self.drag_time].delete()
            else:
                for c in self.cursors.values():
                    c.delete()
            self.cursors = {}
            self.drag_time = None
            self.offset = np.array([0.0, 0.0, 0.0])
            self.mirrored = False
            self.rotation = 0

        def copy_to_clipboard(self):
            # copy everything when nothing is selected
            wall_data = walls if not self.sources else {t: walls[t] for t in self.sources}
            synth_format.export_clipboard(synth_format.ClipboardDataContainer(walls=wall_data), False)
            info(f"Copied {len(wall_data)} walls to clipboard")

        def delete(self):
            if not self.sources:
                return
            undo.push_undo("delete selection")
            ts = self.sources
            self.clear()
            for t in ts:
                del walls[t]
            _soft_refresh()
            ui.notify(f"Deleted {len(ts)} walls", type="info")

        def select(self, new_sources: set[float], mode: Literal["toggle", "expand", "set"]):
            if mode == "toggle":
                new_sources ^= self.sources
            elif mode == "expand" and self.sources:  # "expand" and nothing selected: "set"
                if len(new_sources) != 1:
                    raise RuntimeError("Cannot expand to more than one new time")
                new_t = min(new_sources)
                low = min(self.sources)
                high = max(self.sources)
                if new_t < low:
                    new_sources = self.sources | {t for t in walls if new_t <= t <= low}
                elif new_t > high:
                    new_sources = self.sources | {t for t in walls if high <= t <= new_t}
                else:
                    new_sources = self.sources | {t for t in walls if low <= t <= high}
            # else: leave new_sources as is
            self.clear()
            self.sources = new_sources
            self._update_cursors()

        def _update_cursors(self):
            if not self.sources:
                return
            first = min(self.sources)
            copy_offset = [0.0,0.0,_find_free_slot(first+self.offset[2])-first-self.offset[2],0.0,0.0] if self.copy else 0.0
            if self.drag_time is None:
                # re-create cursors
                for c in self.cursors.values():
                    c.delete()
                preview_settings = sp.parse_settings()
                with preview_scene:
                    pivot_3d = walls[first][0,:3]
                    scale_3d = np.array([1.0, -1.0 if self.mirrored else 1.0, 1.0])
                    for t in self.sources:
                        w = walls[t] + copy_offset
                        w = movement.rotate_around(w, self.rotation, pivot_3d)
                        w = movement.scale_from(w, scale_3d, pivot_3d)
                        w = movement.offset(w, self.offset)
                        e = preview_scene.wall_extrusion(w, preview_settings.wall.size * time_scale.parsed_value).draggable()
                        if self.copy:
                            e.material(copy_color.value, copy_opacity.parsed_value)
                        else:
                            e.material(move_color.value, move_opacity.parsed_value)
                        self.cursors[t] = e
                preview_scene.props('drag_constraints=""')
            else:
                w = walls[self.drag_time][0] + copy_offset
                scene_pos = preview_scene.to_scene(w[:3] + self.offset)
                # move cursor
                cur = self.cursors[self.drag_time]
                cur.move(*scene_pos)
                rot = w[4]+self.rotation
                if self.mirrored:
                    cur.scale(1,-1,1)
                    cur.rotate(np.deg2rad(90), np.deg2rad(180 + rot), 0)
                else:
                    cur.scale(1,1,1)
                    cur.rotate(np.deg2rad(90), np.deg2rad(180 - rot), 0)
                # update drag constraints
                if axis_z.value:
                    scene_time_step = time_step.parsed_value*time_scale.parsed_value
                    preview_scene.props(f'drag_constraints="x={scene_pos[0]},z={scene_pos[2]},y=Math.round(y/({scene_time_step}))*({scene_time_step})"')
                else:
                    preview_scene.props(f'drag_constraints="y={scene_pos[1]}"')
            
            for c in self.cursors.values():
                if self.copy:
                    c.material(copy_color.value, copy_opacity.parsed_value)
                else:
                    c.material(move_color.value, move_opacity.parsed_value)

        def move(self, offset: "numpy array (3)"):
            self.offset += offset
            self._update_cursors()

        def rotate(self, rotation: float):
            self.rotation += rotation if not self.mirrored else -rotation
            self._update_cursors()

        def mirror(self, horizontal: bool):
            self.mirrored = not self.mirrored
            if horizontal:
                self.rotation += 180
            self._update_cursors()

        def set_copy(self, copy: bool):
            self.copy = copy
            self._update_cursors()

        def apply(self):
            nonlocal walls
            ops = [l for v, l in [(self.copy, "copy"), (self.rotation, "rotate"), (self.mirrored, "mirror"), (np.any(self.offset), "offset")] if v]
            undo.push_undo(f"{pretty_list(ops)} {len(self.sources)} walls")
            first = min(self.sources)
            copy_offset = [0.0,0.0,_find_free_slot(first+self.offset[2])-first-self.offset[2],0.0,0.0] if self.copy else 0.0
            pivot_3d = walls[self.drag_time if self.drag_time is not None else first][0,:3]
            scale_3d = np.array([1.0, -1.0 if self.mirrored else 1.0, 1.0])
            new_sources = set()
            new_walls = {}
            for t in sorted(self.sources):
                w = walls[t]+copy_offset if self.copy else walls.pop(t)
                w = movement.rotate_around(w, self.rotation, pivot_3d)
                w = movement.scale_from(w, scale_3d, pivot_3d)
                w = movement.offset(w, self.offset)
                new_walls[w[0,2]] = w
                new_sources |= {w[0,2]}

            try:
                sym_ops: list[str|int] = []
                if mirror_x.value:
                    sym_ops.append("mirror_x")
                if mirror_y.value:
                    sym_ops.append("mirror_y")
                if rotsym_direction.value is not None:
                    rsym = rotsym.value * (-1 if rotsym_direction.value else 1)
                    if rotate_first.value:
                        sym_ops.insert(0, int(rsym))
                    else:
                        sym_ops.append(int(rsym))
                sym_interval = symmetry_step.parsed_value
                new_walls |= pattern_generation.generate_symmetry(new_walls, sym_ops, sym_interval)
            except ParseInputError as pie:
                error(f"Error parsing symmetry setting: {pie.input_id}", pie, data=pie.value)
                # continue anyway
                
            for _, w in sorted(new_walls.items()):
                _insert_wall(w, displace_forward=self.offset[2]>0)
            _soft_refresh()
            self.select(new_sources, "set")

        def start_drag(self, object_id: str):
            for t, c in self.cursors.items():
                if c.id == object_id:
                    self.drag_time = t
                    break
            else:
                return
            for t, c in self.cursors.items():
                if t != self.drag_time:
                    c.delete()
            pivot = walls[self.drag_time]
            preview_settings = sp.parse_settings()
            with self.cursors[self.drag_time]:
                for t in self.sources:
                    if t != self.drag_time:
                        w = walls[t]
                        relative = np.array([[0.0,0.0,0.0, w[0,3], 0.0]])
                        e = preview_scene.wall_extrusion(relative, preview_settings.wall.size * time_scale.parsed_value)
                        offset = movement.rotate(w-pivot, 180-pivot[0,4])
                        e.move(offset[0,0], offset[0,1], -(w[0,2]-pivot[0,2])*time_scale.parsed_value).rotate(0,0,np.deg2rad(w[0,4]-pivot[0,4]))
                        if self.copy:
                            e.material(copy_color.value, copy_opacity.parsed_value/2)
                        else:
                            e.material(move_color.value, move_opacity.parsed_value/2)
                        self.cursors[t] = e
            self._update_cursors()

        def end_drag(self, xyt: tuple[float, float, float]):
            self.offset = np.array(xyt) - walls[self.drag_time][0,:3]
            self.apply()

    selection = Selection()

    def _on_key(e: events.KeyEventArguments) -> None:
        if e.key.control:
            selection.set_copy(e.action.keydown)
        if not e.action.keydown:
            return
        try:
            # note: don't use key.code, as that doesn't account for keyboard layout
            key_name = e.key.name.upper()  # key.name is upper/lowercase depending on shift
            # CTRL-independent
            if e.key.number in range(1, len(synth_format.WALL_LOOKUP)+1):
                wall_type = sorted(synth_format.WALL_LOOKUP)[e.key.number-1]
                _spawn_wall(wall_type=wall_type, change_selection=e.modifiers.ctrl, extend_selection=e.modifiers.shift)
            elif e.key.is_cursorkey:
                selection.move(np.array([(e.key.arrow_right-e.key.arrow_left),(e.key.arrow_up-e.key.arrow_down),0.0])*offset_step.parsed_value)
            elif e.key.page_up or e.key.page_down:
                selection.move(np.array([0.0,0.0,(e.key.page_up-e.key.page_down)*time_step.parsed_value])*offset_step.parsed_value)
            elif e.key.enter or e.key.space:
                selection.apply()
            # CTRL: Yes
            elif e.modifiers.ctrl:
                if key_name == "A":
                    # select all
                    selection.select(set(walls), mode="set")
                    # clear text selection
                    ui.run_javascript("""
                    var sel = window.getSelection ? window.getSelection() : document.selection;
                        if (sel) {
                            if (sel.removeAllRanges) {
                                sel.removeAllRanges();
                            } else if (sel.empty) {
                                sel.empty();
                            }
                        }
                    """)
                elif key_name == "C":
                    selection.copy_to_clipboard()
                elif key_name == "X":
                    selection.copy_to_clipboard()
                    if selection.sources:
                        selection.delete()
                    else:
                        undo.push_undo("cut to clipboard")
                        walls.clear()
                        _soft_refresh()
                elif key_name == "V":
                    _paste()
                elif key_name == "Z":
                    undo.undo()
                elif key_name == "Y":
                    undo.redo()
            # CTRL: No
            elif e.key.escape:
                selection.select(set(), "set")
            elif key_name == "T":
                axis_z.value = not axis_z.value
                selection.select(set(), "toggle")
            elif key_name == "R":
                _compress()
            elif key_name == "B":
                _open_blend_dialog()
            elif key_name == "E":
                ordered_keys = sorted(walls)
                if not ordered_keys:
                    return
                if not selection.sources:
                    selection.select({ordered_keys[0]}, mode="set")
                elif max(selection.sources) in ordered_keys[:-1]:
                    selection.select({ordered_keys[ordered_keys.index(max(selection.sources))+1]}, mode="set" if not e.modifiers.shift else "expand")
            elif key_name == "Q":
                ordered_keys = sorted(walls)
                if not ordered_keys:
                    return
                if not selection.sources:
                    selection.select({ordered_keys[-1]}, mode="set")
                elif min(selection.sources) in ordered_keys[1:]:
                    selection.select({ordered_keys[ordered_keys.index(min(selection.sources))-1]}, mode="set" if not e.modifiers.shift else "expand")
            elif not selection.sources:
                return
            elif e.key.delete or e.key.backspace:
                selection.delete()
            elif key_name == "D":
                selection.rotate(-(angle_step.parsed_value if not e.modifiers.shift else 90.0))
            elif key_name == "A":
                selection.rotate(angle_step.parsed_value if not e.modifiers.shift else 90.0)
            elif key_name in "WS":
                selection.mirror(horizontal=(key_name=="S"))
        except ParseInputError as pie:
            error(f"Error parsing setting: {pie.input_id}", pie, data=pie.value)
            return
    keyboard = ui.keyboard(on_key=_on_key, ignore=['input', 'select', 'button', 'textarea', "switch"])
    # dummy checkbox to bind keyboard enable state
    kb_enable = ui.checkbox(value=False).style("display:none").bind_enabled_to(keyboard, "active").bind_value_from(app.storage.user, "active_tab", backward=lambda v: v=="Wall Art")
    with ui.card():
        with ui.row():
            with ui.row():
                axis_z = LargeSwitch("axis", "(T) Change movement axis between X/Y and Time", color="info", icon_unchecked="open_with", icon_checked="schedule")
                displace = LargeSwitch("displace", "Displace existing walls when moving in time instead of replacing them.", color="warning", icon_unchecked="cancel", icon_checked="move_up")
                time_step = SMHInput("Time Step", "1/64", "time_step", suffix="b", tooltip="Time step for adding walls or moving via dragg or (page-up)/(page-down)")
                offset_step = SMHInput("Offset Step", "1", "offset_step", suffix="sq", tooltip="Step for moving via (arrow keys)")
                angle_step = SMHInput("Angle Step", "15", "angle_step", suffix="°", tooltip="Step for rotation via (A)/(D)")
            with ui.expansion("Symmetry", icon="flip").props("dense"):
                with ui.row():
                    symmetry_step = SMHInput("Interval", "1/4", "symmetry_step", suffix="b", tooltip="Time step for symmetry copies")
                    rotate_first = LargeSwitch("rotate_first", "Mirror or rotate first", color="secondary", icon_unchecked="flip", icon_checked="rotate_left")
                    ui.separator().props("vertical")
                    mirror_x = LargeSwitch("mirror_x", "Mirror across X axis, ie left-right", color="negative", icon_unchecked="align_horizontal_left", icon_checked="align_horizontal_center")
                    mirror_y = LargeSwitch("mirror_y", "Mirror across Y axis, ie up-down", color="positive", icon_unchecked="align_vertical_bottom", icon_checked="align_vertical_center")
                with ui.row():
                    ui.label("Rotation: ").classes("my-auto")
                    rotsym_direction = LargeSwitch("rotsym_direction", "Rotation direction", color="secondary", icon_unchecked="rotate_left", icon_checked="rotate_right").props('toggle-indeterminate indeterminate-icon="cancel"')
                    with ui.row():
                        ui.tooltip("Number of rotational symmetry. Note that mirror in both X and Y overlaps with even symmetries, ie 2x/4x/etc")
                        rotsym = ui.slider(min=2, max=12, value=2).props('snap markers selection-color="transparent" color="secondary" track-size="2px" thumb-size="25px"').classes("w-28").bind_value(app.storage.user, "wall_art_rotsym").bind_enabled_from(rotsym_direction, "value", backward=lambda v: v is not None)
                        ui.label().classes("my-auto w-8").bind_text_from(rotsym, "value", backward=lambda v: f"x{v}")
            with ui.expansion("Preview setttings", icon="palette").props("dense"):
                sp = SettingsPanel()
                ui.separator()
                with ui.row():
                    move_color = ui.color_input("Move", value="#888888", preview=True).props("dense").classes("w-28").bind_value(app.storage.user, "wall_art_move_color")
                    move_color.button.style("color: black")
                    move_opacity = SMHInput("Opacity", "0.5", "move_opacity")
                    copy_color = ui.color_input("Copy", value="#00ff00", preview=True).props("dense").classes("w-28").bind_value(app.storage.user, "wall_art_copy_color")
                    copy_color.button.style("color: black")
                    copy_opacity = SMHInput("Opacity", "0.5", "copy_opacity")
                ui.separator()
                with ui.row():
                    scene_width = SMHInput("Render Width", "800", "preview_width", suffix="px", tooltip="Width of the preview in px")
                    scene_height = SMHInput("Render Height", "600", "preview_height", suffix="px", tooltip="Height of the preview in px")
                    time_scale = SMHInput("Time Scale", "64", "preview_time_scale", tooltip="Ratio between XY and time")
                    frame_length = SMHInput("Frame Length", "16", "preview_frame_length", suffix="b", tooltip="Number of beats to draw frames for")
                ui.separator()
                with ui.element():
                    ui.tooltip("Display a reference image to align wall art. A low time scale (e.g. 1) is recommended to avoid distortion due to perspective, but may cause display issues.")
                    refimg_url = ui.input("Reference Image URL").props("dense").classes("w-full").bind_value(app.storage.user, "wall_art_ref_url")
                    with ui.row():
                        refimg_width = SMHInput("Width", "16", "wall_art_ref_width", suffix="sq", tooltip="Width of the reference image in sq")
                        refimg_height = SMHInput("Height", "12", "wall_art_ref_height", suffix="sq", tooltip="Height of the reference image in sq")
                        refimg_opacity = SMHInput("Opacity", "0.1", "ref_opacity")
                    with ui.row():
                        refimg_x = SMHInput("X", "0", "wall_art_ref_x", suffix="sq", tooltip="Center X of the reference image in sq")
                        refimg_y = SMHInput("Y", "0", "wall_art_ref_y", suffix="sq", tooltip="Center Y of the reference image in sq")
                        refimg_t = SMHInput("Time", "1/4", "wall_art_ref_time", suffix="b", tooltip="Time of the reference image in beats")
                apply_button = ui.button("Apply").props("outline")
        def _find_free_slot(t: float) -> float:
            while t in walls:
                t = np.round(t/time_step.parsed_value + 1)*time_step.parsed_value
            return t

        def _insert_wall(w: "np.array (1,5)", displace_forward: bool = False):
            if not displace.value:
                walls[w[0,2]] = w
                return
            pending = w
            displace_dir = -1 if displace_forward else 1
            while pending[0,2] in walls:
                walls[pending[0,2]], pending = pending, walls[pending[0,2]]
                pending[0,2] = np.round(pending[0,2]/time_step.parsed_value + displace_dir)*time_step.parsed_value
            walls[pending[0,2]] = pending

        def _spawn_wall(wall_type: int, change_selection: bool = False, extend_selection: bool = False):
            if change_selection:
                if not selection.sources:
                    return
                undo.push_undo(f"change {len(selection.sources)} walls to {synth_format.WALL_LOOKUP[wall_type]}")
                for s in selection.sources:
                    walls[s] = np.array([[0.0,0.0,s, wall_type,0.0]])
                _soft_refresh()
                selection.select(set(), "toggle")
            else:
                undo.push_undo(f"add {synth_format.WALL_LOOKUP[wall_type]}")
                try:
                    new_t = 0.0 if not selection.sources else max(selection.sources) + time_step.parsed_value
                    if not displace.value:
                        new_t = _find_free_slot(max(selection.sources, default=0.0))
                    _insert_wall(np.array([[0.0,0.0,new_t,wall_type,0.0]]))
                    _soft_refresh()
                    selection.select({new_t}, mode="set" if not extend_selection else "toggle")
                except ParseInputError as pie:
                    error(f"Error parsing setting: {pie.input_id}", pie, data=pie.value)
                    return

        def _soft_refresh():
            nonlocal refimg_obj
            try:
                preview_settings = sp.parse_settings()
            except ParseInputError as pie:
                error(f"Error parsing preview setting: {pie.input_id}", pie, data=pie.value)
                return
            if preview_scene is None:
                draw_preview_scene.refresh()
            if refimg_obj is not None:
                refimg_obj.delete()
                refimg_obj = None
            if preview_scene is not None:
                if refimg_url.value:
                    try:
                        with preview_scene:
                            coords = np.array([[[-1/2,0,1/2],[1/2,0,1/2]],[[-1/2,0,-1/2],[1/2,0,-1/2]]]) * [refimg_width.parsed_value,0,refimg_height.parsed_value]
                            pos = (refimg_x.parsed_value, refimg_t.parsed_value*time_scale.parsed_value, refimg_y.parsed_value)
                            opacity = refimg_opacity.parsed_value
                            refimg_obj = preview_scene.texture(f"/image_proxy?url={refimg_url.value}",coords).move(*pos).material(opacity=opacity)
                    except ParseInputError as pie:
                        error(f"Error parsing reference image setting: {pie.input_id}", pie, data=pie.value)
                wall_data = synth_format.DataContainer(walls=walls)
                preview_scene.render(wall_data, preview_settings)

        def _on_click(e: events.SceneClickEventArguments):
            nonlocal is_dragging
            if is_dragging or e.alt:
                is_dragging = False
                return
            try:
                for h in e.hits:
                    if h.object_id in preview_scene.wall_lookup:
                        t = preview_scene.wall_lookup[h.object_id]
                        selection.select({t}, mode="toggle" if e.ctrl else "expand" if e.shift else "set")
                        return
                selection.select(set(), "set")
            except ParseInputError as pie:
                error(f"Error parsing preview setting: {pie.input_id}", pie, data=pie.value)
                return
        def _on_dstart(e: events.SceneDragEventArguments):
            nonlocal is_dragging
            is_dragging = True
            selection.start_drag(e.object_id)

        def _on_dend(e: events.SceneDragEventArguments):
            if is_dragging:
                selection.end_drag((e.x, e.z, round((e.y / time_scale.parsed_value)/time_step.parsed_value)*time_step.parsed_value))

        @ui.refreshable
        def draw_preview_scene():
            nonlocal preview_scene
            try:
                w = int(scene_width.parsed_value)
                h = int(scene_height.parsed_value)
                l = int(frame_length.parsed_value)
                t = time_scale.parsed_value
            except ParseInputError as pie:
                error_str = f"Error parsing preview setting: {pie.input_id}"
                ui.label(error_str).classes("bg-red")
                error(error_str, pie, data=pie.value)
                return
            preview_scene = MapScene(width=w, height=h, frame_length=l, time_scale=t, on_click=_on_click, on_drag_start=_on_dstart, on_drag_end=_on_dend)
            preview_scene.move_camera(0,-t,0,0,0,0)
            _soft_refresh()

        with ui.row():
            with ui.column():
                with ui.dialog() as key_dialog, ui.card():
                    with ui.row().classes("bg-orange w-full"):
                        ui.icon("warning", size="xl").classes("my-auto")
                        ui.label("This is quite experimental. Let me know if you run into any bugs.").classes("m-auto")
                        ui.icon("warning", size="xl").classes("my-auto")
                    ui.markdown("""
                        ## Camera
                        Use left mouse to rotate the camera, right mouse to move. Scroll wheel zooms.  
                        To turn the camera *without* deselecting, hold down ALT.

                        Click on a wall to select it. Multiple walls can be selected by CTRL-Click (to add), or SHIFT-Click (expand selection to clicked wall).
                        Then drag it around using left mouse and/or use one of the edit keys below. Holding CTRL copies to the next free slot instead of moving.

                        ## General
                        |Key|Function|
                        |-|-|
                        |ESC|Deselect all|
                        |CTRL+🇦|Select all|
                        |CTRL+🇨|Copy to clipboard (selection or everything)|
                        |CTRL+🇽|Cut to clipboard (selection or everything)|
                        |CTRL+🇻|Add walls from clipboard (overrides existing)|
                        |CTRL+🇿|Undo last operation|
                        |CTRL+🇾|Redo last operation|
                        |🇶/🇪|Select previous/next Wall (SHIFT: Expand selection)|
                        |🇹|Change Axis between X/Y and Time|
                        |🇷|Compress all walls to timestep|
                        |🇧|Open Blender|

                        ## Edit
                        If you use keyboard shortcuts instead of dragging, press enter, space or click the shadow to apply.

                        |Key|Function|
                        |-|-|
                        |1️⃣-8️⃣|Spawn & select wall (SHIFT: Add to current selection)|
                        |CTRL+1️⃣-8️⃣|Change wall type|
                        |`Del`/Backspace|Delete selection|
                        |🇦/🇩|Rotate by step (SHIFT: 90 degree)|
                        |🇼|Mirror on Y axis (up-down)|
                        |🇸|Mirror on X axis (left-right)|
                        |⬅️➡️⬆️⬇️|Offset X/Y|
                        |Page Up/Down|Offset Time|
                        |Enter/Space|Apply (CTRL: Copy to next free slot)|
                    """)
                with ui.button(icon="keyboard", on_click=key_dialog.open, color="info").classes("cursor-help").style("width: 36px"):
                    ui.tooltip("Show controls")
                ui.separator()
                with ui.button(icon="undo", color="negative", on_click=undo.undo).props("outline").style("width: 36px").bind_enabled_from(undo, "undo_stack", backward=bool):
                    ui.tooltip().bind_text_from(undo, "undo_stack", backward=lambda us: f"Undo '{us[-1][0]}' (CTRL+Z) [{len(us)} steps]" if us else "Undo (CTRL+Z)")
                with ui.button(icon="redo", color="positive", on_click=undo.redo).props("outline").style("width: 36px").bind_enabled_from(undo, "redo_stack", backward=bool):
                    ui.tooltip().bind_text_from(undo, "redo_stack", backward=lambda rs: f"Redo '{rs[-1][0]}' (CTRL+Y) [{len(rs)} steps]" if rs else "Redo (CTRL+Y)")
                ui.separator()
                def _paste():
                    clipboard = pyperclip.paste()
                    try:
                        data = synth_format.import_clipboard_json(clipboard, use_original=False)
                    except ValueError as ve:
                        error(f"Error reading data from clipboard", ve, data=clipboard)
                        return
                    undo.push_undo("paste from clipboad")
                    walls.update(data.walls)
                    _soft_refresh()
                    info(f"Added {len(data.walls)} walls from clipboard")
                with ui.button(icon="content_paste", color="positive", on_click=_paste).style("width: 36px"):
                    ui.tooltip("Add walls from clipboard (CTRL+V)")
                with ui.button(icon="deselect", on_click=lambda: selection.select(set(), "set")).props("outline").style("width: 36px").bind_enabled_from(selection, "sources", backward=bool):
                    ui.tooltip("Deselect (ESC)")
                with ui.button(icon="select_all", on_click=lambda: selection.select(set(walls), "set")).props("outline").style("width: 36px"):
                    ui.tooltip("Select all (CTRL+A)")
                with ui.button(icon="content_copy", on_click=selection.copy_to_clipboard).style("width: 36px"):
                    ui.tooltip("Copy (CTRL+C)")
                with ui.button(icon="clear", color="negative", on_click=lambda _: (undo.reset(), walls.clear(), _soft_refresh())).props("outline").style("width: 36px"):
                    ui.tooltip("Clear everything (includes undo steps)")
                ui.separator()
                def _compress():
                    undo.push_undo("compress")
                    new_sources = set()
                    for i, (t, w) in enumerate(sorted(walls.items())):
                        w = w.copy()
                        del walls[t]
                        w[...,2] = i * time_step.parsed_value
                        walls[w[0,2]] = w
                        if t in selection.sources:
                            new_sources.add(w[0,2])
                    selection.select(new_sources, mode="set")
                    _soft_refresh()

                with ui.button(icon="compress", on_click=_compress).props("outline").style("width: 36px"):
                    ui.tooltip("Compress wall spacing to time step (effects all walls)")
                with ui.dialog() as blend_dialog, ui.card():
                    ui.label("Blend between patterns")
                    blend_pattern = ui.select({}, label="Choose a detected pattern:")
                    # >1 option: show selector
                    blend_pattern.bind_visibility_from(blend_pattern, "options", backward=lambda opts: len(opts)!=1)
                    # 1 option: show just text
                    ui.label("").bind_visibility_from(blend_pattern, "options", backward=lambda opts: len(opts)==1).bind_text_from(
                        blend_pattern, "options", backward=lambda opts: "Detected: " + next(iter(opts.values())) if opts else ""
                    )
                    with ui.row():
                        blend_interval = SMHInput("Interval", "1/2", "blend_interval", "Interval between blending steps", suffix="b")
                        def _do_blend():
                            nonlocal walls
                            wc, pc, pl = blend_pattern.value
                            if len(walls) != wc*pc:
                                error(f"Wall count changed! Expected {pc*wc}, found {len(walls)}", data=walls)
                                return
                            try:
                                patterns = np.array([w[0] for _, w in sorted(walls.items())]).reshape((pc, wc, 5))
                                interval = blend_interval.parsed_value
                            except ValueError as ve:
                                error(f"Could not split up {len(walls)} walls into {pc} patterns with {wc} wall{'s'*(wc!=1)} each", ve, data=walls)
                                return
                            pattern_deltas = np.diff(patterns[:,0,2])
                            if pattern_deltas.max() <= interval:
                                error(
                                    f"Blend interval ({pretty_fraction(interval)}b) must be greater than largest pattern distance ({pretty_fraction(pattern_deltas.max())}b), else blending will do nothing.",
                                    data=walls,
                                )
                                return

                            if interval <= pl:
                                ui.notify(
                                    f"Blend interval ({pretty_fraction(interval)}b) is shorter than pattern length ({pretty_fraction(pl)}b), leading to overlaps. This may result in strange results.",
                                    type="warning",
                                )

                            small_deltas = np.sum(pattern_deltas < interval)  # equal is a "regular" usecase, ie when re-blending some parts
                            if small_deltas: 
                                ui.notify(
                                    f"Blend interval ({pretty_fraction(interval)}b) is smaller than {small_deltas} of {patterns.shape[0]-1} pattern distances. Blending will do nothing between these.",
                                    type="warning"
                                )
                            undo.push_undo("blend")
                            try:
                                walls |= pattern_generation.blend_walls_multiple(patterns, interval=interval)
                            except ValueError as ve:
                                error("Error blending walls", ve, data=walls)
                                return
                            added = len(walls)//patterns.shape[1] - patterns.shape[0]
                            ui.notify(f"Created {added} additional pattern{'s'*(added!=1)} between the existing {patterns.shape[0]}", type="info")
                            _soft_refresh()
                            blend_dialog.close()
                        ui.button(icon="blender", on_click=_do_blend).props("outline").classes("w-16 h-10")

                def _open_blend_dialog():
                    if len(walls) < 2:
                        error("Need at least two walls to do blending", data=walls)
                        returnc
                    # autodetect patterns
                    try:
                        detected_patterns = pattern_generation.find_wall_patterns(walls)
                    except ValueError as ve:
                        error(f"Could not detect patterns in walls: {ve}", data=walls)
                        return
                    blend_dialog.open()
                    blend_pattern.set_options({
                        (w, p, l): (
                            f"{p} patterns, each with {w} walls and {pretty_fraction(l)}b long"
                            if w != 1 else f"{p} instances of a single wall"
                        )
                        for w, p, l in detected_patterns
                    })
                    blend_pattern.set_value(detected_patterns[0])
                    blend_interval.update()  # workaround for nicegui#2149

                with ui.button(icon="blender", on_click=_open_blend_dialog, color="info").style("width: 36px"):
                    ui.tooltip("Blend wall patterns (effects all walls)")
            draw_preview_scene()
            with ui.column():
                with ui.button(icon="delete", color="negative", on_click=selection.delete).style("width: 36px").bind_enabled_from(selection, "sources", backward=bool):
                    ui.tooltip("Delete selection (Delete/Backspace)")
                for k, (i, t) in enumerate(sorted(synth_format.WALL_LOOKUP.items())):
                    def _add_wall(e: events.GenericEventArguments, wall_type=i):
                        # python closure doesn't work as needed here, so enclose i as default param instead
                        _spawn_wall(wall_type=wall_type, change_selection=e.args["ctrlKey"], extend_selection=e.args["shiftKey"])
                    with ui.button(color="positive").on("click", _add_wall).classes("p-2"):
                        ui.tooltip(f"({k+1}) Spawn '{t}' wall (after selection), hold CTRL to change wall type instead")
                        v = synth_format.WALL_VERTS[t]
                        # draw wall vertices as svg
                        content = f'''
                            <svg viewBox="-10 -10 20 20" width="20" height="20" xmlns="http://www.w3.org/2000/svg">
                                <polygon points="{' '.join(f"{-x},{y}" for x,y in v)}" stroke="white"/>
                            </svg>
                        '''
                        ui.html(content)
            
        apply_button.on("click", draw_preview_scene.refresh)
