#/usr/bin/env python3
import base64
from io import BytesIO
import codecs
from contextlib import contextmanager
import dataclasses
import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from typing import Any, Generator, Union
import zipfile
import sys

import numpy as np
import pyperclip
import soundfile

from synth_mapping_helper import movement, __version__
from synth_mapping_helper.audio_format import AudioData
from synth_mapping_helper.utils import second_to_beat, beat_to_second

# For simplicity, we exclusively use grid coordinates (x, y) and use measures for time (z)
# These values are only needed to convert to / from the format the game uses

INDEX_SCALE = 64  # index = measure * INDEX_SCALE
GRID_SCALE = 0.1365  # xy_coord = xy_grid * GRID_SCALE
TIME_SCALE = 20  # z_coord = second * TIME_SCALE

# Apparently the editor grid snap is off by a small amount...
X_OFFSET = 0.002
Y_OFFSET = 0.0012

NOTE_TYPES = ("right", "left", "single", "both")
NOTE_TYPE_STRINGS = ("RightHanded", "LeftHanded", "OneHandSpecial", "BothHandsSpecial")
# Note: wall offsets are eyeballed
WALL_TYPES: dict[str, tuple[int, list[float]]] = {
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
WALL_MIRROR_ID = {id: WALL_TYPES[
        name.replace("left", "right") if "left" in name
        else name.replace("right", "left") if "right" in name
        else name
    ][0]
    for name, (id, _) in WALL_TYPES.items()
}
# symmetry angles in degrees, 360=no symmetry
WALL_SYMMETRY = {
    "wall_right": 180,
    "wall_left": 180,
    "angle_right": 360,
    "center": 180,
    "angle_left": 360,
    "crouch": 360,
    "square": 90,
    "triangle": 120,
}
SLIDE_TYPES = tuple(name for name, (id, _) in WALL_TYPES.items() if id < 100)
LEFT_WALLS = [id for name, (id, _) in WALL_TYPES.items() if "left" in name]
WALL_VERTS = {
    "angle_right": (
        (7.4, -8.75), (-4.6, 8.75), (-5.85, 8.75), (-5.85, 0.2), (5.25, -8.75)
    ),
    "square": (  # drawn as single, concave polygon (similar to a "c", but with the ends touching)
        (8.4, 8.4), (8.4, -8.4), (-8.4, -8.4), (-8.4, 8.4),
        (8.4, 8.4),  # complete the outer ring
        (7.5, 7.5), (-7.5, 7.5), (-7.5, -7.5), (7.5, -7.5),  # inner ring in reverse order (going "back")
        (7.5, 7.5)  # complete inner ring
    ),
    "triangle": (
        (0, -11.2), (-9.7, 5.6), (9.7, 5.6),
        (0, -11.2),
        (0, -10), (8.6, 5), (-8.6, 5),
        (0, -10),
    )
}
# mirror x/y:
for w, (x1, y1), (x2, y2) in (
    ("wall_right", (2.8, 8.4), (4, 6)),
    ("center", (0.15, 11), (2.1, 7.5)),
    ("crouch", (5.6, 5.6), (8, 4)),
):
    WALL_VERTS[w] = ((x1, y1), (x2, y2), (x2, -y2), (x1, -y1), (-x1, -y1), (-x2, -y2), (-x2, y2), (-x1, y1))
# mirror _right to _left:
for w in ("wall_", "angle_"):
    WALL_VERTS[w + "left"] = tuple((-x, y) for x, y in WALL_VERTS[w + "right"][::-1])

ALL_TYPES = NOTE_TYPES + tuple(WALL_TYPES) + ("lights", "effects")

SINGLE_COLOR_NOTES = dict[float, "numpy array (n, 3)"]   # rail segment (n>1) and x,y,t
WALLS = dict[float, "numpy array (1, 5)"]    # x,y,t, type, angle

BEATMAP_JSON_FILE = "beatmap.meta.bin"
METADATA_JSON_FILE = "track.data.json"
DIFFICULTIES = ("Easy", "Normal", "Hard", "Expert", "Master", "Custom")
DIFFICULTY_SPEEDS = {
    "Easy": 1,
    "Normal": 1,
    "Hard": 1,
    "Export": 1.25,
    "Master": 1.5,
}
META_KEYS = ("Name", "Author", "Beatmapper", "CustomDifficultyName", "BPM")

BETA_WARNING_SHOWN = False

class JSONParseError(ValueError):
    def __init__(self, d: dict|list, t: str) -> None:
        super().__init__()
        self.dict = d
        self.type = t

    def __str__(self) -> str:
        return f"Error while parsing JSON of {self.type}: {self.dict}"

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self})"


def beta_warning() -> None:
    global BETA_WARNING_SHOWN
    if not BETA_WARNING_SHOWN:
        print("\n\n ⚠️  W A R N I N G ⚠️")
        print("\tThis was tested with the beta version of the editor only.")
        print("\tYou may want to switch to it if you encounter bugs or weird behavior.\n\n")
        BETA_WARNING_SHOWN = True
        time.sleep(0.5)

def round_time_to_fractions(time: float) -> float:
    # Round to 1/64 or 1/48, whichever is closer
    r64 = round(time * 64) / 64
    r48 = round(time * 48) / 48
    return r64 if abs(time-r64) <= abs(time-r48) else round(r48, 11)

def round_tick_for_json(time: float) -> float:
    # same as above, but in 1/64 ticks the json needs for some things
    # this is a seperate function to only do one float operation after rounding before output, to minimize errors
    r64 = float(round(time))
    r48 = round(time * 0.75) / 0.75  # 0.75 = 48/64
    return r64 if abs(time-r64) <= abs(time-r48) else round(r48, 11)

def round_tick_for_json_index(time: float) -> float | int:
    # same as above, but for notes dict, which uses int when possible
    if time.is_integer():
        return int(time)
    return round_tick_for_json(time)

# basic coordinate
def coord_from_synth(bpm: float, startMeasure: float, coord: list[float], c_type: str = "unlabeled") -> "numpy array (3)":
    try:
        return np.array([
            (coord[0] - X_OFFSET) / GRID_SCALE,
            (coord[1] - Y_OFFSET) / GRID_SCALE,
            # convert absolute coordinate to number of beats since start
            round_time_to_fractions(second_to_beat(coord[2] / TIME_SCALE, bpm) - startMeasure / 64),
        ])
    except (ValueError, TypeError) as exc:
        raise JSONParseError(coord, c_type) from exc

def coord_to_synth(bpm: float, coord: "numpy array (3)") -> list[float]:
    return [
        round((coord[0] * GRID_SCALE) + X_OFFSET, 11),
        round((coord[1] * GRID_SCALE) + Y_OFFSET, 11),
        round(beat_to_second(round_time_to_fractions(coord[2]), bpm) * TIME_SCALE, 11),
    ]

# full note dict
def note_from_synth(bpm: float, startMeasure: float, note_dict: dict) -> tuple[int, "numpy array (n, 3)"]:
    start = coord_from_synth(bpm, startMeasure, note_dict["Position"], "note" if note_dict["Segments"] is None else "rail head")
    note_type = note_dict["Type"]
    if note_dict["Segments"] is None:
        return note_type, start[np.newaxis]  # just add new axis
    else:
        return note_type, np.stack((start,) + tuple(coord_from_synth(
            bpm, startMeasure, node, f"rail node #{i} of rail starting at json index {startMeasure + start[2]*64}"
        ) for i, node in enumerate(note_dict["Segments"])))

def note_to_synth(bpm: float, note_type: int, nodes: "numpy array (n, 3)") -> dict:
    return {
        "Position": coord_to_synth(bpm, nodes[0]),
        "Segments": [coord_to_synth(bpm, node) for node in nodes[1:]] if nodes.shape[0] > 1 else None,
        "Type": note_type,
    }

# full wall dict
def wall_from_synth(bpm: float, startMeasure: float, wall_dict: dict, wall_type: int) -> "numpy array (1, 5)":
    if wall_type not in WALL_LOOKUP:
        raise JSONParseError(wall_dict, "wall") from ValueError(f"Unexpected wall type ({wall_type})")
    return np.concatenate((
        coord_from_synth(bpm, startMeasure, wall_dict["position"], f"{WALL_LOOKUP[wall_type]} wall") + WALL_OFFSETS[wall_type],
        (wall_type, wall_dict.get("zRotation", 0.0))
    ))[np.newaxis]

def wall_to_synth(bpm: float, wall: "numpy array (1, 5)") -> tuple[str, dict]:
    wall_type = int(wall[0, 3])
    pos = coord_to_synth(bpm, wall[0, :3] - WALL_OFFSETS[wall_type])
    wall_dict = {
        "time": round_tick_for_json(wall[0, 2] * 64),  # time as 1/64
        "slideType": wall_type,
        "position": pos,
        "zRotation": round(wall[0, 4] % 360, 3),  # note: crouch walls cannot be rotated, this will be ignored for them
        "initialized": True,  # no idea what this is for
    }
    # crouch, square and triangle are not in the "slides" list, each has their own list and they do not use the "slideType" key
    if wall_type < 100:  # we gave crouch, square and triangle the types 100, 101 and 102
        dest_list = "slides"
    else:
        dest_list = WALL_LOOKUP[wall_type] + "s"
        del wall_dict["slideType"]
        if wall_type == WALL_TYPES["crouch"][0]:
            # cannot rotate crouch walls
            del wall_dict["zRotation"]
    return dest_list, wall_dict

@dataclasses.dataclass
class DataContainer:
    bpm: float = 60.0
    right: SINGLE_COLOR_NOTES = dataclasses.field(default_factory=dict)
    left: SINGLE_COLOR_NOTES = dataclasses.field(default_factory=dict)
    single: SINGLE_COLOR_NOTES = dataclasses.field(default_factory=dict)
    both: SINGLE_COLOR_NOTES = dataclasses.field(default_factory=dict)
    walls: WALLS = dataclasses.field(default_factory=dict)
    # reuse same structure as notes for common code
    lights: SINGLE_COLOR_NOTES = dataclasses.field(default_factory=dict)
    effects: SINGLE_COLOR_NOTES = dataclasses.field(default_factory=dict)

    def __bool__(self) -> bool:
        # truthy when there is *any* object in any of the dicts
        return any(bool(getattr(self, f)) for f in NOTE_TYPES + ("walls", "lights", "effects"))

    def get_counts(self) -> dict[str, dict[str, int]|int]:
        out: dict[str, dict[str, int]] = {
            "walls": {k: 0 for k in WALL_TYPES},
            "notes": {},
            "rails": {},
            "rail_nodes": {},
        }
        for wall in self.walls.values():
            out["walls"][WALL_LOOKUP[wall[0, 3]]] += 1
        for t in NOTE_TYPES:
            n_nodes = [n.shape[0] for n in getattr(self, t).values()]
            notes = sum(1 if n==1 else 0 for n in n_nodes)
            out["notes"][t] = notes
            out["rails"][t] = len(n_nodes) - notes
            out["rail_nodes"][t] = sum(n_nodes) - len(n_nodes)
        for e in ("walls", "notes", "rails", "rail_nodes"):
            out[e]["total"] = sum(out[e].values())
        return out | {"lights": len(self.lights), "effects": len(self.effects)}

    # Note: None of these functions are allowed to *modify* the dicts, instead they must create new dicts
    # This avoids requring deep copies for everything

    def apply_for_notes(self, f, *args, types: tuple[str, ...] = NOTE_TYPES, mirror_left: bool = False, **kwargs) -> None:
        for t in NOTE_TYPES:
            if t not in types:
                continue
            notes = getattr(self, t)
            out = {}
            for _, nodes in sorted(notes.items()):
                out_nodes = f(nodes, *args, direction=(-1 if mirror_left and t == "left" else 1), **kwargs)
                out[out_nodes[0, 2]] = out_nodes
            setattr(self, str(t), out)

    def apply_for_walls(self, f, *args, types: tuple[str, ...] = tuple(WALL_TYPES), mirror_left: bool = False, **kwargs) -> None:
        wall_types = [WALL_TYPES[t][0] for t in WALL_TYPES if t in types]
        out_walls = {}
        for time_index, wall in sorted(self.walls.items()):
            if wall[0, 3] in wall_types:
                wall = f(wall, *args, direction=(-1 if mirror_left and wall[0, 3] in LEFT_WALLS else 1), **kwargs)
                out_walls[wall[0, 2]] = wall
            else:
                out_walls[time_index] = wall
        self.walls = out_walls

    def apply_for_all(self, f, *args, types: tuple[str, ...] = ALL_TYPES, mirror_left: bool = False, **kwargs) -> None:
        self.apply_for_notes(f, *args, types=types, mirror_left=mirror_left, **kwargs)
        self.apply_for_walls(f, *args, types=types, mirror_left=mirror_left, **kwargs)
        for t in ("lights", "effects"):
            if t not in types:
                continue
            objs = getattr(self, t)
            out = {}
            for _, nodes in sorted(objs.items()):
                out_nodes = f(nodes, *args, **kwargs)
                out[out_nodes[0, 2]] = out_nodes
            setattr(self, t, out)


    # used when the functions needs access to all notes and rails of a color at once
    def apply_for_note_types(self, f, *args, types: tuple[str, ...] = NOTE_TYPES, mirror_left: bool = False, **kwargs) -> None:
        for t in types:
            if t not in NOTE_TYPES:
                continue
            setattr(self, t, f(getattr(self, t), *args, direction=(-1 if mirror_left and t == "left" else 1), **kwargs))

    def filtered(self, types: tuple[str, ...] = ALL_TYPES) -> "DataContainer":
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
        self.lights |= other.lights
        self.effects |= other.effects

    def get_object_dict(self, type_name: str) -> Union[SINGLE_COLOR_NOTES, WALLS]:
        if type_name in NOTE_TYPES + ("lights", "effects"):
            return getattr(self, type_name)
        wall_type = WALL_TYPES[type_name][0]
        return {
            time_index: wall
            for time_index, wall in sorted(self.walls.items())
            if wall[0, 3] == wall_type
        }

    def to_clipboard_json(self, realign_start: bool = True) -> str:
        clipboard: dict[str, Any] = {
            "BPM": self.bpm,
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
        if isinstance(self, ClipboardDataContainer) and self.original_json:
            clipboard["original_json"] = self.original_json

        first = 99999.0
        last = -99999.0
        for note_type, notes in enumerate((self.right, self.left, self.single, self.both)):
            type_notes = {}  # buffer single type to avoid multiple of the same type at the same time
            for time_index, nodes in notes.items(): 
                type_notes[round_tick_for_json(time_index * 64)] = note_to_synth(self.bpm, note_type, nodes)
                if nodes[0, 2] < first:
                    first = nodes[0, 2]
                if nodes[-1, 2] > last:
                    last = nodes[-1, 2]
            for time_tick, synth_dict in sorted(type_notes.items()):
                clipboard["notes"].setdefault(time_tick, []).append(synth_dict)
        for _, wall in self.walls.items():
            if wall[0, 2] < first:
                first = wall[0, 2]
            if wall[0, 2] > last:
                last = wall[0, 2]
            dest_list, wall_dict = wall_to_synth(self.bpm, wall)
            clipboard[dest_list].append(wall_dict)

        for t in self.lights:
            if t < first:
                first = t
            if t > last:
                last = t
            clipboard["lights"].append(round_tick_for_json(t * 64))
        for t in self.effects:
            if t < first:
                first = t
            if t > last:
                last = t
            clipboard["effects"].append(round_tick_for_json(t * 64))

        if realign_start:
            # position of selection start in beats*64 
            clipboard["startMeasure"] = round_tick_for_json(first * 64)
            # position of selection start in ms
            clipboard["startTime"] = beat_to_second(first, self.bpm) * 1000
            # length of the selection in milliseconds
            # and yes, the editor has a typo, so we need to missspell it too
            clipboard["lenght"] = beat_to_second(last, self.bpm) * 1000
        # always update length
        clipboard["lenght"] = beat_to_second(last - first, self.bpm) * 1000
        return json.dumps(clipboard)

    def change_bpm(self, bpm: float) -> None:
        if not bpm > 0:
            raise ValueError("BPM must be greater than 0")
        if self.bpm != bpm:
            ratio = bpm/self.bpm
            self.apply_for_all(movement.scale, [1,1,ratio])
            self.bpm = bpm

@dataclasses.dataclass
class ClipboardDataContainer(DataContainer):
    original_json: str = ""
    selection_length: float = 0.0

    @classmethod
    def from_json(cls, clipboard_json: str, use_original: bool=False) -> "ClipboardDataContainer":
        clipboard = json.loads(clipboard_json)
        if not isinstance(clipboard, dict):
            raise ValueError("clipboard did not contain json dict")
        if "original_json" in clipboard:
            original_json = clipboard["original_json"]
            if use_original:
                clipboard = json.loads(original_json)
        else:
            original_json = clipboard_json
        bpm = clipboard["BPM"]
        startMeasure = clipboard["startMeasure"]
        # r, l, s, b
        right: SINGLE_COLOR_NOTES = {}
        left: SINGLE_COLOR_NOTES = {}
        single: SINGLE_COLOR_NOTES = {}
        both: SINGLE_COLOR_NOTES = {}
        notes_lookup: tuple[SINGLE_COLOR_NOTES, SINGLE_COLOR_NOTES, SINGLE_COLOR_NOTES, SINGLE_COLOR_NOTES] = (right, left, single, both)
        for time_index, time_notes in clipboard["notes"].items():
            for note in time_notes:
                note_type, nodes = note_from_synth(bpm, startMeasure, note)
                notes_lookup[note_type][nodes[0,2]] = nodes

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
        
        lights = {
            b: np.array([[0,0,b]])
            for t in clipboard["lights"]
            for b in [round_time_to_fractions((t-startMeasure)/64)]
        }
        effects = {
            b: np.array([[0,0,b]])
            for t in clipboard["effects"]
            for b in [round_time_to_fractions((t-startMeasure)/64)]
        }

        return cls(
            # DataContainer
            bpm=bpm, right=right, left=left, single=single, both=both, walls=walls, lights=lights, effects=effects,
            # ClipboardDataContainer
            original_json=original_json, selection_length=second_to_beat(clipboard["lenght"]/1000, bpm),
        )

# Hacky classes used to trick ZipFile._open_to_write
class _TrueInt(int):
    # this makes it think there are already flags, so it doesn't add "permissions: ?rw-------"
    def __bool__(self):
        return True
class _NonAsciiStr(str):
    # this makes it think the filename is not ascii, so it adds the UTF8 flag
    def encode(self, encoding: str = "utf-8", errors: str = "strict") -> bytes:
        if encoding == "ascii":
            raise UnicodeEncodeError(encoding, self, 0, 0, "dummy error to trick ZipFile._open_to_write")
        return super().encode(encoding=encoding, errors=errors)

@dataclasses.dataclass
class SynthFileMeta:
    name: str
    artist: str
    mapper: str
    audio_name: str
    explicit: bool = False
    cover_name: str = "No cover"
    cover_data: bytes = b""  # from base64 in json, overwrites separate file
    custom_difficulty_name: str = "Custom"
    custom_difficulty_speed: float = 1.0

    def get_safe_name(self, audio_data: bytes) -> str:
        # editor tracks spectrum data by filename, so just append sha256 of content to filename
        sha256_hash = sha256(audio_data).hexdigest()
        # <name>_<hash:64 hexdigits>.<ext> or <name>.<ext>
        m = re.match(r"(.*?)(?:_[0-9a-fA-F]{64})*\.([^.]*)$", self.audio_name)
        if m:
            name, ext = m[1], m[2]
        else:  # should only happen if there is no dot in the filename
            name = self.audio_name
            ext = "ogg"
        return f"{name}_{sha256_hash}.{ext}"

@dataclasses.dataclass
class SynthFile:
    meta: SynthFileMeta
    audio: AudioData
    bookmarks: dict[float, str]
    difficulties: dict[str, DataContainer]

    errors: dict[str, list[tuple[JSONParseError, str]]]
    offset_ms: int

    @staticmethod
    def empty_from_audio(audio_file: Union[Path, BytesIO], *, filename: str|None = None, name: str|None = None, artist: str = "unknown artist", mapper: str = "your name here") -> "SynthFile":
        raw_data = audio_file.read_bytes() if isinstance(audio_file, Path) else audio_file.read()
        audio = AudioData.from_raw(raw_data, allow_conversion=True)
        if filename is None:
            if isinstance(audio_file, Path):
                filename = audio_file.stem
            elif name is not None:
                filename = name
            else:
                filename = "unnamed"
        elif "." in filename:
            filename = filename.rsplit(".", 1)[0]
        if name is None:
            name = filename
        return SynthFile(
            meta=SynthFileMeta(
                name=name,
                artist=artist,
                mapper=mapper,
                audio_name=filename + ".ogg",
            ),
            audio=audio,
            bookmarks={},
            difficulties={DIFFICULTIES[0]: DataContainer()},
            errors={},
            offset_ms=0,
        )

    @property
    def bpm(self) -> float:
        for d, c in self.difficulties.items():
            return c.bpm
        return 0.0  # no difficulties

    @staticmethod
    def from_synth(synth_file: Union[Path, BytesIO]) -> "SynthFile":
        errors: dict[str, list[tuple[JSONParseError, str]]] = {}
        with zipfile.ZipFile(synth_file) as inzip:
            # load beatmap json
            beatmap = json.loads(inzip.read(BEATMAP_JSON_FILE))
            audio = AudioData.from_raw(inzip.read(beatmap["AudioName"]))

        bpm: float = beatmap["BPM"]
        difficulties: dict[str, DataContainer] = {}
        for diff in DIFFICULTIES:
            diff_removed : list[tuple[JSONParseError, str]] = []
            # r, l, s, b
            right: SINGLE_COLOR_NOTES = {}
            left: SINGLE_COLOR_NOTES = {}
            single: SINGLE_COLOR_NOTES = {}
            both: SINGLE_COLOR_NOTES = {}
            notes_lookup: tuple[SINGLE_COLOR_NOTES, SINGLE_COLOR_NOTES, SINGLE_COLOR_NOTES, SINGLE_COLOR_NOTES] = (right, left, single, both)
            for time, time_notes in beatmap["Track"][diff].items():
                time_types = set()
                for note in time_notes:
                    try:
                        note_type, nodes = note_from_synth(bpm, 0, note)
                        if note_type in time_types:
                            raise JSONParseError(note, "duplicate note type")
                        time_types.add(note_type)
                        notes_lookup[note_type][nodes[0,2]] = nodes
                    except JSONParseError as jpe:
                        try:
                            time = f"{time} (measure {float(time)/64})"
                        except:
                            pass
                        diff_removed.append((jpe, time))

            walls: dict[float, list["numpy array (1, 5)"]] = {}
            # slides (right, left, angle_right, center, angle_right)
            for wall_dict in beatmap["Slides"][diff]:
                try:
                    wall = wall_from_synth(bpm, 0, wall_dict, wall_dict["slideType"])
                    walls[wall[0, 2]] = wall
                except JSONParseError as jpe:
                    time = str(wall_dict.get("time"))
                    try:
                        time = f"{time} (measure {float(time)/64})"
                    except:
                        pass
                    diff_removed.append((jpe, time))
            # other (crouch, square, triangle)
            for wall_type in ("Crouch", "Square", "Triangle"):
                if wall_type + "s" not in beatmap:
                    beta_warning()
                    continue  # these are only in the beta editor
                for wall_dict in beatmap[wall_type + "s"][diff]:
                    try:
                        wall = wall_from_synth(bpm, 0, wall_dict, WALL_TYPES[wall_type.lower()][0])
                        walls[wall[0, 2]] = wall
                    except JSONParseError as jpe:
                        time = str(wall_dict.get("time"))
                        try:
                            time = f"{time} (measure {float(time)/64})"
                        except:
                            pass
                        diff_removed.append((jpe, time))
            lights = {
                b: np.array([[0,0,b]])
                for t in beatmap["Lights"][diff]
                for b in [round_time_to_fractions(t / 64)]
            }
            effects = {
                b: np.array([[0,0,b]])
                for t in beatmap["Effects"][diff]
                for b in [round_time_to_fractions(t / 64)]
            }
            # add difficulty when there is a note of any type, a wall or lights/effects
            if any(notes_lookup) or walls or lights or effects:
                difficulties[diff] = DataContainer(bpm=bpm, right=right, left=left, single=single, both=both, walls=walls, lights=lights, effects=effects)

            if diff_removed:
                errors[diff] = diff_removed

        if not difficulties:
            # at add least one difficulty, such that BPM can be tracked
            difficulties[DIFFICULTIES[0]] = DataContainer(bpm=bpm)
            
        return SynthFile(
            meta=SynthFileMeta(
                name = beatmap["Name"],
                artist = beatmap["Author"],
                mapper = beatmap["Beatmapper"],
                explicit = beatmap.get("Explicit", False),
                cover_name = Path(beatmap["Artwork"]).stem + ".png",  # change to .png, regardless of input type
                cover_data = base64.b64decode(beatmap["ArtworkBytes"] or b""),  # this seems to be a converted form (to png)
                audio_name = beatmap["AudioName"],
                custom_difficulty_name = beatmap["CustomDifficultyName"],
                custom_difficulty_speed = beatmap["CustomDifficultySpeed"],
            ),
            audio=audio,
            bookmarks={
                # bookmarks are stored in steps of 64 per beat (regardless of BPM)
                round_time_to_fractions(bookmark_dict["time"] / 64): bookmark_dict["name"]
                for bookmark_dict in beatmap["Bookmarks"]["BookmarksList"]
            },
            difficulties=difficulties,
            errors=errors,
            offset_ms=beatmap["Offset"],
        )

    def save_as(self, output_file: Union[Path, BytesIO]) -> None:
        out_buffer = output_file if isinstance(output_file, BytesIO) else BytesIO()  # buffer output zip file in memory, only write on success

        bookmark_list = [
            {"time": round_tick_for_json(t * 64), "name": n}
            for t, n in sorted(self.bookmarks.items())
        ]
        safe_audio_name = self.meta.get_safe_name(self.audio.raw_data)
        now = datetime.datetime.now(datetime.timezone.utc)
        out_beatmap: dict[str, Any] = {
            "Name": self.meta.name,
            "Author": self.meta.artist,
            "Artwork": self.meta.cover_name,
            "ArtworkBytes": base64.b64encode(self.meta.cover_data).decode(),
            "AudioName": safe_audio_name,
            "AudioData": None,
            "AudioFrecuency": self.audio.sample_rate,
            "AudioChannels": self.audio.channels,
            "BPM": self.bpm,
            "Offset": self.offset_ms,
            "Track": {d: {} for d in DIFFICULTIES},  # notes/rails
            "Effects": {d: [] for d in DIFFICULTIES},
            "Bookmarks" : {"BookmarksList": bookmark_list},
            # note: for some of the following I just use dummy value, no idea what they are used for
            "Jumps": {d: [] for d in DIFFICULTIES},  # ?
            "Crouchs": {d: [] for d in DIFFICULTIES},
            "Slides": {d: [] for d in DIFFICULTIES},
            "Lights": {d: [] for d in DIFFICULTIES},
            "Squares": {d: [] for d in DIFFICULTIES},
            "Triangles": {d: [] for d in DIFFICULTIES},
            "DrumSamples": None,  # ?
            "FilePath": "Redacted",
            "IsAdminOnly": False,  # ?
            "EditorVersion": f"SMH v{__version__}",
            "Beatmapper": self.meta.mapper,
            "CustomDifficultyName": self.meta.custom_difficulty_name,
            "CustomDifficultySpeed": self.meta.custom_difficulty_speed,
            "UsingBeatMeasure": True,  # ?
            "UpdatedWithMovementPositions": True,  # ?
            "ProductionMode": False,  # ?
            "Tags": [],  # ?
            "BeatConverted": False,  # ?
            "BeatModified": False,  # ?
            "ModifiedTime": now.timestamp(),
            "Explicit": self.meta.explicit,
        }

        # fill per-difficulty arrays/dicts
        for diff, data in self.difficulties.items():
            new_notes: dict[float, list[dict]] = {}
            for note_type, notes in enumerate((data.right, data.left, data.single, data.both)):
                type_notes: dict[float, dict] = {}  # buffer single type to avoid multiple of the same type at the same time
                for time_index, nodes in sorted(notes.items()):
                    type_notes[round_tick_for_json_index(time_index * 64)] = note_to_synth(data.bpm, note_type, nodes)
                for time_tick, synth_dict in sorted(type_notes.items()):
                    existing = new_notes.setdefault(time_tick, [])
                    # edit by reference
                    existing.append(
                        # keep same order as editor
                        {"Id": f"Note_{time_tick}{NOTE_TYPE_STRINGS[note_type]}{len(existing)}", "ComboId": -1}
                        | synth_dict
                        | {"Direction": 0}
                    )
            out_beatmap["Track"][diff] = {k: v for k,v in sorted(new_notes.items())}
            walls: dict[str, list[dict]] = {
                "crouchs": [],
                "squares": [],
                "triangles": [],
                "slides": [],
            }
            for _, wall in sorted(data.walls.items()):
                dest_list, wall_dict = wall_to_synth(data.bpm, wall)
                walls[dest_list].append(wall_dict)
            for t, wall_list in walls.items():
                out_beatmap[t.capitalize()][diff] = wall_list
            out_beatmap["Lights"][diff] = [round_tick_for_json(t * 64) for t in data.lights]
            out_beatmap["Effects"][diff] = [round_tick_for_json(t * 64) for t in data.effects]

        # write modified beatmap json, in a way that closely mirrors the editor
        beatmap_json = json.dumps(out_beatmap, indent=2, allow_nan=False)
        meta_json = json.dumps({
            "name": self.meta.name,
            "artist": self.meta.artist,
            "duration": f"{self.audio.duration//60:.0f}:{self.audio.duration%60:02.0f}",
            "coverImage": self.meta.cover_name,
            "audioFile": safe_audio_name,
            "supportedDifficulties": [
                d if self.difficulties.get(d, False) else "" for d in DIFFICULTIES
            ],
            "bpm": self.bpm,
            "mapper": self.meta.mapper,
        }, indent=2, allow_nan=False)
        
        with zipfile.ZipFile(out_buffer, "w") as outzip:
            def make_fileinfo(filename: str) -> zipfile.ZipInfo:
                info = zipfile.ZipInfo(filename, now.timetuple()[:6])
                info.compress_type = zipfile.ZIP_DEFLATED
                # fake various file headers
                info.create_system = 0
                info.create_version = zipfile.ZIP64_VERSION
                # editor files also contain NTFS timestamps, see "PKWARE Win95/WinNT Extra Field (0x000a)"" at
                # https://mdfs.net/Docs/Comp/Archiving/Zip/ExtraField

                # trick header encoder
                info.external_attr = _TrueInt(0)
                info.filename = _NonAsciiStr(filename)
                return info
            
            outzip.writestr(make_fileinfo(BEATMAP_JSON_FILE), codecs.BOM_UTF8 + beatmap_json.encode("utf-8").replace(b"\n", b"\r\n"))
            outzip.writestr(make_fileinfo(safe_audio_name), self.audio.raw_data)
            outzip.writestr(make_fileinfo(self.meta.cover_name), self.meta.cover_data)
            outzip.writestr(make_fileinfo(METADATA_JSON_FILE), codecs.BOM_UTF8 + meta_json.encode("utf-8").replace(b"\n", b"\r\n"))
        # write output zip
        if isinstance(output_file, BytesIO):
            output_file.seek(0)
        else:
            output_file.write_bytes(out_buffer.getbuffer())

    def reload(self, new_file: Union[Path, BytesIO]) -> "SynthFile":
        new = type(self).from_synth(new_file)
        if new.audio.raw_data == self.audio.raw_data:
            # keep audio cache, if applicable
            new.audio = self.audio
        return new

    def change_bpm(self, bpm: float) -> None:
        if not bpm > 0:
            raise ValueError("BPM must be greater than 0")
        if self.bpm != bpm:
            ratio = bpm/self.bpm
            self.bookmarks = {
                time * ratio: name
                for time, name in self.bookmarks.items()
            }
            for c in self.difficulties.values():
                c.change_bpm(bpm)

    def offset_everything(self, delta_s: float|None = None, delta_b: float|None = None) -> None:
        if (delta_s is not None) == (delta_b is not None):
            raise ValueError("Specify either delta_s or delta_b")
        elif delta_b is None and delta_s is not None:
            delta_b = second_to_beat(delta_s, self.bpm)
        if delta_b:
            self.bookmarks = {
                time + delta_b: name
                for time, name in self.bookmarks.items()
            }
            for c in self.difficulties.values():
                c.apply_for_all(movement.offset, [0,0,delta_b])

    def change_offset(self, offset_ms: int) -> None:
        if offset_ms < 0:
            raise ValueError("Offset must be greater than 0")
        if self.offset_ms != offset_ms:
            self.offset_everything(delta_s=(offset_ms-self.offset_ms)/1000)
            self.offset_ms = offset_ms

    def merge(self, other: "SynthFile", adjust_bpm: bool = True, merge_bookmarks: bool = True) -> None:
        if adjust_bpm and self.bpm != other.bpm:
            other.change_bpm(self.bpm)
        if adjust_bpm and self.offset_ms != other.offset_ms:
            other.change_offset(self.offset_ms)
        if merge_bookmarks:
            self.bookmarks |= other.bookmarks
        for d, c in other.difficulties.items():
            if d in self.difficulties:
                self.difficulties[d].merge(c)
            else:
                self.difficulties[d] = c
        for d, e in other.errors.items():
            if d in self.errors:
                self.errors[d].extend(e)
            else:
                self.errors[d] = e

    def with_added_silence(self, *, before_start_ms: int|None = 0, after_end_ms: int|None = 0) -> "SynthFile":
        if not before_start_ms and not after_end_ms:
            return
        if before_start_ms is None:
            before_start_ms = 0
        if after_end_ms is None:
            after_end_ms = 0
        new_audio = self.audio.with_silence(before_start_s=before_start_ms/1000, after_end_s=after_end_ms/1000)
        output = dataclasses.replace(self, audio=new_audio)
        if before_start_ms:
            output.offset_everything(delta_s=before_start_ms/1000)
        return output

# convenience wrappers

# clipboard json
def import_clipboard_json(original_json: str, use_original: bool = False) -> ClipboardDataContainer:
    return ClipboardDataContainer.from_json(clipboard_json=original_json, use_original=use_original)

def export_clipboard_json(data: DataContainer, realign_start: bool = True) -> str:
    return data.to_clipboard_json(realign_start=realign_start)

# direct clipboard
def import_clipboard(use_original: bool = False) -> ClipboardDataContainer:
    return import_clipboard_json(pyperclip.paste(), use_original)

def export_clipboard(data: DataContainer, realign_start: bool = True):
    pyperclip.copy(export_clipboard_json(data, realign_start))

@contextmanager
def clipboard_data(use_original: bool = False, realign_start: bool = True) -> Generator[ClipboardDataContainer, None, None]:
    # Usage:
    #   with synth_format.clipboard_data() as data:
    #     data.apply_for_all(...)
    data = ClipboardDataContainer.from_json(pyperclip.paste(), use_original=use_original)
    yield data
    pyperclip.copy(data.to_clipboard_json(realign_start=realign_start))

# file
def import_file(file_path: Union[Path, BytesIO]) -> SynthFile:
    return SynthFile.from_synth(file_path)

@contextmanager
def file_data(filename: str|Path|None = None, save_suffix: str|None = "_out") -> Generator[SynthFile, None, None]:
    if filename is None and len(sys.argv) == 2 and sys.argv[1].endswith(".synth") and Path(sys.argv[1]).is_file():
        # if given a single command line argument that is a .synth file, use that
        fp = Path(sys.argv[1])
    elif filename is not None:
        fp = Path(filename)
    else:
        raise ValueError("No filename provided")
    print(f"Loading {fp.absolute()}")
    f = SynthFile.from_synth(fp)
    yield f
    if save_suffix is not None:
        fp_out = fp.with_stem(f"{fp.stem}{save_suffix}")
        print(f"Saving {fp_out.absolute()}")
        f.save_as(fp_out)
