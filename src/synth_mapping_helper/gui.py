from multiprocessing import freeze_support
freeze_support()

from argparse import ArgumentParser
from pathlib import Path
import logging
import sys

from nicegui import app, ui
import requests

from synth_mapping_helper import __version__
from synth_mapping_helper.gui_tabs.utils import *
from synth_mapping_helper.gui_tabs.commands import command_tab
from synth_mapping_helper.gui_tabs.file_utils import file_utils_tab
from synth_mapping_helper.gui_tabs.dashboard import dashboard_tab
from synth_mapping_helper.gui_tabs.autobackup import autobackup_tab
from synth_mapping_helper.gui_tabs.version import version_tab
from synth_mapping_helper.gui_tabs.stacking import stacking_tab
from synth_mapping_helper.gui_tabs.text_gen import text_gen_tab
from synth_mapping_helper.gui_tabs.wall_art import wall_art_tab

tab_list: list[GUITab] = [
    dashboard_tab,
    stacking_tab,
    text_gen_tab,
    wall_art_tab,
    command_tab,
    file_utils_tab,
    autobackup_tab,
    version_tab,
]

version = f"SMH-GUI v{__version__}"

@app.get("/version")
def get_version():
    return version

async def stop():
    logger.info("Stopping...")
    await ui.run_javascript("setTimeout(window.close, 100);")
    app.shutdown()

def entrypoint():
    parser = ArgumentParser(description=version)
    parser.add_argument("-l", "--log-level", type=str, help="Set log level")
    parser.add_argument("--host", type=str, default="127.0.0.1",
        help="""Host for the webserver. Defaults to 127.0.0.1 (localhost).
            Can be set to a local IP if you want to access the GUI from another device, eg. tablet.\n
            Note that there is NO PASSWORD CHECK, so only use if you trust ALL devices on that network to have access to your clipboard and files.""")
    parser.add_argument("--port", type=int, default=8080, help="Port for the webserver")
    parser.add_argument("--background", action="store_true", help="Open in background (does not open browser)")
    parser.add_argument("--dev-mode", action="store_true", help="Open in dev mode (reloads when editing python files)")

    args = parser.parse_args()
    if args.log_level is None:
        args.log_level = "DEBUG" if args.dev_mode else "INFO"

    if not args.dev_mode and __name__ == "__main__":  # don't check in dev mode or when spawned as child process
        try:
            resp = requests.get(f"http://{args.host}:{args.port}/version", timeout=1)
            resp.raise_for_status()
            print(f"ERROR: {resp.json()} is already running on http://{args.host}:{args.port}")
            sys.exit(-1)
        except requests.ConnectionError:
            # we want an connection error to occur, else there is another instance (or something else) running
            pass
        except Exception as e:
            # unexpected error getting or parsing version
            print(f"ERROR: Could not check if there is another instance already running on http://{args.host}:{args.port}")
            print(f"           {e!r}")
            print("       If this persists after a restart, something else may be using that port and you could add e.g. --port=8181 to change the SMH-GUI port")
            sys.exit(-1)

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
            .q-uploader__header-content {
                padding: 0px !important;
            }
            .q-uploader__list {
                min-height: 0 !important;
                padding: 0 !important;
            }
        </style>""")
        with ui.header(elevated=True):
            with ui.tabs() as tabs:
                tab_containers = [
                    ui.tab(name=t.name, label=t.label, icon=t.icon)
                    for t in tab_list
                ]
            with ui.button(icon="bug_report" + "support", color="negative", on_click=lambda _:ui.download("error_report", "smh_gui_error.json")).props("text-color=white").classes("ml-auto"):
                ui.tooltip("Save report of last error")
            with ui.element():
                ui.tooltip("Switch dark mode")
                dark = ui.dark_mode(True)  # start in dark mode (matching editor)
                ui.button(icon="dark_mode", on_click=dark.enable).bind_visibility_from(dark, "value", backward=lambda v: v is not True).props('text-color=white')
                ui.button(icon="light_mode", on_click=dark.disable).bind_visibility_from(dark, "value", backward=lambda v: v is not False).props('text-color=white')

            with ui.button(icon="question_mark", color="white", on_click=lambda _:navigate.to(wiki_base, new_tab=True)).props("text-color=primary"):
                ui.tooltip("Open wiki")
            with ui.button(icon="close", color="red", on_click=stop) as close_button:
                ui.tooltip("Quit")
                
        with ui.tab_panels(tabs, value=tab_list[0].name).classes("w-full").bind_value(app.storage.user, "active_tab"):
            for t in tab_list:
                with ui.tab_panel(t.name) as panel:
                    try:
                        t.content_func()
                    except Exception as exc:
                        panel.clear()
                        error(f"Error loading {t.label} tab", exc=exc, context=t.name, data=t.get_settings())
                        ui.label(f"Error loading {t.label} tab: {exc!r}")
                        ui.label("Consider sending me the error report, so this can be avoided in the future.")
                        ui.label("You may try reverting to the default settings below.")
                        ui.button("Delete settings", icon="delete", color="negative", on_click=lambda: t.delete_settings())

    logging.basicConfig(
        format='%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
        level=args.log_level,
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler("smh_gui.log"),
            logging.StreamHandler()
        ]
    )
    # hide some spammy logs
    for ln in ("watchfiles", "multipart", "numba"):
        logging.getLogger(ln).setLevel(logging.WARN)

    if __name__ == "__main__":  # don't run when spawned as child process
        logger.info(f"Starting {version}{' in background' if args.background else ''}. Working directory: {Path().absolute()}")
    ui.run(
        host=args.host,
        port=args.port,
        title=f"{version} [beta]",
        favicon="🚧" if args.dev_mode else "🤦",
        reload=args.dev_mode,
        storage_secret="smh_gui",
        show=not args.background,
    )

if __name__ in {"__main__", "__mp_main__"}:
    entrypoint()
