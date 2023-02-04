from argparse import ArgumentParser, RawDescriptionHelpFormatter
from io import BytesIO
import json
from json import JSONDecodeError
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter
from matplotlib.widgets import Button, CheckButtons, RadioButtons

from . import movement, synth_format, __version__
from .rails import interpolate_spline
from .synth_format import DataContainer, SynthFile

@FuncFormatter
def min_sec_formatter(x, _) -> str:
    f"{int(x//60):d}:{int(x%60):02d}{'.{:03d}'.format(int((x%1)*1000)) if x%1 else ''}"

NOTE_COLORS = {"right": "red", "left": "cyan", "single": "lime", "both": "gold"}

VELOCITY_WINDOW = 0.5  # half a second gap breaks up velocity / acceleration calculations
RENDER_WINDOW = 4  # 4 seconds of elements are rendered
WALL_DESPAWN_PC = 80  # limit of visible walls, earlier ones despawn
WALL_DESPAWN_QUEST = 40
QUEST_WALL_DELAY = 0.050  # 50 ms on highest wall density

def get_parser():
    parser = ArgumentParser(
        formatter_class=RawDescriptionHelpFormatter,
        prog=f"python3 -m {__package__}.{Path(__file__).stem}",
        description='\n'.join([
            "Also see the wiki on GitHub, which contains more detailed explainations, as well as some examples and images: https://github.com/adosikas/synth_mapping_helper/wiki",
        ]),
        epilog=f"Version: {__version__}",
    )
    parser.add_argument("input", type=Path, help="Input file")
    return parser

def abort(reason: str):
    print("ERROR: " + reason)
    exit(1)

def plot_bookmarks(bookmarks: dict[float, str], axs: "container of mpl axes"):
    for time, name in bookmarks.items():
        for ax in axs:
            ax.axvline(time, color="grey")
        axs[0].text(time, 0.99, name, ha='left', va='bottom', rotation=45, transform=axs[0].get_xaxis_transform())

def prepare_data(data: DataContainer) -> tuple[
    list[tuple[list["rails"], "positions", "velocity", "acceleration"]],
    list[tuple[
        tuple["pc_density", "pc_ok", "pc_despawn"],
        tuple["quest_density", "quest_ok", "quest_despawn", "quest_hidden"]
    ]],
]:
    # NOTES DATA
    velocity_window_beats = VELOCITY_WINDOW * (data.bpm / 60)  # [seconds] / [beats / second]
    note_out = []
    for t, note_type in enumerate(synth_format.NOTE_TYPES):
        rails: list["xyz"] = []
        pos_dict: dict[float, "xyz"] = {}
        notes_dict = getattr(data, note_type)
        if not notes_dict:
            # early abort when there are no notes
            out.append((np.zeros((0,3)), np.zeros((0,2)), np.zeros((0,2))))
            continue
        
        # first, dump all notes and interpolated rails into a dict, to get positions over time
        last_time = sorted(notes_dict)[0]
        for time in sorted(notes_dict):
            if time - last_time > velocity_window_beats:
                # insert nan to break up plotted lines
                pos_dict[(last_time+time)/2] = np.array((np.nan, np.nan, np.nan))
            pos = notes_dict[time]
            if pos.shape[0] == 1:
                # single note
                pos_dict[pos[0, 2]] = pos[0, :3]
            else:
                # interpolate at 1/64
                new_times = np.arange(pos[0,2], pos[-1,2] + 1/64, 1/64)
                new_times[-1] = pos[-1,2]  # ensure last position matches actual end of rail
                interp_pos = interpolate_spline(pos, new_times)
                rails.append(interp_pos)
                for p in interp_pos:
                    pos_dict[p[2]] = p[:3]
            last_time = time

        # convert dict to np array [time, xyz]
        pos = np.array([p for _, p in sorted(pos_dict.items())])
        pos_diff = np.diff(pos, axis=0)  # difference in position across time
        vel = pos_diff[:, :2] / pos_diff[:, 2:3]
        vel_diff = np.diff(pos_diff, axis=0)
        # acceleration at point b can be considered over have the previous and next time delta
        acc = vel_diff / ((pos_diff[1:, 2:3] + pos_diff[:-1, 2:3]) / 2)
        note_out.append((rails, pos, vel, acc))

    wall_out = []
    
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
    quest_wall_delay_beats = QUEST_WALL_DELAY * (data.bpm / 60)  # [seconds] / [beats / second] => [beats]

    for wall_type in synth_format.WALL_TYPES:
        pc_density: list[tuple[float, int]] = []
        quest_density: list[tuple[float, int]] = []

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
                if other_time > end:
                    break
                visible_count += 1
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
                if other_time > end:
                    break
                visible_count += 1
            quest_density.append((time, visible_count))
            if visible_count > WALL_DESPAWN_QUEST:
                quest_despawn.append(time)
            else:
                quest_ok.append(time)

        wall_out.append(((pc_density, pc_ok, pc_despawn), (quest_density, quest_ok, quest_despawn, quest_hidden)))
    return note_out, wall_out

def plot_notes(fig, infile: SynthFile, data: DataContainer, prepared_data, **kwargs):
    axs = fig.subplots(4)
    axs[-1].set_xlabel("beats")
    plot_bookmarks(infile.bookmarks, axs)

    ax_x, ax_y, ax_vel, ax_acc = axs
    ax_x.set_ylabel("X-Position (sq)")
    ax_x.set_ylim((-8,8))
    ax_x.set_yticks(range(-8,8+1), (str(t) if not t%2 else "" for t in range(-8,8+1)))
    ax_x.grid(True)

    ax_y.set_ylabel("Y-Position (sq)")
    ax_y.set_ylim((-6,6))
    ax_y.set_yticks(range(-6,6+1), (str(t) if not t%2 else "" for t in range(-6,6+1)))
    ax_y.grid(True)

    ax_vel.set_ylabel("Velocity (sq/s)")
    ax_vel.set_ylim((0,100))
    vel_mul = data.bpm / 60
    ax_acc.set_ylabel("Acceleration (sq/s²)")
    ax_acc.set_ylim((0,100))
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
        # velocity (n-1), plotted between two nodes
        ax_vel.plot((pos[1:, 2] + pos[:-1, 2])/2, [np.sqrt(v.dot(v)) * vel_mul for v in vel], color=color)
        # acceleration (n-2) plotted at nodes (skipping first and last position)
        ax_acc.plot(pos[1:-1, 2], [np.sqrt(a.dot(a)) * acc_mul for a in acc], color=color)

def plot_walls(fig, infile: SynthFile, data: DataContainer, prepared_data, platform: str):
    axs = fig.subplots(2)
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
        "wall_left": ("s", "left", 7),
        "wall_right": ("s", "right", 6),
        "angle_left": ("o", "left", 5),
        "angle_right":  ("o", "right", 4),
        "center": ("d", "full", 3),
        "crouch": ("s", "top", 2),
        "triangle": ("^", "none", 1),
        "square": ("s", "none", 0),
    }
    quest_wall_delay_beats = QUEST_WALL_DELAY * (data.bpm / 60)  # [seconds] / [beats / second] => [beats]

    for i, wall_type in enumerate(synth_format.WALL_TYPES):
        marker, fill, y = wall_markers[wall_type]
        if platform == "PC":
            # pc: ok first, despawn on top
            pc_density, pc_ok, pc_despawn = prepared_data[1][i][0]
            for walls, color in zip((pc_ok, pc_despawn), ("green", "orange")):
                for time in walls:
                    ax_status.plot([time], [y], marker=marker, fillstyle=fill, color=color)
            ax_density.plot([time for time, _ in pc_density], [count for _, count in pc_density], label=wall_type)
        else:
            # quest: ok first, then despawn, hidden on top
            quest_density, quest_ok, quest_despawn, quest_hidden = prepared_data[1][i][1]
            for walls, color in zip((quest_ok, quest_despawn, quest_hidden), ("green", "orange", "red")):
                for time in walls:
                    ax_status.plot([time], [y], marker=marker, fillstyle=fill, color=color)
            ax_density.plot([time for time, _ in quest_density], [count for _, count in quest_density], label=wall_type)


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

def show_warnings(fig, infile: SynthFile, data: DataContainer, prepared_data, platform: str):
    ax = fig.subplots(1)
    ax.set_axis_off()
    ax.table(loc="top", colWidths=(1/20, 19/20), cellLoc="left", rowLabels=["123 5/6"], cellText=[["note:left", "placeholder, ie extreme peak in acceleration"]])

TABS = [
    ("Notes", plot_notes),
    ("Walls", plot_walls),
    ("Warnings", show_warnings)
]
PLATFORMS = ("PC", "Quest")

def main(options):
    if not options.input.is_file():
        abort("Input file is not a file, is the path correct?")

    # load beatmap json
    data = synth_format.import_file(options.input)

    active_tab = 0
    active_difficulty = 0
    active_platform = 0
    difficulties = [(d, prepare_data(data.difficulties[d])) for d in synth_format.DIFFICULTIES if d in data.difficulties]

    fig = plt.figure(figsize=(16, 9), layout="constrained")
    fig.canvas.manager.set_window_title(f"SMH Companion - {data.meta['Author']} - {data.meta['Name']}")
    menu, tab = fig.subfigures(2, 1, height_ratios=(1,8))

    menu_axs = menu.subplots(1, 16)
    for ax in menu_axs:
        ax.set_axis_off()

    def replace_prepared_data():
        nonlocal difficulties
        difficulties = [(d, prepare_data(data.difficulties[d])) for d in synth_format.DIFFICULTIES if d in data.difficulties]

    def redraw():
        tab.clear()
        _, tab_func = TABS[active_tab]
        diff_name, prepared_data = difficulties[active_difficulty]
        tab_func(tab, data, data.difficulties[diff_name], prepared_data, platform=PLATFORMS[active_platform])
        plt.draw()

    def btn_reload(active: bool) -> None:
        data.reload()
        replace_prepared_data()
        print(f"Reloaded {data.input_file.absolute()}")
        redraw()
    
    def btn_autoreload(active:bool) -> None:
        print("WIP")

    def btn_finalize(active: bool) -> None:
        if active and (data.bookmarks.get(0.0) != "#smh_finalized"):
            data.bookmarks[0.0] = "#smh_finalized"
            for _, diff_data in data.difficulties.items():
                diff_data.apply_for_walls(movement.offset, offset_3d=(0,2.1,0), types=synth_format.SLIDE_TYPES)
            print("Finalized map")
        elif not active and (data.bookmarks.get(0.0) == "#smh_finalized"):
            del data.bookmarks[0.0]
            for _, diff_data in data.difficulties.items():
                diff_data.apply_for_walls(movement.offset, offset_3d=(0,-2.1,0), types=synth_format.SLIDE_TYPES)
            print("Reversed finalization")

    def btn_save_output(active: bool) -> None:
            out = Path("output.synth")
            data.save_as(out)
            print(f"Saved to {out.absolute()}")
    
    btns = (
        ("Reload", None, btn_reload),
        ("Auto-Reload", True, btn_autoreload),
        ("Finalize", data.bookmarks.get(0.0) == "#smh_finalized", btn_finalize),
        ("Save Output", None, btn_save_output),
    )
    button_cb = CheckButtons(menu_axs[0], [t for t, *_ in btns])
    for i, (_, start_checked, _) in enumerate(btns):
        button_cb.labels[i].set_bbox({"facecolor": "lightgrey", "boxstyle": "Round"})
        if start_checked is None:  # hide actual checkbox
            button_cb.rectangles[i].set(visible=False)
        elif start_checked:
            button_cb.set_active(i)

    def button_clicked(button: str):
        for btn_id, (name, start_checked, btn_func) in enumerate(btns):
            if name == button:
                active = button_cb.get_status()[btn_id]
                if start_checked is None:
                    if active:
                        # instantly uncheck non-checkboxes
                        button_cb.set_active(btn_id)
                    else:
                        # ignore "unpress"
                        return
                btn_func(active)
                return

    button_cb.on_clicked(button_clicked)

    tab_rb = RadioButtons(menu_axs[1], [n for n, *_ in TABS], active_tab)
    def tab_clicked(selected: str):
        nonlocal active_tab
        for tab_id, (name, *_) in enumerate(TABS):
            if name == selected and tab_id != active_tab:
                active_tab = tab_id
                redraw()
                break
    tab_rb.on_clicked(tab_clicked)

    diff_rb = RadioButtons(menu_axs[2], [d for d, *_ in difficulties], active_difficulty)
    def diff_clicked(selected: str):
        nonlocal active_difficulty
        for diff_id, name in enumerate(difficulties):
            if name == selected and diff_id != active_difficulty:
                active_difficulty = diff_id
                redraw()
                break
    diff_rb.on_clicked(diff_clicked)

    platform_rb = RadioButtons(menu_axs[3], PLATFORMS, active_difficulty)
    def platform_clicked(selected: str):
        nonlocal active_platform
        for platform_id, name in enumerate(PLATFORMS):
            if name == selected and platform_id != active_platform:
                active_platform = platform_id
                redraw()
                break
    platform_rb.on_clicked(platform_clicked)

    redraw()
    plt.show()

if __name__ == "__main__":
    main(get_parser().parse_args())