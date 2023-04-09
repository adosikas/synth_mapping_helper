#/usr/bin/env python3
from io import BytesIO
import dataclasses
import json
from pathlib import Path
from typing import Union
from zipfile import ZipFile

import numpy as np
import pyperclip

# For simplicity, we exclusively use grid coordinates (x, y) and use measures for time (z)
# These values are only needed to convert to / from the format the game uses

INDEX_SCALE = 64  # index = measure * INDEX_SCALE
GRID_SCALE = 0.1365  # xy_coord = xy_grid * GRID_SCALE

# Apparently the editor grid snap is off by a small amount...
X_OFFSET = 0.002
Y_OFFSET = 0.0012

# not sure where this comes from, but is needed to work with z coordinates
# z_coord = index * (bpm / BPM_DIVISOR)
# also maybe useful: bpm = (z_coord / index) * BPM_DIVISOR
BPM_DIVISOR = 1200

NOTE_TYPES = ("right", "left", "single", "both")
# Note: wall offsets are eyeballed
WALL_TYPES = {
    # name: (index, center_offset)
    # index 0-4 are the same "slideType" used in the JSON in the "slides" list
    "wall_right": (0, [4.05, -1.85]),
    "wall_left": (1, [-3.95, -1.85]),
    "angle_right": (2, [2.5, -2.2]),
    "center": (3, [0, -1.3]),
    "angle_left": (4, [-2.5, -2.2]),
    # 5-99: placeholder for future slide types
    # Since there can be only be one wall anyway, just treat these three the same as slides
    "crouch": (100, [0.1, 7.5]),
    "square": (101, [0, -2]),
    "triangle": (102, [0, -4.7]),
}
WALL_LOOKUP = {id: name for name, (id, _) in WALL_TYPES.items()}
WALL_OFFSETS = {id: np.array(offset + [0]) for _, (id, offset) in WALL_TYPES.items()}
SLIDE_TYPES = [name for name, (id, _) in WALL_TYPES.items() if id < 100]

ALL_TYPES = NOTE_TYPES + tuple(WALL_TYPES)

SINGLE_COLOR_NOTES = dict[float, "numpy array (n, 3)"]   # rail segment (n>1) and x,y,t
WALLS = dict[float, "numpy array (1, 5)"]    # x,y,t, type, angle

BEATMAP_JSON_FILE = "beatmap.meta.bin"
DIFFICULTIES = ("Easy", "Normal", "Hard", "Expert", "Master", "Custom")
META_KEYS = ("Name", "Author", "Beatmapper", "CustomDifficultyName", "BPM")

BETA_WARNING_SHOWN = False


def beta_warning() -> None:
    if not BETA_WARNING_SHOWN:
        print("This was tested with the beta version of the editor only. You may want to switch to it.")
        BETA_WARNING_SHOWN = True

def round_time_to_fractions(time: float) -> float:
    # 192 is the lowest common multiple of 64 and 48, so this covers all steps the editor supports and more
    # effectively this is 3 intermediate steps for each 1/64 step, or 4 for each 1/48 step
    # those intermediate steps are also possible in the editor by abusing snap or copy-paste and switching
    # between 1/64 and 1/48 step.
    # But the editor does no rounding at all, leading to float erros creeping up. 
    return round(time * 192) / 192

def round_tick_for_json(time: float) -> float:
    # same as above, but in 1/64 ticks the json needs for some things
    # this is a seperate function to only do one float operation after rounding before output, to minimize errors
    return round(time * 3) / 3

@dataclasses.dataclass
class DataContainer:
    bpm: float
    right: SINGLE_COLOR_NOTES
    left: SINGLE_COLOR_NOTES
    single: SINGLE_COLOR_NOTES
    both: SINGLE_COLOR_NOTES
    walls: WALLS

    # Note: None of these functions are allowed to *modify* the dicts, instead they must create new dicts
    # This avoids requring deep copies for everything

    def apply_for_notes(self, f, *args, types: list = NOTE_TYPES, mirror_left: bool = False, **kwargs) -> None:
        for t in types:
            if t not in NOTE_TYPES:
                continue
            notes = getattr(self, t)
            out = {}
            for _, nodes in sorted(notes.items()):
                out_nodes = f(nodes, *args, direction=(-1 if mirror_left and t == "left" else 1), **kwargs)
                out[out_nodes[0, 2]] = out_nodes
            setattr(self, str(t), out)

    def apply_for_walls(self, f, *args, types: list = WALL_TYPES, mirror_left: bool = False, **kwargs) -> None:
        wall_types = [WALL_TYPES[t][0] for t in types if t in WALL_TYPES]
        out_walls = {}
        for time_index, wall in sorted(self.walls.items()):
            if wall[0, 3] in wall_types:
                wall = f(wall, *args, **kwargs)  # TODO: support mirror_left
                out_walls[wall[0, 2]] = wall
            else:
                out_walls[time_index] = wall
        self.walls = out_walls

    def apply_for_all(self, f, *args, types: list = ALL_TYPES, mirror_left: bool = False, **kwargs) -> None:
        self.apply_for_notes(f, *args, types=types, mirror_left=mirror_left, **kwargs)
        self.apply_for_walls(f, *args, types=types, mirror_left=mirror_left, **kwargs)

    # used when the functions needs access to all notes and rails of a color at one
    def apply_for_note_types(self, f, *args, types: list = NOTE_TYPES, mirror_left: bool = False, **kwargs) -> None:
        for t in types:
            if t not in NOTE_TYPES:
                continue
            setattr(self, t, f(getattr(self, t), *args, direction=(-1 if mirror_left and t == "left" else 1), **kwargs))

    def filtered(self, types: list = ALL_TYPES) -> "DataContainer":
        replacement = {
            t: getattr(self, t) if t in types else {}
            for t in NOTE_TYPES
        }
        wall_types = [WALL_TYPES[t][0] for t in types if t in WALL_TYPES]
        replacement["walls"] = {
            time_index: wall
            for time_index, wall in sorted(self.walls.items())
            if wall[0, 3] in wall_types
        }
        return dataclasses.replace(self, **replacement)
        
    def merge(self, other: "DataContainer") -> None:
        for t in NOTE_TYPES:
            self_notes = getattr(self, t)
            other_notes = getattr(other, t)
            setattr(self, t, self_notes | other_notes)
        self.walls |= other.walls

    def get_object_dict(self, type_name: str) -> Union[SINGLE_COLOR_NOTES, WALLS]:
        if type_name in NOTE_TYPES:
            return getattr(self, type_name)
        wall_type = WALL_TYPES[type_name][0]
        return {
            time_index: wall
            for time_index, wall in sorted(self.walls.items())
            if wall[0, 3] == wall_type
        }

@dataclasses.dataclass
class ClipboardDataContainer(DataContainer):
    original_json: str

@dataclasses.dataclass
class SynthFile:
    input_file: Path
    meta: dict[str, str]
    bookmarks: dict[float, str]
    difficulties: dict[str, DataContainer]

    def reload(self) -> None:
        in_bio = BytesIO(self.input_file.read_bytes())  # buffer whole file in memory
        with ZipFile(in_bio) as inzip:
            # load beatmap json
            beatmap = json.loads(inzip.read(BEATMAP_JSON_FILE))
            bpm: float = beatmap["BPM"]
            self.meta = {k: beatmap[k] for k in META_KEYS}
            self.bookmarks = {
                # bookmarks are stored in steps of 64 per beat (regardless of BPM)
                round_time_to_fractions(bookmark_dict["time"] / 64): bookmark_dict["name"]
                for bookmark_dict in beatmap["Bookmarks"]["BookmarksList"]
            }

            for diff in DIFFICULTIES:
                # r, l, s, b
                notes: list[SINGLE_COLOR_NOTES] = [{} for _ in range(4)]
                for _, time_notes in beatmap["Track"][diff].items():
                    for note in time_notes:
                        note_type, nodes = note_from_synth(bpm, 0, note)
                        notes[note_type][nodes[0,2]] = nodes

                walls: dict[float, list["numpy array (1, 5)"]] = {}
                # slides (right, left, angle_right, center, angle_right)
                for wall_dict in beatmap["Slides"][diff]:
                    wall = wall_from_synth(bpm, 0, wall_dict, wall_dict["slideType"])
                    walls[wall[0, 2]] = wall
                # other (crouch, square, triangle)
                for wall_type in ("Crouch", "Square", "Triangle"):
                    if wall_type + "s" not in beatmap:
                        beta_warning()
                        continue  # these are only in the beta editor
                    for wall_dict in beatmap[wall_type + "s"][diff]:
                        wall = wall_from_synth(bpm, 0, wall_dict, WALL_TYPES[wall_type.lower()][0])
                        walls[wall[0, 2]] = wall
                # add difficulty when there is a note of any type or a wall
                if any(nt for nt in notes) or walls:
                    self.difficulties[diff] = DataContainer(bpm, *notes, walls)

    def save_as(self, output_file: Path) -> None:
        out_buffer = BytesIO()  # buffer output zip file in memory, only write on success
        with ZipFile(self.input_file) as inzip, ZipFile(out_buffer, "w") as outzip:
            # copy all content except beatmap json
            outzip.comment = inzip.comment
            for info in inzip.infolist():
                if info.filename != BEATMAP_JSON_FILE:
                    outzip.writestr(info, inzip.read(info.filename))

            beatmap = json.loads(inzip.read(BEATMAP_JSON_FILE))

            beatmap["Bookmarks"]["BookmarksList"] = [
                {"time": round_tick_for_json(t * 64), "name": n}
                for t, n in sorted(self.bookmarks.items())
            ]

            for diff, data in self.difficulties.items():
                new_notes = {}
                for note_type, notes in enumerate((data.right, data.left, data.single, data.both)):
                    for time_index, nodes in sorted(notes.items()):
                        new_notes.setdefault(round_tick_for_json(time_index * 64), []).append(note_to_synth(data.bpm, note_type, nodes))
                beatmap["Track"][diff] = new_notes
                walls = {
                    "crouchs": [],
                    "squares": [],
                    "triangles": [],
                    "slides": [],
                }
                for _, wall in sorted(data.walls.items()):
                    dest_list, wall_dict = wall_to_synth(data.bpm, wall)
                    walls[dest_list].append(wall_dict)
                for t, wall_list in walls.items():
                    beatmap[t.capitalize()][diff] = wall_list

            # write modified beatmap json
            outzip.writestr(inzip.getinfo(BEATMAP_JSON_FILE), json.dumps(beatmap))
        # write output zip
        output_file.write_bytes(out_buffer.getbuffer())

# basic coordinate
def coord_from_synth(bpm: float, startMeasure: float, coord: list[float]) -> "numpy array (3)":
    return np.array([
        (coord[0] - X_OFFSET) / GRID_SCALE,
        (coord[1] - Y_OFFSET) / GRID_SCALE,
        # convert absolute coordinate to number of beats since start
        round_time_to_fractions(coord[2] * bpm / BPM_DIVISOR - startMeasure / 64),
    ])

def coord_to_synth(bpm: float, coord: "numpy array (3)") -> list[float]:
    return [
        (coord[0] * GRID_SCALE) + X_OFFSET,
        (coord[1] * GRID_SCALE) + Y_OFFSET,
        (round_time_to_fractions(coord[2]) / bpm) * BPM_DIVISOR,  # ([beat] / [beat / minute]) * 1200 = ([sec] * 60) * 1200
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
        "time": round_tick_for_json(wall[0, 2] * 64),  # time as 1/64
        "slideType": wall_type,
        "position": pos,
        "zRotation": wall[0, 4] % 360,  # note: crouch walls cannot be rotated, this will be ignored for them
        "initialized": True,  # no idea what this is for
    }
    # crouch, square and triangle are not in the "slides" list, each has their own list and they do not use the "slideType" key
    if wall_type < 100:  # we gave crouch, square and triangle the types 100, 101 and 102
        dest_list = "slides"
    else:
        dest_list = WALL_LOOKUP[wall_type] + "s"
        del wall_dict["slideType"]
    return dest_list, wall_dict

# full json
def import_clipboard(use_original: bool = False) -> ClipboardDataContainer:
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
        if wall_type + "s" not in clipboard:
            beta_warning()
            continue  # these are only in the beta editor
        for wall_dict in clipboard[wall_type + "s"]:
            wall = wall_from_synth(bpm, startMeasure, wall_dict, WALL_TYPES[wall_type][0])
            walls[wall[0, 2]] = wall

    return ClipboardDataContainer(bpm, *notes, walls, original_json)

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
    }
    if isinstance(data, ClipboardDataContainer):
        clipboard["original_json"] = data.original_json

    first = 99999
    last = -99999
    for note_type, notes in enumerate((data.right, data.left, data.single, data.both)):
        for time_index, nodes in notes.items():
            clipboard["notes"].setdefault(round_tick_for_json(time_index * 64), []).append(note_to_synth(data.bpm, note_type, nodes))
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


    ms_per_min = 60 * 1000
    if realign_start:
        # position of selection start in beats*64 
        clipboard["startMeasure"] = round_tick_for_json(first * 64)
        # position of selection start in ms
        clipboard["startTime"] = first * ms_per_min / data.bpm
        # length of the selection in milliseconds
        # and yes, the editor has a typo, so we need to missspell it too
        clipboard["lenght"] = last * ms_per_min / data.bpm
    # always update length
    clipboard["lenght"] = (last - first) * ms_per_min / data.bpm

    pyperclip.copy(json.dumps(clipboard))

def import_file(file_path: Path) -> SynthFile:
    out = SynthFile(file_path, {}, {}, {})
    out.reload()
    return out
