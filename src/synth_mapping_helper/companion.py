from argparse import ArgumentParser, RawDescriptionHelpFormatter
from io import BytesIO
import json
from json import JSONDecodeError
import logging
import os
from pathlib import Path
from time import strftime, time, sleep
from zipfile import ZipFile

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import PowerNorm
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter
from matplotlib.widgets import Button, CheckButtons, RadioButtons, Slider
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from . import movement, synth_format, utils, __version__
from .rails import interpolate_spline
from .synth_format import DataContainer, SynthFile

NOTE_COLORS = {"right": "red", "left": "cyan", "single": "lime", "both": "gold"}

RENDER_WINDOW = 4  # 4 seconds of elements are rendered
WALL_DESPAWN_PC = 80  # limit of visible walls, earlier ones despawn
WALL_DESPAWN_QUEST = 40
# TODO: quest delay needs more research, sometimes 47 ms delay still renders
# TODO: find a way to configure this in a way that matches ingame settings
QUEST_WALL_DELAY = 0.050  # 50 ms on highest wall density

DEFAULT_OUTPUT_FILE = Path("output.synth")  # inside working directory
DEFAULT_BACKUP_DIR = Path("smh_backup")  # inside working directory

DEFAULT_VELOCITY_WINDOW = utils.SecondFloat(0.5)  # half a second gap breaks up velocity / acceleration calculations
DEFAULT_INTERPOLATION = 1/16
DEFAULT_VEL_LIMIT = 100
DEFAULT_ACC_LIMIT = 2000
DEFAULT_HEATMAP_BIN_COUNT = 3
DEFAULT_HEATMAP_NORM_POWER = 0.6

DEFAULT_WINDOW_WIDTH = 1600
DEFAULT_WINDOW_HEIGHT = 900
DEFAULT_MENU_SIZE = 100

# TODO: make those command line arguments
AUTORELOAD_DEFAULT = True
AUTORELOAD_WAIT_SEC = 1  # Editor overwrites the file twice, we want the final result
AUTORELOAD_COOLDOWN_SEC = 5  # Don't reload very fast

AUTOBACKUP_DEFAULT_MIN = 5  # in minutes, or None

def get_parser():
    parser = ArgumentParser(
        formatter_class=RawDescriptionHelpFormatter,
        prog=f"python3 -m {__package__}.{Path(__file__).stem}",
        description='\n'.join([
            "velocity window and interpolation accept any time format, by default in beats, but also '0.5s'",
            ""
            "Also see the wiki on GitHub, which contains more detailed explainations, as well as some examples and images: https://github.com/adosikas/synth_mapping_helper/wiki",
        ]),
        epilog=f"Version: {__version__}",
    )
    parser.add_argument("input", type=Path, help="Input file")
    parser.add_argument("-o", "--output-file", type=Path, default=DEFAULT_OUTPUT_FILE, help=f"Output file. Default: {DEFAULT_OUTPUT_FILE}")
    parser.add_argument("-b", "--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR, help=f"Directory for autobackups. Default: {DEFAULT_BACKUP_DIR}")

    parser.add_argument("--velocity-window", type=utils.parse_time, default=DEFAULT_VELOCITY_WINDOW, help=f"Breaks at least this long reset velocity/acceleration calculation. Default: {DEFAULT_VELOCITY_WINDOW}")
    parser.add_argument("--interpolation", type=utils.parse_time, default=DEFAULT_INTERPOLATION, help=f"Interpolation distance for plots and velocity/accelation calculation. Default: {DEFAULT_INTERPOLATION}")
    parser.add_argument("--velocity-limit", type=float, default=DEFAULT_VEL_LIMIT, help=f"Starting limit of the velocity plot. Default: {DEFAULT_VEL_LIMIT}")
    parser.add_argument("--acceleration-limit", type=float, default=DEFAULT_ACC_LIMIT, help=f"Starting limit of the acceleration plot. Default: {DEFAULT_ACC_LIMIT}")
    parser.add_argument("--heatmap-bin-count", type=float, default=DEFAULT_HEATMAP_BIN_COUNT, help=f"Number of heatmap bins per grid square. Default: {DEFAULT_HEATMAP_BIN_COUNT}")
    parser.add_argument("--heatmap-norm-power", type=float, default=DEFAULT_HEATMAP_NORM_POWER, help=f"Power of heatmap normalisation. Default: {DEFAULT_HEATMAP_NORM_POWER}")

    parser.add_argument("--window-size", type=str, default=f"{DEFAULT_WINDOW_WIDTH}x{DEFAULT_WINDOW_HEIGHT}", help=f"Size of plot window (excluding toolbars) in pixels. Default: {DEFAULT_WINDOW_WIDTH}x{DEFAULT_WINDOW_HEIGHT}")
    parser.add_argument("--menu-size", type=int, default=f"{DEFAULT_MENU_SIZE}", help=f"Height of menu in pixels. Also influences text size. Default: {DEFAULT_MENU_SIZE}")
    return parser

def abort(reason: str):
    logging.error(reason)
    exit(1)

def plot_bookmarks(bookmarks: dict[float, str], axs: "container of mpl axes"):
    for time, name in bookmarks.items():
        for ax in axs:
            ax.axvline(time, color="grey")
        axs[0].text(time, 0.99, name, ha='left', va='bottom', rotation=45, transform=axs[0].get_xaxis_transform())

def prepare_data(data: DataContainer, options) -> tuple[
    list[tuple[list["rails"], "positions", "velocity", "acceleration"]],  # note data
    list[tuple[  # wall data (pc + quest)
        tuple["pc_density", "pc_ok", "pc_despawn"],
        tuple["quest_density", "quest_ok", "quest_despawn", "quest_hidden"]
    ]],
]:
    # NOTES DATA
    velocity_window_beats = utils.second_to_beat(options.velocity_window, data.bpm)
    note_out: list[tuple[list["rails"], "positions", "velocity", "acceleration"]] = []
    for t, note_type in enumerate(synth_format.NOTE_TYPES):
        rails: list["xyz"] = []
        pos_dict: dict[float, "xyz"] = {}
        notes_dict = getattr(data, note_type)
        if not notes_dict:
            # early abort when there are no notes
            note_out.append(([], np.zeros((0,2)), np.zeros((0,2)), np.zeros((0,2))))
            continue
        
        # first, dump all notes and rails nodes into a dict, to get positions over time
        last_time = sorted(notes_dict)[0]
        for time in sorted(notes_dict):
            if time - last_time > velocity_window_beats:
                # insert None to mark end of this window
                pos_dict[(last_time+time)/2] = None
            pos = notes_dict[time]
            for p in pos:
                pos_dict[p[2]] = p[:3]
            if pos.shape[0] > 1:
                # add interpolated spline for this rail (ensuring last position matches the input, ie the interpolation doesn't make it longer)
                rails.append(interpolate_spline(pos, utils.bounded_arange(pos[0,2], pos[-1,2], options.interpolation)))
            last_time = pos[-1,2]

        pos_dict[last_time+1] = None  # cap off with None to simply the coming loop
        # convert dict to np array [time, xyz], interpolating windows at 1/64
        all_pos = []
        current_window = []
        for _, p in sorted(pos_dict.items()):
            if p is not None:
                current_window.append(p)
            else:
                if len(current_window) == 1:
                    # add single note
                    all_pos.extend(current_window)
                elif len(current_window) > 1:
                    # same as rail interpolation above, but on window instead of rail
                    all_pos.extend(interpolate_spline(np.array(current_window), utils.bounded_arange(current_window[0][2], current_window[-1][2], options.interpolation)))
                # add spacer to break up vel/acc plots
                all_pos.append((np.nan, np.nan, np.nan))
                current_window = []
        pos = np.array(all_pos)
        # velocity calculation: delta_xy / delta_t = delta_v
        # this will be plottet at each center between two notes
        delta_pos = np.diff(pos, axis=0)  # difference in x, y and time
        vel = delta_pos[:, :2] / delta_pos[:, 2:3]
        # acceleration: delta_vel / avg(preceding_delta_t, following_delta_t)²
        # this will be plotted at every note position (excluding first and last of each window)
        delta_vel = np.diff(delta_pos, axis=0)
        avg_delta_t = ((delta_pos[:-1, 2:3] + delta_pos[1:, 2:3])/2)
        acc = delta_vel[:, :2] / avg_delta_t ** 2
        note_out.append((rails, pos, vel, acc))

    wall_out: list[tuple[  # wall data (pc + quest)
        tuple["pc_density", "pc_ok", "pc_despawn"],
        tuple["quest_density", "quest_ok", "quest_despawn", "quest_hidden"]
    ]] = []
    
    # walls
    all_walls: dict[str, list[float]] = {
        w_type: sorted([t for t, wall in data.walls.items() if wall[0,3] == w])
        for w, w_type in synth_format.WALL_LOOKUP.items()
    }

    wall_markers = {
        "wall_left": ("s", "left", 7),
        "wall_right": ("s", "right", 6),
        "angle_left": ("o", "left", 5),
        "angle_right":  ("o", "right", 4),
        "center": ("d", "full", 3),
        "crouch": ("s", "top", 2),
        "triangle": ("^", "none", 1),
        "square": ("s", "none", 0),
    }
    quest_wall_delay_beats = utils.second_to_beat(QUEST_WALL_DELAY, data.bpm)

    for wall_type in synth_format.WALL_TYPES:
        pc_density: list[tuple[float, int|float]] = []
        quest_density: list[tuple[float, int|float]] = []

        pc_ok: list[float] = []
        pc_despawn: list[float] = []
        quest_hidden: list[float] = []
        quest_nothidden: list[float] = []
        quest_ok: list[float] = []
        quest_despawn: list[float] = []

        last_time_quest = None
        for i, time in enumerate(all_walls[wall_type]):
            # pc - filter out despawn
            visible_count = 1
            end = time + RENDER_WINDOW
            for other_time in all_walls[wall_type][i+1:]:
                if other_time > end:  # next wall is not visible yet
                    pc_density.append((time, visible_count))
                    if visible_count == 1:  # only a single wall visible (ie last wall of a group)
                        # break up density plot
                        pc_density.append(((time+other_time)/2, np.nan))
                    break
                visible_count += 1
            else:  # all remaining walls are visisble
                pc_density.append((time, visible_count))
            if visible_count > WALL_DESPAWN_PC:
                pc_despawn.append(time)
            else:
                pc_ok.append(time)
            # quest - first step: filter out hidden ones
            hidden_on_quest = last_time_quest is not None and time - last_time_quest < quest_wall_delay_beats
            if hidden_on_quest:
                quest_hidden.append(time)
            else:
                last_time_quest = time
                quest_nothidden.append(time)

        # quest - second step: filter out despawn
        for i, time in enumerate(quest_nothidden):
            visible_count = 1
            end = time + RENDER_WINDOW
            for other_time in quest_nothidden[i+1:]:
                if other_time > end:  # next wall is not visible yet
                    quest_density.append((time, visible_count))
                    if visible_count == 1:  # only a single wall visible (ie last wall of a group)
                        # break up density plot
                        quest_density.append(((time+other_time)/2, np.nan))
                    break
                visible_count += 1
            else:  # all remaining walls are visisble
                quest_density.append((time, visible_count))
            if visible_count > WALL_DESPAWN_QUEST:
                quest_despawn.append(time)
            else:
                quest_ok.append(time)

        wall_out.append(((pc_density, pc_ok, pc_despawn), (quest_density, quest_ok, quest_despawn, quest_hidden)))
    return note_out, wall_out

def plot_notes(options, fig, infile: SynthFile, data: DataContainer, prepared_data, **kwargs):
    axs = fig.subplots(4, sharex=True)
    axs[-1].set_xlabel("beats")
    plot_bookmarks(infile.bookmarks, axs)

    ax_x, ax_y, ax_vel, ax_acc = axs
    ax_x.set_ylabel("X-Position (sq)")
    ax_x.set_ylim((8,-8))
    ax_x.set_yticks(range(-8,8+1), (str(t) if not t%2 else "" for t in range(-8,8+1)))
    ax_x.grid(True)

    ax_y.set_ylabel("Y-Position (sq)")
    ax_y.set_ylim((-6,6))
    ax_y.set_yticks(range(-6,6+1), (str(t) if not t%2 else "" for t in range(-6,6+1)))
    ax_y.grid(True)

    ax_vel.set_ylabel("Velocity (sq/s)")
    ax_vel.set_ylim((0, options.velocity_limit))
    vel_mul = utils.second_to_beat(1, data.bpm)
    ax_acc.set_ylabel("Acceleration (sq/s²)")
    ax_acc.set_ylim((0, options.acceleration_limit))
    acc_mul = vel_mul * vel_mul

    for t, note_type in enumerate(synth_format.NOTE_TYPES):
        color = NOTE_COLORS[note_type]
        notes_dict = getattr(data, note_type)
        
        for time in sorted(notes_dict):
            pos = notes_dict[time]
            # single note / rail head
            ax_x.plot(pos[0, 2], pos[0, 0], color=color, linestyle="", marker="o")
            ax_y.plot(pos[0, 2], pos[0, 1], color=color, linestyle="", marker="o")

            if pos.shape[0] != 1:
                # rail segment markers
                ax_x.plot(pos[1:, 2], pos[1:, 0], color=color, linestyle="", marker=".")
                ax_y.plot(pos[1:, 2], pos[1:, 1], color=color, linestyle="", marker=".")

        rails, pos, vel, acc = prepared_data[0][t]
        # actual rail paths
        for r in rails:
            ax_x.plot(r[:, 2], r[:, 0], color=color)
            ax_y.plot(r[:, 2], r[:, 1], color=color)

        if pos.shape[0] > 1:
            # velocity (n-1), plotted between two nodes
            #                                                  [sq/beat] * [beat/sec] = [sq/s]
            ax_vel.plot((pos[1:, 2] + pos[:-1, 2])/2, [np.sqrt(v.dot(v)) * vel_mul for v in vel], color=color)
        if pos.shape[0] > 2:
            # acceleration (n-2) plotted at nodes (skipping first and last position)
            #                                 [sq/beat²] * ([beat/sec])² = [sq/s²]
            ax_acc.plot(pos[1:-1, 2], [np.sqrt(a.dot(a)) * acc_mul for a in acc], color=color)

def plot_walls(options, fig, infile: SynthFile, data: DataContainer, prepared_data, platform: str):
    axs = fig.subplots(2, sharex=True)
    axs[-1].set_xlabel("beats")
    plot_bookmarks(infile.bookmarks, axs)

    ax_density, ax_status = axs
    ax_density.set_ylabel("Walls visible")
    if platform == "PC":
        ax_density.set_ylim([0, 120])
        ax_density.axhline(80, color="red")
    else:
        ax_density.set_ylim([0, 60])
        ax_density.axhline(40, color="red")
    ax_status.set_ylabel("Wall Type")
    ax_status.set_yticks([])
    ax_status.set_ylim((-0.5,9))

    wall_markers = {
        # wall_type: (marker_shape, marker_fill, y-slot in type plot)
        "wall_left": ("s", "left", 7),
        "wall_right": ("s", "right", 6),
        "angle_left": ("o", "left", 5),
        "angle_right":  ("o", "right", 4),
        "center": ("d", "full", 3),
        "crouch": ("s", "top", 2),
        "triangle": ("^", "none", 1),
        "square": ("s", "none", 0),
    }
    quest_wall_delay_beats = utils.second_to_beat(QUEST_WALL_DELAY, data.bpm)

    for i, wall_type in enumerate(synth_format.WALL_TYPES):
        marker, fill, y = wall_markers[wall_type]
        if platform == "PC":
            # pc: ok first, despawn on top
            pc_density, pc_ok, pc_despawn = prepared_data[1][i][0]
            for walls, color in zip((pc_ok, pc_despawn), ("green", "orange")):
                for time in walls:
                    ax_status.plot([time], [y], marker=marker, fillstyle=fill, color=color)
            ax_density.plot([time for time, _ in pc_density], [count for _, count in pc_density], label=wall_type, marker=".")
        else:
            # quest: ok first, then despawn, hidden on top
            quest_density, quest_ok, quest_despawn, quest_hidden = prepared_data[1][i][1]
            for walls, color in zip((quest_ok, quest_despawn, quest_hidden), ("green", "orange", "red")):
                for time in walls:
                    ax_status.plot([time], [y], marker=marker, fillstyle=fill, color=color)
            ax_density.plot([time for time, _ in quest_density], [count for _, count in quest_density], label=wall_type, marker=".")


    legend_elements = [
        Line2D([0], [0], color='green', label='ok', marker="o", linestyle=""),
        Line2D([0], [0], color='orange', label='despawn', marker="o", linestyle=""),
        Line2D([0], [0], color='red', label='hidden', marker="o", linestyle=""),
    ]
    ax_density.legend(loc="upper right", ncol=len(wall_markers))
    if platform == "PC":
        ax_status.legend(handles=legend_elements[:2], loc="upper right", ncol=2)
    else:
        ax_status.legend(handles=legend_elements, loc="upper right", ncol=3)

def plot_heatmap(options, fig, infile: SynthFile, data: DataContainer, prepared_data, platform: str):
    axs = fig.subplots(2,2)
    axs = (
        axs[0,1],  # right
        axs[0,0],  # left
        axs[1,0],  # single
        axs[1,1],  # both
    )
    for t, note_type in enumerate(synth_format.NOTE_TYPES):
        _, pos, _, _ = prepared_data[0][t]
        axs[t].hist2d(
            pos[:, 0], pos[:,1],
            bins=[int(17 * options.heatmap_bin_count),int(13 * options.heatmap_bin_count)], range=[[-8,8],[-6,6]],
            cmap=("Reds", "Blues", "Greens", "Oranges")[t],
            density=False, norm=PowerNorm(options.heatmap_norm_power),
        )
        avg = np.nanmean(pos, axis=0)
        axs[t].plot(avg[0], avg[1], marker="x", color="white", markeredgecolor="black", markersize=10)
        axs[t].grid(True)
        axs[t].text((-7,7,7,-7)[t], (-5,-5,5,5)[t], len(getattr(data, note_type)), ha="center", va="center")

def show_warnings(options, fig, infile: SynthFile, data: DataContainer, prepared_data, platform: str):
    ax = fig.subplots(1)
    ax.set_axis_off()
    ax.table(loc="top", colWidths=(1/20, 19/20), cellLoc="left", rowLabels=["123 5/6"], cellText=[["note:left", "placeholder, ie extreme peak in acceleration"]])

TABS = [
    ("Notes", plot_notes),
    ("Walls", plot_walls),
    ("Heatmap", plot_heatmap),
    # ("Warnings", show_warnings)
]
PLATFORMS = ("PC", "Quest")

def main(options):
    if not options.input.is_file():
        abort("Input file is not a file, is the path correct?")

    win_sizes = options.window_size.split("x")
    if len(win_sizes) != 2:
        abort("Window size must be '<width>x<height>'")
    # scale the GUI based on one GUI block
    win_w = int(win_sizes[0]) / options.menu_size
    win_h = int(win_sizes[1]) / options.menu_size

    if win_w < 5:
        abort("Window width is too small")
    if win_h < 5:
        abort("Window height is too small")

    # load beatmap json
    data = synth_format.import_file(options.input)

    if isinstance(options.velocity_window, utils.SecondFloat):
        options.velocity_window = options.velocity_window.to_beat(data.bpm)
    if isinstance(options.interpolation, utils.SecondFloat):
        options.interpolation = options.interpolation.to_beat(data.bpm)

    fig = plt.figure(figsize=(win_w, win_h), dpi=options.menu_size, layout="constrained")
    fig.canvas.manager.set_window_title(f"SMH Companion - {data.meta.artist} - {data.meta.name}")
    menu, tab = fig.subfigures(2, 1, height_ratios=(1,win_h-1))

    active_tab = 0
    active_difficulty = 0
    active_platform = 0

    difficulties: list[tuple["difficulty_name", "prepared_data"]] = None
    def replace_prepared_data():
        nonlocal difficulties
        logging.info("Preparing data")
        difficulties = [(d, prepare_data(data.difficulties[d], options)) for d in synth_format.DIFFICULTIES if d in data.difficulties]
        if not difficulties:
            abort("No notes found")
        logging.info("Preparing complete")

    replace_prepared_data()

    def redraw():
        tab_name, tab_func = TABS[active_tab]
        diff_name, prepared_data = difficulties[active_difficulty]
        logging.info(f"Drawing {tab_name}: {diff_name}")
        tab.clear()
        tab_func(options, tab, data, data.difficulties[diff_name], prepared_data, platform=PLATFORMS[active_platform])
        fig.canvas.draw()
        fig.canvas.flush_events()
        logging.info("Drawing complete")

    btns = {}
    colors = ("darksalmon", "limegreen")
    hovercolors = ("lightsalmon", "lightgreen")
    reload_last = time()
    autobackup_last = None

    autobackup_interval_min = AUTOBACKUP_DEFAULT_MIN

    # this is changed when doing reload and autobackup
    reload_txt = menu.text(4.3/win_w, 0.3, f"Last reload: {strftime('%H:%M:%S')}", horizontalalignment="left", verticalalignment="center")
    autobackup_txt = menu.text(4.3/win_w, 0.1, "Last backup: <None>", horizontalalignment="left", verticalalignment="center")

    # this is used by btn_reload
    def btn_backup(ev) -> None:
        nonlocal autobackup_last, autobackup_interval_min
        autobackup_last = time()
        autobackup_txt.set_text(f"Last backup: {strftime('%H:%M:%S')}")
        redraw()  # force redraw to update text

        options.backup_dir.mkdir(exist_ok=True, parents=True)  # make dir if it doesn't exist
        out = options.backup_dir / f"{data.input_file.stem}_{strftime('%Y-%m-%d_%H-%M-%S')}{data.input_file.suffix}"
        out.write_bytes(data.input_file.read_bytes())  # binary identical copy, do not rexport
        logging.info(f"Backup created at {out.resolve()}")

    # this is used by autoreloader
    def btn_reload(ev) -> None:
        nonlocal data, reload_last, autobackup_last, autobackup_interval_min
        reload_last = time()
        reload_txt.set_text(f"Last reload: {strftime('%H:%M:%S')}")
        data = synth_format.import_file(options.input)
        replace_prepared_data()
        logging.info(f"Reloaded {options.input.resolve()}")
        # Update finalize button
        btns["Finalize"].label.set_text("UnFinalize" if data.bookmarks.get(0.0) == "#smh_finalized" else "Finalize")
        # Make a backup when enough time has passed
        if autobackup_interval_min is not None and (autobackup_last is None or time() > autobackup_last + autobackup_interval_min * 60):
            btn_backup(None)  # this redraws
        else:
            redraw()

    file_observer = None
    def refresh_watchdog():
        nonlocal file_observer
        if file_observer is not None:
            file_observer.stop()
        file_observer = Observer()

        class FileEventHandler(FileSystemEventHandler):
            def on_modified(self, event):
                if Path(event.src_path) == options.input:
                    if time() > reload_last + AUTORELOAD_COOLDOWN_SEC:  # don't reload twice
                        # TODO: figure out if something actually changed (only beatmap and ignore image/metadata/etc)
                        logging.info(f"Detected file modification, reloading shortly")
                        sleep(AUTORELOAD_WAIT_SEC)
                        btn_reload(None)  # simulate button click
                    refresh_watchdog()  # editor does weird stuff, so restart watchdog every time
        # Windows does not support watching single files, so we watch the whole directory (and filter for the target)
        file_observer.schedule(FileEventHandler(), options.input.parent if os.name == "nt" else options.input)
        file_observer.start()

    if AUTORELOAD_DEFAULT:
        refresh_watchdog()
    
    def btn_autoreload(ev) -> None:
        nonlocal file_observer
        if file_observer is None:
            refresh_watchdog()
            btns["AutoReload"].color = colors[True]
            btns["AutoReload"].hovercolor = hovercolors[True]
        else:
            file_observer.stop()
            file_observer = None
            btns["AutoReload"].color = colors[False]
            btns["AutoReload"].hovercolor = hovercolors[False]
        plt.draw()

    def btn_finalize(ev) -> None:
        if data.bookmarks.get(0.0) != "#smh_finalized":
            data.bookmarks[0.0] = "#smh_finalized"
            for _, diff_data in data.difficulties.items():
                diff_data.apply_for_walls(movement.offset, offset_3d=(0,-2.1,0), types=synth_format.SLIDE_TYPES)
            btns["Finalize"].label.set_text("UnFinalize")
            logging.info("Finalized map")
        elif data.bookmarks.get(0.0) == "#smh_finalized":
            del data.bookmarks[0.0]
            for _, diff_data in data.difficulties.items():
                diff_data.apply_for_walls(movement.offset, offset_3d=(0,2.1,0), types=synth_format.SLIDE_TYPES)
            btns["Finalize"].label.set_text("Finalize")
            logging.info("Reversed finalization")
        plt.draw()

    def btn_output(active: bool) -> None:
        data.save_as(options.output_file)
        logging.info(f"Saved output to {options.output_file.resolve()}")

    btn_info = [
        ("Reload", btn_reload),
        ("AutoReload", btn_autoreload),
        ("Finalize", btn_finalize),
        ("Output", btn_output),
    ]

    for i, (text, func) in enumerate(btn_info):
        btns[text] = Button(menu.add_axes((0,(len(btn_info)-(i+0.9))/len(btn_info),1/win_w,0.9/len(btn_info))), text)
        btns[text].on_clicked(func)

    btns["AutoReload"].color = colors[file_observer is not None]
    btns["AutoReload"].hovercolor = hovercolors[file_observer is not None]
    if data.bookmarks.get(0.0) == "#smh_finalized":
        btns["Finalize"].label.set_text("UnFinalize")

    tab_rb = RadioButtons(menu.add_axes((1/win_w,0,1/win_w,1)), [n for n, *_ in TABS], active_tab)
    def tab_clicked(selected: str):
        nonlocal active_tab
        for tab_id, (name, *_) in enumerate(TABS):
            if name == selected and tab_id != active_tab:
                active_tab = tab_id
                redraw()
                break
    tab_rb.on_clicked(tab_clicked)

    diff_rb = RadioButtons(menu.add_axes((2/win_w,0,1/win_w,1)), [d for d, *_ in difficulties], active_difficulty)
    def diff_clicked(selected: str):
        nonlocal active_difficulty
        for diff_id, (name, _) in enumerate(difficulties):
            if name == selected and diff_id != active_difficulty:
                active_difficulty = diff_id
                redraw()
                break
    diff_rb.on_clicked(diff_clicked)

    platform_rb = RadioButtons(menu.add_axes((3/win_w,0,1/win_w,1)), PLATFORMS, active_difficulty)
    def platform_clicked(selected: str):
        nonlocal active_platform
        for platform_id, name in enumerate(PLATFORMS):
            if name == selected and platform_id != active_platform:
                active_platform = platform_id
                redraw()
                break
    platform_rb.on_clicked(platform_clicked)

    backup_btn = Button(menu.add_axes((4/win_w,3/4,1/win_w,1/4)), "Backup now")
    backup_btn.on_clicked(btn_backup)

    autobackup_btn = Button(menu.add_axes((5/win_w,3/4,1/win_w,1/4)), "AutoBackup")
    autobackup_sl = Slider(menu.add_axes((4.05/win_w,0.6,1.9/win_w,1/8)), "", 0, 15, valinit=autobackup_interval_min or 0, valstep=1)
    autobackup_sl.valtext.set_visible(False)
    autobackup_slider_txt = menu.text(4.3/win_w, 0.5, f"Minimum age: {autobackup_interval_min} min", horizontalalignment="left", verticalalignment="center")

    def btn_autobackup(ev):
        nonlocal autobackup_interval_min
        if autobackup_interval_min is None:
            autobackup_interval_min = autobackup_sl.val
            autobackup_btn.color = colors[True]
            autobackup_btn.hovercolor = hovercolors[True]
        else:
            autobackup_interval_min = None
            autobackup_btn.color = colors[False]
            autobackup_btn.hovercolor = hovercolors[False]
    autobackup_btn.on_clicked(btn_autobackup)
    autobackup_btn.color = colors[autobackup_interval_min is not None]
    autobackup_btn.hovercolor = hovercolors[autobackup_interval_min is not None]

    def sl_autobackup(ev):
        nonlocal autobackup_interval_min
        autobackup_slider_txt.set_text(f"Minimum age: {autobackup_sl.val} min")
        if autobackup_interval_min is not None:
            autobackup_interval_min = autobackup_sl.val
    autobackup_sl.on_changed(sl_autobackup)

    redraw()
    plt.show()

def entrypoint():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    main(get_parser().parse_args())

if __name__ == "__main__":
    entrypoint()
