from dataclasses import dataclass, field

from nicegui import app, ui, elements
import numpy as np

from ..utils import parse_number, pretty_fraction
from .. import synth_format, utils

GRID_SIZE = (8, 6)

@dataclass
class ObjectSettings:
    color: str
    opacity: float
    size: float

@dataclass
class RenderSettings:
    color_left: str = "#4ff"
    color_right: str = "#f4f"
    color_single: str = "#4f4"
    color_both: str = "#ff4"

    note: ObjectSettings = field(default_factory=lambda:ObjectSettings("", 1.0, 0.6))
    rail: ObjectSettings = field(default_factory=lambda:ObjectSettings("", 0.5, 0.2))
    rail_node: ObjectSettings = field(default_factory=lambda:ObjectSettings("", 1.0, 0.3))

    wall: ObjectSettings = field(default_factory=lambda:ObjectSettings("#808", 0.1, 1/64))
    wall_outline: ObjectSettings = field(default_factory=lambda:ObjectSettings("#808", 1, 0.0))

DEFAULT_SETTINGS = RenderSettings()

WALL_VERTS = {
    i: np.array(synth_format.WALL_VERTS[synth_format.WALL_LOOKUP[i]])
    for i in synth_format.WALL_LOOKUP
}

class SMHInput(ui.input):
    def __init__(self, label: str, value: str|float, storage_id: str, tooltip: str|None=None, suffix: str|None = None, **kwargs):
        super().__init__(label=label, value=str(value), **kwargs)
        self.bind_value(app.storage.user, f"render_{storage_id}")
        self.classes("w-14 h-10")
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
            raise utils.ParseInputError(self.storage_id, self.value) from ve

class SettingsPanel(ui.element):
    def __init__(self) -> None:
        super().__init__()
        with self:
            with ui.row():
                self.wall_size = SMHInput("Wall Depth", pretty_fraction(DEFAULT_SETTINGS.wall.size), "wall_size", suffix="b")
                ui.separator().props("vertical")
                self.wall_color = ui.color_input("Wall", value=DEFAULT_SETTINGS.wall.color, preview=True).props("dense").classes("w-24").bind_value(app.storage.user, "render_wall_color")
                self.wall_color.button.style("color: black")
                self.wall_opacity = SMHInput("Opacity", DEFAULT_SETTINGS.wall.opacity, "wall_opacity")
                ui.separator().props("vertical")
                self.wall_outline_color = ui.color_input("Outline", value=DEFAULT_SETTINGS.wall_outline.color, preview=True).props("dense").classes("w-24").bind_value(app.storage.user, "render_wall_outline_color")
                self.wall_outline_color.button.style("color: black")
                self.wall_outline_opacity = SMHInput("Opacity", DEFAULT_SETTINGS.wall_outline.opacity, "wall_outline_opacity")
            ui.separator().classes("my-2")
            with ui.row():
                self.note_colors: dict[str, SMHInput] = {
                    t: ui.color_input(t.capitalize(), value=getattr(DEFAULT_SETTINGS, "color_"+t), preview=True).props("dense").classes("w-24")
                    for t in synth_format.NOTE_TYPES
                }
                for t, ci in self.note_colors.items():
                    ci.bind_value(app.storage.user, "render_color_"+t)
                    ci.button.style("color: black")
            ui.separator().classes("my-2")
            with ui.row():
                self.note_size = SMHInput("Note Size", DEFAULT_SETTINGS.note.size, "note_size", suffix="sq")
                self.note_opacity = SMHInput("Opacity", DEFAULT_SETTINGS.note.opacity, "note_opacity")
                ui.separator().props("vertical")
                self.rail_size = SMHInput("Rail Size", DEFAULT_SETTINGS.rail.size, "rail_size", suffix="sq")
                self.rail_opacity = SMHInput("Opacity", DEFAULT_SETTINGS.rail.opacity, "rail_opacity")
                ui.separator().props("vertical")
                self.rail_node_size = SMHInput("Node Size", DEFAULT_SETTINGS.rail_node.size, "rail_node_size", suffix="sq")
                self.rail_node_opacity = SMHInput("Opacity", DEFAULT_SETTINGS.rail_node.opacity, "rail_node_opacity")

    def parse_settings(self) -> RenderSettings:
        return RenderSettings(
            color_left=self.note_colors["left"].value,
            color_right=self.note_colors["right"].value,
            color_single=self.note_colors["single"].value,
            color_both=self.note_colors["both"].value,
            note=ObjectSettings("", self.note_opacity.parsed_value, self.note_size.parsed_value),
            rail=ObjectSettings("", self.rail_opacity.parsed_value, self.rail_size.parsed_value),
            rail_node=ObjectSettings("", self.rail_node_opacity.parsed_value, self.rail_node_size.parsed_value),
            wall=ObjectSettings(self.wall_color.value, self.wall_opacity.parsed_value, self.wall_size.parsed_value),
            wall_outline=ObjectSettings(self.wall_outline_color.value, self.wall_outline_opacity.parsed_value, 0),
        )

class MapScene(ui.scene):
    def __init__(self, *args, frame_length: int, time_scale: float, zoomout: float=10, **kwargs) -> None:
        super().__init__(*args, grid=False, **kwargs)
        self.time_scale = time_scale
        self.walls: dict[float, Tuple[elements.scene_objects.Extrusion, elements.scene_objects.Extrusion]] = {}
        self.wall_lookup: dict[str, float] = {}
        with self:
            self._obj_group = self.group()
            self.move_camera(zoomout,-self.time_scale*zoomout/20,zoomout, 0,self.time_scale/2,0)
            for i in range(frame_length):
                with self.group().move(0,(i+0.5)*self.time_scale,0):
                    self.box(16, self.time_scale, 12, wireframe=True).material("#008", 0.2)
                    self.box(0.1, self.time_scale, 12, wireframe=True).material("#080", 0.1)
                    self.box(16, self.time_scale, 0.1, wireframe=True).material("#800", 0.1)
    def to_scene(self, xyt: "numpy array (3+)") -> tuple[float, float, float]:
        return (xyt[0], xyt[2]*self.time_scale, xyt[1])
    def _sphere(self, xyt: "numpy array (3+)", obj_settings: ObjectSettings, color: str) -> elements.scene_objects.Sphere:
        return self.sphere(obj_settings.size).move(*self.to_scene(xyt)).material(color, obj_settings.opacity)

    def wall_extrusion(self, xytwa: "numpy array (5)", thickness: float) -> elements.scene_objects.Extrusion:
        return self.extrusion(
            WALL_VERTS[int(xytwa[0,3])], -thickness,
        ).rotate(
            np.deg2rad(90), np.deg2rad(180 - xytwa[0,4]), 0
        ).move(
            *self.to_scene(xytwa[0])
        )

    def render(self, data: synth_format.DataContainer, settings: RenderSettings = RenderSettings()) -> None:
        self._obj_group.delete()
        with self.group() as self._obj_group:
            for t, w in data.walls.items():
                body = self.wall_extrusion(
                    w, settings.wall.size * self.time_scale
                ).material(
                    settings.wall.color, settings.wall.opacity
                )

                with body:
                    outline = self.extrusion(
                        WALL_VERTS[int(w[0,3])], -settings.wall.size * self.time_scale, wireframe=True
                    ).material(
                        settings.wall_outline.color, settings.wall_outline.opacity
                    )
                self.walls[t] = (body, outline)
                self.wall_lookup[body.id] = t
            for t in synth_format.NOTE_TYPES:
                color: str = getattr(settings, "color_" + t)
                for _, n in getattr(data, t).items():
                    parent = self._sphere(n[0], settings.note, color)
                    with parent:
                        diff = n - n[0]
                        for i in range(1, n.shape[0]):
                            self._sphere(diff[i], settings.rail_node, color)

                            self.quadratic_bezier_tube(
                                self.to_scene(diff[i-1]),
                                self.to_scene((diff[i-1]+diff[i])/2),
                                self.to_scene(diff[i]),
                                radius=settings.rail.size,
                            ).material(
                                color, settings.rail.opacity
                            )


