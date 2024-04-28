from io import BytesIO
import dataclasses
from typing import Optional
import sys

import plotly.graph_objects as go
from nicegui import app, events, ui

from .utils import *
from ..utils import pretty_list
from .. import synth_format, movement, analysis, __version__
    

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
            self.data.merge(merge, merge_bookmarks=merge_bookmarks.value)
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

            data = BytesIO()
            self.data.save_as(data)
            ui.download(data.getvalue(), filename=self.output_filename)

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

            ui.download('\n'.join(out).encode(), filename="smh_error_report.txt")
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
                with ui.button("Save error report", icon="summarize", color="warning", on_click=self.save_errors):
                    ui.tooltip("Use this if you want to re-add notes that were corrupted.")

            ui.label("Object counts (click to see more)")
            def _stats_notify(ev: events.GenericEventArguments) -> None:
                if "." in ev.args["colId"]:
                    col = ev.args["colId"].rsplit(".",1)[0]
                    col_data = ev.args["data"][col]
                    ui.notify(
                        f"{col_data['total']} {col}: " + pretty_list([f"{v} {k}" for k,v in col_data.items() if k != "total"]),
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
            wfig = go.Figure(
                layout=go.Layout(
                    xaxis=go.layout.XAxis(title="Measure"),
                    yaxis=go.layout.YAxis(title="Visible Walls (4s)"),
                    legend=go.layout.Legend(x=-0.05, xanchor="right", y=1, yanchor="top", orientation="v", groupclick="toggleitem"),
                    margin=go.layout.Margin(l=0, r=0, t=0, b=0),
                ),
            )
            for t, b in self.data.bookmarks.items():
                wfig.add_vline(t, line={"color": "lightgray"}, annotation=go.layout.Annotation(text="[]", font=dict(color="gray"), hovertext=b, xanchor="center", yanchor="bottom"), annotation_position="bottom")
            
            # difficulty->wall_type
            wall_densities: dict[str, dict[str, analysis.PlotDataContainer]] = {
                d: analysis.wall_densities(c)
                for d, c in self.data.difficulties.items()
            }
            # show horizontal lines when combined y is close to or over the limit
            max_com_d = max(den_dict["combined"].max_value for den_dict in wall_densities.values())
            if max_com_d > 0.9 * analysis.QUEST_WIREFRAME_LIMIT:
                wfig.add_hline(analysis.QUEST_WIREFRAME_LIMIT, line={"color": "gray"}, annotation=go.layout.Annotation(text="Quest wireframe (combined)", xanchor="left", yanchor="bottom"), annotation_position="left")
            if max_com_d > 0.9 * analysis.QUEST_RENDER_LIMIT:
                wfig.add_hline(analysis.QUEST_RENDER_LIMIT, line={"color": "red"}, annotation=go.layout.Annotation(text="Quest limit (combined)", xanchor="left", yanchor="bottom"), annotation_position="left")
            # show horizontal lines when single y is over the limit
            max_single_d = max(max(pdc.max_value for wt, pdc in den_dict.items() if wt != "combined") for den_dict in wall_densities.values())
            if max_single_d > 0.95 * analysis.PC_TYPE_DESPAWN:
                wfig.add_hline(analysis.PC_TYPE_DESPAWN, line={"color": "yellow"}, annotation=go.layout.Annotation(text="PC despawn (per type)", xanchor="left", yanchor="bottom"), annotation_position="left")

            for d, den_dict in wall_densities.items():
                for wt in ("combined", *synth_format.WALL_TYPES):
                    pdc = den_dict[wt]
                    if pdc.max_value:
                        wfig.add_scatter(
                            x=pdc.plot_times, y=pdc.plot_values, name=f"{d} ({wt}) [{analysis.wall_mode(pdc.max_value, combined=(wt == 'combined'))}]",
                            showlegend=True,
                            legendgroup=d,
                            # start with only combined visible and single only when above PC limit
                            visible=(wt == "combined" or pdc.max_value > 0.95 * analysis.PC_TYPE_DESPAWN) or "legendonly"
                        )
            ui.plotly(wfig).classes("w-full h-96")

            # mostly the same thing, but for combined notes and rail nodes
            ui.label("Note & Rail density")
            nfig = go.Figure(
                layout=go.Layout(
                    xaxis=go.layout.XAxis(title="Measure"),
                    yaxis=go.layout.YAxis(title="Visible (4s)"),
                    legend=go.layout.Legend(x=-0.05, xanchor="right", y=1, yanchor="top", orientation="v", groupclick="toggleitem"),
                    margin=go.layout.Margin(l=0, r=0, t=0, b=0),
                ),
            )
            for t, b in self.data.bookmarks.items():
                nfig.add_vline(t, line={"color": "lightgray"}, annotation=go.layout.Annotation(text="[]", font=dict(color="gray"), hovertext=b, xanchor="center", yanchor="bottom"), annotation_position="bottom")

            for d, c in self.data.difficulties.items():
                den_dict = analysis.note_densities(c)
                for nt in ("combined", *synth_format.NOTE_TYPES):
                    den_subdict = den_dict[nt]
                    for sub_t, pdc in den_subdict.items():
                        if pdc.max_value:
                            nfig.add_scatter(
                                x=pdc.plot_times, y=pdc.plot_values, name=f"{d} ({nt} {sub_t}s) [max {pdc.max_value}]",
                                showlegend=True,
                                legendgroup=f"{d} {nt}",
                                # start with only combined note visible
                                visible=(nt == "combined" and sub_t == "note") or "legendonly",
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
            merge_bookmarks = ui.switch("Merge Bookmarks", value=True).classes("w-full").bind_value(app.storage.user, "merge_bookmarks").bind_enabled_from(fi, "is_valid").tooltip("Disable this if you merge maps that contain the same bookmarks")
            ui.upload(label="One or more files", multiple=True, auto_upload=True, on_upload=fi.upload_merge).props('color="positive"').classes("h-14 w-full").bind_enabled_from(fi, "is_valid")
            ui.label("Note: BPM & Offset will be matched automatically.")
            ui.tooltip("Select a base file first").bind_visibility_from(fi, "is_valid", backward=lambda v: not v).classes("bg-red")
    with ui.card().classes("w-full"):
        fi.info_card()
