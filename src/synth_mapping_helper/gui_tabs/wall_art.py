from base64 import b64decode, b64encode
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
from .utils import GUITab, SMHInput, PrettyError, ParseInputError, PreventDefaultKeyboard, handle_errors, info, error, safe_clipboard_data
from ..utils import parse_number, pretty_time_delta, pretty_fraction, pretty_list
from .. import synth_format, movement, pattern_generation

TURBOSTACK_COUNTS = (3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 32)

def make_input(label: str, value: str|float, storage_id: str, **kwargs) -> SMHInput:
    default_kwargs: dict[str, str|int] = {"tab_id": "wall_art", "width": 16}
    return SMHInput(storage_id=storage_id, label=label, default_value=value, **(default_kwargs|kwargs))

class LargeSwitch(ui.switch):
    def __init__(self, value: bool|None, storage_id: str, tooltip: str|None=None, color: str="primary", icon_unchecked: str|None=None, icon_checked: str|None=None, **kwargs):
        # ui.switch doesn't annotate tristate
        super().__init__(value=value, **kwargs)  # type: ignore
        self.bind_value(app.storage.user, f"wall_art_{storage_id}")
        self.classes("my-auto")
        self.props(f'dense size="xl" color="{color}" keep-color' + (f' unchecked-icon="{icon_unchecked}"' if icon_unchecked is not None else '') + (f' checked-icon="{icon_checked}"' if icon_checked is not None else ''))
        if tooltip is not None:
            self.tooltip(tooltip)

@ui.page("/wall_art_ref_image")
def image_proxy() -> Response:
    return Response(content=b64decode(app.storage.user.get("wall_art_ref_image", "")))

def _wall_art_tab() -> None:
    preview_scene: MapScene|None = None
    refimg_obj: Texture|None = None
    walls: synth_format.WALLS = {}
    is_dragging: bool = False

    @dataclass
    class Undo:
        undo_stack: list[tuple[str, float, synth_format.WALLS, set[float]]] = field(default_factory=list)
        redo_stack: list[tuple[str, float, synth_format.WALLS, set[float]]] = field(default_factory=list)
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
        drag_time: float|None = None
        offset: "np.array (3)" = field(default_factory=lambda: np.array([0.0, 0.0, 0.0]))
        mirrored: bool = False
        rotation: float = 0.0
        copy_button: bool = False
        axis_button: bool = False

        def clear(self) -> None:
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

        def copy_to_clipboard(self) -> None:
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

        def select(self, new_sources: set[float], mode: Literal["toggle", "expand", "set"]) -> None:
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

        def _update_cursors(self) -> None:
            if not self.sources or preview_scene is None:
                return
            first = min(self.sources)
            copy_mode = self.copy_button ^ drag_copy.value
            copy_offset = [0.0,0.0,_find_free_slot(first+self.offset[2])-first-self.offset[2],0.0,0.0] if copy_mode else 0.0
            if self.drag_time is None:
                # re-create cursors
                for c in self.cursors.values():
                    try:
                        c.delete()
                    except KeyError:
                        # scene sometimes loses track of objects, so use internal delete
                        c._delete()
                preview_settings = sp.parse_settings()
                with preview_scene:
                    pivot_3d = walls[first][0,:3]
                    scale_3d = np.array([1.0, -1.0 if self.mirrored else 1.0, 1.0])
                    for t in self.sources:
                        w = walls[t] + copy_offset
                        w = movement.rotate(w, angle=self.rotation, pivot=pivot_3d)
                        w = movement.scale(w, scale_3d=scale_3d, pivot=pivot_3d)
                        w = movement.offset(w, self.offset)
                        e = preview_scene.wall_extrusion(w, preview_settings.wall.size * time_scale.parsed_value).draggable()
                        if copy_mode:
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
                if self.axis_button ^ axis_z.value:
                    scene_time_step = time_step.parsed_value*time_scale.parsed_value
                    preview_scene.props(f'drag_constraints="x={scene_pos[0]},z={scene_pos[2]},y=Math.round(y/({scene_time_step}))*({scene_time_step})"')
                else:
                    preview_scene.props(f'drag_constraints="y={scene_pos[1]}"')
            
            for c in self.cursors.values():
                if copy_mode:
                    c.material(copy_color.value, copy_opacity.parsed_value)
                else:
                    c.material(move_color.value, move_opacity.parsed_value)

        def move(self, offset: "numpy array (3)") -> None:
            self.offset += offset
            self._update_cursors()

        def rotate(self, rotation: float) -> None:
            self.rotation += rotation if not self.mirrored else -rotation
            self._update_cursors()

        def mirror(self, horizontal: bool) -> None:
            self.mirrored = not self.mirrored
            if horizontal:
                self.rotation += 180
            self._update_cursors()

        def set_copy_button(self, copy_button: bool) -> None:
            if copy_button != self.copy_button:
                self.copy_button = copy_button
                self._update_cursors()

        def set_axis_button(self, axis_button: bool) -> None:
            if axis_button != self.axis_button:
                self.axis_button = axis_button
                self._update_cursors()

        @handle_errors
        def apply(self) -> None:
            nonlocal walls
            copy_mode = self.copy_button ^ drag_copy.value
            ops = [l for v, l in [(copy_mode, "copy"), (self.rotation, "rotate"), (self.mirrored, "mirror"), (np.any(self.offset), "offset")] if v]
            undo.push_undo(f"{pretty_list(ops)} {len(self.sources)} walls")
            first = min(self.sources)
            copy_offset = [0.0,0.0,_find_free_slot(first+self.offset[2])-first-self.offset[2],0.0,0.0] if copy_mode else 0.0
            pivot_3d = walls[self.drag_time if self.drag_time is not None else first][0,:3]
            scale_3d = np.array([1.0, -1.0 if self.mirrored else 1.0, 1.0])
            new_walls = {}
            for t in sorted(self.sources):
                w = walls[t]+copy_offset if copy_mode else walls.pop(t)
                w = movement.rotate(w, angle=self.rotation, pivot=pivot_3d)
                w = movement.scale(w, scale_3d=scale_3d, pivot=pivot_3d)
                w = movement.offset(w, self.offset)
                new_walls[w[0,2]] = w
            if turbostack.value and copy_mode:
                extra_count = TURBOSTACK_COUNTS[turbostack.value-1] - 2  # subtract base and copy
                stack_walls = new_walls.copy()
                for _ in range(extra_count):
                    stack_new = {}
                    for t in sorted(stack_walls):
                        w = stack_walls[t]+copy_offset
                        w = movement.rotate(w, angle=self.rotation, pivot=pivot_3d)
                        w = movement.scale(w, scale_3d=scale_3d, pivot=pivot_3d)
                        w = movement.offset(w, self.offset)
                        stack_new[w[0,2]] = w
                    new_walls |= stack_new
                    stack_walls = stack_new
            new_sources = set(new_walls)

            sym_ops: list[Literal["mirror_x", "mirror_y"]|int] = []
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
            new_walls |= pattern_generation.generate_symmetry(source=new_walls, operations=sym_ops, interval=sym_interval)
                
            for _, w in sorted(new_walls.items()):
                _insert_wall(w, displace_forward=self.offset[2]>0)
            _soft_refresh()
            self.select(new_sources, "set")

        @handle_errors
        def start_drag(self, object_id: str) -> None:
            if preview_scene is None:
                return
            copy_mode = self.copy_button ^ drag_copy.value
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
                        if copy_mode:
                            e.material(copy_color.value, copy_opacity.parsed_value/2)
                        else:
                            e.material(move_color.value, move_opacity.parsed_value/2)
                        self.cursors[t] = e
            self._update_cursors()

        def end_drag(self, xyt: tuple[float, float, float]) -> None:
            if self.drag_time not in walls:
                self.clear()
                return
            self.offset = np.array(xyt) - walls[self.drag_time][0,:3]
            self.apply()

    selection = Selection()
    last_ctrl_press = None
    last_shift_press = None
    @handle_errors
    def _on_key(e: events.KeyEventArguments) -> None:
        nonlocal last_ctrl_press, last_shift_press
        if e.key.control and not e.action.repeat:
            if e.action.keydown:
                # on CTRL double-tap, toggle drag_copy value
                if last_ctrl_press is not None and time() - last_ctrl_press < 0.5:
                    drag_copy.set_value(not drag_copy.value)
                    last_ctrl_press = None
                    return
                else:
                    last_ctrl_press = time()
            selection.set_copy_button(e.action.keydown)
        else:
            # if any other key is pressed/release clear double-tap
            last_ctrl_press = None

        if e.key.shift and not e.action.repeat:
            if e.action.keydown:
                # on SHIFT double-tap, toggle axis_z value
                if last_shift_press is not None and time() - last_shift_press < 0.5:
                    axis_z.set_value(not axis_z.value)
                    last_shift_press = None
                    return
                else:
                    last_shift_press = time()
            selection.set_axis_button(e.action.keydown)
        else:
            # if any other key is pressed/release clear double-tap
            last_shift_press = None

        if not e.action.keydown:
            return
        try:
            # note: don't use key.code, as that doesn't account for keyboard layout
            key_name = e.key.name.upper()  # key.name is upper/lowercase depending on shift
            # CTRL-independent
            if e.key.number in range(1, len(synth_format.WALL_LOOKUP)+1):
                assert e.key.number is not None  # mypy doesn't unstand the range above
                wall_type = sorted(synth_format.WALL_LOOKUP)[e.key.number-1]
                _spawn_wall(wall_type=wall_type, change_selection=e.modifiers.ctrl, extend_selection=e.modifiers.shift)
            elif e.key.page_up or e.key.page_down:
                selection.move(np.array([0.0,0.0,(e.key.page_up-e.key.page_down)*time_step.parsed_value])*offset_step.parsed_value)
            elif e.key.enter or key_name == " ":
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
            elif key_name == "C":
                _reset_camera()
            elif e.key.escape:
                selection.select(set(), "set")
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
            elif key_name in "AD":
                selection.rotate((angle_step.parsed_value if not e.modifiers.shift else 90.0) * (-1 if key_name == "D" else 1))
            elif key_name in "WS":
                selection.mirror(horizontal=(key_name=="S"))
            elif e.key.is_cursorkey:
                selection.move(np.array([(e.key.arrow_right-e.key.arrow_left),(e.key.arrow_up-e.key.arrow_down),0.0])*offset_step.parsed_value)
        except ParseInputError as pie:
            error(f"Error parsing setting: {pie.input_id}", pie, data=pie.value)
            return
    PreventDefaultKeyboard(on_key=_on_key).bind_active_from(app.storage.user, "active_tab", backward=lambda v: v=="wall_art")
    with ui.card():
        with ui.row():
            with ui.row():
                axis_z = LargeSwitch(False, "axis", "(Double-tab SHIFT) Change movement axis between X/Y and Time (inverts with SHIFT held)", color="info", icon_unchecked="open_with", icon_checked="schedule")
                drag_copy = LargeSwitch(False, "drag_copy", "(Double-tap CTRL) Switch default drag behavior between move and copy (inverts with CTRL held).", color="positive", icon_unchecked="start", icon_checked="call_split", on_change=selection._update_cursors)
                displace = LargeSwitch(False, "displace", "Displace existing walls when moving in time instead of replacing them.", color="warning", icon_unchecked="cancel", icon_checked="move_up")
                time_step = make_input("Time Step", "1/64", "time_step", suffix="b", tooltip="Time step for adding walls or moving via dragg or (page-up)/(page-down)")
                offset_step = make_input("Offset Step", "1", "offset_step", suffix="sq", tooltip="Step for moving via (arrow keys)")
                angle_step = make_input("Angle Step", "15", "angle_step", suffix="°", tooltip="Step for rotation via (A)/(D)")
            with ui.expansion("Symmetry", icon="flip").props("dense") as sym_exp:
                with ui.row():
                    symmetry_step = make_input("Interval", "1/4", "symmetry_step", suffix="b", tooltip="Time step for symmetry copies")
                    with LargeSwitch(False, "rotate_first", color="secondary", icon_unchecked="flip", icon_checked="adjust") as rotate_first:
                        ui.tooltip().bind_text_from(rotate_first, "value", lambda rf: "Rotate first, then mirror" if rf else "Mirror first, then rotate")
                    ui.separator().props("vertical")
                    mirror_x = LargeSwitch(False, "mirror_x", "Mirror across X axis, ie left-right", color="negative", icon_unchecked="align_horizontal_left", icon_checked="align_horizontal_center")
                    mirror_y = LargeSwitch(False, "mirror_y", "Mirror across Y axis, ie up-down", color="positive", icon_unchecked="align_vertical_bottom", icon_checked="align_vertical_center")
                with ui.row():
                    ui.label("Rotation: ").classes("my-auto")
                    rotsym_direction = LargeSwitch(None, "rotsym_direction", "Rotation direction", color="white", icon_unchecked="rotate_left", icon_checked="rotate_right").props('toggle-indeterminate indeterminate-icon="cancel" icon-color="black"')
                    ui.tooltip("Number of rotational symmetry. Note that mirror in both X and Y overlaps with even symmetries, ie 2x/4x/etc")
                    rotsym = ui.slider(min=2, max=12, value=2).props('snap markers selection-color="transparent" color="secondary" track-size="2px" thumb-size="25px"').classes("w-24").bind_value(app.storage.user, "wall_art_rotsym").bind_enabled_from(rotsym_direction, "value", backward=lambda v: v is not None)
                    ui.label().classes("my-auto w-8").bind_text_from(rotsym, "value", backward=lambda v: f"x{v}").bind_visibility_from(rotsym_direction, "value", backward=lambda v: v is not None)
                with ui.row():
                    ui.label("TurboStack: ").classes("my-auto")
                    ui.tooltip("Create stacked copies")
                    turbostack = ui.slider(min=0, max=len(TURBOSTACK_COUNTS), value=0).props('snap markers selection-color="transparent" color="lime" track-size="2px" thumb-size="25px"').classes("w-24").bind_value(app.storage.user, "wall_art_turbostack")
                    ui.label().classes("my-auto w-8").bind_text_from(turbostack, "value", backward=lambda v: f"{TURBOSTACK_COUNTS[v-1]}x" if v else "off")#.bind_visibility_from(rotsym_direction, "value", backward=lambda v: v is not None)
                def _update_symex(_) -> str:
                    enabled = []
                    if mirror_x.value:
                        enabled.append("X")
                    if mirror_y.value:
                        enabled.append("Y")
                    if rotsym_direction.value is not None:
                        rotdir = "↻" if rotsym_direction.value else "↺"
                        if rotate_first.value:
                            enabled.insert(0, f"{rotdir}{rotsym.value}")
                        else:
                            enabled.append(f"{rotdir}{rotsym.value}")
                    stack_str = f"Stack: {TURBOSTACK_COUNTS[turbostack.value-1]}x, " if turbostack.value else ""
                    return f"{stack_str}Symmetry: {', '.join(enabled) or 'off'}"
                for inp in (mirror_x, mirror_y, rotsym_direction, rotate_first, turbostack):
                    inp.bind_value_to(sym_exp, "text", forward=_update_symex)
            with ui.expansion("Reference", icon="image").props("dense"):
                ui.tooltip("Display a reference image to align wall art.")
                refimg_url = ui.input("Reference Image URL").props("dense").classes("w-full").bind_value(app.storage.user, "wall_art_ref_image_url").tooltip("Direct URL to image file. Press the download button below to download.")
                with ui.row():
                    def _clear_image() -> None:
                        app.storage.user["wall_art_ref_image"] = ""
                        ui.notify("Reference image cleared. Click APPLY to apply.", type="positive")
                    ui.button(icon="clear", on_click=_clear_image, color="negative").props("outline").tooltip("Clear image data").classes("w-10")
                    @handle_errors
                    def _download_image() -> None:
                        url = refimg_url.value
                        if not url:
                            raise PrettyError(msg="Set an URL above")
                        else:
                            try:
                                r = requests.get(url)
                                r.raise_for_status()
                            except requests.RequestException as req_exc:
                                raise PrettyError(msg="Downloading image failed", exc=req_exc, data=url) from req_exc
                            data = r.content
                            app.storage.user["wall_art_ref_image"] = b64encode(data).decode()
                            ui.notify(f"Downloaded reference image ({len(data)/1024:.1f} KiB). Click APPLY to apply.", type="positive")
                    ui.button(icon="cloud_download", on_click=_download_image, color="positive").props("outline").tooltip("Download image from URL").classes("w-10")
                    def _upload_image(e: events.UploadEventArguments) -> None:
                        upl: ui.upload = e.sender  # type:ignore
                        upl.reset()
                        data = e.content.read()
                        app.storage.user["wall_art_ref_image"] = b64encode(data).decode()
                        ui.notify(f"Uploaded reference image ({len(data)/1024:.1f} KiB). Click APPLY to apply.", type="positive")
                    refimg_upload = ui.upload(label="Upload File", multiple=True, auto_upload=True, on_upload=_upload_image).props('outline color="positive" accept="image/*"').classes("w-28")
                    with refimg_upload.add_slot("list"):
                        pass
                with ui.row():
                    refimg_width = make_input("Width", "16", "ref_width", suffix="sq", tooltip="Width of the reference image in sq")
                    refimg_height = make_input("Height", "12", "height", suffix="sq", tooltip="Height of the reference image in sq")
                    refimg_opacity = make_input("Opacity", "0.5", "ref_opacity", tooltip="Opacity of the image (0-1). 1=completely opaque, 0=completely transparent")
                with ui.row():
                    refimg_x = make_input("X", "0", "ref_x", suffix="sq", tooltip="Center X of the reference image in sq")
                    refimg_y = make_input("Y", "0", "ref_y", suffix="sq", tooltip="Center Y of the reference image in sq")
                    refimg_t = make_input("Time", "1/4", "ref_time", suffix="b", tooltip="Time of the reference image in beats")
                refimg_apply_button = ui.button("Apply").props("outline")
            with ui.expansion("Preview setttings", icon="palette").props("dense"):
                sp = SettingsPanel()
                ui.separator()
                with ui.row():
                    ui.icon("highlight_alt", size="3em").tooltip("Appearance of selected walls")
                    move_color = ui.color_input("Move", value="#888888", preview=True).props("dense").classes("w-28").bind_value(app.storage.user, "wall_art_move_color")
                    move_color.button.style("color: black")
                    move_opacity = make_input("Opacity", "0.5", "move_opacity")
                    copy_color = ui.color_input("Copy", value="#00ff00", preview=True).props("dense").classes("w-28").bind_value(app.storage.user, "wall_art_copy_color")
                    copy_color.button.style("color: black")
                    copy_opacity = make_input("Opacity", "0.5", "copy_opacity")
                ui.separator()
                with ui.row():
                    ui.icon("preview", size="3em").tooltip("Change size and scaling of preview")
                    scene_width = make_input("Width", "800", "width", tab_id="preview", suffix="px", tooltip="Width of the preview in px")
                    scene_height = make_input("Height", "600", "height", tab_id="preview", suffix="px", tooltip="Height of the preview in px")
                    time_scale = make_input("Time Scale", "64", "time_scale", tab_id="preview", tooltip="Ratio between XY and time")
                    frame_length = make_input("Frame Length", "2", "frame_length", tab_id="preview", suffix="b", tooltip="Number of beats to draw frames for")
                ui.separator()
                with ui.row():
                    ui.icon("camera_indoor", size="3em").tooltip("Change home position of camera")
                    cam_height = make_input("Cam Height", "2", "cam_height", tab_id="preview", suffix="sq", tooltip="Default camera height")
                    cam_time = make_input("Cam Time", "1/2", "cam_time", tab_id="preview", suffix="b", tooltip="Default camera time center")
                    cam_distance = make_input("Cam Distance", "1", "cam_distance", tab_id="preview", suffix="b", tooltip="Default camera distance from center")
                preview_apply_button = ui.button("Apply").props("outline")
        def _find_free_slot(t: float) -> float:
            while t in walls:
                t = np.round(t/time_step.parsed_value + 1)*time_step.parsed_value
            return t

        @handle_errors
        def _insert_wall(w: "np.array (1,5)", displace_forward: bool = False) -> None:
            if not displace.value:
                walls[w[0,2]] = w
                return
            pending = w
            displace_dir = -1 if displace_forward else 1
            while pending[0,2] in walls:
                walls[pending[0,2]], pending = pending, walls[pending[0,2]]
                pending[0,2] = np.round(pending[0,2]/time_step.parsed_value + displace_dir)*time_step.parsed_value
            walls[pending[0,2]] = pending

        @handle_errors
        def _spawn_wall(wall_type: int, change_selection: bool = False, extend_selection: bool = False) -> None:
            if change_selection:
                if not selection.sources:
                    return
                undo.push_undo(f"change {len(selection.sources)} walls to {synth_format.WALL_LOOKUP[wall_type]}")
                for s in selection.sources:
                    walls[s] = pattern_generation.change_wall_type(walls[s], wall_type)
                _soft_refresh()
                selection.select(set(), "toggle")
            else:
                undo.push_undo(f"add {synth_format.WALL_LOOKUP[wall_type]}")
                new_t = 0.0 if not selection.sources else max(selection.sources) + time_step.parsed_value
                if not displace.value:
                    new_t = _find_free_slot(max(selection.sources, default=0.0))
                _insert_wall(np.array([[0.0,0.0,new_t,wall_type,0.0]]))
                _soft_refresh()
                selection.select({new_t}, mode="set" if not extend_selection else "toggle")

        @handle_errors
        def _soft_refresh() -> None:
            nonlocal refimg_obj
            preview_settings = sp.parse_settings()
            if preview_scene is None:
                draw_preview_scene.refresh()
                _reset_camera()
            if refimg_obj is not None:
                refimg_obj.delete()
                refimg_obj = None
            if preview_scene is not None:
                if refimg_url.value:
                    with preview_scene:
                        coords = np.array([[[-1/2,0,1/2],[1/2,0,1/2]],[[-1/2,0,-1/2],[1/2,0,-1/2]]]) * [refimg_width.parsed_value,0,refimg_height.parsed_value]
                        pos = (refimg_x.parsed_value, refimg_t.parsed_value*time_scale.parsed_value, refimg_y.parsed_value)
                        opacity = refimg_opacity.parsed_value
                        if app.storage.user.get("wall_art_ref_image"):
                            # add parameter to bypass cache
                            refimg_obj = preview_scene.texture(f"/wall_art_ref_image?nocache={time()}", coords.tolist()).move(*pos).material(opacity=opacity)
                wall_data = synth_format.DataContainer(walls=walls)
                preview_scene.render(wall_data, preview_settings)

        @handle_errors
        def _reset_camera() -> None:
            if preview_scene is None:
                return
            preview_scene.move_camera(
                0, (cam_time.parsed_value-cam_distance.parsed_value)*time_scale.parsed_value, cam_height.parsed_value,
                0, cam_time.parsed_value*time_scale.parsed_value, cam_height.parsed_value,
                duration=0,
            )

        @handle_errors
        def _on_click(e: events.SceneClickEventArguments) -> None:
            if preview_scene is None:
                return
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
        @handle_errors
        def draw_preview_scene() -> None:
            nonlocal preview_scene
            w = int(scene_width.parsed_value)
            h = int(scene_height.parsed_value)
            l = int(frame_length.parsed_value)
            t = time_scale.parsed_value
            preview_scene = MapScene(width=w, height=h, frame_length=l, time_scale=t, on_click=_on_click, on_drag_start=_on_dstart, on_drag_end=_on_dend)
            _reset_camera()
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
                        🇨 resets the camera to the position configured in the settings. 

                        Click on a wall to select it. Multiple walls can be selected by CTRL-Click (to add), or SHIFT-Click (expand selection to clicked wall).
                        Then drag it around using left mouse and/or use one of the edit keys below.  
                        Holding CTRL creates a (modified) copy in the next free slot instead of moving.  
                        Holding SHIFT drags in time instead of X/Y.

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
                        |Tap SHIFT twice|Toggle drag axis between time and X/Y| 
                        |Tap CTRL twice|Toggle drag behavior between move and copy| 
                        |🇶/🇪|Select previous/next Wall (SHIFT: Expand selection)|
                        |🇷|Compress all walls to timestep|
                        |🇧|Open Blender|

                        ## Edit
                        If you use keyboard shortcuts instead of dragging, press enter, space or click the shadow to apply.

                        Note: If you hold down CTRL to copy, most of these will not work.  
                        Either let down of CTRL to use them (and then press it again), or toggle the copy mode via CTRL double-tap.  
                        You have to move the mouse around slightly to correct the drag position after switching CTRL state.

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
                @handle_errors
                def _paste() -> None:
                    with safe_clipboard_data(use_original=False, write=False) as data:
                        undo.push_undo("paste from clipboad")
                        walls.update(data.walls)
                    selection.select(set(), mode="toggle")
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
                def _clear() -> None:
                    undo.reset()
                    walls.clear()
                    _soft_refresh()
                with ui.button(icon="clear", color="negative", on_click=_clear).props("outline").style("width: 36px"):
                    ui.tooltip("Clear everything (includes undo steps)")
                ui.separator()
                @handle_errors
                def _compress() -> None:
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
                        blend_interval = make_input("Interval", "1/2", "blend_interval", tooltip="Interval between blending steps", suffix="b")
                        def _do_blend() -> None:
                            nonlocal walls
                            wc, pc, pl = blend_pattern.value
                            error_data = [w.tolist() for w in walls.values()]
                            if len(walls) != wc*pc:
                                error(f"Wall count changed! Expected {pc*wc}, found {len(walls)}", data=error_data)
                                return
                            try:
                                patterns = np.array([w[0] for _, w in sorted(walls.items())]).reshape((pc, wc, 5))
                                interval = blend_interval.parsed_value
                            except ValueError as ve:
                                error(f"Could not split up {len(walls)} walls into {pc} patterns with {wc} wall{'s'*(wc!=1)} each", ve, data=error_data)
                                return
                            pattern_deltas = np.diff(patterns[:,0,2])
                            if pattern_deltas.max() <= interval:
                                error(
                                    f"Blend interval ({pretty_fraction(interval)}b) must be greater than largest pattern distance ({pretty_fraction(pattern_deltas.max())}b), else blending will do nothing.",
                                    data=error_data,
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
                                error("Error blending walls", ve, data=error_data)
                                return
                            added = len(walls)//patterns.shape[1] - patterns.shape[0]
                            ui.notify(f"Created {added} additional pattern{'s'*(added!=1)} between the existing {patterns.shape[0]}", type="info")
                            _soft_refresh()
                            blend_dialog.close()
                        ui.button(icon="blender", on_click=_do_blend).props("outline").classes("w-16 h-10")

                def _open_blend_dialog() -> None:
                    error_data = [w.tolist() for w in walls.values()]
                    if len(walls) < 2:
                        error("Need at least two walls to do blending", data=error_data)
                        return
                    # autodetect patterns
                    try:
                        detected_patterns = pattern_generation.find_wall_patterns(walls)
                    except ValueError as ve:
                        error(f"Could not detect patterns in walls: {ve}", data=error_data)
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
                with ui.button(icon="camera_indoor", on_click=_reset_camera).style("width: 36px"):
                    ui.tooltip("Reset camera position (C), can be adjusted in preview settings")
                ui.separator()
                with ui.button(icon="delete", color="negative", on_click=selection.delete).style("width: 36px").bind_enabled_from(selection, "sources", backward=bool):
                    ui.tooltip("Delete selection (Delete/Backspace)")
                for k, (i, t) in enumerate(sorted(synth_format.WALL_LOOKUP.items())):
                    def _add_wall(e: events.GenericEventArguments, wall_type=i) -> None:
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

        refimg_apply_button.on("click", draw_preview_scene.refresh)
        preview_apply_button.on("click", draw_preview_scene.refresh)

wall_art_tab = GUITab(
    name="wall_art",
    label="Wall Art",
    icon="wallpaper",
    content_func=_wall_art_tab,
)