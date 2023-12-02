from dataclasses import dataclass, field

from nicegui import ui, app, events
from nicegui.elements.scene_objects import Extrusion
import numpy as np
import pyperclip

from .map_render import MapScene, SettingsPanel
from .utils import ParseInputError, info, error
from ..utils import parse_number
from .. import synth_format, movement

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

def wall_art_tab():
    preview_scene: MapScene|None = None
    walls: synth_format.WALLS = {}
    is_dragging: bool = False

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
            ts = self.sources
            self.clear()
            for t in ts:
                del walls[t]
            _soft_refresh()
            ui.notify(f"Deleted {len(ts)} walls", type="info")

        def select(self, new_sources: set[float], mode: str):
            # mode can be "set", "toggle", or "expand"
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
            pivot_3d = walls[self.drag_time if self.drag_time is not None else min(self.sources)][0,:3]
            scale_3d = np.array([1.0, -1.0 if self.mirrored else 1.0, 1.0])
            new_sources = set()
            wall_copy = walls.copy()
            for t in sorted(self.sources):
                w = wall_copy[t] if copy.value else walls.pop(t)
                w = movement.rotate_around(w, self.rotation, pivot_3d)
                w = movement.scale_from(w, scale_3d, pivot_3d)
                w = movement.offset(w, self.offset)
                walls[w[0,2]] = w
                new_sources |= {w[0,2]}
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
            if e.modifiers.ctrl:
                if e.key.code == "KeyA":
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
                elif e.key.code == "KeyC":
                    selection.copy_to_clipboard()
                elif e.key.code == "KeyV":
                    _paste()
            elif e.key.escape:
                selection.select(set(), "set")
            elif e.key.code == "KeyX":
                axis_z.value = not axis_z.value
                selection.select(set(), "toggle")
            elif e.key.code == "KeyC":
                copy.value = not copy.value
                for c in selection.cursors.values():
                    if copy.value:
                        c.material(copy_color.value, copy_opacity.parsed_value)
                    else:
                        c.material(move_color.value, move_opacity.parsed_value)
                selection.select(set(), "toggle")
            elif e.key.code == "KeyR":
                _compress()
            elif e.key.number in range(1, len(synth_format.WALL_LOOKUP)+1):
                wall_type = sorted(synth_format.WALL_LOOKUP)[e.key.number]
                new_t = _find_free_slot(max(selection.sources, default=0.0))
                _insert_wall(np.array([[0.0,0.0,new_t,wall_type,0.0]]))
                _soft_refresh()
                selection.select({new_t}, mode="toggle")
            elif e.key.code == "KeyE":
                ordered_keys = sorted(walls)
                if not ordered_keys:
                    return
                if not selection.sources:
                    selection.select({ordered_keys[0]}, mode="set")
                elif max(selection.sources) in ordered_keys[:-1]:
                    selection.select({ordered_keys[ordered_keys.index(max(selection.sources))+1]}, mode="set" if not e.modifiers.shift else "expand")
            elif e.key.code == "KeyQ":
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
            elif e.key.code in ("Enter", "NumpadEnter", "Space"):
                selection.apply()
            elif e.key.is_cursorkey:
                selection.move(np.array([(e.key.arrow_right-e.key.arrow_left),(e.key.arrow_up-e.key.arrow_down),0.0])*offset_step.parsed_value)
            elif e.key.page_up or e.key.page_down:
                selection.move(np.array([0.0,0.0,(e.key.page_up-e.key.page_down)*time_step.parsed_value])*offset_step.parsed_value)
            elif e.key.code == "KeyD":
                selection.rotate(-(angle_step.parsed_value if not e.modifiers.shift else 90.0))
            elif e.key.code == "KeyA":
                selection.rotate(angle_step.parsed_value if not e.modifiers.shift else 90.0)
            elif e.key.code in ("KeyW", "KeyS"):
                selection.mirror(horizontal=(e.key.code=="KeyS"))
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
                    ui.tooltip("Change movement axis")
                ui.label("Copy:").classes("my-auto")
                with ui.switch().props("dense").classes("my-auto") as copy:
                    ui.tooltip("Copy to next free slot instead of moving. Makes selection look weird.")
                time_step = SMHInput("Time Step", "1/64", "time_step", suffix="b", tooltip="Time step for adding and moving walls via page-up/down")
                offset_step = SMHInput("Offset Step", "1", "offset_step", suffix="sq", tooltip="Step for offsetting when pressing arrow keys")
                angle_step = SMHInput("Angle Step", "15", "angle_step", suffix="°", tooltip="Rotation when pressing A/D")
            with ui.expansion("Settings", icon="settings").props("dense"):
                with ui.row():
                    scene_width = SMHInput("Render Width", "800", "preview_width", suffix="px", tooltip="Width of the preview in px")
                    scene_height = SMHInput("Render Height", "600", "preview_height", suffix="px", tooltip="Height of the preview in px")
                    time_scale = SMHInput("Time Scale", "64", "preview_time_scale", tooltip="Ratio between XY and time")
                    frame_length = SMHInput("Frame Length", "16", "preview_frame_length", suffix="b", tooltip="Number of beats to draw frames for")
                with ui.row():
                    move_color = ui.color_input("Move", value="#888888", preview=True).props("dense").classes("w-28").bind_value(app.storage.user, "wall_art_move_color")
                    move_color.button.style("color: black")
                    move_opacity = SMHInput("Opacity", 0.5, "move_opacity")
                    copy_color = ui.color_input("Copy", value="#00ff00", preview=True).props("dense").classes("w-28").bind_value(app.storage.user, "wall_art_copy_color")
                    copy_color.button.style("color: black")
                    copy_opacity = SMHInput("Opacity", 0.5, "copy_opacity")
                apply_button = ui.button("Apply")
            with ui.expansion("Colors & Sizes", icon="palette").props("dense"):
                sp = SettingsPanel()
        def _find_free_slot(t: float) -> float:
            while t in walls:
                t = np.round(t/time_step.parsed_value + 1)*time_step.parsed_value
            return t
        def _insert_wall(w: "np.array (1,5)"):
            pending = w
            while pending[0,2] in walls:
                walls[pending[0,2]], pending = pending, walls[pending[0,2]]
                pending[0,2] = np.round(pending[0,2]/time_step.parsed_value + 1)*time_step.parsed_value
            walls[pending[0,2]] = pending

        def _soft_refresh():
            try:
                preview_settings = sp.parse_settings()
            except ParseInputError as pie:
                error(f"Error parsing preview setting: {pie.input_id}", pie, data=pie.value)
                return
            if preview_scene is None:
                draw_preview_scene.refresh()
            if preview_scene is not None:
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
                        |CTRL+🇻|Add walls from clipboard (overrides existing)|
                        |🇪/🇶|Next or previous Wall (SHIFT: Expand selection)|
                        |🇽|Change Axis|
                        |🇨|Toggle Copy (Makes selection look weird)|
                        |🇷|Compress|

                        ## Edit
                        If you use keyboard shortcuts instead of dragging, press enter, space or click the shadow to apply.

                        |Key|Function|
                        |-|-|
                        |1️⃣-8️⃣|Spawn wall|
                        |`Del`/Backspace|Delete selection|
                        |🇦/🇩|Rotate by step (SHIFT: 90 degree)|
                        |🇼|Mirror on Y axis (up-down)|
                        |🇸|Mirror on X axis (left-right)|
                        |⬅️➡️⬆️⬇️|Offset X/Y|
                        |Page Up/Down|Offset Time|
                        |Enter/Space|Apply|
                    """)
                with ui.button(icon="keyboard", on_click=key_dialog.open).style("width: 36px"):
                    ui.tooltip("Show controls")
                ui.separator()
                def _paste():
                    clipboard = pyperclip.paste()
                    try:
                        data = synth_format.import_clipboard_json(clipboard, use_original=False)
                    except ValueError as ve:
                        error(f"Error reading data from clipboard", ve, data=clipboard)
                        return
                    walls.update(data.walls)
                    _soft_refresh()
                    info(f"Added {len(data.walls)} walls from clipboard")
                with ui.button(icon="content_paste", color="positive", on_click=_paste).style("width: 36px"):
                    ui.tooltip("Add walls from clipboard (CTRL+V)")
                with ui.button(icon="deselect", on_click=lambda: selection.select(set(), "set")).style("width: 36px").bind_enabled_from(selection, "sources", backward=bool):
                    ui.tooltip("Deselect (ESC)")
                with ui.button(icon="select_all", on_click=lambda: selection.select(set(walls), "set")).style("width: 36px"):
                    ui.tooltip("Select all (CTRL+A)")
                with ui.button(icon="content_copy", on_click=selection.copy_to_clipboard).style("width: 36px"):
                    ui.tooltip("Copy (CTRL+C)")
                with ui.button(icon="clear", color="negative", on_click=lambda _: (walls.clear(), _soft_refresh())).props("outline").style("width: 36px"):
                    ui.tooltip("Clear all")
                ui.separator()
                def _compress():
                    new_sources = set()
                    for i, (t, w) in enumerate(sorted(walls.items())):
                        del walls[t]
                        w[...,2] = i * time_step.parsed_value
                        walls[w[0,2]] = w
                        if t in selection.sources:
                            new_sources.add(w[0,2])
                    selection.select(new_sources, mode="set")
                    _soft_refresh()

                with ui.button(icon="compress", on_click=_compress).style("width: 36px"):
                    ui.tooltip("Compress wall spacing to time step")
            draw_preview_scene()
            with ui.column():
                with ui.button(icon="delete", color="negative", on_click=selection.delete).style("width: 36px").bind_enabled_from(selection, "sources", backward=bool):
                    ui.tooltip("Delete selection (Delete/Backspace)")
                for k, (i, t) in enumerate(sorted(synth_format.WALL_LOOKUP.items())):
                    v = synth_format.WALL_VERTS[t]
                    def _add_wall(*_, wall_type=i):  # python closure doesn't work as needed here, so enclose i as default param instead
                        new_t = _find_free_slot(max(selection.sources, default=0.0))
                        _insert_wall(np.array([[0.0,0.0,new_t, wall_type,0.0]]))
                        _soft_refresh()
                        selection.select({new_t}, "toggle")
                    with ui.button(color="positive", on_click=_add_wall).classes("p-2"):
                        ui.tooltip(f"Spawn '{t}' wall after selection ({k})")
                        content = f'''
                            <svg viewBox="-10 -10 20 20" width="20" height="20" xmlns="http://www.w3.org/2000/svg">
                                <polygon points="{' '.join(f"{-x},{y}" for x,y in v)}" stroke="white"/>
                            </svg>
                        '''
                        ui.html(content)
            
        apply_button.on("click", draw_preview_scene.refresh)