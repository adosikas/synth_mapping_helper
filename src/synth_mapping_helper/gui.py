from argparse import ArgumentParser, ArgumentError
from io import BytesIO
import logging
from typing import Optional

from nicegui import app, ui, events

from . import synth_format, cli, __version__
from .gui_tabs.utils import *
from .gui_tabs.commands import command_tab
from .gui_tabs.file_utils import file_utils_tab
from .gui_tabs.dashboard import dashboard_tab
from .gui_tabs.autobackup import autobackup_tab
from .gui_tabs.version import version_tab
from .gui_tabs.stacking import stacking_tab
from .gui_tabs.text_gen import text_gen_tab
from .gui_tabs.wall_art import wall_art_tab

tab_list = [
    ["Dashboard", "dashboard", dashboard_tab, None],
    ["Stacking", "layers", stacking_tab, None],
    ["Text", "rtt", text_gen_tab, None],
    ["Wall Art", "wallpaper", wall_art_tab, None],
    ["Commands", "play_arrow", command_tab, None],
    ["File utils", "construction", file_utils_tab, None],
    ["Autobackup", "manage_history", autobackup_tab, None],
    ["Version History", "update", version_tab, None],
]

async def stop():
    logger.info("Stopping...")
    await ui.run_javascript("setTimeout(window.close, 100);")
    app.shutdown()
def entrypoint():
    parser = ArgumentParser()
    parser.add_argument("-l", "--log-level", type=str, default="INFO", help="Set log level")
    parser.add_argument("--host", type=str, default="127.0.0.1",
        help="""Host for the webserver. Defaults to localhost.
            Can be set to a local IP if you want to access the GUI from another device, eg. tablet.\n
            Note that there is NO PASSWORD CHECK, so only use if you trust ALL devices on that network.""")
    parser.add_argument("--port", type=int, default=8080, help="Port for the webserver")
    parser.add_argument("--background", action="store_true", help="Open in background (does not open browser)")
    parser.add_argument("--dev-mode", action="store_true", help="Open in dev mode (reloads when editing python files)")

    args = parser.parse_args()

    @ui.page("/")
    def index():
        ui.add_head_html("""<style>
            .q-field__suffix {
                color: grey !important;
            }
            .q-field__bottom {
                min-height: 0 !important;
                padding: 0 !important;
            }
        </style>""")
        with ui.header(elevated=True):
            with ui.tabs() as tabs:
                for idx, (name, icon, *_) in enumerate(tab_list):
                    tab_list[idx][3] = ui.tab(name, icon=icon)
            with ui.button(icon="bug_report" + "support", color="negative", on_click=lambda _:ui.download("error_report", "smh_gui_error.json")).props("text-color=white").classes("ml-auto"):
                ui.tooltip("Save report of last error")
            with ui.element():
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
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler("smh_gui.log"),
            logging.StreamHandler()
        ]
    )
    if args.dev_mode:
        logging.getLogger("watchfiles.main").level = logging.WARN  # hide change detection

    logger.info(f"Starting v{__version__}{' in background' if args.background else ''}...")
    ui.run(
        host=args.host,
        port=args.port,
        title=f"SMH-GUI v{__version__} [beta]",
        favicon="🚧" if args.dev_mode else "🤦",
        reload=args.dev_mode,
        storage_secret="smh_gui",
        show=not args.background,
    )

if __name__ in {"__main__", "__mp_main__"}:
    entrypoint()
