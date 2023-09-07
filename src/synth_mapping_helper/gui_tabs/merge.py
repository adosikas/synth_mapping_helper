from nicegui import app, events, ui

from .utils import *

def merge_tab():
    base_file: Optional[synth_format.SynthFile] = None
    base_filename: Optional[str] = None
    merged_filenames: list[str] = []

    def clear(e: events.ClickEventArguments) -> None:
        nonlocal base_file
        nonlocal base_filename
        base_file = None
        base_filename = None
        merged_filenames.clear()
        info_card.refresh()
        stepper.set_value("Base File")

    @ui.refreshable
    def info_card() -> None:
        if base_file is None:
            ui.label("No file selected")
            return

        ui.label(f"Base: {base_filename} - {base_file.bpm} BPM")
        ui.aggrid({
            "domLayout": "autoHeight",
            "columnDefs": [
                {"headerName": "Difficulty", "field": "diff"},
                {"headerName": "Notes", "field": "notes"},
                {"headerName": "Walls", "field": "walls"},
            ],
            "rowData": [
                {"diff": d, "notes": c.notecount, "walls": len(c.walls)} 
                for d, c in base_file.difficulties.items()
            ],
        }).style("height: auto")
        ui.label(f"{len(base_file.bookmarks)} Bookmarks")
        if merged_filenames:
            ui.label("Merged:")
            for m in merged_filenames:
                ui.label(m)

    def upload_base(e: events.UploadEventArguments) -> None:
        nonlocal base_file
        nonlocal base_filename
        base_file = try_load_synth_file(e)
        if base_file is None:
            return
        base_filename = e.name
        merged_filenames.clear()

        e.sender.reset()
        info_card.refresh()
        stepper.next()

    def upload_other(e: events.UploadEventArguments) -> None:
        other = try_load_synth_file(e)
        if other is None:
            return
        base_file.merge(other)
        merged_filenames.append(e.name)
    
        e.sender.reset()
        info_card.refresh()

    def save(e: events.ClickEventArguments) -> None:
        download_content.truncate()
        base_file.save_as(download_content)
        ui.download("download", filename=add_suffix(base_filename, "merged"))

    with ui.stepper().style("max-width: 400px") as stepper:
        with ui.step("Base File"):
            ui.label("Select any .synth file.")
            ui.label("Tip: You can drag and drop.")
            ui.upload(label="Base file", auto_upload=True, on_upload=upload_base).classes("h-14 w-full")
            with ui.stepper_navigation():
                with ui.row().classes("w-full"):
                    with ui.button("Next").classes("ml-auto") as next_btn:
                        ui.tooltip("No base file selected")
                    next_btn.set_enabled(False)
        with ui.step("Merge Files"):
            ui.label("Select one or more files to merge.")
            ui.label("BPM will automatically be matched to the base.")
            ui.label("Tip: You can drag from the file selector too.")
            ui.upload(label="Merge files", multiple=True, auto_upload=True, on_upload=upload_other).classes("h-14 w-full")
            with ui.stepper_navigation():
                with ui.row().classes("w-full"):
                    ui.button("Restart", on_click=clear, icon="clear").props("flat")
                    ui.button("Save", on_click=save, icon="save").classes("ml-auto")
    with ui.card().style("max-width: 400px"):
        info_card()
