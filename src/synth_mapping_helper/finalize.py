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
    parser.add_argument("--plot", action="store_true", help="Plot velocity and acceleration")
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
        if options.plot:
            for diff in DIFFICULTIES:
                notes_dict = beatmap["Track"][diff]
                if not notes_dict:
                    continue
                fig, axs = plt.subplots(4, 1, sharex=True, figsize=(16, 8))
                fig.suptitle(f"{beatmap['Author']} - {beatmap['Name']}: {diff}")
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

                ax_acc.set_xlabel("time (s)")
                ax_acc.xaxis.set_major_formatter(min_sec_formatter)
                # bookmarks
                for bookmark in beatmap["Bookmarks"]["BookmarksList"]:
                    time = int(bookmark["time"]) / 64 * 60 / beatmap["BPM"]
                    for ax in axs:
                        ax.axvline(time, color="grey")
                    ax_x.text(time, 0.99, bookmark["name"], ha='left', va='bottom', rotation=45, transform=ax_x.get_xaxis_transform())
                # notes & rails
                positions = [{} for _ in synth_format.NOTE_TYPES]
                for time in sorted(notes_dict):
                    note_list = notes_dict[time]
                    for note in note_list:
                        note_type, pos = synth_format.note_from_synth(beatmap["BPM"], 0, note)
                        color = NOTE_COLORS[synth_format.NOTE_TYPES[note_type]]
                        if pos.shape[0] != 1:
                            new_times = np.arange(pos[0,2], pos[-1,2], 1/64)
                            pos = interpolate_spline(pos, new_times)
                        pos[:, 2] *= 60 / beatmap["BPM"]  # convert beat to second
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
                # fig.savefig(f"{diff}.png")
        if not options.revert:
            beatmap["Bookmarks"]["BookmarksList"].append(FINALIZED_BOOKMARK)
        # write modified beatmap json
        outzip.writestr(inzip.getinfo(BEATMAP_JSON_FILE), json.dumps(beatmap))
    # write output zip
    options.output.write_bytes(out_buffer.getbuffer())

if __name__ == "__main__":
    main(get_parser().parse_args())