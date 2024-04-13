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
from ..utils import parse_number, pretty_time_delta
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
                ui.notify("Nothing to undo", type="info")
                return
            label, timestamp, undo_walls, undo_selection = self.undo_stack.pop()
            self.redo_stack.append((label, timestamp, walls.copy(), selection.sources.copy()))
            selection.clear()
            walls.clear()
            walls |= undo_walls
            selection.select(undo_selection, mode="set")
            _soft_refresh()
            ui.notify(f"Undo: {label} ({pretty_time_delta(time() - timestamp)} ago)", type="info")

        def redo(self):
            nonlocal walls
            if not self.redo_stack:
                ui.notify("Nothing to redo", type="info")
                return
            label, timestamp, redo_walls, redo_selection = self.redo_stack.pop()
            self.undo_stack.append((label, timestamp, walls.copy(), selection.sources.copy()))
            selection.clear()
            walls.clear()
            walls |= redo_walls
            selection.select(redo_selection, mode="set")
            _soft_refresh()
            ui.notify(f"Redo: {label} ({pretty_time_delta(time() - timestamp)} ago)", type="info")

    undo = Undo()

    @dataclass
    class Selection:
        sources: set[float] = field(default_factory=set)
        cursors: dict[float, Extrusion] = field(default_factory=dict)
        drag_time: float = None
        offset: "np.array (3)" = field(default_factory=lambda: np.array([0.0, 0.0, 0.0]))
        mirrored: bool = False
        rotation: float = 0.0

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
            if self.sources:
                if copy.value:
                    first = min(self.sources)
                    self.offset += [0,0,_find_free_slot(first)-first]
                preview_settings = sp.parse_settings()
                with preview_scene:
                    for t in self.sources:
                        e = preview_scene.wall_extrusion(walls[t] + [*self.offset, 0.0, 0.0], preview_settings.wall.size * time_scale.parsed_value).draggable()
                        if copy.value:
                            e.material(copy_color.value, copy_opacity.parsed_value)
                        else:
                            e.material(move_color.value, move_opacity.parsed_value)
                        self.cursors[t] = e

        def _update_cursors(self):
            pivot = walls[self.drag_time if self.drag_time is not None else min(self.sources)]
            for t, c in ([(self.drag_time, self.cursors[self.drag_time])] if self.drag_time is not None else self.cursors.items()):
                xyt = pivot[0,:3]+movement.rotate((walls[t]-pivot)[0,:3], self.rotation)*[1, -1 if self.mirrored else 1,1]+self.offset
                c.move(xyt[0], xyt[2]*time_scale.parsed_value, xyt[1])
                if self.mirrored:
                    # couldn't figure out how to change the verts, so just mirror by scaling
                    c.scale(1, -1, 1)
                    c.rotate(np.deg2rad(90), np.deg2rad(180 + (walls[t][0,4]+self.rotation)), 0)

                else:
                    c.scale(1, 1, 1)
                    c.rotate(np.deg2rad(90), np.deg2rad(180 - (walls[t][0,4]+self.rotation)), 0)

            if selection.drag_time is not None:
                if axis_z.value:
                    x, y = walls[selection.drag_time][0,:2]+selection.offset[:2]
                    preview_scene.props(f'drag_constraints="x={x},z={y},y=Math.round(y/({time_step.parsed_value*time_scale.parsed_value}))*({time_step.parsed_value*time_scale.parsed_value})"')
                else:
                    t = (_find_free_slot(selection.drag_time + selection.offset[2]) if copy.value else selection.drag_time + selection.offset[2])
                    preview_scene.props(f'drag_constraints="y={t*time_scale.parsed_value}"')

        def move(self, offset: "numpy array (4)"):
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

        def apply(self):
            nonlocal walls
            undo.push_undo("apply transform")
            pivot_3d = walls[self.drag_time if self.drag_time is not None else min(self.sources)][0,:3]
            scale_3d = np.array([1.0, -1.0 if self.mirrored else 1.0, 1.0])
            new_sources = set()
            new_walls = {}
            for t in sorted(self.sources):
                w = walls[t] if copy.value else walls.pop(t)
                w = movement.rotate_around(w, self.rotation, pivot_3d)
                w = movement.scale_from(w, scale_3d, pivot_3d)
                w = movement.offset(w, self.offset)
                new_walls[w[0,2]] = w
                new_sources |= {w[0,2]}
            walls |= new_walls
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
                        if copy.value:
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
        if not e.action.keydown:
            return
        try:
            # note: don't use key.code, as that doesn't account for keyboard layout
            key_name = e.key.name.upper()  # key.name is upper/lowercase depending on shift
            if e.modifiers.ctrl:
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
            elif e.key.escape:
                selection.select(set(), "set")
            elif key_name == "T":
                axis_z.value = not axis_z.value
                selection.select(set(), "toggle")
            elif key_name == "C":
                copy.value = not copy.value
                for c in selection.cursors.values():
                    if copy.value:
                        c.material(copy_color.value, copy_opacity.parsed_value)
                    else:
                        c.material(move_color.value, move_opacity.parsed_value)
                selection.select(set(), "toggle")
            elif key_name == "R":
                _compress()
            elif key_name == "B":
                _open_blend_dialog()
            elif e.key.number in range(1, len(synth_format.WALL_LOOKUP)+1):
                wall_type = sorted(synth_format.WALL_LOOKUP)[e.key.number]
                new_t = _find_free_slot(max(selection.sources, default=0.0))
                _insert_wall(np.array([[0.0,0.0,new_t,wall_type,0.0]]))
                _soft_refresh()
                selection.select({new_t}, mode="set" if not e.modifiers.shift else "toggle")
            elif key_name == "E":
                ordered_keys = sorted(walls)
                if not ordered_keys:
                    return
                if not selection.sources:
                    selection.select({ordered_keys[0]}, mode="set")
                elif max(selection.sources) in ordered_keys[:-1]:
                    selection.select({ordered_keys[ordered_keys.index(max(selection.sources))+1]}, mode="set" if not e.modifiers.shift else "expand")
            elif key_name == "E":
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
            elif e.key.enter or e.key.space:
                selection.apply()
            elif e.key.is_cursorkey:
                selection.move(np.array([(e.key.arrow_right-e.key.arrow_left),(e.key.arrow_up-e.key.arrow_down),0.0])*offset_step.parsed_value)
            elif e.key.page_up or e.key.page_down:
                selection.move(np.array([0.0,0.0,(e.key.page_up-e.key.page_down)*time_step.parsed_value])*offset_step.parsed_value)
            elif key_name == "D":
                selection.rotate(-(angle_step.parsed_value if not e.modifiers.shift else 90.0))
            elif key_name == "A":
                selection.rotate(angle_step.parsed_value if not e.modifiers.shift else 90.0)
            elif key_name in "WS":
                selection.mirror(horizontal=(key_name=="S"))
        except ParseInputError as pie:
            error(f"Error parsing preview setting: {pie.input_id}", pie, data=pie.value)
            return
    keyboard = ui.keyboard(on_key=_on_key)
    # dummy checkbox to bind keyboard enable state
    kb_enable = ui.checkbox(value=False).style("display:none").bind_enabled_to(keyboard, "active").bind_value_from(app.storage.user, "active_tab", backward=lambda v: v=="Wall Art")
    with ui.card():
        with ui.row():
            with ui.row():
                ui.label("Axis:").classes("my-auto")
                with ui.toggle({False: "X&Y", True: "Time"}, value=False).props('color="grey-7" rounded dense').classes("my-auto") as axis_z:
                    ui.tooltip("Change movement axis (T)")
                ui.label("Copy:").classes("my-auto")
                with ui.switch().props("dense").classes("my-auto") as copy:
                    ui.tooltip("Copy to next free slot instead of moving (C). Makes selection look weird.")
                time_step = SMHInput("Time Step", "1/64", "time_step", suffix="b", tooltip="Time step for adding and moving walls via (page-up)/(page-down)")
                offset_step = SMHInput("Offset Step", "1", "offset_step", suffix="sq", tooltip="Step for offsetting when pressing (arrow keys)")
                angle_step = SMHInput("Angle Step", "15", "angle_step", suffix="°", tooltip="Rotation when pressing (A)/(D)")
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
        def _insert_wall(w: "np.array (1,5)"):
            undo.push_undo(f"add {synth_format.WALL_LOOKUP[w[0,3]]}")
            pending = w
            while pending[0,2] in walls:
                walls[pending[0,2]], pending = pending, walls[pending[0,2]]
                pending[0,2] = np.round(pending[0,2]/time_step.parsed_value + 1)*time_step.parsed_value
            walls[pending[0,2]] = pending

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
                        Use left mouse to rotate the camera, right mouse (or left mouse and SHIFT or CTRL) to move. Scroll wheel zooms.  
                        To turn the camera *without* deselecting, hold down ALT.

                        Click on a wall to select it. Multiple walls can be selected by CTRL-Click (add/remove), or SHIFT-Click (expand selection to clicked wall).
                        Then drag it around using left mouse and/or use one of the edit keys below.

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
                        |🇪/🇶|Next or previous Wall (SHIFT: Expand selection)|
                        |🇹|Change Axis between X/Y and Time|
                        |🇨|Toggle Copy (Makes selection look weird)|
                        |🇷|Compress all walls to timestep|
                        |🇧|Open Blender|

                        ## Edit
                        If you use keyboard shortcuts instead of dragging, press enter, space or click the shadow to apply.

                        |Key|Function|
                        |-|-|
                        |1️⃣-8️⃣|Spawn & select wall (SHIFT: Add to selection)|
                        |`Del`/Backspace|Delete selection|
                        |🇦/🇩|Rotate by step (SHIFT: 90 degree)|
                        |🇼|Mirror on Y axis (up-down)|
                        |🇸|Mirror on X axis (left-right)|
                        |⬅️➡️⬆️⬇️|Offset X/Y|
                        |Page Up/Down|Offset Time|
                        |Enter/Space|Apply|
                    """)
                with ui.button(icon="keyboard", on_click=key_dialog.open, color="info").classes("cursor-help").style("width: 36px"):
                    ui.tooltip("Show controls")
                ui.separator()
                with ui.button(icon="undo", color="negative", on_click=undo.undo).props("outline").style("width: 36px").bind_enabled_from(undo, "undo_stack", backward=bool):
                    ui.tooltip("Undo (CTRL+Z)")
                with ui.button(icon="redo", color="positive", on_click=undo.redo).props("outline").style("width: 36px").bind_enabled_from(undo, "redo_stack", backward=bool):
                    ui.tooltip("Redo (CTRL+Y)")
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
                    with ui.row():
                        blend_wallcount = SMHInput("Walls", 0, "blend_wallcount", "Walls per pattern. Can be -1 if pattern count is set")
                        blend_patterncount = SMHInput("Patterns", 0, "blend_patterncount", "Number of patterns to blend between. Can be -1 if wall count is set")
                    with ui.row():
                        blend_spacing = SMHInput("Spacing", "1/2", "blend_spacing", "Interval between blending stemps")
                        def _do_blend():
                            nonlocal walls
                            try:
                                patterns = np.array([w[0] for _, w in sorted(walls.items())]).reshape((int(blend_patterncount.parsed_value), int(blend_wallcount.parsed_value), 5))
                                interval = blend_spacing.parsed_value
                            except ParseInputError as pie:
                                error(f"Error parsing blend inputs: {pie.input_id}", pie, data=pie.value)
                                return
                            except ValueError as ve:
                                error(f"Could not split up walls into {blend_patterncount.parsed_value} x {blend_wallcount.parsed_value}", ve, data=walls)
                                return
                            undo.push_undo("blend")
                            try:
                                walls |= pattern_generation.blend_walls_multiple(patterns, interval=interval)
                            except ValueError as ve:
                                error("Error blending walls", ve, data=walls)
                                return
                            _soft_refresh()
                            blend_dialog.close()
                        ui.button(icon="blender", on_click=_do_blend).props("outline").classes("w-16 h-10")

                def _open_blend_dialog():
                    # autodetect patterns
                    try:
                        wallcount, patterncount = pattern_generation.find_wall_patterns(walls)
                    except ValueError as ve:
                        error("Could not detect patterns in walls", ve, data=walls)
                        return
                    blend_dialog.open()
                    blend_wallcount.set_value(str(wallcount))
                    blend_patterncount.set_value(str(patterncount))
                    blend_spacing.update()  # workaround for nicegui#2149

                with ui.button(icon="blender", on_click=_open_blend_dialog, color="info").style("width: 36px"):
                    ui.tooltip("Blend wall patterns (effects all walls)")
            draw_preview_scene()
            with ui.column():
                with ui.button(icon="delete", color="negative", on_click=selection.delete).style("width: 36px").bind_enabled_from(selection, "sources", backward=bool):
                    ui.tooltip("Delete selection (Delete/Backspace)")
                for k, (i, t) in enumerate(sorted(synth_format.WALL_LOOKUP.items())):
                    def _add_wall(*_, wall_type=i):  # python closure doesn't work as needed here, so enclose i as default param instead
                        new_t = _find_free_slot(max(selection.sources, default=0.0))
                        _insert_wall(np.array([[0.0,0.0,new_t, wall_type,0.0]]))
                        _soft_refresh()
                        selection.select({new_t}, "set")
                    with ui.button(color="positive", on_click=_add_wall).classes("p-2"):
                        ui.tooltip(f"Spawn '{t}' wall after selection ({k})")
                        v = synth_format.WALL_VERTS[t]
                        # draw wall vertices as svg
                        content = f'''
                            <svg viewBox="-10 -10 20 20" width="20" height="20" xmlns="http://www.w3.org/2000/svg">
                                <polygon points="{' '.join(f"{-x},{y}" for x,y in v)}" stroke="white"/>
                            </svg>
                        '''
                        ui.html(content)
            
        apply_button.on("click", draw_preview_scene.refresh)