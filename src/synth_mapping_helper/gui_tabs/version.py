import datetime

from nicegui import app, ui
import requests

from .utils import error
from .. import __version__

releases = None

def version_tab():
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
                    time_delta_str = f"{time_delta.days} day{'' if time_delta.days==1 else 's'}" if time_delta.days else f"{time_delta.seconds//3600} day{'' if time_delta.seconds//3600==1 else 's'}"
                    v = r["tag_name"][1:]
                    color = "positive" if new else "dark"
                    icon = "stars" if new else "check_circle"
                    if v == __version__:
                        color = "primary"
                        icon = "play_circle"
                        new = False
                    with ui.expansion(f'{r["name"]} ({time_delta_str} ago)', icon=icon).props(f'group="ver_hist" header-class="bg-{color}"').classes("textcolor-red"):
                        ui.link(r["html_url"], target=r["html_url"], new_tab=True) 
                        ui.markdown(r["body"])
                except:
                    ui.label("Error parsing version information")
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

    with ui.card():
        release_list()

    with ui.row():
        ui.button("Check now", icon="sync", on_click=check)
        auto_check = ui.switch("Check on start", value=False).bind_value(app.storage.user, "version_history_autocheck")

    if auto_check.value:
        global releases
        if not releases:  # don't check if we already have data
            releases = []
            ui.timer(0.001, check, once=True)  # Use a timer to detect when the client connects
