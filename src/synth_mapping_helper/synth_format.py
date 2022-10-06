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

TYPES = ("right", "left", "single", "both")
	
SINGLE_COLOR_NOTES = dict[float, list["numpy array (n, 3)"]]

@dataclass
class DataContainer:
	original_json: str
	bpm: float
	right: SINGLE_COLOR_NOTES
	left: SINGLE_COLOR_NOTES
	single: SINGLE_COLOR_NOTES
	both: SINGLE_COLOR_NOTES

	def apply_for_note_types(self, f, *args, types: list = TYPES, **kwargs) -> None:
		for t in types:
			notes = getattr(self, t)
			f(notes, *args, **kwargs)

	def apply_for_notes(self, f, *args, types: list = TYPES, **kwargs) -> None:
		for t in types:
			notes = getattr(self, t)
			out = {}
			for _, nodes in notes.items():
				out_nodes = f(nodes, *args, **kwargs)
				out[out_nodes[0, 2]] = out_nodes
			setattr(self, str(t), out)

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
    notes: list[str, SINGLE_COLOR_NOTES] = [{} for _ in range(4)]
    for time_index, time_notes in clipboard["notes"].items():
        for note in time_notes:
            note_type, nodes = note_from_synth(bpm, startMeasure, note)
            notes[note_type][nodes[0,2]] = nodes

    # bpm, notes
    return DataContainer(original_json, bpm, *notes)

def export_clipboard(data: DataContainer, realign_start: bool = True):
    notes_dict = {}
    first = 99999
    last = -99999
    for note_type, notes in enumerate((data.right, data.left, data.single, data.both)):
        for time_index, nodes in notes.items():
            notes_dict.setdefault(round(time_index * 64), []).append(note_to_synth(data.bpm, note_type, nodes))
            if nodes[0, 2] < first:
                first = nodes[0, 2]
            if nodes[-1, 2] > last:
                last = nodes[-1, 2]
    if not realign_start:
        first = 0

    clipboard = {
        "BPM": data.bpm,
        "notes": notes_dict,
        # position of selection start in beats*64 
        "startMeasure": round(first * 64),
        # position of selection start in ms
        "startTime": first * MS_PER_MIN / data.bpm,
        # length of the selection in milliseconds
        # and yes, the editor has a typo, so we need to missspell it too
        "lenght": last * MS_PER_MIN / data.bpm,
        "effects": [],
        "jumps": [],
        "crouchs": [],
        "squares": [],
        "triangles": [],
        "slides": [],
        "lights": [],
        "original_json": data.original_json,
    }
    pyperclip.copy(json.dumps(clipboard))

