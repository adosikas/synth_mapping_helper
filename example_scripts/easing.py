#!/usr/bin/env python3
from typing import Callable, Literal

import numpy as np

# list of functions based on https://easings.net

EASE_MAGIC_BACK_C1 = 1.70158
EASE_MAGIC_BACK_C3 = 2.70158
EASE_MAGIC_ELASTIC_C4 = np.pi * (2/3)
EASE_MAGIC_BOUNCE_N1 = 7.5625
EASE_MAGIC_BOUNCE_D1 = 2.75
EASE_MAGIC_BOUNCE_SHIFTS: tuple[float,float,float,float] = (0.0, 1.5, 2.25, 2.625)
EASE_MAGIC_BOUNCE_OFFSETS: tuple[float,float,float,float] = (0.0, 0.75, 0.9375, 0.984375)

Easing = Literal["static", "linear", "sine", "quad", "cubic", "quart", "quint", "expo", "circ", "back", "elastic", "bounce"]
EaseDirection = Literal["in", "out", "inout"]

easings: dict[Easing, Callable[[float|np.ndarray], float|np.ndarray]] = {
    "static":  np.sign,
    "linear":  np.atleast_1d,
    "sine":    lambda x: np.sin(x * np.pi / 2),
    "quad":    lambda x: (1-(1-x)**2),
    "cubic":   lambda x: (1-(1-x)**3),
    "quart":   lambda x: (1-(1-x)**4),
    "quint":   lambda x: (1-(1-x)**5),
    "expo":    lambda x: (1-2**(-20*x)),
    "circ":    lambda x: (np.sqrt(1-(x-1)**2)),
    "back":    lambda x: (1-((1-x)**3 * EASE_MAGIC_BACK_C3 - (1-x)**2 * EASE_MAGIC_BACK_C1)),
    "elastic": lambda x: ((2**(-10*x)) * np.sin((10*x-0.75)*EASE_MAGIC_ELASTIC_C4) + 1),
    "bounce":  lambda x: np.min(tuple(  # type: ignore
        EASE_MAGIC_BOUNCE_N1*(x-s/EASE_MAGIC_BOUNCE_D1)**2+o
        for s, o in zip(EASE_MAGIC_BOUNCE_SHIFTS, EASE_MAGIC_BOUNCE_OFFSETS)
    ), axis=0),
}

def ease(easing: Easing, dir: EaseDirection, data: float|np.ndarray) -> float|np.ndarray:
    # data can either be number or any array. numbers will be clipped to between 0.0 and 1.0
    # the curve always starts at in=0.0,out=0.0 and ends at in=1,out=1.0
    # if direction is "in", the curve will be flat-ish near in=0.0 and steep-ish near in=1.0
    # if direction is "out", the curve will be steep-ish near in=0.0 and flat-ish near in=1.0
    # if direction is "inout", the curve will be flat-ish near in=0.0 and in=1.0, and steep-ish near in=0.5
    x = np.clip(data, 0, 1)
    f = easings[easing]
    if dir == "out":
        return f(x)
    if dir == "in":
        return 1-f(1-x)
    # inout
    x_scaled = x * 2 - 1  # range: -1 to +1
    y_scaled = np.sign(x_scaled) * f(np.abs(x_scaled))  # range: -1 to +1
    return y_scaled / 2 + 0.5

def demoplot(dir: Literal["out", "in", "inout"], filter: set[Easing]|None = None):
    from matplotlib import pyplot as plt
    x = np.array(range(1000+1))/1000
    for n in easings.keys():
        if filter is None or n in filter: 
            plt.plot(x, ease(n, dir, x), label=n)
    plt.title(f"{dir}, filter:{filter}")
    plt.legend()
    plt.show()

if __name__ == "__main__":
    demoplot("in")
    # demoplot("out", {"bounce"})
