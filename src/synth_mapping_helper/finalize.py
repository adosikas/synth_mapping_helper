from argparse import ArgumentParser, RawDescriptionHelpFormatter
from io import BytesIO
import json
from json import JSONDecodeError
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as md
from matplotlib.ticker import FuncFormatter

from . import synth_format, __version__
from .rails import interpolate_spline


min_sec_formatter = FuncFormatter(lambda x,_: f"{int(x//60):d}:{int(x%60):02d}{'.{:03d}'.format(int((x%1)*1000)) if x%1 else ''}")

FINALIZED_BOOKMARK = {"time": 0.0, "name": "#smh_finalized"}
BEATMAP_JSON_FILE = "beatmap.meta.bin"
DIFFICULTIES = ("Easy", "Normal", "Hard", "Expert", "Master", "Custom")
NOTE_COLORS = {"right": "red", "left": "cyan", "single": "lime", "both": "gold"}

RENDER_WINDOW = 4  # 4 seconds of elements are rendered
WALL_DESPAWN_PC = 80  # limit of visible walls, earlier ones despawn
WALL_DESPAWN_QUEST = 40

def get_parser():
    parser = ArgumentParser(
        formatter_class=RawDescriptionHelpFormatter,
        prog=f"python3 -m {__package__}.{Path(__file__).stem}",
        description='\n'.join([
            "Finalizes a map:"
            "  * Move certain walls up so they appear ingame as they do in the editor"
            "",
            "Also see the wiki on GitHub, which contains more detailed explainations, as well as some examples and images: https://github.com/adosikas/synth_mapping_helper/wiki",
        ]),
        epilog=f"Version: {__version__}",
    )
    parser.add_argument("input", type=Path, help="Input file")
    parser.add_argument("output", type=Path, help="Output file")
    parser.add_argument("--revert", action="store_true", help="Reverse finalizing options")
    parser.add_argument("--plot-notes", action="store_true", help="Plot note velocity and acceleration")
    parser.add_argument("--plot-walls", action="store_true", help="Plot walls for pc and quest")
    return parser

def abort(reason: str):
    print("ERROR: " + reason)
    exit(1)

def main(options):
    if not options.input.is_file():
        abort("Input file is not a file, is the path correct?")
    out_buffer = BytesIO()  # buffer output zip file in memory, only write on success
    with ZipFile(options.input) as inzip, ZipFile(out_buffer, "w") as outzip:
        # copy all content except beatmap json
        outzip.comment = inzip.comment
        for info in inzip.infolist():
            if info.filename != BEATMAP_JSON_FILE:
                outzip.writestr(info, inzip.read(info.filename))
        # load beatmap json
        beatmap = json.loads(inzip.read(BEATMAP_JSON_FILE))
        bpm = beatmap["BPM"]
        finalized = FINALIZED_BOOKMARK in beatmap["Bookmarks"]["BookmarksList"]
        if not options.revert:
            if finalized:
                abort("Already finalized!")
        else:
            if not finalized:
                abort("Not finalized, will not revert!")
            beatmap["Bookmarks"]["BookmarksList"].remove(FINALIZED_BOOKMARK)
            
        # shift slides up so they appear ingame as they do in the editor
        for _, walls in beatmap["Slides"].items():
            for w in walls:
                if options.revert: 
                    w["position"][1] -= 2.1 * synth_format.GRID_SCALE
                else:
                    w["position"][1] += 2.1 * synth_format.GRID_SCALE

        for diff in DIFFICULTIES:
            # skip difficulties without notes
            if not beatmap["Track"][diff]:
                continue
            if options.plot_notes:
                fig, axs = plt.subplots(4, 1, sharex=True, figsize=(16, 8))
                fig.suptitle(f"{beatmap['Author']} - {beatmap['Name']}: {diff} / Notes")
                (ax_x, ax_y, ax_vel, ax_acc) = axs
                ax_x.set_ylabel("X-Position (sq)")
                ax_x.set_ylim((8, -8))
                ax_x.grid(True)
                ax_y.set_ylabel("Y-Position (sq)")
                ax_y.set_ylim((-6, 6))
                ax_y.grid(True)

                ax_vel.set_ylabel("Velocity (sq/s)")
                ax_vel.set_ylim((0, 50))
                ax_acc.set_ylabel("Acceleration (sq/s²)")
                ax_acc.set_ylim((0, 50))

                axs[-1].set_xlabel("time (s)")
                axs[-1].xaxis.set_major_formatter(min_sec_formatter)
                # bookmarks
                for bookmark in beatmap["Bookmarks"]["BookmarksList"]:
                    time = int(bookmark["time"]) / 64 * 60 / bpm
                    for ax in axs:
                        ax.axvline(time, color="grey")
                    axs[0].text(time, 0.99, bookmark["name"], ha='left', va='bottom', rotation=45, transform=axs[0].get_xaxis_transform())
                
                # notes & rails
                positions = [{} for _ in synth_format.NOTE_TYPES]
                notes_dict = beatmap["Track"][diff]

                for time in sorted(notes_dict):
                    note_list = notes_dict[time]
                    for note in note_list:
                        note_type, pos = synth_format.note_from_synth(bpm, 0, note)
                        color = NOTE_COLORS[synth_format.NOTE_TYPES[note_type]]
                        if pos.shape[0] != 1:
                            new_times = np.arange(pos[0,2], pos[-1,2], 1/64)
                            pos = interpolate_spline(pos, new_times)
                        pos[:, 2] *= 60 / bpm  # convert beat to second
                        for p in pos:
                            positions[note_type][p[2]] = p[:2]

                        # single note / rail head
                        ax_x.plot(pos[0, 2], pos[0, 0], color=color, marker="o")
                        ax_y.plot(pos[0, 2], pos[0, 1], color=color, marker="o")
                        if pos.shape[0] != 1:
                            # rail
                            ax_x.plot(pos[:, 2], pos[:, 0], color=color, marker="")
                            ax_y.plot(pos[:, 2], pos[:, 1], color=color, marker="")

                for note_type, poss in enumerate(positions):
                    if len(poss) <= 1:
                        continue
                    times = sorted(poss)
                    prev_t = times[0]
                    vels = []
                    accs = []
                    for t in times[1:]:
                        if t - prev_t < 1:
                            vel = (poss[t] - poss[prev_t])/(t-prev_t)
                            if vels and vels[-1][1] is not None:
                                accs.append((prev_t, vel - vels[-1][1]))
                            else:
                                accs.append((prev_t, None))
                            vels.append(((t+prev_t)/2, vel))
                        else:
                            vels.append(((t+prev_t)/2, None))
                        prev_t = t
                    ax_vel.plot([t for t, _ in vels], [np.sqrt(v.dot(v)) if v is not None else np.nan for _, v in vels], color=NOTE_COLORS[synth_format.NOTE_TYPES[note_type]])
                    ax_acc.plot([t for t, _ in accs], [np.sqrt(a.dot(a)) if a is not None else np.nan for _, a in accs], color=NOTE_COLORS[synth_format.NOTE_TYPES[note_type]])

                fig.tight_layout()
                plt.show()
                # fig.savefig(f"{diff}_notes.png")

            if options.plot_walls:
                fig, axs = plt.subplots(3, 1, sharex=True, figsize=(16, 8))
                fig.suptitle(f"{beatmap['Author']} - {beatmap['Name']}: {diff} / Walls")
                (ax_density, ax_pc, ax_quest) = axs
                ax_density.set_ylabel("Walls visible")
                ax_density.set_ylim([0, 100])
                ax_pc.set_ylabel("Walls Status (PC)")
                ax_pc.set_yticks([])
                ax_quest.set_ylabel("Wall Status (Quest)")
                ax_quest.set_yticks([])

                axs[-1].set_xlabel("time (s)")
                axs[-1].xaxis.set_major_formatter(min_sec_formatter)
                # bookmarks
                for bookmark in beatmap["Bookmarks"]["BookmarksList"]:
                    time = int(bookmark["time"]) / 64 * 60 / bpm
                    for ax in axs:
                        ax.axvline(time, color="grey")
                    axs[0].text(time, 0.99, bookmark["name"], ha='left', va='bottom', rotation=45, transform=axs[0].get_xaxis_transform())

                ax_density.axhline(40, color="lightblue")
                ax_density.axhline(80, color="grey")

                # walls
                walls: dict[str, list[float]] = {w_type: [] for w_type in synth_format.WALL_TYPES}
                for slide in beatmap["Slides"][diff]:
                    walls[synth_format.WALL_LOOKUP[slide["slideType"]]].append(slide["time"] / 64 * 60 / bpm)
                walls["crouch"] = [w["time"] / 64 * 60 / bpm for w in beatmap["Crouchs"][diff]]
                walls["square"] = [w["time"] / 64 * 60 / bpm for w in beatmap["Squares"][diff]]
                walls["triangle"] = [w["time"] / 64 * 60 / bpm for w in beatmap["Triangles"][diff]]

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

                walls_all: list[tuple[float, str]] = sorted({time: wall_type for wall_type in wall_markers for time in walls[wall_type]}.items())
                visible: dict[float, int] = {}
                for i, (time, _) in enumerate(walls_all):
                    end = time + RENDER_WINDOW
                    count = 1
                    for other_time, _ in walls_all[i+1:]:
                        if other_time > end:
                            break
                        count += 1
                    visible[time] = count

                sorted_visible = sorted(visible.items())
                ax_density.plot([time for time, _ in sorted_visible], [count for _, count in sorted_visible])


                quest_ok: dict[float, str] = {}
                quest_hidden: dict[float, str] = {}

                seconds_per_tick = 60 / (64 * bpm)  # [seconds / minute] / ([ticks / beat] * [beats / minute])
                quest_wall_delay = np.ceil(0.05 / seconds_per_tick) * seconds_per_tick

                for wall_type in wall_markers:
                    last_time = None
                    for time in sorted(walls[wall_type]):
                        hidden_on_quest = last_time is not None and time - last_time < quest_wall_delay
                        if hidden_on_quest:
                            quest_hidden[time] = wall_type
                        else:
                            last_time = time
                            quest_ok[time] = wall_type

                # pc
                for time, wall_type in walls_all:
                    marker, fill, y = wall_markers[wall_type]
                    ax_pc.plot([time], [y], marker=marker, fillstyle=fill, color="green" if visible[time] < WALL_DESPAWN_PC else "orange")
    
                # quest: draw ok ones first
                for time, wall_type in sorted(quest_ok.items()):
                    marker, fill, y = wall_markers[wall_type]
                    ax_quest.plot([time], [y], marker=marker, fillstyle=fill, color="green" if visible[time] < WALL_DESPAWN_QUEST else "orange")
                # quest: draw hidden ones "on top"
                for time, wall_type in sorted(quest_hidden.items()):
                    marker, fill, y = wall_markers[wall_type]
                    ax_quest.plot([time], [y], marker=marker, fillstyle=fill, color="red")

                fig.tight_layout()
                plt.show()
                # fig.savefig(f"{diff}_walls.png")

        if not options.revert:
            beatmap["Bookmarks"]["BookmarksList"].append(FINALIZED_BOOKMARK)
        # write modified beatmap json
        outzip.writestr(inzip.getinfo(BEATMAP_JSON_FILE), json.dumps(beatmap))
    # write output zip
    options.output.write_bytes(out_buffer.getbuffer())

if __name__ == "__main__":
    main(get_parser().parse_args())