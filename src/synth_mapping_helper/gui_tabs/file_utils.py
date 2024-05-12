import base64
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

        def clear(self) -> None:
            self.data = None
            self.output_filename = "No base file selected"
            self.output_bpm = 0.0
            self.output_offset = 0.0
            self.merged_filenames = None
            self.refresh()

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
            self.refresh()

        def upload_merge(self, e: events.UploadEventArguments) -> None:
            merge = try_load_synth_file(e)
            if merge is None:
                return
            if merge.audio.raw_data != self.data.audio.raw_data:
                ui.notify("Difference in audio files detected. Merge may yield weird results.", type="warning")
            self.data.merge(merge, merge_bookmarks=merge_bookmarks.value)
            self.merged_filenames.append(e.name)
        
            e.sender.reset()
            self.refresh()

        def upload_cover(self, e: events.UploadEventArguments) -> None:
            if not e.name.lower().endswith(".png"):
                error("Cover image must be .png")
                return
            self.data.meta.cover_data = e.content.read()
            self.data.meta.cover_name = e.name
            ui.notify(f"Changed cover image to {e.name}", type="info")
            self.refresh()

        def upload_audio(self, e: events.UploadEventArguments) -> None:
            if not e.name.lower().endswith(".ogg"):
                error("Audio file must be .ogg")
                return
            try:
                new_audio = synth_format.AudioData.from_raw(e.content.read())
            except ValueError as ve:
                error("Audio file rejected", exc=ve, data=e.name)
            else:
                self.data.audio = new_audio
                self.data.meta.audio_name = e.name
                ui.notify(f"Changed audio to {e.name}", type="info")
                self.refresh()

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
                f"  Base Offset: {self.data.offset_ms}",
                f"  Merged {len(self.merged_filenames)} other files",
            ]
            for diff, errors in self.data.errors.items():
                for jpe, time in errors:
                    out.append(f"{diff}@{time}: {jpe!r}")

            ui.download('\n'.join(out).encode(), filename="smh_error_report.txt")
            info("Saved error log")

        def refresh(self) -> None:
            self.info_card.refresh()
            self.stats_card.refresh()

        @ui.refreshable
        def info_card(self):
            if self.data is None:
                ui.label("Load a map to show info")
                return
            ui.markdown("**Edit metadata**")
            meta = self.data.meta
            with ui.row():
                with ui.column().classes("p-0 gap-0"):
                    with ui.upload(label="Replace Cover", auto_upload=True, on_upload=self.upload_cover).classes("w-32").props('accept="image/png"').add_slot("list"):
                        ui.image("data:image/png;base64,"+base64.b64encode(meta.cover_data).decode()).classes("w-32 h-32").tooltip(meta.cover_name)
                with ui.column():
                    ui.input("Name").props("dense").classes("h-8").bind_value(meta, "name")
                    ui.input("Artist").props("dense").classes("h-8").bind_value(meta, "artist")
                    ui.input("Mapper").props("dense").classes("h-8").bind_value(meta, "mapper")
                    ui.checkbox("Explicit lyrics").classes("h-8").props("dense").bind_value(meta, "explicit")
            with ui.row():
                ui.upload(label="Replace Audio", auto_upload=True, on_upload=self.upload_audio).props('accept="audio/ogg,*/*"').classes("w-32")
                ui.number("BPM").props("dense").classes("w-16").bind_value(self, "output_bpm")
                ui.number("Offset", suffix="ms").props("dense").classes("w-20").bind_value(self, "output_offset")
            ui.audio("data:audio/ogg;base64,"+base64.b64encode(self.data.audio.raw_data).decode())

        @ui.refreshable
        def stats_card(self) -> None:
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
                wfig.add_vline(t, line={"color": "lightgray", "dash": "dash"}, annotation=go.layout.Annotation(text="[]", font=dict(color="gray"), hovertext=b, xanchor="center", yanchor="bottom"), annotation_position="bottom")
            
            # difficulty->wall_type
            wall_densities: dict[str, dict[str, analysis.PlotDataContainer]] = {
                d: analysis.wall_densities(c)
                for d, c in self.data.difficulties.items()
            }
            # show horizontal lines when combined y is close to or over the limit
            max_com_d = max(den_dict["combined"].max_value for den_dict in wall_densities.values()) if wall_densities else 0
            if max_com_d > 0.9 * analysis.QUEST_WIREFRAME_LIMIT:
                wfig.add_hline(analysis.QUEST_WIREFRAME_LIMIT, line={"color": "gray", "dash": "dash"}, annotation=go.layout.Annotation(text="Quest wireframe (combined)", xanchor="left", yanchor="bottom"), annotation_position="left")
            if max_com_d > 0.9 * analysis.QUEST_RENDER_LIMIT:
                wfig.add_hline(analysis.QUEST_RENDER_LIMIT, line={"color": "red", "dash": "dash"}, annotation=go.layout.Annotation(text="Quest limit (combined)", xanchor="left", yanchor="bottom"), annotation_position="left")
            # show horizontal lines when single y is over the limit
            max_single_d = max(max(pdc.max_value for wt, pdc in den_dict.items() if wt != "combined") for den_dict in wall_densities.values()) if wall_densities else 0
            if max_single_d > 0.95 * analysis.PC_TYPE_DESPAWN:
                wfig.add_hline(analysis.PC_TYPE_DESPAWN, line={"color": "yellow", "dash": "dash"}, annotation=go.layout.Annotation(text="PC despawn (per type)", xanchor="left", yanchor="bottom"), annotation_position="left")

            for d, den_dict in wall_densities.items():
                for wt in ("combined", *synth_format.WALL_TYPES):
                    pdc = den_dict[wt]
                    if pdc.max_value:
                        wfig.add_scatter(
                            x=pdc.plot_data[:,0], y=pdc.plot_data[:,1], name=f"{d} ({wt}) [{analysis.wall_mode(pdc.max_value, combined=(wt == 'combined'))}]",
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
                nfig.add_vline(t, line={"color": "lightgray", "dash": "dash"}, annotation=go.layout.Annotation(text="[]", font=dict(color="gray"), hovertext=b, xanchor="center", yanchor="bottom"), annotation_position="bottom")

            for d, c in self.data.difficulties.items():
                den_dict = analysis.note_densities(c)
                for nt in ("combined", *synth_format.NOTE_TYPES):
                    den_subdict = den_dict[nt]
                    for sub_t, pdc in den_subdict.items():
                        if pdc.max_value:
                            nfig.add_scatter(
                                x=pdc.plot_data[:,0], y=pdc.plot_data[:,1], name=f"{d} ({nt} {sub_t}s) [max {pdc.max_value}]",
                                showlegend=True,
                                legendgroup=f"{d} {nt}",
                                # start with only combined note visible
                                visible=(nt == "combined" and sub_t == "note") or "legendonly",
                            )
            ui.plotly(nfig).classes("w-full h-96")

    fi = FileInfo()

    with ui.dialog() as help_dialog, ui.card():
        ui.markdown("""
            **This tab allows you to work .synth files directly.**

            The following features are supported:

            * View and edit metadata:
                * audio file
                * cover image
                * name, artist and mapper
            * Change BPM/Offset (without changing timing of existing objects)
            * Detect and correct certain types of file corruption (NaN value, duplicate notes)
            * Merge files, including different BPM
            * Show stats
                * Object counts per difficulty
                * Density plot for Walls (including checks for PC or Quest limitations)
                * Density plot for Notes and Rails

            To start, just open a .synth file by clciking the plus button below.  
            You can also drag files directly onto these file selectors.
        """)
    ui.button("What can I do here?", icon="help", color="info", on_click=help_dialog.open)
    
    with ui.row().classes("mb-4"):
        with ui.card().classes("mb-4"):
            with ui.upload(label="Select a .synth file ->", auto_upload=True, on_upload=fi.upload).classes("w-full").add_slot("list"):
                ui.tooltip("Select a file first").bind_visibility_from(fi, "is_valid", backward=lambda v: not v).classes("bg-red")
                ui.input("Output Filename").props("dense").bind_value(fi, "output_filename").bind_enabled_from(fi, "is_valid")
                with ui.switch("Finalize Walls").bind_value(fi, "output_finalize").bind_enabled_from(fi, "is_valid").classes("my-auto"):
                    ui.tooltip("Shifts some walls down, such that they look ingame as they do in the editor")
                with ui.row():
                    ui.button("clear", icon="clear", color="negative", on_click=fi.clear).props("dense").classes("w-24").bind_enabled_from(fi, "is_valid")
                    ui.button("save", icon="save", color="positive", on_click=fi.save).props("dense").classes("w-24").bind_enabled_from(fi, "is_valid")
        with ui.card().classes("w-100").bind_visibility(fi, "is_valid"):
            fi.info_card()

        with ui.card().bind_visibility(fi, "is_valid"):
            ui.markdown("**Merge files into base**")
            merge_bookmarks = ui.switch("Merge Bookmarks", value=True).classes("w-full").bind_value(app.storage.user, "merge_bookmarks").tooltip("Disable this if you merge maps that contain the same bookmarks")
            with ui.upload(label="One or more files", multiple=True, auto_upload=True, on_upload=fi.upload_merge).props('color="positive"').classes("w-full").add_slot("list"):
                ui.markdown("""
                    Should have the same audio file as the base.  
                    BPM & Offset will be matched automatically.
                """)
            

    with ui.card().classes("w-full"):
        fi.stats_card()
