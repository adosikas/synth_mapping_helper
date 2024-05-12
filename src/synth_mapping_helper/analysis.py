from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from synth_mapping_helper.synth_format import DataContainer, NOTE_TYPES, WALL_TYPES, AudioData

RENDER_WINDOW = 4.0  # the game always renders 4 seconds ahead
QUEST_WIREFRAME_LIMIT = 200  # combined
QUEST_RENDER_LIMIT = 500  # combined
PC_TYPE_DESPAWN = 80  # for each type

@dataclass
class PlotDataContainer:
    times: list[float]
    plot_data: "numpy array (n, 2)"
    max_value: float = field(init=False)
    plot_times: list[np.datetime64] = field(init=False)

    def __post_init__(self) -> None:
        self.max_value = self.plot_data[:,1].max() if self.plot_data.shape[0] else 0.0
        self.plot_times = list(map(datetime.utcfromtimestamp, self.plot_data[:,0]))


def density(times: list[float], window: float) -> PlotDataContainer:
    # prepares density plot
    if not times:
        return PlotDataContainer(times=[], plot_data=np.zeros((0,2)))
    # time, count
    out: list[tuple[float, int]] = []
    visible_t: list[float] = []
    c = 0  # tracks len(visible_t)
    for t in sorted(times):
        start = t - window
        while c and visible_t[0] < start:
            # always create two datapoints to force discrete "steps"
            out.append((visible_t[0], c))
            out.append((visible_t[0], c-1))
            visible_t = visible_t[1:]
            c -= 1
        out.append((start, c))
        out.append((start, c+1))
        visible_t.append(t)
        c += 1
    while visible_t:
        out.append((visible_t[0], c))
        out.append((visible_t[0], c-1))
        visible_t = visible_t[1:]
        c -= 1

    return PlotDataContainer(
        times=times,
        plot_data=np.array(out)
    )

def wall_mode(highest_density: int, *, combined: bool) -> str:
    mode = "OK"
    if combined:
        if highest_density >= QUEST_RENDER_LIMIT:
            mode = "Quest-Limited"
        elif highest_density >= QUEST_WIREFRAME_LIMIT:
            mode = "Quest-Wireframe"
    else:
        if highest_density >= PC_TYPE_DESPAWN:
            mode = "PC-Despawn"

    return f"{mode}, max {highest_density}"

def note_densities(data: DataContainer) -> dict[str, dict[str, PlotDataContainer]]:
    window_b = RENDER_WINDOW*data.bpm/60
    out = {}
    for nt in NOTE_TYPES:
        # time, node_count
        notes = [(t, n.shape[0]) for t, n in getattr(data, nt).items()]
        # time for every single node (excluding rail head)
        all_nodes = [
            xyt[2]
            for t, n in getattr(data, nt).items()
            for xyt in n[1:]
        ]
        out[nt] = {
            "note": density(times=[t for t,_ in notes], window=window_b),
            "single": density(times=[t for t, c in notes if c==1], window=window_b),
            "rail": density(times=[t for t, c in notes if c>1], window=window_b),
            "rail node": density(times=all_nodes, window=window_b),
        }
    out["combined"] = {
        k: density(
            times=[t for nt in NOTE_TYPES for t in out[nt][k].times],
            window=window_b
        )
        for k in out[NOTE_TYPES[0]]
    }
    return out

def wall_densities(data: DataContainer) -> dict[str, PlotDataContainer]:
    window_b = RENDER_WINDOW*data.bpm/60
    out = {
        wt: density(times=[t for t, w in data.walls.items() if w[0,3] == tid], window=window_b)
        for wt, (tid, *_) in WALL_TYPES.items()
    }
    out["combined"] = density(times=list(data.walls), window=window_b)
    return out
