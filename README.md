# Synth Mapping Helper

Toolbox for manipulating the JSON-Format used by *Synth Riders Beatmap Editor* in the clipboard and `.synth` files.

# Installation

## Simple Installation (Windows)

Simply download the latest `.exe` from the [Release Page](https://github.com/adosikas/synth_mapping_helper/releases).

You can just place it anywhere and run it, no installation needed.

To update, simply download the latest file.  
You can enable checks for updates in the *Version History* Tab.

## Advanced Installation

If you are unsure what any of the following means, you should go for the simple installation.

This is a PyPi package: `synth_mapping_helper`.  
The main entry point for the GUI is `python3 -m synth_mapping_helper.gui` (or `smh-gui` if you got `$PATH` setup correctly).

If you want to implement highly custom stuff, you can interface with it directly, check out the [`example_scripts` directory](https://github.com/adosikas/synth_mapping_helper/tree/main/example_scripts) and the [Glossary on the wiki](https://github.com/adosikas/synth_mapping_helper/wiki/Glossary) to learn about how I represent positions, notes, rails and walls.

A virtual environment is recommended for the installation:

```sh
# Initial installation
python3 -m venv smh  # create a virtual environment in a new "smh" directory
smh/bin/pip3 install synth_mapping_helper  # install package and dependencies inside the venv
# Starting GUI
smh/bin/smh-gui
# Note that this calls smh-gui directly inside the venv, without entering it first.
# So, you can just make a shortcut or .desktop file for that command.
```

To update, either delete the venv and start over, or run `smh/bin/pip3 install --upgrade synth_mapping_helper`

# GUI Features


The GUI works like a website running on your local machine (accessible only to you), and accesses the clipboard.

If you are overwhelmed by the amount of buttons, start with one segment at a time.  
You can hover your mouse over pretty much all buttons and input fields to get a short tooltip.

The following is a list of features broken down by GUI tab:

## Dashboard

* Filter for type, rail length, and more
* Switch between reference frames (absolute, relative to rail/wall or custom pivot)
* **Offsetting** in X/Y and time
* **Scaling** in X/Y and time
    * Note that wall sizes cannot scale, only their positions
* Flattening in X/Y
* **Mirroring** across X/Y and time, or with custom angle
    * Can optionally create a mirrored copy instead of replacing the original
* **Rotation** in XY-plane
    * Walls also rotate as one would except (except crouch walls)
* Add **parallel/crossover** patterns
* **Merge and split rails**, even when there are gaps
* Turn **rails into notes**, and **notes into rails**
* Create **notestacks** or lightning rails
* Shorten or extend rails
* **Automatic rails smoothing**
* Change type of notes
* Add **spirals, zigzags or spikes** to any rail
* Remove time gaps in wallart, or adjust spacing to stay below game limits

## Stacking

* Quickly create complex geometric wall or note patterns
    * Create spirals by using just pattern rotation and time offset
    * Create vortices by adding scaling and in/outset to spirals 
* Auto-Detection of parameters, which can then be iterated on
* Subdivision of parameters allows smoother transitions
* Optional randomisation for more organic patterns
* Fast iteration via the **integrated 3D-preview**

## Text

* Automatically create walls to show text
* Custom font support ([submissions welcome](https://github.com/adosikas/synth_mapping_helper/discussions/2))
* _Please_, don't overuse text. So e.g. don't add _all_ lyrics.

## Custom Wall Art Editor

* _Please_, read the **build-in controls / shortcuts popup**
* Fully 3D and using browser acceleration
* Walls render with **transparency**
* Highly customisable, with configurable snapping steps and custom color settings
* Supports symmetry in almost real time (rotational and mirror)
* **TurboStack**, for almost real time "drag and drop" stacking
* Overlay **reference image** to create accurate wall art
* **Compress wall-art** to remove time gaps
* **Blender** to blend between two wall art patterns
    * Uses shortest rotation amount, taking into account symmetry
    * Note: Patterns must match in type and timing, Example:
        * First pattern: Square&Triangle at 10+0/64 and 10+1/64
        * Second pattern: Square&Triangle at 20+0/64 and 20+1/64 (at different XY & rotation)
        * Interpolate with interval 1/2 to create 19 intermediate patterns

## Commands

* Basic scripting support, replacing the legacy "drag and drop onto smh.bat" system
* Chaining operations
* Save frequently used operations as one-click **Quick run** button.
* See the [wiki for syntax](https://github.com/adosikas/synth_mapping_helper/wiki)

## File Utils

* **Create `.synth` from any audio file**
    * While `.mp3`, etc are accepted, please prefer higher quality audio files
* Output can be saved/downloaded, instead of landing in some hard-to-find location
* Fix some common errors that can result in the editor refusing to open the file
* **Automatic BPM detection**
    * Detection BPM & Offset can directly be applied to the file
    * Plot error between detected BPM and onsets (peaks) in the audio
    * Plot which shows when BPM drifts or changes throughout the song
        * In that case manual action is still required, but now you know what's going on instead of just getting a few low-confidence guesses
* **Audio preview with beat ticks (metronome)** to check BPM / Offset
* Fine tune BPM/Offset with quick buttons
* **Adjust BPM/Offset without messing up existing content**
* Pad or trim audio to tweak silence at beginning or end
* **Merge files**, even when they have different BPM
    * This is very useful when mapping parts of a map at different BPM
* Advanced statistics/analysis
    * Plot hand movement, velocity/speed and acceleration/g-force
    * Show various warnings
        * Note at head position (**vision block**)
        * Something to close to end of map
        * Patterns will look messed or be unplayable in spiral, due to a bug in the game
    * Plot nall density, and see if you reach the "**wireframe limit**"
    * Plot note/rail density to identify potentially laggy sections

## AutoBackup

* Periodically checks `.synth` files in a certain directory for changes and creates **backups**
* Backups **never get deleted/overwritten**, so you can _always_ go back
    * You should cleaned up old backups once you are done with that map, as that is _not_ done automatically

## Version History

* **Check for a new version**, either manually or on every start
* Show release notes, with **explaination of new features** (and typically a screenshot)
    * Last few releases only, full list [here](https://github.com/adosikas/synth_mapping_helper/releases)
* Direct link to release for easy download (but no automatic download/install)

# Technical information

The GUI is built with [NiceGUI](https://nicegui.io/), allowing me to write a "frontend" with pure python. Even the wall art editor is created from python, which is why I am not currently able to make a "full editor" as that requires some fully clientside logic (ThreeJS in particular).  
If you have experience there and would like to help me make a proper editor (with native intergration for SMH, please let me know).

In the "backend" everything is python and numpy arrays, and uses fairly modular functions for the various operations. Feel free to experiment with using the API to make custom python scripts, but that requires the advanced installation (see above).

# 100% LLM Free

This project (to the best of my knowledge) does not contain any LLM-Generated code.

Please do not suggest any features that involve what is called "AI" these days (aka LLM/GPT).  
I am open to "normal" statistics (like the BPM detection).

Also, I _urge_ you not to use any of functionality provided here to make something resembling an "automapper", including (but not limited to) mass-parsing `.synth` files for AI-Training or exporting LLM-Output into a map.  
This project is MIT-licensed, so I won't stop you, but please consider the implications of an auto-mapping, including:

* Rapid decrease of map quality, as LLMs will just go for what is "statistically likely", meaning boring, repetitive patterns and no "new" creative patterns
* Even further decrease, once training data includes automapped inputs
* Everyone can just get a mediocre map for whatever they want, leading to multiple maps for the same song (many of them similar)
* Just look at _other game_, where you have thousands of maps, but **need** curation to find the good ones.
* Currently, the majority is good, so you can just get all. With auto-mapped maps, that won't work, meaning multiplayer won't work as it does now.
* Dying out of the custom map community as it currently exists, as people won't have an incentive to learn mapping
* Insert more general talking points against LLMs here, e.g. energy usage, ethic training data, etc.
