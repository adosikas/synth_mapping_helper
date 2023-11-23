import dataclasses
from typing import Optional
import sys

import plotly.graph_objects as go
from nicegui import app, events, ui

from .utils import *
from .. import synth_format, movement
from .. import __version__

def density(times: list[float], window: float) -> tuple[list[float], list[int]]:
    out = []
    visible_t = []
    c = 0
    for t in sorted(times):
        start = t - window
        while c and visible_t[0] < start:
            out.append((visible_t[0], c))
            out.append((visible_t[0], c-1))
            visible_t = visible_t[1:]
            c -= 1
        out.append((start, c))
        out.append((start, c+1))
        visible_t.append(t)
        c += 1
    while visible_t:
        out.append((visible_t[0], c))
        out.append((visible_t[0], c-1))
        visible_t = visible_t[1:]
        c -= 1

    return [x for x,_ in out], [y for _,y in out]

def wall_mode(highest_density: int) -> str:
    if highest_density < 200:
        return f"OK, max {highest_density}"
    if highest_density < 500:
        return f"Wireframe, max {highest_density}"
    return f"Limited, max {highest_density}"

def file_utils_tab():
    @dataclasses.dataclass
    class FileInfo:
        data: Optional[synth_format.SynthFile] = None
        output_filename: str = "No file selected"
        output_bpm: float = 0.0
        output_offset: float = 0.0
        output_finalize: bool = False
        merged_filenames: Optional[list[str]] = None

        @property
        def is_valid(self) -> bool:
            return self.data is not None

        def upload(self, e: events.UploadEventArguments) -> None:
            self.clear()
            self.data = try_load_synth_file(e)
            if self.data is None:
                self.info_card.refresh()
                return
            self.output_filename = add_suffix(e.name, "out")
            self.output_bpm = self.data.bpm
            self.output_offset = self.data.offset_ms
            self.output_finalize = (self.data.bookmarks.get(0) == "#smh_finalized")
            self.merged_filenames = []

            e.sender.reset()
            self.info_card.refresh()

        def upload_merge(self, e: events.UploadEventArguments) -> None:
            merge = try_load_synth_file(e)
            if merge is None:
                return
            self.data.merge(merge)
            self.merged_filenames.append(e.name)
        
            e.sender.reset()
            self.info_card.refresh()

        def clear(self) -> None:
            self.data = None
            self.output_filename = "No base file selected"
            self.output_bpm = 0.0
            self.output_offset = 0.0
            self.merged_filenames = None
            self.info_card.refresh()

        def save(self) -> None:
            download_content.truncate()
            if self.output_bpm != self.data.bpm:
                self.data.change_bpm(self.output_bpm)
            if self.output_offset != self.data.offset_ms:
                self.data.change_offset(self.output_offset)
            finalized = (self.data.bookmarks.get(0.0) == "#smh_finalized")
            if finalized != self.output_finalize:
                if not finalized:
                    self.data.bookmarks[0.0] = "#smh_finalized"
                    for _, diff_data in self.data.difficulties.items():
                        diff_data.apply_for_walls(movement.offset, offset_3d=(0,-2.1,0), types=synth_format.SLIDE_TYPES)
                else:
                    del self.data.bookmarks[0.0]
                    for _, diff_data in self.data.difficulties.items():
                        diff_data.apply_for_walls(movement.offset, offset_3d=(0,2.1,0), types=synth_format.SLIDE_TYPES)

            self.data.save_as(download_content)
            ui.download("download", filename=self.output_filename)

        def save_errors(self):
            out = [
                "SMH-GUI fixed error report:",
                f"  SMH Version: {__version__}",
                f"  Base BPM: {self.data.bpm}",
                f"  Base Offset: {self.data.output_offset}",
                f"  Merged {len(self.merged_filenames)} other files",
            ]
            for diff, errors in self.data.errors.items():
                for jpe, time in errors:
                    out.append(f"{diff}@{time}: {jpe!r}")
            download_content.truncate()
            download_content.write('\n'.join(out).encode())
            ui.download("download", filename="smh_error_report.txt")
            info("Saved error log")

        @ui.refreshable
        def info_card(self) -> None:
            if self.data is None:
                ui.label("Load a map to show stats and graphs")
                return
            ui.label(f"{len(self.data.bookmarks)} Bookmarks")
            if self.merged_filenames:
                ui.label("Merged:")
                for m in self.merged_filenames:
                    ui.label(m)
            if self.data.errors:
                with ui.button("Save error report", icon="summarize", color="warning", on_click=self.save_errors).classes("ml-auto"):
                    ui.tooltip("Use this if you want to re-add notes that were corrupted.")

            ui.label("Object counts (click to see more)")
            def _stats_notify(ev: events.GenericEventArguments) -> None:
                if "." in ev.args["colId"]:
                    col = ev.args["colId"].rsplit(".",1)[0]
                    col_data = ev.args["data"][col]
                    ui.notify(
                        f"{col_data['total']} {col}: " + ", ".join(f"{k}: {v}" for k,v in col_data.items() if k != "total"),
                        position="center",
                        type="info"
                    )
            ui.aggrid({
                "domLayout": "autoHeight",
                "columnDefs": [
                    {"headerName": "Difficulty", "field": "diff"},
                    {"headerName": "Fixed Errors", "field": "errors"},
                    {"headerName": "Notes", "field": "notes.total"},
                    {"headerName": "Rails", "field": "rails.total"},
                    {"headerName": "Rail nodes", "field": "rail_nodes.total"},
                    {"headerName": "Walls", "field": "walls.total"},
                    {"headerName": "Lights", "field": "lights"},
                    {"headerName": "Effects", "field": "effects"},
                ],
                "rowData": [
                    c.get_counts() | {"diff": d, "errors": len(self.data.errors.get(d, []))} 
                    for d, c in self.data.difficulties.items()
                ],
            }).classes("w-full h-auto").on("cellClicked", _stats_notify)

            ui.label("Wall density")
            wall_densities = {
                d: density(self.data.difficulties[d].walls.keys(), 4*self.data.bpm/60)
                for d in self.data.difficulties
            }
            wfig = go.Figure(
                [
                    go.Scatter(x=x, y=y, name=f"{d} [{wall_mode(max(y))}]", showlegend=True)
                    for d, (x, y) in wall_densities.items()
                    if y
                ],
                layout=go.Layout(
                    xaxis=go.layout.XAxis(title="Measure"),
                    yaxis=go.layout.YAxis(title="Visible Walls (4s)"),
                    legend=go.layout.Legend(x=0, xanchor="left", y=1, yanchor="bottom", orientation="h"),
                    margin=go.layout.Margin(l=0, r=0, t=0, b=0),
                ),
            )
            # show horizontal lines when close to or over the limit
            max_d = max(max(y) if y else 0 for _,y in wall_densities.values() )
            if max_d >= 180:
                wfig.add_hline(200, line={"color": "gray"}, annotation=go.layout.Annotation(text="Wireframe", xanchor="left", yanchor="bottom"), annotation_position="left")
            if max_d >= 450:
                wfig.add_hline(500, line={"color": "red"}, annotation=go.layout.Annotation(text="Spawn limit", xanchor="left", yanchor="bottom"), annotation_position="left")
            ui.plotly(wfig).classes("w-full h-96")

            # same thing, but for combined notes and rail nodes
            ui.label("Note & Rail density")
            note_densities = {
                d: (
                    # notes & all rail nodes
                    density([
                        n[2]
                        for ty in synth_format.NOTE_TYPES  # all types
                        for ns in getattr(c, ty).values()  # all nodes & rails
                        for n in ns # all rail nodes
                    ], window=4*self.data.bpm/60),
                    # notes & rail starts (aka orbs)
                    density([
                        ti
                        for ty in synth_format.NOTE_TYPES  # all types
                        for ti in getattr(c, ty)  # all nodes & rails
                    ], window=4*self.data.bpm/60),
                    # just rail nodes
                    density([
                        n[2]
                        for ty in synth_format.NOTE_TYPES  # all types
                        for ns in getattr(c, ty).values()  # all nodes & rails
                        for n in ns[1:] # just rail nodes
                    ], window=4*self.data.bpm/60),
                )
                for d, c in self.data.difficulties.items()
            }
            nfig = go.Figure(
                [
                    go.Scatter(
                        x=x, y=y, name=f"{d} ({l}) [max {max(y)}]",
                        showlegend=True,
                        visible=(l == "Combined") or "legendonly", # start with only "Combined" visible
                    )
                    for d, con in note_densities.items()
                    for l, (x,y) in zip(("Combined", "Notes & Rail Heads", "Rail Nodes"), con)
                    if y
                ],
                layout=go.Layout(
                    xaxis=go.layout.XAxis(title="Measure"),
                    yaxis=go.layout.YAxis(title="Visible (4s)"),
                    legend=go.layout.Legend(x=0, xanchor="left", y=1, yanchor="bottom", orientation="h"),
                    margin=go.layout.Margin(l=0, r=0, t=0, b=0),
                ),
            )
            ui.plotly(nfig).classes("w-full h-96")

    fi = FileInfo()

    with ui.card().classes("mb-4"):
        ui.label("Here you can work with .synth files directly. This can also fix some kinds of corrupted data.")
        ui.label("Tip: You can drag and drop files on the boxes below, including from the file selector.")
    
    with ui.row().classes("mb-4"):
        with ui.card():
            ui.label("Base / Repair / BPM change")
            ui.upload(label="Base file", auto_upload=True, on_upload=fi.upload).classes("h-14 w-full")
            ui.input("Filename").classes("w-full").bind_value(fi, "output_filename").bind_enabled_from(fi, "is_valid")
            with ui.row().classes("w-full"):
                ui.number("BPM").classes("w-16").bind_value(fi, "output_bpm").bind_enabled_from(fi, "is_valid")
                ui.number("Offset", suffix="ms").classes("w-24").bind_value(fi, "output_offset").bind_enabled_from(fi, "is_valid")
                with ui.switch("Finalize Walls").props("dense").classes("my-auto").bind_value(fi, "output_finalize").bind_enabled_from(fi, "is_valid"):
                    ui.tooltip("Shifts some walls down, such that they look ingame as they do in the editor")
                ui.tooltip("Select a base file first").bind_visibility_from(fi, "is_valid", backward=lambda v: not v).classes("bg-red")
            with ui.row().classes("w-full"):
                ui.button("clear", icon="clear", color="negative", on_click=fi.clear).bind_enabled_from(fi, "is_valid")
                ui.button("save", icon="save", color="positive", on_click=fi.save).bind_enabled_from(fi, "is_valid").classes("ml-auto")
                ui.tooltip("Select a base file first").bind_visibility_from(fi, "is_valid", backward=lambda v: not v).classes("bg-red")
        with ui.card():
            ui.label("Merge files into base")
            ui.upload(label="One or more files", multiple=True, auto_upload=True, on_upload=fi.upload_merge).classes("h-14 w-full").bind_enabled_from(fi, "is_valid")
            ui.label("Note: BPM & Offset will be matched automatically.")
            ui.tooltip("Select a base file first").bind_visibility_from(fi, "is_valid", backward=lambda v: not v).classes("bg-red")
    with ui.card().classes("w-full"):
        fi.info_card()