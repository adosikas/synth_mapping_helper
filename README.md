# Synth Mapping Helper

Toolbox for manipulating the JSON-Format used by *Synth Riders Beatmap Editor* in the clipboard.

## Features

* Movement in XY and Time:
    * Translation
    * Rotation
    * Scaling / Mirroring
* Pattern generation:
    * Spirals/Zigzags
    * Spike/Buzz-Rails
* Rail manipulation
    * Merging
    * Splitting
    * Interpolation
* Cross-Platform (Windows, Linux)
* Imports directly from clipboard, and export to it
* Uses an internal format that is easy to work with:
    * Position in editor grid coordinates (+x=right, +y=up)
    * Time in measures (starting from start of selection)
    * Angles in degrees (positive=counterclockwise)
    * Notes/Rails seperated by color and as `n x 3` numpy-arrays

### Planned Features
* Support for walls
* Tiling/Stacking operations
* Command line interface

### Maybe
* GUI
* Smoothing
* Momentum analysis

## How to Install

Linux / TL;DR: `pip3 install synth_mapping_helper`, requires python 3.9 or higher

### Windows
* Install Python 3.10 via the store: https://apps.microsoft.com/store/detail/python-310/9PJPW5LDXLZ5
* Open a command prompt and run `pip3 install synth_mapping_helper`
