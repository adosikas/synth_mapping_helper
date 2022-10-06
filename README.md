# Synth Mapping Helper

Toolbox for manipulating the JSON-Format used by *Synth Riders Beatmap Editor* in the clipboard.

## Features

* Movement in XY and Time:
    * Translation
    * Rotation
    * Scaling / Mirroring
* Changing colors
* Pattern generation (TODO: needs to be exposed via cli)
    * Spirals/Zigzags
    * Spike/Buzz-Rails
* Rail manipulation
    * Merging
    * Splitting
    * Interpolation
* Cross-Platform (Windows, Linux)
    * For Windows, supports drag and drop actions (fully usable without command prompt)
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

## How to Install and use

### TL;DR / Command prompt users:
* Install via `pip3 install synth_mapping_helper` (requires python 3.9 or higher)
* See `python3 -m synth_mapping_helper.cli -h` for usage
* Feel free to experiment with extending functionality by using the module functions directly

### Windows
* Install Python 3.10 via the store: https://apps.microsoft.com/store/detail/python-310/9PJPW5LDXLZ5
* Download the windows_helpers.zip from the releases and double-click `install.bat` to download the library and dependencies
* Drag Text files like `merge_rails.txt` or `example_rotate.txt` onto `smh.bat` to execute the actions line by line
* Run `show_help.bat` to learn which options are supported and make your own library of actions
