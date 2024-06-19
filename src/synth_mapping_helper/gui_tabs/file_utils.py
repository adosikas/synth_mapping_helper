import asyncio
import base64
from io import BytesIO
import dataclasses
from pathlib import Path
from typing import Optional
import sys

import librosa
from nicegui import app, events, run, ui
import numpy as np
import plotly.graph_objects as go

from synth_mapping_helper.gui_tabs.utils import *
from synth_mapping_helper.utils import pretty_list, beat_to_second
from synth_mapping_helper import synth_format, movement, analysis, audio_format, __version__

def circmedian(values: "numpy array (n,)", high: float) -> float:
    # doing statistics on "circular data" (ie 0-beat_time) is hard, but we can treat each value as "angle" (0-2pi, ie 0-360 deg)
    # see also: scipy.stats.circmean
    # via median of sine and cosine, we get the "median angle" and transform that back
    # we get the median instead of mean, to avoid outliers influencing the result
    scaling = 2*np.pi/high
    sines = np.sin(values*scaling)
    cosines = np.cos(values*scaling)
    return (np.arctan2(np.median(sines), np.median(cosines)) / scaling + high)%high

def circerror(values: "numpy array (n,)", target: float, high: float) -> "numpy array (n,)":
    # shift the delta such that equal -> h/2  and opposite -> 0 or h
    shifted_delta = (values - target + high*1.5) % high
    # now get the delta from high/2, and transform into 0 (equal) to 1 (opposite)
    return np.abs(shifted_delta-high/2) / (high/2)

def _file_utils_tab() -> None:
    @dataclasses.dataclass
    class FileInfo:
        data: Optional[synth_format.SynthFile] = None
        output_filename: str = "No file selected"
        output_bpm: float = 0.0
        output_offset: int = 0
        output_finalize: bool = False
        preview_audio: Optional[tuple[str, bytes]] = None
        # [diff][type]
        wall_densities: Optional[dict[str, dict[str, analysis.PlotDataContainer]]] = None
        # [diff][color][subtype]
        note_densities: Optional[dict[str, dict[str, dict[str, analysis.PlotDataContainer]]]] = None
        bpm_scan_data: Optional[dict] = None
        merged_filenames: list[str] = dataclasses.field(default_factory=list)

        @property
        def is_valid(self) -> bool:
            return self.data is not None

        def clear(self) -> None:
            self.data = None
            self.output_filename = "No base file selected"
            self.output_bpm = 0.0
            self.output_offset = 0
            self.merged_filenames = []
            self.bpm_scan_data = None
            self.wall_densities = None
            self.note_densities = None
            self.refresh()

        @handle_errors
        async def upload(self, e: events.UploadEventArguments) -> None:
            upl: ui.upload = e.sender  # type:ignore
            upl.reset()
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

        @handle_errors
        def upload_merge(self, e: events.UploadEventArguments) -> None:
            upl: ui.upload = e.sender  # type:ignore
            upl.reset()
            if self.data is None:
                return
            merge = try_load_synth_file(e)
            if merge is None:
                return
            if merge.audio.raw_data != self.data.audio.raw_data:
                ui.notify("Difference in audio files detected. Merge may yield weird results.", type="warning")
            self.data.merge(merge, merge_bookmarks=merge_bookmarks.value)
            self.merged_filenames.append(e.name)
        
            self.refresh()

        def upload_cover(self, e: events.UploadEventArguments) -> None:
            upl: ui.upload = e.sender  # type:ignore
            upl.reset()
            if self.data is None:
                return
            if not e.name.lower().endswith(".png"):
                error("Cover image must be .png")
                return
            self.data.meta.cover_data = e.content.read()
            self.data.meta.cover_name = e.name
            ui.notify(f"Changed cover image to {e.name}", type="info")
            self.refresh()

        @handle_errors
        async def upload_audio(self, e: events.UploadEventArguments) -> None:
            upl: ui.upload = e.sender  # type:ignore
            upl.reset()
            if self.data is None:
                return
            try:
                raw_data = e.content.read()
                try:
                    # spinning up another process is slow, so lets attempt without conversion first
                    new_audio = audio_format.AudioData.from_raw(raw_data)
                except audio_format.AudioNotOggError as anoe:
                    ui.notify(f"Audio not ogg ({anoe.detected_format}), attempting conversion...", type="info")
                    # conversion takes a while, so offload that to another process
                    new_audio = await run.cpu_bound(audio_format.AudioData.from_raw, raw_data=raw_data, allow_conversion=True)
            except ValueError as ve:
                error("Error reading audio file", exc=ve, data=e.name)
            else:
                self.data.audio = new_audio
                self.data.meta.audio_name = e.name
                self._audio_info.refresh()
                ui.notify(f"Changed audio to {e.name}", type="info")
                self.bpm_scan_data = {"state": "Waiting"}
                # note: this callback runs inside the scope of the container of the uploader
                # so if we did a full refresh here, the info_card would get re-created, deleting the container and the timer with it
                # See https://github.com/zauberzeug/nicegui/issues/3187
                self._bpm_card.refresh()
                ui.timer(0.1, self._calc_bpm, once=True)

        @handle_errors
        def save(self) -> None:
            if self.data is None:
                return
            if self.output_bpm is None or not self.output_bpm > 0:
                error("BPM must be greater than 0", data=self.output_bpm)
                return
            if self.output_offset is None or self.output_offset < 0:
                error("Offset must be 0 or greater", data=self.output_offset)
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

        async def add_silence(self, before_start_ms: int=0, after_end_ms: int=0) -> None:
            if self.data is None:
                return
            self.bpm_scan_data = {"state": "Waiting"}
            self._bpm_card.refresh()
            # note: this edits the object, so it cannot easily be offloaded to another process
            # but io_bound is just another thread, which is fine
            await run.io_bound(self.data.add_silence, before_start_ms=before_start_ms, after_end_ms=after_end_ms)
            self._audio_info.refresh()
            ui.timer(0.01, self._calc_bpm, once=True)

        @ui.refreshable
        def _audio_info(self) -> None:
            if self.data is None:
                return
            default_source = "data:audio/ogg;base64,"+base64.b64encode(self.data.audio.raw_data).decode()
            preview_audio = ui.audio(default_source)
            with ui.row():
                with ui.number("BPM", min=1.0, max=600.0, step=0.1).props("dense").classes("w-20").bind_value(self, "output_bpm"):
                    ui.tooltip("").bind_text_from(self, "output_bpm", backward=lambda bpm: f"{round(60000/bpm)} ms/b" if bpm is not None else "Invalid")
                def _multiply_bpm(mult: float) -> None:
                    self.output_bpm = round(self.output_bpm*mult, 3)
                ui.button("½", on_click=lambda _: _multiply_bpm(1/2), color="secondary").props("dense outline").classes("w-8 my-auto").tooltip("Divide BPM by 2")
                ui.button("2", on_click=lambda _: _multiply_bpm(2)).props("dense outline").classes("w-8 my-auto").tooltip("Double BPM")
                ui.separator().props("vertical")
                ui.button("⅓", on_click=lambda _: _multiply_bpm(1/3), color="secondary").props("dense outline").classes("w-8 my-auto").tooltip("Divide BPM by 3")
                ui.button("3", on_click=lambda _: _multiply_bpm(3)).props("dense outline").classes("w-8 my-auto").tooltip("Triple BPM")
            with ui.row():
                with ui.number("Offset", min=0, step=1, suffix="ms").props("dense").classes("w-20").bind_value(self, "output_offset"):
                    def _update_offset_tooltip(_) -> str:
                        bpm = self.output_bpm
                        offset = self.output_offset
                        return f"-{round(60000/bpm-offset)} ms" if bpm and offset is not None else "Invalid"
                    ui.tooltip("").bind_text_from(self, "output_bpm", backward=_update_offset_tooltip).bind_text_from(self, "output_offset", backward=_update_offset_tooltip)
                def _shift_offset(beats: float) -> None:
                    beat_time = 60/self.output_bpm
                    offset = round((self.output_offset/1000 + beats*beat_time)*1000)
                    if offset >= 0:
                        self.output_offset = offset
                    else:
                        ui.notify("Negative offset is not supported", type="warning")
                ui.button(icon="chevron_left", on_click=lambda _: _shift_offset(-1), color="negative").props("dense outline").classes("w-8 my-auto").tooltip("Subtract a beat from offset")
                ui.button(icon="chevron_right", on_click=lambda _: _shift_offset(1), color="positive").props("dense outline").classes("w-8 my-auto").tooltip("Add a beat to offset")
                ui.separator().props("vertical")
                ui.button("<½", on_click=lambda _: _shift_offset(-0.5), color="negative").props("dense outline").classes("w-8 my-auto").tooltip("Subtract half a beat from offset")
                ui.button(">½", on_click=lambda _: _shift_offset(0.5), color="positive").props("dense outline").classes("w-8 my-auto").tooltip("Add half a beat to offset")
            with ui.row().classes("pt-2"):
                def _reset_bpm():
                    self.output_bpm = self.data.bpm
                    self.output_offset = self.data.offset_ms
                reset_button = ui.button(icon="undo", on_click=_reset_bpm, color="warning").props("dense outline").classes("w-8 my-auto").tooltip("Reset BPM and Offset to original values")
                ui.separator().props("vertical")

                async def _pad_offset() -> None:
                    offset_ms = int(self.output_offset)
                    ui.notify(f"Adding {offset_ms} ms of silence. This may take a few seconds.", type="info")
                    self.output_offset = 0
                    await self.add_silence(before_start_ms=offset_ms)
                pad_button = ui.button(icon="keyboard_tab", on_click=_pad_offset, color="positive").props("dense").classes("w-8 my-auto").bind_enabled_from(self, "output_offset")
                with pad_button:
                    ui.tooltip().bind_text_from(self, "output_offset", lambda o: f"Add {int(o) if o else '<offset>'} ms of silence before the audio")
                with ui.dialog() as pad_dialog, ui.card():
                    ui.label("Note: After these, offset should be re-applied")
                    with ui.row():
                        before_ms = ui.number("Before", value=0, suffix="ms").props("dense").classes("w-24").tooltip("Amount to add. Negative trims instead.")
                        async def _pad_audio():
                            pad_dialog.close()
                            ui.notify(f"Padding audio. This may take a few seconds.", type="info")
                            await self.add_silence(before_start_ms=before_ms.value, after_end_ms=after_ms.value)
                        ui.timer(0.01, self._calc_bpm, once=True)
                        ui.button(icon="settings_ethernet", color="positive", on_click=_pad_audio).props("dense").classes("my-auto").tooltip("Add silence to start and end")
                        after_ms = ui.number("After", value=0, suffix="ms").props("dense").classes("w-24").tooltip("Amount to add. Negative trims instead.")
                    ui.separator()
                    with ui.row():
                        async def _trim_silence():
                            pad_dialog.close()
                            ui.notify(f"Trimming silence from audio. This may take a few seconds.", type="info")
                            trim_start, trim_end = await run.io_bound(audio_format.find_trims, raw_audio_data=self.data.audio.raw_data)
                            await self.add_silence(before_start_ms=-round(trim_start*1000), after_end_ms=-round(trim_end*1000))
                            ui.notify(f"Trimmed {trim_start:.3f} s from beginning and {trim_end:.3f} s from end", type="info")
                        ui.button(icon="content_cut volume_off", color="negative", on_click=_trim_silence).props("dense").classes("w-16").tooltip("Detect and remove silence from beginning and end")
                        async def _add_2s():
                            pad_dialog.close()
                            ui.notify(f"Adding two seconds of silence. This may take a few seconds.", type="info")
                            await self.add_silence(before_start_ms=2000)
                        ui.button("2s", icon="start", color="positive", on_click=_add_2s).props("dense").tooltip("Add two seconds of silence before start")
                        async def _align_bookmark():
                            pad_dialog.close()
                            bookmarks = sorted(self.data.bookmarks.items())
                            if not bookmarks:
                                error(msg="No bookmarks found")
                            bm_beat, bm_name = bookmarks[0]
                            bm_time = beat_to_second(bm_beat, bpm=self.data.bpm) - self.data.offset_ms/1000
                            if bm_time > 2:
                                ui.notify(f"Removing {bm_time-2:.3f} s to align first bookmark ({bm_name!r}) to 2 second mark. This may take a few seconds.", type="info")
                            elif bm_time < 2:
                                ui.notify(f"Adding {2-bm_time:.3f} s to align first bookmark ({bm_name!r}) to 2 second mark. This may take a few seconds.", type="info")
                            before_start_ms = round((2-bm_time)*1000)
                            await self.add_silence(before_start_ms=before_start_ms)
                            self.data.change_offset(0)
                            self.output_offset = 0
                        with ui.button("2s", icon="bookmark_added", color="positive", on_click=_align_bookmark).props("dense").bind_enabled_from(self.data, "bookmarks"):
                            ui.tooltip().bind_text_from(self.data, "bookmarks", backward=lambda b: "Align first bookmark with 2 second mark" + ("" if b else " (no bookmarks found)"))
                def _open_pad_dialog() -> None:
                    pad_dialog.open()
                    pad_dialog.update()
                ui.button(icon="settings_ethernet", color="info", on_click=_open_pad_dialog).props("dense").classes("w-8 my-auto").tooltip("Pad or trim audio")
                ui.separator().props("vertical")
                async def _add_clicks(e: events.ClickEventArguments):
                    if self.data is None:
                        return
                    bpm = self.output_bpm
                    offset = self.output_offset
                    if bpm is None or not bpm > 0:
                        error("BPM must be greater than 0", data=bpm)
                        return
                    if offset is None or offset < 0:
                        error("Offset must be 0 or greater", data=offset)
                        return
                    btn: ui.button = e.sender  # type: ignore
                    btn.props('color="grey"').classes("cursor-wait")  # turn grey and indicate wait
                    try:
                        data = await run.cpu_bound(audio_format.audio_with_clicks, raw_audio_data=self.data.audio.raw_data, duration=self.data.audio.duration, bpm=bpm, offset_ms=offset)
                        preview_audio.set_source("data:audio/ogg;base64,"+base64.b64encode(data).decode())
                    except Exception as exc:
                        error("Generating click audio failed", exc=exc, data={"bpm":bpm, "offset_ms": offset})
                    btn.props('color="positive"').classes(remove="cursor-wait")  # reset visuals
                ui.button(icon="timer", on_click=_add_clicks, color="positive").props("dense outline").classes("w-8 my-auto").tooltip("Add or update clicks in preview")
                ui.button(icon="timer_off", on_click=lambda _: preview_audio.set_source(default_source), color="negative").props("dense outline").classes("w-8 my-auto").tooltip("Remove clicks from preview")
        @ui.refreshable
        def info_card(self):
            if self.data is None:
                ui.label("Load a map to show info")
                return
            ui.markdown("**Edit metadata**")
            meta = self.data.meta
            with ui.row():
                with ui.upload(label="Replace Cover" if meta.cover_data else "Set Cover", auto_upload=True, on_upload=self.upload_cover).classes("w-32").props('accept="image/png"').add_slot("list"):
                    ui.image("data:image/png;base64,"+base64.b64encode(meta.cover_data).decode()).tooltip(meta.cover_name)
                with ui.column():
                    ui.input("Name").props("dense").classes("h-8").bind_value(meta, "name")
                    ui.input("Artist").props("dense").classes("h-8").bind_value(meta, "artist")
                    ui.input("Mapper").props("dense").classes("h-8").bind_value(meta, "mapper")
                    ui.checkbox("Explicit lyrics").classes("h-8").props("dense").bind_value(meta, "explicit")
            with ui.upload(label="Replace Audio", auto_upload=True, on_upload=self.upload_audio).props('accept="audio/ogg,*/*"').classes("w-full").add_slot("list"):
                self._audio_info()

        async def _calc_bpm(self):
            sd = self.bpm_scan_data  # create a pointer to avoid messing up data when it gets replaced during calc
            sd["state"] = "Loading Audio"
            data, sr = await run.cpu_bound(audio_format.load_for_analysis, raw_data=self.data.audio.raw_data)
            sd["data"] = data
            sd["sr"] = sr
            sd["state"] = "Detecting Onsets"
            onsets = await run.cpu_bound(analysis.calculate_onsets, data=data, sr=sr)
            sd["onsets"] = onsets
            sd["state"] = "Finding BPM"
            peak_bpms, peak_values, pulse = await run.cpu_bound(analysis.find_bpm, onsets=onsets, sr=sr)
            sd["peak_bpms"] = peak_bpms
            sd["peak_values"] = peak_values
            sd["pulse"] = pulse
            best_bpm, bpm_sections = analysis.group_bpm(peak_bpms, peak_values)
            sd["bpm_sections"] = bpm_sections
            sd["best_bpm"] = best_bpm
            sd["bpm_override"] = None
            if id(self.bpm_scan_data) == id(sd):
                # only continue when the pointer is still identical
                await self._calc_beats()

        async def _calc_beats(self):
            # have this seperate so it could be updated seperately later
            sd = self.bpm_scan_data
            sr = sd["sr"]
            onsets = sd["onsets"]
            bpm_override = sd["bpm_override"]
            if bpm_override is None:
                bpm_sections = sd["bpm_sections"]
            else:
                bpm_sections = [(0, onsets.shape[-1], bpm_override, 1)]
            sd["state"] = f"Processing {len(bpm_sections)} sections"
            self._bpm_card.refresh()
            offset_sections = []
            beat_results = await asyncio.gather(
                *[
                    run.cpu_bound(analysis.locate_beats, onsets=onsets[section_start:section_end], sr=sr, bpm=section_bpm)
                    for section_start, section_end, section_bpm, _ in bpm_sections
                ]
            )
            for i, ((section_start, section_end, section_bpm, _), beats) in enumerate(zip(bpm_sections, beat_results)):
                if not beats.any():
                    # ignore sections without detected beats
                    continue
                # not sure why, but a 22ms offset seems to be required...
                beats = librosa.frames_to_time(beats + section_start, sr=sr) - 0.022
                beat_time = 60/section_bpm
                median_offset = circmedian(beats % beat_time, high=beat_time)
                offset_error = circerror(beats % beat_time, median_offset, high=beat_time)
                offset_ms = int((beat_time - median_offset)*1000)  # the game offsets the audio, so negate offset
                offset_sections.append((section_start, section_end, beats, section_bpm, offset_ms, offset_error))
            sd["offset_sections"] = offset_sections
            sd["state"] = "Done"
            self._bpm_card.refresh()

        @ui.refreshable
        def _bpm_card(self) -> None:
            if self.bpm_scan_data is None:
                ui.label("No BPM data")
                return
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
            best_bpm = self.bpm_scan_data["best_bpm"]
            bpm_sections = self.bpm_scan_data["bpm_sections"]
            offset_sections = self.bpm_scan_data["offset_sections"]
            bpm_override = self.bpm_scan_data["bpm_override"]

            with ui.row():
                async def _reset_bpm():
                    self.bpm_scan_data["bpm_override"] = None
                    await self._calc_beats()
                if bpm_override is not None:
                    ui.button(icon="undo", on_click=_reset_bpm, color="warning").props("dense outline").classes("my-auto").tooltip("Reset back to detected BPM")
                async def _override_bpm():
                    self.bpm_scan_data["bpm_override"] = self.output_bpm
                    await self._calc_beats()
                ui.button("BPM Override", icon="south", on_click=_override_bpm, color="warning").props("dense outline").tooltip("Override detected BPM with current BPM and recalculate beats and offset")
                with ui.dropdown_button("Apply", auto_close=True, icon="auto_fix_high").props("dense outline").tooltip("Apply detected BPM and offset"):
                    for i, (_, _, _, section_bpm, section_offset, _) in enumerate(offset_sections):
                        color = "green" if section_bpm==best_bpm else ("blue", "red")[i%2]
                        def _apply_bpm(bpm=section_bpm, offset_ms=section_offset):
                            self.output_bpm = bpm
                            self.output_offset = offset_ms
                        ui.item(f"Section {i+1}: {section_bpm} BPM, {section_offset} ms", on_click=_apply_bpm).classes(f"text-{color}")
                def _add_bookmarks():
                    # clear existing bpm bookmarks
                    for t, n in list(self.data.bookmarks.items()):
                        if n.startswith("#smh_bpm"):
                            del self.data.bookmarks[t]
                    # add new
                    self.data.bookmarks |= {
                        librosa.frames_to_time(s, sr=sr): f"#smh_bpm: {s_bpm}"
                        for (s, _, s_bpm, _) in bpm_sections
                    }
                    # update plots
                    self.stats_card.refresh()
                ui.button("Add bookmarks", icon="bookmark", on_click=_add_bookmarks, color="positive").props("dense outline").tooltip("Add bookmark on section starts")
            ui.markdown("""
                Note: This may not be accurate. Double check below if the *Error* plot below for the section stays low (meaning *Actual Beats* and *Stable BPM* align), and this matches up with the *Note onsets* plot.

                You can zoom the plots by dragging the axis or selecting a rectangle. Use the "Reset Axis" button (home icon) in the top right of each plot to reset. You can also switch to "Pan" mode there. 
            """)

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
            for i, (section_start, section_end, section_bpm, str_sum) in enumerate(bpm_sections):
                color = "green" if section_bpm==best_bpm else ("blue", "red")[i%2]
                start_time, end_time = librosa.frames_to_time(section_start, sr=sr), librosa.frames_to_time(section_end, sr=sr)
                bpmfig.add_shape(
                    dict(type="rect", x0=librosa.frames_to_time(section_start, sr=sr), x1=librosa.frames_to_time(section_end, sr=sr), y0=0, y1=str_sum),
                    line_width=0, fillcolor=color, opacity=0.1, yref="paper",
                )
                bpmfig.add_annotation(
                    go.layout.Annotation(text=f"{section_bpm}", yanchor="bottom", font=dict(color=color)),
                    yref="paper", showarrow=False,
                    x=(start_time+end_time)/2, y=0,
                )
            ui.plotly(bpmfig).classes("w-full h-96")

            onset_fig = go.Figure(
                layout=go.Layout(
                    xaxis=go.layout.XAxis(title="Time"),
                    yaxis=go.layout.YAxis(title=" "),
                    legend=go.layout.Legend(x=0, xanchor="left", y=1, yanchor="top", orientation="h", groupclick="toggleitem", bgcolor="rgba(255,255,255,0.3)", borderwidth=1),
                    margin=go.layout.Margin(l=0, r=0, t=0, b=0),
                ),
            )
            onset_fig.add_scatter(
                x=librosa.times_like(onsets, sr=sr), y=onsets,
                name="Note onsets",
                legendgroup="common",
                legendgrouptitle=dict(text="Click to toggle:"),
            )
            onset_fig.add_scatter(
                x=librosa.times_like(peak_values, sr=sr), y=peak_values,
                name="BPM confidence",
                legendgroup="common",
            )
            onset_fig.add_scatter(
                x=librosa.times_like(pulse, sr=sr), y=pulse,
                name="Pulse curve",
                visible="legendonly",  # hide by default
                legendgroup="common",
            )
            for i, (section_start, section_end, beats, section_bpm, section_offset, offset_error) in enumerate(offset_sections):
                color = "green" if section_bpm==best_bpm else ("blue", "red")[i%2]
                start_time, end_time = librosa.frames_to_time(section_start, sr=sr), librosa.frames_to_time(section_end, sr=sr)
                onset_fig.add_vrect(
                    start_time, end_time,
                    line_width=0, fillcolor=color, opacity=0.1,
                    annotation=go.layout.Annotation(text=f"Section {i+1}<br>{section_bpm} bpm<br>{section_offset} ms", yanchor="bottom", yref="paper", font=dict(color=color), bgcolor="white"),
                    annotation_position="bottom",
                )
                onset_fig.add_scatter(
                    # just vertical lines
                    x=beats.repeat(3), y=[0,1,None]*len(beats),
                    name="Actual Beats",
                    line=dict(dash="dash", color=color),
                    mode="lines",
                    visible="legendonly",  # hide by default
                    legendgroup=f"sec_{i+1}",
                    legendgrouptitle=dict(text=f"Section {i+1}", font=dict(color=color))
                )
                beat_time = 60/section_bpm
                stable_beats = np.arange((start_time-start_time%beat_time)-(section_offset/1000)%beat_time+beat_time, end_time, beat_time)
                onset_fig.add_scatter(
                    # just vertical lines
                    x=stable_beats.repeat(3), y=[0,1,None]*len(stable_beats),
                    name="Stable BPM",
                    line=dict(dash="dot", color=color),
                    mode="lines",
                    visible="legendonly",  # hide by default
                    legendgroup=f"sec_{i+1}",
                )
                onset_fig.add_scatter(
                    x=beats,
                    y=offset_error,
                    name="Offset Error",
                    line=dict(color=color),
                    mode="lines",
                    legendgroup=f"sec_{i+1}",
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
            if self.data is None or self.wall_densities is None:
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
            if self.data is None or self.note_densities is None:
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
                                x=pdc.plot_data[:,0], y=pdc.plot_data[:,1], name=f"{d} ({nt} {sub_t}s) [max {round(pdc.max_value)}]",
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

        def __repr__(self) -> str:
            return type(self).__name__  # avoid spamming logs with binary data

    fi = FileInfo()

    with ui.dialog() as help_dialog, ui.card():
        ui.markdown("""
            **This tab allows you to work .synth files directly.**

            The following features are supported:

            * Create new .synth files from audio files
                * many common formats (including `.mp3`) will be converted to `.ogg` via [libsndfile](http://www.mega-nerd.com/libsndfile)
            * Detect and edit BPM/Offset (without changing timing of existing objects)
                * Advanced audio processing to detect sections with different BPM via [librosa](https://librosa.org/)
                * Graphical representation of intermediate data (via [plotly](https://plotly.com/python/))
                * Manual BPM override
                * Shift offset by half beats for easy alignment
            * Replace audio file
            * View and edit metadata:
                * name, artist and mapper
                * cover image
            * Detect and correct certain types of file corruption or errors (NaN values, duplicate notes)
            * Merge files, including different BPM and Offset
            * Show stats
                * Object counts per difficulty
                * Density plot for Walls (including checks for PC or Quest limitations)
                * Density plot for Notes and Rails

            To start, just open a .synth file by clicking the plus button below.  
            You can also drag files directly onto these file selectors.

            Note: Sometimes the file upload gets stuck. In that case just press the button twice more (first time it will be an "X", the second time a upload-cloud icon)
        """)
    ui.button("What can I do here?", icon="help", color="info", on_click=help_dialog.open)
    
    with ui.row().classes("mb-4"):
        with ui.card().classes("mb-4"):
            with ui.upload(label="Select a .synth or audio file ->", auto_upload=True, on_upload=fi.upload).props('accept=".synth,audio/*,*"').classes("w-full").add_slot("list"):
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
            with ui.upload(label="One or more files", multiple=True, auto_upload=True, on_upload=fi.upload_merge).props('color="positive" accept=".synth,*"').classes("w-full").add_slot("list"):
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
