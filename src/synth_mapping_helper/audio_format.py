import dataclasses
from io import BytesIO

import librosa
import numpy as np
import soundfile


OGG_WRITE_CHUNK_SIZE = 0x10000

class AudioNotOggError(RuntimeError):
    def __init__(self, detected_format: str) -> None:
        self.detected_format = detected_format

@dataclasses.dataclass
class AudioData:
    raw_data: bytes
    sample_rate: int
    channels: int
    duration: float

    @staticmethod
    def from_raw(raw_data: bytes, *, allow_conversion: bool = False) -> "AudioData":
        try:
            info = soundfile.info(BytesIO(raw_data))
        except soundfile.SoundFileError as sfe:
            raise ValueError(f"Could not parse audio file: {sfe!r}")
        if info.format != "OGG":
            if not allow_conversion:
                raise AudioNotOggError(info.format)
            data, sr = soundfile.read(BytesIO(raw_data))
            raw_data = export_ogg(data.T, samplerate=sr)
        return AudioData(
            raw_data=raw_data,
            sample_rate=info.samplerate,
            channels=info.channels,
            duration=info.duration,
        )

    def with_silence(self, before_start_s: float = 0, after_end_s: float = 0) -> "AudioData":
        if not before_start_s and not after_end_s:
            return self
        data, sr = soundfile.read(BytesIO(self.raw_data))
        if before_start_s < 0:
            data = data[librosa.time_to_samples(-before_start_s, sr=sr):]
        if before_start_s > 0:
            p = np.zeros_like(data, shape=(librosa.time_to_samples(before_start_s, sr=sr), *data.shape[1:]))
            data = np.concatenate((p, data))
        if after_end_s < 0:
            data = data[:-librosa.time_to_samples(-after_end_s, sr=sr)]
        if after_end_s > 0:
            p = np.zeros_like(data, shape=(librosa.time_to_samples(after_end_s, sr=sr), *data.shape[1:]))
            data = np.concatenate((data, p))
        return AudioData(
            raw_data=export_ogg(data.T, samplerate=sr),
            sample_rate=sr,
            channels=data.shape[1],
            duration=librosa.samples_to_time(data.shape[0], sr=sr),
        )

def load_for_analysis(raw_data: bytes) -> tuple["numpy array (f,)", int]:
    data, sr = librosa.load(BytesIO(raw_data))  # load with default samplerate and as mono
    return data, int(sr)

def export_ogg(data: "numpy array (c, s)|(s,)", samplerate: int = 22050) -> bytes:
    # librosa uses channels x samples instead of samples x channels, so transpose
    data = data.T
    bio = BytesIO()
    # saving as ogg segfauls if the chunks are too big, so chunk the writes
    # based on https://github.com/bastibe/python-soundfile/issues/426#issuecomment-2150934383
    if data.ndim == 1:
        channels = 1
    else:
        channels = data.shape[1]
    with soundfile.SoundFile(bio, 'w', samplerate=samplerate, channels=channels, format="ogg") as f:
        num_chunks = (len(data) + OGG_WRITE_CHUNK_SIZE - 1) // OGG_WRITE_CHUNK_SIZE
        for chunk in np.array_split(data, num_chunks, axis=0):
            f.write(chunk)

    return bio.getvalue()

def export_wav(data: "numpy array (c, s)|(s,)", samplerate: int = 22050) -> bytes:
    # librosa uses channels x samples instead of samples x channels, so transpose
    data = data.T
    bio = BytesIO()
    soundfile.write(file=bio, data=data, samplerate=samplerate, format="wav")
    return bio.getvalue()

def audio_with_clicks(raw_audio_data: bytes, duration: float, bpm: float, offset_ms: int) -> bytes:
    beat_time = 60/bpm
    data, sr = librosa.load(BytesIO(raw_audio_data))
    clicks = librosa.clicks(times=np.arange(beat_time-(offset_ms/1000)%beat_time, duration, beat_time), length=len(data), sr=sr)
    return export_ogg(data+clicks, samplerate=int(sr))

def find_trims(raw_audio_data: bytes) -> tuple[float, float]:
    data, sr = librosa.load(BytesIO(raw_audio_data))
    _, (start, end) = librosa.effects.trim(data)
    return librosa.samples_to_time(start), librosa.samples_to_time(data.shape[0]-end)