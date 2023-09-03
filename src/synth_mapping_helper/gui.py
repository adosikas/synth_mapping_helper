from argparse import ArgumentParser, ArgumentError
from io import BytesIO
import logging
from typing import Optional

from nicegui import app, ui, events
from fastapi.responses import Response

from . import synth_format, cli

download_content: BytesIO = BytesIO()
logger = logging.getLogger("SMH-GUI")

presets = {
    "Merge Rails": "--merge-rails",
    "Split Rails": "--split-rails",
}
wiki_base = "https://github.com/adosikas/synth_mapping_helper/wiki"

@app.get("/download")
def download():
    download_content.seek(0)
    return Response(download_content.read())

def wiki_reference(page: str) -> ui.badge:
    b = ui.badge("?").style("cursor: help")
    b.on("click.stop", lambda _ : ui.open(f"{wiki_base}/{page}", new_tab=True))
    with b:
        ui.tooltip(f"Open wiki: {page}")
    return b

def try_load_synth_file(e: events.UploadEventArguments) -> Optional[synth_format.SynthFile]:
    try:
        return synth_format.import_file(BytesIO(e.content.read()))
    except Exception as exc:
        msg = f"Error reading {e.name} as SynthFile: {exc!r}"
        e.sender.reset()
        logger.error(msg)
        ui.notify(msg, type="warning")
    return None

def add_suffix(filename: str, suffix: str) -> str:
    return f"{filename.removesuffix('.synth')}_{suffix}.synth"

def home_tab():
    with ui.card().style("max-width: 400px"):
        ui.label("Welcome.")
        ui.label("Select one of the tabs above.")

def command_tab():
    @ui.refreshable
    def quick_run_buttons():
        for p in presets:
            ui.button(p, icon="fast_forward", on_click=run_preset)

    def presets_updated():
        preset_selector.set_options(list(presets))
        quick_run_buttons.refresh()

    def load_commands(e: events.UploadEventArguments):
        data = e.content.read()
        try:
            presets[e.name] = data.decode()
            presets_updated()
            preset_selector.value = e.name  # this also loads the content
        except UnicodeDecodeError as exc:
            msg = f"Error reading commands from {e.name}"
            logger.error(msg)
            ui.notify(msg, type="negative")
        e.sender.reset()

    def run_command():
        p = cli.get_parser()
        p.exit_on_error = False
        commands = command_input.value.splitlines()
        count = 0
        for i, line in enumerate(commands):
            if line.startswith("#"):
                continue
            error = None
            args = line.split(" ")
            if not count and use_orig_cb.value:
                args.append("--use-original")
            if mirror_left_cb.value:
                args.append("--mirror-left")

            try:
                opts, remaining = p.parse_known_args(args)
            except ArgumentError as exc:
                error = f"Error parsing line {i+1}: {exc!s}"
            else:
                if remaining:
                    error = f"Unknown arguments in line {i+1}: {remaining}"
                else:
                    try:
                        cli.main(opts)
                    except RuntimeError as exc:
                        error = f"Error running line {i+1}: {exc!r}"
            if error:
                logger.error(error)
                ui.notify(error, type="negative")
                break
            count += 1
        else:
            if preset_selector.value:
                message = f"Sucessfully executed preset '{preset_selector.value}' ({count} command{'s'*(count>1)})"
            else:
                message = f"Sucessfully executed {count} command{'s'*(count>1)}"
            logger.info(message)
            ui.notify(message, type="positive")

    def run_preset(e: events.ClickEventArguments):
        preset_selector.value = e.sender.text
        run_command()

    def load_presets():
        global presets
        loaded_presets = app.storage.user.get("command_presets")
        if loaded_presets:
            presets = {**loaded_presets}  # copy
            presets_updated()
            logger.info(f"Loaded {len(presets)} presets")

    def save_presets():
        app.storage.user["command_presets"] = presets
        logger.info(f"Saved {len(presets)} presets")

    def add_preset():
        presets[add_preset_name.value] = command_input.value
        presets_updated()
        preset_selector.value = add_preset_name.value
        add_dialog.close()

    with ui.dialog() as add_dialog, ui.card():
        add_preset_name = ui.input("Preset name", value="Untitled")
        with ui.row():
            ui.button("Cancel", icon="cancel", on_click=add_dialog.close).props("flat")
            ui.button("Add", icon="add", color="green", on_click=add_preset)

    def delete_preset(e: events.ClickEventArguments):
        del presets[preset_selector.value]
        presets_updated()
        preset_selector.value = None
        remove_dialog.close()

    with ui.dialog() as remove_dialog, ui.card():
        remove_confirmation_label = ui.label("Really delete?")
        with ui.row():
            ui.button("Cancel", icon="cancel", on_click=remove_dialog.close).props("flat")
            ui.button("Delete", icon="delete", color="red", on_click=delete_preset)

    with ui.card():
        with ui.row():
            with ui.select(list(presets), with_input=True) as preset_selector:
                ui.tooltip("Select a preset")
            preset_selector.bind_value(app.storage.user, "command_preset")
            with ui.button(icon="delete", color="red", on_click=remove_dialog.open).classes("m-auto").bind_enabled_from(preset_selector, "value"):
                ui.tooltip("Delete current preset")
            with ui.button(icon="add", color="green", on_click=add_dialog.open).classes("m-auto") as add_button:
                ui.tooltip("Add current command as preset")
            ui.upload(label="Add from file", auto_upload=True, multiple=True, on_upload=load_commands).classes("h-14 w-40")
            with ui.button(icon="restore", on_click=load_presets).classes("m-auto"):
                ui.tooltip("Restore presets")
            with ui.button(icon="save", on_click=save_presets).classes("m-auto"):
                ui.tooltip("Store presets")
        ui.separator()
        command_input = ui.textarea("Commands", placeholder="--offset=1,0,0", on_change=lambda e: presets.get(preset_selector.value) == e.value or preset_selector.set_value(None)).props("autogrow").classes("w-full")
        command_input.bind_value(app.storage.user, "command_input")
        preset_selector.bind_value_to(command_input, forward=lambda v: v and presets.get(v))
        preset_selector.bind_value_to(remove_confirmation_label, "text", forward=lambda v: f"Really delete '{v}'?")
        add_button.bind_enabled_from(command_input, "value")

        with ui.row():
            ui.button("Execute", icon="play_arrow", on_click=run_command).bind_enabled_from(command_input, "value")
            with ui.checkbox("Use original JSON") as use_orig_cb:
                wiki_reference("Miscellaneous-Options#use-original-json")
            with ui.checkbox("Mirror for left hand") as mirror_left_cb:
                wiki_reference("Miscellaneous-Options#mirror-operations-for-left-hand")
        ui.separator()
    
        ui.label("Quick run:")
        with ui.row():
            quick_run_buttons()

    load_presets()

def bpmchange_tab():
    def upload(e: events.UploadEventArguments) -> None:
        bpm = newbpm_input.value
        data = try_load_synth_file(e)
        if data is None:
            return
        data.change_bpm(bpm)

        download_content.truncate()
        data.save_as(download_content)
        ui.download("download", filename=add_suffix(e.name, f"bpm_{bpm}"))

        e.sender.reset()

    with ui.card().style("max-width: 400px"):
        newbpm_input = ui.number("New BPM", value=60).bind_value(app.storage.user, "bpm_change")

        ui.separator()

        ui.label("Select a .synth files.")
        ui.label("Tip: You can use drag and drop.")
        ui.upload(label="Target files", auto_upload=True, on_upload=upload).classes("h-14 w-100")
        ui.label("The result is downloaded automatically.")


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

tab_list = [
    ["Home", "home", home_tab, None],
    ["Commands", "play_arrow", command_tab, None],
    ["Change BPM", "speed", bpmchange_tab, None],
    ["Merge Files", "merge", merge_tab, None],
]

async def stop():
    logger.info("Stopping...")
    await ui.run_javascript("setTimeout(window.close, 100);")
    app.shutdown()

@ui.page("/")
def index():
    with ui.header(elevated=True):
        with ui.tabs() as tabs:
            for idx, (name, icon, *_) in enumerate(tab_list):
                tab_list[idx][3] = ui.tab(name, icon=icon)

        ui.button("Open wiki", icon="question_mark", color="white", on_click=lambda _:ui.open(wiki_base, new_tab=True)).classes("ml-auto").props("text-color=primary")
        ui.button(icon="close", color="red", on_click=stop).set_enabled(not args.dev_mode)
            
    with ui.tab_panels(tabs, value=tab_list[0][3]).classes("w-full"):
        for _, _, func, elem in tab_list:
            with ui.tab_panel(elem):
                func()

if __name__ in {"__main__", "__mp_main__"}:
    parser = ArgumentParser()
    parser.add_argument("-l", "--log-level", type=str, default="INFO", help="Set log level")
    parser.add_argument("--dev-mode", action="store_true", help="Open in dev mode (reloads when editing python files)")

    args = parser.parse_args()

    logging.basicConfig(
        format='%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
        level=args.log_level,
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logger.info("Starting...")
    ui.run(
        title="SMH-GUI [beta]",
        favicon="🚧" if args.dev_mode else "🤦",
        reload=args.dev_mode,
        dark=None,  # auto
        storage_secret="smh_gui"
    )