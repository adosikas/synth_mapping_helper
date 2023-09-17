from argparse import ArgumentParser, ArgumentError
from io import BytesIO
import logging
from typing import Optional

from nicegui import app, ui, events

from . import synth_format, cli
from .gui_tabs.utils import *
from .gui_tabs.commands import command_tab
from .gui_tabs.merge import merge_tab
from .gui_tabs.dashboard import dashboard_tab

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


tab_list = [
    ["Dashboard", "dashboard", dashboard_tab, None],
    ["Commands", "play_arrow", command_tab, None],
    ["Change BPM", "speed", bpmchange_tab, None],
    ["Merge Files", "merge", merge_tab, None],
]

async def stop():
    logger.info("Stopping...")
    await ui.run_javascript("setTimeout(window.close, 100);")
    app.shutdown()
if __name__ in {"__main__", "__mp_main__"}:
    parser = ArgumentParser()
    parser.add_argument("-l", "--log-level", type=str, default="INFO", help="Set log level")
    parser.add_argument("--dev-mode", action="store_true", help="Open in dev mode (reloads when editing python files)")

    args = parser.parse_args()

    @ui.page("/")
    def index():
        ui.add_head_html("""<style>
            .q-field__suffix {
                color: grey !important;
            }
        </style>""")
        with ui.header(elevated=True):
            with ui.tabs() as tabs:
                for idx, (name, icon, *_) in enumerate(tab_list):
                    tab_list[idx][3] = ui.tab(name, icon=icon)
            with ui.element().classes("ml-auto"):
                ui.tooltip("Switch dark mode")
                dark = ui.dark_mode(True)  # start in dark mode (matching editor)
                ui.button(icon="dark_mode", on_click=dark.enable).bind_visibility_from(dark, "value", backward=lambda v: v is not True).props('text-color=white')
                ui.button(icon="light_mode", on_click=dark.disable).bind_visibility_from(dark, "value", backward=lambda v: v is not False).props('text-color=white')

            with ui.button(icon="question_mark", color="white", on_click=lambda _:ui.open(wiki_base, new_tab=True)).props("text-color=primary"):
                ui.tooltip("Open wiki")
            with ui.button(icon="close", color="red", on_click=stop) as close_button:
                if args.dev_mode:
                    ui.tooltip("Cannot stop in dev mode, abort script manually")
                    close_button.set_enabled(False)
                else:
                    ui.tooltip("Quit")
                
        with ui.tab_panels(tabs, value=tab_list[0][0]).classes("w-full").bind_value(app.storage.user, "active_tab"):
            for _, _, func, elem in tab_list:
                with ui.tab_panel(elem):
                    func()


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
        storage_secret="smh_gui"
    )