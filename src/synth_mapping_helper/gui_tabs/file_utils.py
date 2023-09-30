import dataclasses
from typing import Optional
import sys

from nicegui import app, events, ui

from .utils import *
from .. import synth_format
from .. import __version__

def file_utils_tab():
    @dataclasses.dataclass
    class FileInfo:
        data: Optional[synth_format.SynthFile] = None
        output_filename: str = "No file selected"
        output_bpm: float = 0
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
            self.output_bpm = 0
            self.merged_filenames = None
            self.info_card.refresh()

        def save(self) -> None:
            download_content.truncate()
            if self.output_bpm != self.data.bpm:
                self.data.change_bpm(self.output_bpm)
            self.data.save_as(download_content)
            ui.download("download", filename=self.output_filename)

        def save_errors(self):
            out = [
                "SMH-GUI fixed error report:",
                f"  SMH Version: {__version__}",
                f"  Base BPM: {self.data.bpm}",
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
            with ui.row():
                ui.input("Filename").classes("w-80").bind_value(self, "output_filename").bind_enabled_from(self, "is_valid")
                ui.number("BPM").classes("w-16").bind_value(self, "output_bpm").bind_enabled_from(self, "is_valid")
                ui.tooltip("Select a base file first").bind_visibility_from(self, "is_valid", backward=lambda v: not v).classes("bg-red")
            if self.data is None:
                return
            with ui.row().classes("w-full"):
                ui.button("clear", icon="clear", color="negative", on_click=self.clear)
                ui.button("save", icon="save", color="positive", on_click=self.save).classes("ml-auto")
            ui.separator()
            ui.aggrid({
                "domLayout": "autoHeight",
                "columnDefs": [
                    {"headerName": "Difficulty", "field": "diff"},
                    {"headerName": "Notes", "field": "notes"},
                    {"headerName": "Walls", "field": "walls"},
                    {"headerName": "Fixed Errors", "field": "errors"},
                ],
                "rowData": [
                    {"diff": d, "notes": c.notecount, "walls": len(c.walls), "errors": len(self.data.errors.get(d, []))} 
                    for d, c in self.data.difficulties.items()
                ],
            }).style("height: auto")
            ui.label(f"{len(self.data.bookmarks)} Bookmarks")
            if self.merged_filenames:
                ui.label("Merged:")
                for m in self.merged_filenames:
                    ui.label(m)
            if self.data.errors:
                with ui.button("Save error report", icon="summarize", color="warning", on_click=self.save_errors).classes("ml-auto"):
                    ui.tooltip("Use this if you want to re-add notes that were corrupted.")


    fi = FileInfo()

    with ui.card().classes("mb-4"):
        ui.label("Here you can work with .synth files directly. This can also fix some kinds of corrupted data.")
        ui.label("Tip: You can drag and drop files on the boxes below, including from the file selector.")
    
    with ui.row():
        with ui.card():
            ui.label("Base / Repair / BPM change")
            ui.upload(label="Base file", auto_upload=True, on_upload=fi.upload).classes("h-14 w-full")
            fi.info_card()
        with ui.card():
            ui.label("Merge files into base")
            ui.upload(label="One or more files", multiple=True, auto_upload=True, on_upload=fi.upload_merge).classes("h-14 w-full").bind_enabled_from(fi, "is_valid")
            ui.label("Note: BPM will be matched automatically.")
            ui.tooltip("Select a base file first").bind_visibility_from(fi, "is_valid", backward=lambda v: not v).classes("bg-red")