import datetime

from nicegui import app, ui
import requests
import logging

from .utils import GUITab, error
from .. import __version__
from ..utils import pretty_time_delta

releases = None

def _version_tab():
    @ui.refreshable
    def release_list():
        if releases == "error":
            ui.label("Error requesting version information")
        elif releases:
            now = datetime.datetime.now(datetime.timezone.utc)
            new = True
            for r in releases[:10]:
                try:
                    time_delta = now - datetime.datetime.fromisoformat(r["created_at"]).replace(tzinfo=datetime.timezone.utc)
                    name = r["name"]
                    v = r["tag_name"][1:]
                    url = r["html_url"]
                    body = r["body"]
                except:
                    ui.label("Error parsing version information")
                else:
                    color = "positive" if new else "auto"
                    icon = "stars" if new else "check_circle"
                    if v == __version__:
                        color = "primary"
                        icon = "play_circle"
                        new = False
                    with ui.expansion(f'{name} ({pretty_time_delta(time_delta.total_seconds())} ago)', icon=icon).props(f'group="ver_hist" header-class="bg-{color} w-auto"'):
                        with ui.row():
                            ui.label("Github link:")
                            ui.link(url, target=url, new_tab=True) 
                        with ui.card().props("bordered"):
                            ui.markdown(r["body"])
        elif releases is not None:
            with ui.row():
                ui.spinner()
                ui.label("Requesting...")
        else:
            ui.label("To protect your privacy, this does not automatically contact github.com. Press the button or enable auto-check below.")

    def check():
        global releases
        try:
            releases = []
            release_list.refresh()
            r = requests.get("https://api.github.com/repos/adosikas/synth_mapping_helper/releases")
            r.raise_for_status()
            new_data = r.json()
            if not isinstance(new_data, list):
                releases = "error"
                release_list.refresh()
                error("github.com returned unexpected data", data=new_data)
                return
            releases = new_data
            if releases[0]["tag_name"][1:] != __version__:
                ui.notify(
                    f"A new update is available: {releases[0]['name']}",
                    caption="To update, run the installer again",
                    type="info", close_button=True, timeout=0,
                )
            release_list.refresh()
        except Exception as exc:
            releases = "error"
            release_list.refresh()
            error("Requesting version information from github.com failed", exc)

    with ui.card().classes("w-full"):
        release_list()

    with ui.row():
        ui.button("Check now", icon="sync", on_click=check, color="positive")
        auto_check = ui.switch("Check on start", value=False).bind_value(app.storage.user, "version_history_autocheck")

    if auto_check.value:
        global releases
        if not releases:  # don't check if we already have data
            releases = []
            ui.timer(0.001, check, once=True)  # Use a timer to detect when the client connects

version_tab = GUITab(
    name="version_history",
    label="Version History",
    icon="update",
    content_func=_version_tab,
)