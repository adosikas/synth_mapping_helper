from io import BytesIO
from dataclasses import dataclass, field
from datetime import datetime
from datetime import datetime

import numpy as np
import librosa
import soundfile

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

def export_wav(data: "numpy array", samplerate: int = 22050) -> bytes:
    bio = BytesIO()
    soundfile.write(file=bio, data=data, samplerate=samplerate, format="wav")
    return bio.getvalue()

def load_audio(raw_data: bytes) -> "numpy array (s,), int":
    data, sr = librosa.load(BytesIO(raw_data))  # load with default samplerate and as mono
    return data, sr

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

def group_bpm(bpms: "numpy array (m,)", bpm_strengths: "numpy array (m,)", max_jump: float=0.1, min_len_ratio: float=0.01) -> list[tuple[int, int, float, float]]:
    min_len = np.ceil(bpms.shape[-1] * min_len_ratio)
    jumps = np.argwhere(np.abs(np.diff(bpms, prepend=bpms[0])) > max_jump)
    jumps = [idx[0] for idx in jumps]

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

def audio_with_clicks(raw_audio_data: bytes, duration: float, bpm: float, offset_ms: int) -> tuple[str, bytes]:
    beat_time = 60/bpm
    data, sr = librosa.load(BytesIO(raw_audio_data))
    clicks = librosa.clicks(times=np.arange(beat_time-(offset_ms/1000)%beat_time, duration, beat_time), length=len(data), sr=sr)
    return "wav", export_wav(data+clicks)