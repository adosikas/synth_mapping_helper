from io import BytesIO
from dataclasses import dataclass, field
from datetime import datetime
from datetime import datetime
from typing import Any, Generator, Literal

import numpy as np
import librosa
import soundfile

from synth_mapping_helper import rails, utils, audio_format
from synth_mapping_helper.synth_format import DataContainer, SINGLE_COLOR_NOTES, NOTE_TYPES, WALL_TYPES, AudioData, GRID_SCALE

RENDER_WINDOW_WALL = 4.0  # the game always renders walls 4 seconds ahead
RENDER_WINDOW_NOTES = 3.5  # the game always renders notes 3.5 seconds ahead
QUEST_WIREFRAME_LIMIT = 200  # combined
QUEST_RENDER_LIMIT = 500  # combined
PC_TYPE_DESPAWN = 80  # for each type

RAIL_NODE_DIST = 2.0  # warn for long rails without intermediate nodes

HEAD_POSITION = np.array([0.0,2.0])
HEAD_RADIUS_SQ = 1.5 ** 2  # pre-squared, such that we can skip the sqrt in sqrt(x**2+y**2) < HEAD_RADIUS

# the game uses some formula like out = in - (in^3) to scale X and Y in spieral, which is not monotonic and breaks down as the coordinates approach 1m
SPIRAL_APEX = 0.65 / GRID_SCALE  # 65 cm away from the center the notes stop getting further out
SPIRAL_FLIP = 0.80 / GRID_SCALE  # 80 cm away from the center the math breaks down completely and returns to center, then flips to other side
SPIRAL_NEUTRAL_OFFSET: dict[str, "numpy array (2,)"] = {
    # center is shifted a bit for left/right hands
    "right": np.array([1.5,0.0]),
    "left": np.array([-1.5,0.0]),
    "single": np.zeros(2),
    "both": np.zeros(2),
}

CURVE_WINDOW_S = 1.0  # time between notes for break in curve
CURVE_INTERP = 192  # 192 bins per beat
RAIL_WEIGHT = 0.3  # rails have a lower weight than notes
RAIL_TAIL_WEIGHT = 0.1  # last 20% of rail
HAND_CURVE_TYPE = tuple["numpy array (n, 2)", "numpy array (n, 2)", "numpy array (n, 2)"]  # curve, velocity, acceleration

END_PADDING = 1.0  # notes should not be in the last second to avoid them not showing up at all

@dataclass
class PlotDataContainer:
    times: list[float]
    plot_data: "numpy array (n, 2)"
    max_value: float = field(init=False)
    plot_times: list[np.datetime64] = field(init=False)

    def __post_init__(self) -> None:
        self.max_value = self.plot_data[:,1].max() if self.plot_data.shape[0] else 0.0
        self.plot_times = [np.datetime64(datetime.utcfromtimestamp(t)) for t in self.plot_data[:,0]]

# DENSITY

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

def wall_mode(highest_density: float, *, combined: bool) -> str:
    mode = "OK"
    if combined:
        if highest_density >= QUEST_RENDER_LIMIT:
            mode = "Quest-Limited"
        elif highest_density >= QUEST_WIREFRAME_LIMIT:
            mode = "Quest-Wireframe"
    else:
        if highest_density >= PC_TYPE_DESPAWN:
            mode = "PC-Despawn"

    return f"{mode}, max {round(highest_density)}"

def note_densities(data: DataContainer) -> dict[str, dict[str, PlotDataContainer]]:
    window_b = utils.second_to_beat(RENDER_WINDOW_NOTES, bpm=data.bpm)
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

def all_note_densities(diffs: dict[str, DataContainer]) -> dict[str, dict[str, dict[str, PlotDataContainer]]]:
    return {
        d: note_densities(c)
        for d, c in diffs.items()
    }

def wall_densities(data: DataContainer) -> dict[str, PlotDataContainer]:
    window_b = RENDER_WINDOW_WALL*data.bpm/60
    out = {
        wt: density(times=[t for t, w in data.walls.items() if w[0,3] == tid], window=window_b)
        for wt, (tid, *_) in WALL_TYPES.items()
    }
    out["combined"] = density(times=list(data.walls), window=window_b)
    return out

def all_wall_densities(diffs: dict[str, DataContainer]) -> dict[str, dict[str, PlotDataContainer]]:
    return {
        d: wall_densities(c)
        for d, c in diffs.items()
    }

# MOVEMENT

def hand_curve(notes: SINGLE_COLOR_NOTES, window_b: float) -> HAND_CURVE_TYPE:
    if not notes:
        return np.full((1,3), np.nan)
    # step 1: find average positions for each time "bin", by weighted average of notes and (interpolated) rails
    data_points: dict[int, "numpy array (3,)"] = {}  # t//i: weight,x,y
    for _, nodes in sorted(notes.items()):
        tb = int(nodes[0,2]*CURVE_INTERP)  # time bin
        if nodes.shape[0] == 1:  # single notes
            # head at full weight
            wxy = np.concatenate(([1.0], nodes[0,:2]))
            if tb not in data_points:
                data_points[tb] = wxy
            else:
                data_points[tb] += wxy
        else:  # rails
            # first, sample at 1/192
            interp_rail = rails.interpolate_nodes(nodes, mode="spline", interval=1/CURVE_INTERP)[:,:2]
            # then, add weights: full for head, reduced for tails
            weights = np.full((interp_rail.shape[0], 1), RAIL_WEIGHT)
            weights[0] = 1.0
            weights[-int(interp_rail.shape[0]*0.2):] = RAIL_TAIL_WEIGHT
            weighted_rail = np.concatenate((weights, interp_rail*weights), axis=-1)
            # finally, dump bins into data points
            for bi, wxy in enumerate(weighted_rail):
                if tb+bi not in data_points:
                    data_points[tb+bi] = wxy
                else:
                    data_points[tb+bi] += wxy
    # step 2: locate continguous sections and interpolate over the averaged locations
    out_rails = []
    out_curve = []
    out_vel = []
    out_acc = []
    current_curve: list[tuple[float, float, float]] = []

    def _append_section():
        interp_pos = rails.interpolate_nodes(np.array(current_curve), mode="hermite", interval=1/CURVE_INTERP)
        out_curve.append(interp_pos)
        out_curve.append(np.full((1,3), np.nan))  # add NaN spacers between sections

        if interp_pos.shape[0] > 1:
            section_vel = np.diff(interp_pos[:, :2], axis=0)
            out_vel.append(np.concatenate((section_vel, interp_pos[:-1, 2:3]), axis=-1))
            out_vel.append(np.full((1,3), np.nan))
            if section_vel.shape[0] > 1:
                section_acc = np.diff(section_vel, axis=0)
                out_acc.append(np.concatenate((section_acc, interp_pos[1:-1, 2:3]), axis=-1))
                out_acc.append(np.full((1,3), np.nan))
        
        current_curve.clear()

    last_b = None
    for bi, (w,x,y) in sorted(data_points.items()):
        this_b = (bi/CURVE_INTERP)
        if last_b is not None and (this_b - last_b) > window_b:
            _append_section()
        current_curve.append((x/w,y/w,this_b))
        last_b = this_b
    if current_curve:
        _append_section()
    # put it all together
    return np.concatenate(out_curve), np.concatenate(out_vel), np.concatenate(out_acc)

def hand_curves(data: DataContainer) -> dict[str, HAND_CURVE_TYPE]:
    return {
        nt: hand_curve(getattr(data, nt), window_b=utils.second_to_beat(CURVE_WINDOW_S, bpm=data.bpm))
        for nt in NOTE_TYPES
        if getattr(data, nt)
    }

def all_hand_curves(diffs: dict[str, DataContainer]) -> dict[str, dict[str, HAND_CURVE_TYPE]]:
    return {
        d: hand_curves(c)
        for d, c in diffs.items()
    }

def sections_from_bools(bools: "numpy array (n,)") -> Generator[tuple[int, int], None, None]:
    if bools.any():
        idx = np.nonzero(bools)[0]
        idx_diff_idx = np.nonzero(np.diff(idx)-1)[0]
        start = 0
        for idi in idx_diff_idx:
            yield idx[start], idx[idi]
            start = idi + 1
        yield idx[start], idx[-1]


# type: icon, text
WARNING_TYPES: dict[str, tuple[str, str]] = {
    "end_padding": ("🔚", "Close to end of song when accounting for offset.<br>This may cause issues."),
    "straight_rail": ("📏", "Long rail without intermediate nodes.<br>This may be unplayable in spiral."),
    "spiral_distortion": ("🌀<br>⚠️", "Somewhat far from hand neutral position.<br>This may look distorted in spiral."),
    "spiral_breakdown": ("🌀<br>💀", "Far away from hand neutral position.<br>This will be massively misplaced in spiral."),
    "head_area": ("🙈" , "Inside head area.<br>This may block line of sight")
}

@dataclass
class Warning:
    type: Literal["straight_rail", "end_padding", "spiral_distortion", "spiral_breakdown", "head_area"]
    figure: Literal["x", "y", "xy"]
    note_type: Literal["left", "right", "single", "both"]
    note_rail: Literal["note", "rail"]
    start_beat: float
    end_beat: float

    @property
    def icon(self) -> str:
        return WARNING_TYPES[self.type][0]
    
    @property
    def text(self) -> str:
        return WARNING_TYPES[self.type][1]

def warnings(data: DataContainer, last_beat: float) -> list[Warning]:
    last_safe_beat = last_beat - utils.second_to_beat(END_PADDING, bpm=data.bpm)
    out: list[Warning] = []
    for nt in NOTE_TYPES:
        for _, nodes in sorted(getattr(data, nt).items()):
            if nodes.shape[0] == 1:
                crv = nodes
                nr = "note"
            else:
                crv = rails.interpolate_nodes(nodes, mode="spline", interval=1/CURVE_INTERP)
                nr = "rail"

                rail_deltas = np.diff(nodes[:,2])
                # nodes more than X beats apart
                for s_idx, e_idx in sections_from_bools(rail_deltas > RAIL_NODE_DIST):
                    out.append(Warning(
                        type="straight_rail",
                        figure="xy",
                        note_type=nt,
                        note_rail=nr,
                        start_beat=crv[s_idx, 2],
                        end_beat=crv[e_idx, 2],
                    ))
            # notes/rails near end
            if nodes[-1, 2] >= last_safe_beat:
                out.append(Warning(
                    type="end_padding",
                    figure="xy",
                    note_type=nt,
                    note_rail=nr,
                    start_beat=max(nodes[0, 2], last_safe_beat),
                    end_beat=nodes[-1, 2],
                ))

            spiral_delta = np.abs((crv[:,:1] - SPIRAL_NEUTRAL_OFFSET[nt]))
            # delta x between apex and flip
            for s_idx, e_idx in sections_from_bools(np.logical_and(spiral_delta[:,0] > SPIRAL_APEX, spiral_delta[:,0] <= SPIRAL_FLIP)):
                out.append(Warning(
                    type="spiral_distortion",
                    figure="x",
                    note_type=nt,
                    note_rail=nr,
                    start_beat=crv[s_idx, 2],
                    end_beat=crv[e_idx, 2],
                ))
            # delta y between apex and flip
            for s_idx, e_idx in sections_from_bools(np.logical_and(spiral_delta[:,1] > SPIRAL_APEX, spiral_delta[:,1] <= SPIRAL_FLIP)):
                out.append(Warning(
                    type="spiral_distortion",
                    figure="y",
                    note_type=nt,
                    note_rail=nr,
                    start_beat=crv[s_idx, 2],
                    end_beat=crv[e_idx, 2],
                ))
            # delta x beyond flip
            for s_idx, e_idx in sections_from_bools(spiral_delta[:,0] > SPIRAL_FLIP):
                out.append(Warning(
                    type="spiral_breakdown",
                    figure="x",
                    note_type=nt,
                    note_rail=nr,
                    start_beat=crv[s_idx, 2],
                    end_beat=crv[e_idx, 2],
                ))
            # delta x beyond flip
            for s_idx, e_idx in sections_from_bools(spiral_delta[:,1] > SPIRAL_FLIP):
                out.append(Warning(
                    type="spiral_breakdown",
                    figure="y",
                    note_type=nt,
                    note_rail=nr,
                    start_beat=crv[s_idx, 2],
                    end_beat=crv[e_idx, 2],
                ))

            head_delta = (crv[:,:2] - HEAD_POSITION)
            # distance to head less than keepout radius
            for s_idx, e_idx in sections_from_bools(head_delta[:,0]**2+head_delta[:,1]**2 <= HEAD_RADIUS_SQ):
                out.append(Warning(
                    type="head_area",
                    figure="xy",
                    note_type=nt,
                    note_rail=nr,
                    start_beat=crv[s_idx, 2],
                    end_beat=crv[e_idx, 2],
                ))
    return sorted(out, key=lambda w: w.start_beat)

def all_warnings(diffs: dict[str, DataContainer], last_beat: float) -> dict[str, list[tuple[str, str, float, float, str]]:]:
    return {
        d: warnings(c, last_beat=last_beat)
        for d, c in diffs.items()
    }

# AUDIO

def calculate_onsets(data: "numpy array (s,)", sr: int) -> "numpy array (m,)":
    return librosa.util.normalize(librosa.onset.onset_strength(y=data, sr=sr, aggregate=np.median, center=True))

def find_bpm(onsets: "numpy array (m,)", sr: int) -> "numpy array (m,), numpy array (m,), numpy array (m,)":
    # bins between 0 and approximately 300 bpm (not sure why, but this formula works out)
    hop_len = 1<<(sr.bit_length()-4)
    # decrease hop for shorter signals
    while hop_len * 3 // 2 > onsets.shape[-1]:
        hop_len //= 2
    # 50 % overlap
    win_len = hop_len * 3 // 2
    # this is based on librosa.beat.plp
    ftgram = librosa.feature.fourier_tempogram(onset_envelope=onsets, sr=sr, hop_length=hop_len, win_length=win_len)
    tempo_frequencies = librosa.fourier_tempo_frequencies(sr=sr, hop_length=hop_len, win_length=win_len)
    ftgram[..., tempo_frequencies < 60, :] = 0
    ftgram[..., tempo_frequencies > 240, :] = 0
    ftmag = np.log1p(1e6 * np.abs(ftgram))
    peak_freq_bins = ftmag.argmax(axis=-2)
    # Now we have peak bins, estimate the binning error (±1/2) using
    # https://ccrma.stanford.edu/~jos/sasp/Quadratic_Interpolation_Spectral_Peaks.html
    # Then we can store BPM and peak value for every frame
    bpm_peaks = []
    bpm_peak_values = []
    bpm_multiplier = sr/(hop_len*win_len) * 60  # used to convert intermediate bin to bpm
    for frame, freq_bin in enumerate(peak_freq_bins):
        if freq_bin == 0 or freq_bin == ftgram.shape[-1]:
            bpm_peaks.append(0)
            bpm_peak_values.append(0)
        else:
            a, b, c = np.abs(ftgram[..., freq_bin-1:freq_bin+2, frame])
            p = 1/2 * (a-c) / (a-2*b+c)
            bpm_peaks.append((freq_bin+p)*bpm_multiplier)
            bpm_peak_values.append(b-1/4*(a-c)*p)
    # back to plp
    peak_values = ftmag.max(axis=-2, keepdims=True)
    ftgram[ftmag < peak_values] = 0
    ftgram /= librosa.util.tiny(ftgram) ** 0.5 + np.abs(ftgram.max(axis=-2, keepdims=True))
    pulse = librosa.istft(ftgram, hop_length=1, n_fft=win_len, length=onsets.shape[-1])
    pulse = np.clip(pulse, 0, None, pulse)
    # bpms, normalized bpm strength, pulse curve
    return np.array(bpm_peaks), librosa.util.normalize(np.array(bpm_peak_values)), librosa.util.normalize(pulse)

def group_bpm(bpms: "numpy array (m,)", bpm_strengths: "numpy array (m,)", max_jump: float=0.1, min_len_ratio: float=0.01) -> tuple[float, list[tuple[int, int, float, float]]]:
    min_len = np.ceil(bpms.shape[-1] * min_len_ratio)
    jumps = [idx[0] for idx in np.argwhere(np.abs(np.diff(bpms, prepend=bpms[0])) > max_jump)]

    out: list[tuple[int, int, float, float]] = []
    max_str = 0
    best_bpm = 0
    for start, end in zip([0, *jumps], [*jumps, bpms.shape[-1]]):
        if (end - start) < min_len:
            # ignore short sections
            continue
        bpm = round(bpms[start:end].mean(), 1)  # round output to 1 decimal
        str_sum = bpm_strengths[start:end].sum()
        if str_sum > max_str:
            max_str = str_sum
            best_bpm = bpm
        out.append((start, end, bpm, str_sum))
    # normalize strength
    return best_bpm, [(s,e,b,st/max_str) for s,e,b,st in out]

def locate_beats(onsets: "numpy array (m,)", sr: int, bpm: float) -> "numpy array (t,)":
    _, beats = librosa.beat.beat_track(onset_envelope=onsets, bpm=bpm, sr=sr, trim=False)
    return beats

def circmedian(values: "numpy array (n,)", high: float) -> float:
    # doing statistics on "circular data" (ie 0-beat_time) is hard, but we can treat each value as "angle" (0-2pi, ie 0-360 deg)
    # see also: scipy.stats.circmean
    # via median of sine and cosine, we get the "median angle" and transform that back
    # we get the median instead of mean, to avoid outliers influencing the result
    scaling = 2*np.pi/high
    sines = np.sin(values*scaling)
    cosines = np.cos(values*scaling)
    return (np.arctan2(np.median(sines), np.median(cosines)) / scaling + high)%high

def circerror(values: "numpy array (n,)", target: float, high: float) -> "numpy array (n,)":
    # shift the delta such that equal -> h/2  and opposite -> 0 or h
    shifted_delta = (values - target + high*1.5) % high
    # now get the delta from high/2, and transform into 0 (equal) to 1 (opposite)
    return np.abs(shifted_delta-high/2) / (high/2)

def find_offsets(onsets: "numpy array (m,)", sr: int, bpm_sections: list[tuple[int, int, float, float]]) -> list[tuple[int, int, "numpy array (n,)", float, int, "numpy array (n,)"]]:
    offset_sections = []
    for i, (section_start, section_end, section_bpm, _) in enumerate(bpm_sections):
        beats = locate_beats(onsets=onsets[section_start:section_end], sr=sr, bpm=section_bpm)
        if not beats.any():
            # ignore sections without detected beats
            continue
        # not sure why, but a 22ms offset seems to be required...
        beats = librosa.frames_to_time(beats + section_start, sr=sr) - 0.022
        beat_time = 60/section_bpm
        median_offset = circmedian(beats % beat_time, high=beat_time)
        offset_error = circerror(beats % beat_time, median_offset, high=beat_time)
        offset_ms = int((beat_time - median_offset)*1000)  # the game offsets the audio, so negate offset
        offset_sections.append((section_start, section_end, beats, section_bpm, offset_ms, offset_error))
    return offset_sections

def bpm_aio(raw_data: bytes) -> dict[str, Any]:
    data, sr = audio_format.load_for_analysis(raw_data)
    onsets = calculate_onsets(data=data, sr=sr)
    peak_bpms, peak_values, pulse = find_bpm(onsets=onsets, sr=sr)
    best_bpm, bpm_sections = group_bpm(bpms=peak_bpms, bpm_strengths=peak_values)
    offset_sections = find_offsets(onsets=onsets, sr=sr, bpm_sections=bpm_sections)
    return {
        "data": data,
        "sr": sr,
        "onsets": onsets,
        "peak_bpms": peak_bpms,
        "peak_values": peak_values,
        "pulse": pulse,
        "best_bpm": best_bpm,
        "bpm_sections": bpm_sections,
        "offset_sections": offset_sections,
    }