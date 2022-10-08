#/usr/bin/env python3
from dataclasses import dataclass
import json

import numpy as np
import pyperclip

# For simplicity, we exclusively use grid coordinates and use measures for time / z
# These values are only need to convert to / from the format the game uses

INDEX_SCALE = 64  # index = measure * INDEX_SCALE
GRID_SCALE = 0.1365  # xy_coord = xy_grid * GRID_SCALE

# Apparently the editor grid snap is off by a small amount...
X_OFFSET = 0.002
Y_OFFSET = 0.0012

# not sure where this comes from, but is needed to work with z coordinates
# z_coord = index * (bpm / BPM_DIVISOR)
# also maybe useful: bpm = (z_coord / index) * BPM_DIVISOR
BPM_DIVISOR = 1200

MS_PER_MIN = 60 * 1000

NOTE_TYPES = ("right", "left", "single", "both")
# Note: wall offsets are eyeballed
WALL_TYPES = {
    # name: (index, center_offset)
    # index 0-4 are the same "slideType" used in the JSON in the "slides" list
    "wall_right": (0, [4, -2]),
    "wall_left": (1, [-4, -2]),
    "angle_right": (2, [2, -2]),
    "center": (3, [0, -1.3]),
    "angle_left": (4, [-2, -2]),
    # 5-99: placeholder for future slide types
    # Since there can be only be one wall anyway, just treat these three the same
    "crouch": (100, [0, 7.5]),
    "square": (101, [0, -2]),
    "triangle": (102, [0, -4.3]),
}
WALL_LOOKUP = {id: name for name, (id, _) in WALL_TYPES.items()}
WALL_OFFSETS = {id: np.array(offset + [0]) for _, (id, offset) in WALL_TYPES.items()}

ALL_TYPES = NOTE_TYPES + tuple(WALL_TYPES)

SINGLE_COLOR_NOTES = dict[float, list["numpy array (n, 3)"]]   # rail segment (n>1) and x,y,t
WALLS = dict[float, list["numpy array (1, 5)"]]    # x,y,t, type, angle

@dataclass
class DataContainer:
    original_json: str
    bpm: float
    right: SINGLE_COLOR_NOTES
    left: SINGLE_COLOR_NOTES
    single: SINGLE_COLOR_NOTES
    both: SINGLE_COLOR_NOTES
    walls: WALLS

    # Note: None of these functions are allowed to *modify* the dicts, instead they must create new dicts
    # This avoids requring deep copies for everything

    def apply_for_notes(self, f, *args, types: list = NOTE_TYPES, **kwargs) -> None:
        for t in types:
            if t not in NOTE_TYPES:
                continue
            notes = getattr(self, t)
            out = {}
            for _, nodes in notes.items():
                out_nodes = f(nodes, *args, **kwargs)
                out[out_nodes[0, 2]] = out_nodes
            setattr(self, str(t), out)

    def apply_for_walls(self, f, *args, types: list = WALL_TYPES, **kwargs) -> None:
        wall_types = [WALL_TYPES[t][0] for t in types if t in WALL_TYPES]
        out_walls = {}
        for time_index, wall in self.walls.items():
            if wall[0, 3] in wall_types:
                wall = f(wall, *args, **kwargs)
                out_walls[wall[0, 2]] = wall
            else:
                out_walls[time_index] = wall
        self.walls = out_walls

    def apply_for_all(self, f, *args, types: list = ALL_TYPES, **kwargs) -> None:
        self.apply_for_notes(f, *args, types=types, **kwargs)
        self.apply_for_walls(f, *args, types=types, **kwargs)

    # used when the functions needs access to all notes and rails of a color at one
    def apply_for_note_types(self, f, *args, types: list = NOTE_TYPES, **kwargs) -> None:
        for t in types:
            if t not in NOTE_TYPES:
                continue
            setattr(self, t, f(getattr(self, t), *args, **kwargs))

    def filtered(self, types: list = ALL_TYPES) -> "DataContainer":
        note_dicts = [
            getattr(self, t) if t in types else {}
            for t in NOTE_TYPES
        ]
        wall_types = [WALL_TYPES[t][0] for t in types if t in WALL_TYPES]
        wall_dict = {
            time_index: wall
            for time_index, wall in self.walls.items()
            if wall[0, 3] in wall_types
        }
        return DataContainer(self.original_json, self.bpm, *note_dicts, wall_dict)
        
    def merge(self, other: "DataContainer") -> None:
        for t in NOTE_TYPES:
            self_notes = getattr(self, t)
            other_notes = getattr(other, t)
            setattr(self, t, self_notes | other_notes)
        self.walls |= other.walls

# basic coordinate
def coord_from_synth(bpm: float, startMeasure: float, coord: list[float]) -> "numpy array (3)":
    return np.array([
        (coord[0] - X_OFFSET) / GRID_SCALE,
        (coord[1]-Y_OFFSET) / GRID_SCALE,
        # convert absolute coordinate to number of beats since start
        round((coord[2] * bpm / BPM_DIVISOR) * 64 - startMeasure) / 64,
    ])

def coord_to_synth(bpm: float, coord: "numpy array (3)") -> list[float]:
    return [
        (coord[0] * GRID_SCALE) + X_OFFSET,
        (coord[1] * GRID_SCALE) + Y_OFFSET,
        (coord[2] / bpm) * BPM_DIVISOR,
    ]

# full note dict
def note_from_synth(bpm: float, startMeasure: float, note_dict: dict) -> tuple[int, "numpy array (n, 3)"]:
    start = coord_from_synth(bpm, startMeasure, note_dict["Position"])
    note_type = note_dict["Type"]
    if note_dict["Segments"] is None:
        return note_type, start[np.newaxis]  # just add new axis
    else:
        return note_type, np.stack((start,) + tuple(coord_from_synth(bpm, startMeasure, node) for node in note_dict["Segments"]))

def note_to_synth(bpm: float, note_type: int, nodes: "numpy array (n, 3)") -> dict:
    return {
        "Type": note_type,
        "Position": coord_to_synth(bpm, nodes[0]),
        "Segments": [coord_to_synth(bpm, node) for node in nodes[1:]] if nodes.shape[0] > 1 else None,
    }

# full wall dict
def wall_from_synth(bpm: float, startMeasure: float, wall_dict: dict, wall_type: int) -> tuple[int, "numpy array (1, 5)"]:
    return np.concatenate((
        coord_from_synth(bpm, startMeasure, wall_dict["position"]) + WALL_OFFSETS[wall_type],
        (wall_type, wall_dict.get("zRotation", 0.0))
    ))[np.newaxis]

def wall_to_synth(bpm: float, wall: "numpy array (1, 5)") -> tuple[str, dict]:
    wall_type = int(wall[0, 3])
    pos = coord_to_synth(bpm, wall[0, :3] - WALL_OFFSETS[wall_type])
    wall_dict = {
        "time": round(wall[0, 2] * 64),
        "slideType": wall_type,
        "position": pos,
        "zRotation": wall[0, 4],  # note: crouch walls cannot be rotated, this may be ignored
        "initialized": True, # no idea what this is for
    }
    if wall_type < 10:
        dest_list = "slides"
    else:
        dest_list = WALL_LOOKUP[wall_type] + "s"
        del wall_dict["slideType"]
    return dest_list, wall_dict

# full json
def import_clipboard(use_original: bool = False) -> DataContainer:
    original_json = pyperclip.paste()
    clipboard = json.loads(original_json)
    if "original_json" in clipboard:
        original_json = clipboard["original_json"]
    if use_original:
        clipboard = json.loads(original_json)
    bpm = clipboard["BPM"]
    startMeasure = clipboard["startMeasure"]
    # r, l, s, b
    notes: list[SINGLE_COLOR_NOTES] = [{} for _ in range(4)]
    for time_index, time_notes in clipboard["notes"].items():
        for note in time_notes:
            note_type, nodes = note_from_synth(bpm, startMeasure, note)
            notes[note_type][nodes[0,2]] = nodes

    walls: dict[float, list["numpy array (1, 5)"]] = {}
    # slides (right, left, angle_right, center, angle_right)
    for wall_dict in clipboard["slides"]:
        wall = wall_from_synth(bpm, startMeasure, wall_dict, wall_dict["slideType"])
        walls[wall[0, 2]] = wall
    # other (crouch, square, triangle)
    for wall_type in ("crouch", "square", "triangle"):
        for wall_dict in clipboard[wall_type + "s"]:
            wall = wall_from_synth(bpm, startMeasure, wall_dict, WALL_TYPES[wall_type][0])
            walls[wall[0, 2]] = wall

    return DataContainer(original_json, bpm, *notes, walls)

def export_clipboard(data: DataContainer, realign_start: bool = True):
    clipboard = {
        "BPM": data.bpm,
        "startMeasure": 0,
        "startTime": 0,
        "lenght": 0,
        "notes": {},
        "effects": [],
        "jumps": [],
        "crouchs": [],
        "squares": [],
        "triangles": [],
        "slides": [],
        "lights": [],
        "original_json": data.original_json,
    }
    first = 99999
    last = -99999
    for note_type, notes in enumerate((data.right, data.left, data.single, data.both)):
        for time_index, nodes in notes.items():
            clipboard["notes"].setdefault(round(time_index * 64), []).append(note_to_synth(data.bpm, note_type, nodes))
            if nodes[0, 2] < first:
                first = nodes[0, 2]
            if nodes[-1, 2] > last:
                last = nodes[-1, 2]
    for _, wall in data.walls.items():
        if wall[0, 2] < first:
            first = wall[0, 2]
        if wall[0, 2] > last:
            last = wall[0, 2]
        dest_list, wall_dict = wall_to_synth(data.bpm, wall)
        clipboard[dest_list].append(wall_dict)
    
    if not realign_start:
        # position of selection start in beats*64 
        clipboard["startMeasure"] = round(first * 64)
        # position of selection start in ms
        clipboard["startTime"] = first * MS_PER_MIN / data.bpm
        # length of the selection in milliseconds
        # and yes, the editor has a typo, so we need to missspell it too
        clipboard["lenght"] = last * MS_PER_MIN / data.bpm
    else:
        clipboard["lenght"] = (last - first) * MS_PER_MIN / data.bpm

    pyperclip.copy(json.dumps(clipboard))

