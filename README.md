# Synth Mapping Helper

Toolbox for manipulating the JSON-Format used by *Synth Riders Beatmap Editor* in the clipboard.

## Features

* Filter by note and wall types for all operations
* Changing type of notes and walls
  * Can cycle between multiple colors to make "rainbows" or alternate between single hand specials and regular notes
* Change BPM indepenent of note timing (helpful if you have a map with different BPM sections)
* Movement in XY and Time ([wiki page](https://github.com/adosikas/synth_mapping_helper/wiki/Movement-options)):  
    Note: All operation can be done in regards to grid center, a pivot point, or the start of rails
    * Rotate
    * Scale and mirror
    * Outset (moving outwards/away by a fixed distance)
    * Offset (Translate/Move)
    * Stacking patterns
* Pattern generation
    * Spirals/Zigzags
    * Spike/Buzz-Rails
    * Stack along rails
* Rail manipulation
    * Merging
    * Splitting
    * Interpolation
    * Convert between single notes and rails
* Cross-Platform (Windows, Linux)
    * For Windows, supports drag and drop actions (fully usable without command prompt)
* Imports directly from clipboard, and export to it
* Uses an internal format that is easy to work with ([wiki page](https://github.com/adosikas/synth_mapping_helper/wiki/Glossary#measurement-system)):
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

See [this wiki page](https://github.com/adosikas/synth_mapping_helper/wiki/Installation-and-Usage-on-Windows) for detailed instructions, including screenshots.
