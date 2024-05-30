import base64
from io import BytesIO
import dataclasses
from pathlib import Path
from typing import Optional
import sys

import plotly.graph_objects as go
from nicegui import app, events, run, ui
import numpy as np
import librosa

from .utils import *
from ..utils import pretty_list
from .. import synth_format, movement, analysis, __version__


def _file_utils_tab():
    @dataclasses.dataclass
    class FileInfo:
        data: Optional[synth_format.SynthFile] = None
        output_filename: str = "No file selected"
        output_bpm: float = 0.0
        output_offset: float = 0.0
        output_finalize: bool = False
        preview_audio: Optional[tuple[str, bytes]] = None
        wall_densities: Optional[dict[str, dict[str, analysis.PlotDataContainer]]] = None
        note_densities: Optional[dict[str, dict[str, analysis.PlotDataContainer]]] = None
        bpm_scan_data: Optional[dict] = None
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
            self.tick_audio = None
            self.bpm_scan_data = None
            self.wall_densities = None
            self.note_densities = None
            self.refresh()

        async def upload(self, e: events.UploadEventArguments) -> None:
            e.sender.reset()
            self.clear()
            if e.name.endswith(".synth"):
                self.data = try_load_synth_file(e)
                self.output_filename = add_suffix(e.name, "out")
            else:
                try:
                    self.data = synth_format.SynthFile.empty_from_audio(audio_file=BytesIO(e.content.read()), filename=e.name)
                except Exception as exc:
                    error(f"Creating .synth from {e.name} failed", exc=exc)
                    self.data = None
                else:
                    self.output_filename = self.data.meta.name + ".synth"
            if self.data is not None:
                self.output_bpm = self.data.bpm
                self.output_offset = self.data.offset_ms
                self.output_finalize = (self.data.bookmarks.get(0) == "#smh_finalized")
                self.merged_filenames = []
                self.bpm_scan_data = {"state": "Waiting"}
                ui.timer(0.1, self._calc_wden, once=True)
                ui.timer(0.2, self._calc_nden, once=True)
                ui.timer(0.5, self._calc_bpm, once=True)

            self.refresh()

        def upload_merge(self, e: events.UploadEventArguments) -> None:
            e.sender.reset()
            merge = try_load_synth_file(e)
            if merge is None:
                return
            if merge.audio.raw_data != self.data.audio.raw_data:
                ui.notify("Difference in audio files detected. Merge may yield weird results.", type="warning")
            self.data.merge(merge, merge_bookmarks=merge_bookmarks.value)
            self.merged_filenames.append(e.name)
        
            self.refresh()

        def upload_cover(self, e: events.UploadEventArguments) -> None:
            e.sender.reset()
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
            if self.output_bpm is None or not self.output_bpm > 0:
                error("BPM must be greater than 0", data=bpm)
                return
            if self.output_offset is None or self.output_offset < 0:
                error("Offset must be 0 or greater", data=offset)
                return
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
            ui.download(data.getvalue(), filename=self.output_filename or "unnamed.synth")

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
            self._bpm_card.refresh()
            self._wden_card.refresh()
            self._nden_card.refresh()

        async def _add_clicks(self, e: events.ClickEventArguments):
            bpm = self.output_bpm
            offset = self.output_offset
            if bpm is None or not bpm > 0:
                error("BPM must be greater than 0", data=bpm)
                return
            if offset is None or offset < 0:
                error("Offset must be 0 or greater", data=offset)
                return
            btn: ui.button = e.sender
            btn.props('color="grey"').classes("cursor-wait")  # turn grey and indicate wait
            try:
                _, self.tick_audio = await run.cpu_bound(analysis.audio_with_clicks, raw_audio_data=self.data.audio.raw_data, duration=self.data.audio.duration, bpm=bpm, offset_ms=offset)
            except Exception as exc:
                error("Generating click audio failed", exc=exc, data={"bpm":bpm, "offset_ms": offset})
            btn.props('color="positive"').classes(remove="cursor-wait")  # reset visuals

        @ui.refreshable
        def info_card(self):
            if self.data is None:
                ui.label("Load a map to show info")
                return
            ui.markdown("**Edit metadata**")
            meta = self.data.meta
            with ui.row():
                with ui.upload(label="Replace Cover", auto_upload=True, on_upload=self.upload_cover).classes("w-32").props('accept="image/png"').add_slot("list"):
                    ui.image("data:image/png;base64,"+base64.b64encode(meta.cover_data).decode()).tooltip(meta.cover_name)
                with ui.column():
                    ui.input("Name").props("dense").classes("h-8").bind_value(meta, "name")
                    ui.input("Artist").props("dense").classes("h-8").bind_value(meta, "artist")
                    ui.input("Mapper").props("dense").classes("h-8").bind_value(meta, "mapper")
                    ui.checkbox("Explicit lyrics").classes("h-8").props("dense").bind_value(meta, "explicit")
            with ui.upload(label="Replace Audio", auto_upload=True, on_upload=self.upload_audio).props('accept="audio/ogg,*/*"').classes("w-full").add_slot("list"):
                ui.audio("").bind_source_from(self, "tick_audio", backward=lambda ta: f"data:audio/{'ogg' if ta is None else 'wav'};base64,"+base64.b64encode(self.data.audio.raw_data if ta is None else ta).decode())
                with ui.row():
                    with ui.number("BPM", min=1.0, max=600.0, step=0.1).props("dense").classes("w-20").bind_value(self, "output_bpm"):
                        ui.tooltip("").bind_text_from(self, "output_bpm", backward=lambda bpm: f"{round(60000/bpm)} ms/b" if bpm is not None else "Invalid")
                    ui.number("Offset", min=0, step=1, suffix="ms").props("dense").classes("w-20").bind_value(self, "output_offset")
                    def _reset_bpm():
                        self.output_bpm = self.data.bpm
                        self.output_offset = self.data.offset_ms
                    ui.button(icon="undo", on_click=_reset_bpm, color="warning").props("dense outline").classes("my-auto").tooltip("Reset to original values")
                    ui.button(icon="timer", on_click=self._add_clicks, color="positive").props("dense outline").classes("my-auto").tooltip("Add or update clicks in preview")
                    def _reset_audio():
                        self.tick_audio = None
                    ui.button(icon="timer_off", on_click=_reset_audio, color="negative").props("dense outline").classes("my-auto").tooltip("Remove clicks from preview").bind_enabled_from(self, "tick_audio", lambda s: s is not None)

        async def _calc_bpm(self):
            self.bpm_scan_data["state"] = "Loading Audio"
            data, sr = await run.cpu_bound(analysis.load_audio, raw_data=fi.data.audio.raw_data)
            self.bpm_scan_data["data"] = data
            self.bpm_scan_data["sr"] = sr
            self.bpm_scan_data["state"] = "Detecting Onsets"
            onsets = await run.cpu_bound(analysis.calculate_onsets, data=data, sr=sr)
            self.bpm_scan_data["onsets"] = onsets
            self.bpm_scan_data["state"] = "Finding BPM"
            peak_bpms, peak_values, pulse = await run.cpu_bound(analysis.find_bpm, onsets=onsets, sr=sr)
            self.bpm_scan_data["peak_bpms"] = peak_bpms
            self.bpm_scan_data["peak_values"] = peak_values
            self.bpm_scan_data["pulse"] = pulse
            self.bpm_scan_data["detected_bpm"] = round(peak_bpms[peak_values.argmax()], 3)
            self.bpm_scan_data["bpm"] = self.bpm_scan_data["detected_bpm"]
            await self._calc_beats()
        async def _calc_beats(self):
            # have this seperate so it could be updated seperately later
            self.bpm_scan_data["state"] = "Locating beats"
            self._bpm_card.refresh()
            sr = self.bpm_scan_data["sr"]
            bpm = self.bpm_scan_data["bpm"]
            onsets = self.bpm_scan_data["onsets"]
            beats = await run.cpu_bound(analysis.locate_beats, onsets=onsets, sr=sr, bpm=bpm)
            self.bpm_scan_data["beats"] = beats
            self.bpm_scan_data["state"] = "Done"
            beat_time = 60/bpm
            offsets = beat_time - (beats % beat_time)
            offset_ms = int(offsets.mean()*1000)
            self.bpm_scan_data["offset_ms"] = offset_ms
            self._bpm_card.refresh()

        @ui.refreshable
        def _bpm_card(self) -> None:
            if self.bpm_scan_data["state"] != "Done":
                with ui.row():
                    ui.spinner(size="xl")
                    ui.label().classes("my-auto").bind_text_from(self.bpm_scan_data, "state", backward=lambda s: s + " (this may take a few seconds)")
                return
            ui.label("BPM Scan Results")
            sr = self.bpm_scan_data["sr"]
            onsets = self.bpm_scan_data["onsets"]
            peak_values = self.bpm_scan_data["peak_values"]
            pulse = self.bpm_scan_data["pulse"]
            peak_bpms = self.bpm_scan_data["peak_bpms"]
            bpm = self.bpm_scan_data["bpm"]
            detected_bpm = self.bpm_scan_data["detected_bpm"]
            beats = self.bpm_scan_data["beats"]
            offset_ms = self.bpm_scan_data["offset_ms"]
            with ui.row():
                ui.label(f"{'Detected' if (detected_bpm==bpm) else 'Overwritten'} BPM: {bpm}, Offset: {offset_ms} ms").classes("my-auto")
                def _apply_bpm():
                    self.output_bpm = bpm
                    self.output_offset = offset_ms
                ui.button("Apply", icon="auto_fix_high", on_click=_apply_bpm, color="positive").props("dense outline").tooltip("Apply detected BPM and offset")
                async def _override_bpm():
                    self.bpm_scan_data["bpm"] = self.output_bpm
                    await self._calc_beats()
                ui.button("BPM Override", icon="south", on_click=_override_bpm, color="warning").props("dense outline").tooltip("Override detected BPM with current BPM and recalculate beats and offset")

            bpmfig = go.Figure(
                layout=go.Layout(
                    xaxis=go.layout.XAxis(title="Time"),
                    yaxis=go.layout.YAxis(title="BPM"),
                    legend=go.layout.Legend(x=0, xanchor="left", y=1, yanchor="top", orientation="h", groupclick="toggleitem"),
                    margin=go.layout.Margin(l=0, r=0, t=0, b=0),
                ),
            )
            bpmfig.add_scatter(
                x=librosa.times_like(peak_bpms, sr=sr), y=peak_bpms,
                name="BPM",
            )
            bpmfig.add_hline(bpm, line={"color": "gray", "dash": "dash"}, annotation=go.layout.Annotation(text="Detected BPM", xanchor="left", yanchor="bottom"), annotation_position="left")
            ui.plotly(bpmfig).classes("w-full h-96")

            onset_fig = go.Figure(
                layout=go.Layout(
                    xaxis=go.layout.XAxis(title="Time"),
                    yaxis=go.layout.YAxis(title=" "),
                    legend=go.layout.Legend(x=0, xanchor="left", y=1, yanchor="top", orientation="h", groupclick="toggleitem"),
                    margin=go.layout.Margin(l=0, r=0, t=0, b=0),
                ),
            )
            onset_fig.add_scatter(
                x=librosa.times_like(onsets, sr=sr), y=onsets,
                name="Onset strength",
            )
            onset_fig.add_scatter(
                x=librosa.times_like(peak_values, sr=sr), y=peak_values,
                name="BPM strength",
            )
            onset_fig.add_scatter(
                x=librosa.times_like(pulse, sr=sr), y=pulse,
                name="Pulse curve",
                visible="legendonly",  # hide by default
            )
            onset_fig.add_scatter(
                # just vertical lines
                x=beats.repeat(3), y=[0,1,None]*len(beats),
                name=f"Beats ({bpm} BPM)",
                line=dict(dash="dot")
            )
            ui.plotly(onset_fig).classes("w-full h-96")

        def _calc_wden(self):
            self.wall_densities = {d: analysis.wall_densities(c) for d, c in self.data.difficulties.items()}
            self._wden_card.refresh()

        def _calc_nden(self):
            self.note_densities = {d: analysis.note_densities(c) for d, c in self.data.difficulties.items()}
            self._nden_card.refresh()

        @ui.refreshable
        def _wden_card(self) -> None:
            ui.label("Wall density")
            if self.wall_densities is None:
                ui.spinner(size="xl")
                return
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
            max_com_d = max(den_dict["combined"].max_value for den_dict in self.wall_densities.values()) if self.wall_densities else 0
            if max_com_d > 0.9 * analysis.QUEST_WIREFRAME_LIMIT:
                wfig.add_hline(analysis.QUEST_WIREFRAME_LIMIT, line={"color": "gray", "dash": "dash"}, annotation=go.layout.Annotation(text="Quest wireframe (combined)", xanchor="left", yanchor="bottom"), annotation_position="left")
            if max_com_d > 0.9 * analysis.QUEST_RENDER_LIMIT:
                wfig.add_hline(analysis.QUEST_RENDER_LIMIT, line={"color": "red", "dash": "dash"}, annotation=go.layout.Annotation(text="Quest limit (combined)", xanchor="left", yanchor="bottom"), annotation_position="left")
            # show horizontal lines when single y is over the limit
            max_single_d = max(max(pdc.max_value for wt, pdc in den_dict.items() if wt != "combined") for den_dict in self.wall_densities.values()) if self.wall_densities else 0
            if max_single_d > 0.95 * analysis.PC_TYPE_DESPAWN:
                wfig.add_hline(analysis.PC_TYPE_DESPAWN, line={"color": "yellow", "dash": "dash"}, annotation=go.layout.Annotation(text="PC despawn (per type)", xanchor="left", yanchor="bottom"), annotation_position="left")

            for d, den_dict in self.wall_densities.items():
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

        @ui.refreshable
        def _nden_card(self) -> None:
            ui.label("Note & Rail density")
            if self.wall_densities is None:
                ui.spinner(size="xl")
                return
            # mostly the same thing as walls, but for combined notes and rail nodes
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

            for d, den_dict in self.note_densities.items():
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

        @ui.refreshable
        def stats_card(self) -> None:
            if self.data is None:
                ui.label("Load a map to show stats and graphs")
                return
            self._bpm_card()
            ui.separator()
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

            ui.separator()
            self._wden_card()
            ui.separator()
            self._nden_card()

    fi = FileInfo()

    with ui.dialog() as help_dialog, ui.card():
        ui.markdown("""
            **This tab allows you to work .synth files directly.**

            The following features are supported:

            * Create new .synth files from .ogg files
            * Detect and edit BPM/Offset (without changing timing of existing objects)
            * View and edit metadata:
                * audio file
                * cover image
                * name, artist and mapper
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
            with ui.upload(label="Select a .synth or .ogg file ->", auto_upload=True, on_upload=fi.upload).classes("w-full").add_slot("list"):
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

file_utils_tab = GUITab(
    name="fileutils",
    label="File Utils",
    icon="construction",
    content_func=_file_utils_tab,
)
