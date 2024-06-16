from typing import Any, Union

import numpy as np

def beat_to_second(beat: float, bpm: float) -> float:
    return beat * 60 / bpm

def second_to_beat(second: float, bpm: float) -> float:
    return second * bpm / 60

def bounded_arange(start: float, end: float, step: float) -> "numpy array (x)":
    # arange would not include the end position, so we intentially overshoot, then correct
    new_times = np.arange(start, end + step, step)
    if np.isclose(new_times[-2], end):
        # we overshot by an interval and the penultimate position already closely matches the end -> remove overshoot
        new_times[-2] = end
        return new_times[:-1]
    # we overshot by less than an interval -> clamp last time to end
    new_times[-1] = end
    return new_times

def bounded_arange_plusminus(start: float, end: float, step: float) -> "numpy array (x)":
    # allow step to be negative, start from end then
    if step > 0:
        return bounded_arange(start, end, step)
    else:
        return end - bounded_arange(0, end-start, -step)

def parse_number(val: str) -> float:
    if not val:
        raise ValueError("Value empty")
    if "/" in val:
        num, denom = val.split("/", 1)
        if " " in num:
            # mixed fraction, ie "1 1/2" -> 1.5
            integer, num = num.split(" ", 1)
            i = int(integer)
            return i + np.sign(i) * (float(num) / float(denom))
        return float(num) / float(denom)
    elif val.endswith("%"):
        return float(val[:-1]) / 100
    return float(val)

def parse_range(val: str) -> tuple[float, float]:
    if ":" not in val:
        v = parse_number(val)
        return (-v, v)
    split = val.split(":")
    if len(split) != 2:
        raise ValueError("Must be in the form 'max' or 'min:max'")
    try:
        min = parse_number(split[0])
    except ValueError:
        raise ValueError("Error parsing minimum")
    try:
        max = parse_number(split[1])
    except ValueError:
        raise ValueError("Error parsing maximum")
    return (min, max)

def parse_xy_range(val: str) -> tuple[tuple[float, float], tuple[float, float]]:
    split = val.split(",")
    if len(split) != 2:
        raise ValueError("Must be in the form X_RANGE,Y_RANGE")
    try:
        x = parse_range(split[0])
    except ValueError:
        raise ValueError("Error parsing x range")
    try:
        y = parse_range(split[1])
    except ValueError:
        raise ValueError("Error parsing y range")
    return ((x[0], y[0]), (x[1], y[1]))


class SecondFloat:
    # dummy class to hold numbers parsed as seconds until bpm was parsed
    def __init__(self, val: float) -> None:
        self.val = val
    def to_beat(self, bpm: float) -> float:
        return second_to_beat(self.val, bpm)
    def __str__(self) -> str:
        return f"{self.val}s"
    def __repr__(self) -> str:
        return f"{type(self).__name__}({self})"


def parse_time(val: str) -> Union[float, SecondFloat]:
    # note that there is no rounding here,
    if val.endswith("s"):
        return SecondFloat(parse_number(val[:-1]))
    elif ":" in val:
        # parse mm:ss.fff into seconds
        m, s = val.rsplit(":", 1)
        return SecondFloat(float(m) * 60 + float(s))
    return parse_number(val)

def parse_position(val: str) -> tuple[float, float, Union[float, SecondFloat]]:
    split = val.split(",")
    if len(split) != 3:
        raise ValueError("Must be in the form x,y,t")
    try:
        x = parse_number(split[0])
    except ValueError:
        raise ValueError("Error parsing x")
    try:
        y = parse_number(split[1])
    except ValueError:
        raise ValueError("Error parsing y")
    try:
        t = parse_time(split[2])
    except ValueError:
        raise ValueError("Error parsing t")
    return (x, y, t)

def pretty_fraction(val: float) -> str:
    if round(val, 4).is_integer():
        return str(int(round(val, 4)))
    if round(val*192, 4).is_integer():
        if val < 1:
            # regular fraction: a/b
            v = int(round(val*192, 4))
            gcd = np.gcd(v,192)
            return f"{v//gcd}/{192//gcd}"
        else:
            # mixed fraction: i a/b
            i = int(val)
            v = int(round((val-i)*192, 4))
            gcd = np.gcd(v,192)
            return f"{i} {v//gcd}/{192//gcd}"
    return str(val)

def pretty_time_delta(seconds: float) -> str:
    seconds = abs(seconds)
    if seconds < 1:
        return f"{seconds*1000:.0f} ms"
    units = {
        "second": 60,
        "minute": 60,
        "hour": 24,
        "day": 7,
        "week": 30/7,
        "month": 365/30,
        "year": 1000,
    }
    value = seconds
    for unit, next_unit in units.items():
        if value < next_unit:
            # add 's' if value rounds to 2 or more
            return f"{value:.0f} {unit}{'s' if value >= 1.5 else ''}"
        value = value / next_unit
    return "a really long time"


def pretty_list(data: list[Any]) -> str:
    if not data:
        return ""
    if len(data) == 1:
        return str(data[0])
    return ", ".join(map(str, data[:-1])) + f" and {data[-1]}"
