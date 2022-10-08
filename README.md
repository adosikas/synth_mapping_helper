# Synth Mapping Helper

Toolbox for manipulating the JSON-Format used by *Synth Riders Beatmap Editor* in the clipboard.

## Features

* Filter by note and wall types for all operations
* Changing colors
* Change BPM indepenent of note timing
* Movement in XY and Time:  
    Note: All operation can be done in regards to grid center, a pivot point, or the start of rails
    * Rotate
    * Scale and mirror
    * Outset (moving outwards/away by a fixed distance)
    * Offset (Translate/Move)
* Pattern generation
    * Spirals/Zigzags
    * Spike/Buzz-Rails
    * Stacking patterns with movement
* Rail manipulation
    * Merging
    * Splitting
    * Interpolation
    * Convert between single notes and rails
* Cross-Platform (Windows, Linux)
    * For Windows, supports drag and drop actions (fully usable without command prompt)
* Imports directly from clipboard, and export to it
* Uses an internal format that is easy to work with:
    * Position in editor grid coordinates (+x=right, +y=up)
    * Time in measures (starting from start of selection)
    * Angles in degrees (positive=counterclockwise)
    * Notes/Rails seperated by color and as `n x 3` numpy-arrays (x, y, time)
    * Walls as `1 x 5` numpy-arrays (x, y, time, type, rotation)
    * Walls positions are adjusted to match their rotation center

### Maybe
* GUI
* Momentum analysis
* Automatic smoothing

## How to Install and use

### Advanced users
* Install via `pip3 install synth_mapping_helper` (requires python 3.9 or higher)
* See `python3 -m synth_mapping_helper.cli -h` for usage
* Feel free to experiment with extending functionality by using the module functions directly. If you have something that you think could help other mappers, please make a PR

### Windows

Installation:

* Install Python 3.10 via the store: https://apps.microsoft.com/store/detail/python-310/9PJPW5LDXLZ5
* Download the `windows_helpers.zip` from [the releases page](https://github.com/adosikas/synth_mapping_helper/releases)
* Extract it somewhere
* Double-click `install.bat` to download the library and dependencies

Updating:

* Optional: Download `windows_helpers.zip` again (backup your custom actions before you overwrite)
* Run `install.bat` again

Usage:

* Copy the notes from the editor with CTRL-C
* Drag an action text file like `merge_rails.txt` or `spiralize.txt` onto `smh.bat` to execute.
* Paste the result into the editor with CTRL-V

Making your own actions:

* Run `show_help.bat` to learn which options are supported
* You can specify multiple different operations in the same line, they will be chained in the order they *appear in the help* (ordering of options in the line has no effect).
* If you want a different order, or want to do the same operation multiple times (ie different offsets for two colors), each action file can contain multiple lines which are executed in sequence
* Each line is an independent command, so ie a pivot specified in the first line does not affect the second lines
* If you made a particularly useful action, feel free to share it so it can be added to the examples
