from pathlib import Path
import time

from nicegui import app, events, ui
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from .local_dir_picker import local_dir_picker
from .utils import *

def _isdir(v: str) -> bool:
    return Path(v).is_dir()

last_check: dict[Path, float] = {}
last_backup: dict[Path, tuple[float, Path]] = {}

def _autobackup_tab() -> None:
    watcher_dir: Path|None = None
    def watcher_func() -> None:
        global last_check
        if not watcher_dir or "autobackup_backupdir" not in app.storage.user or "autobackup_minage" not in app.storage.user:
            return
        now = time.time()
        for p in watcher_dir.glob("*.synth"):
            if not p.is_file():
                continue
            if p.stat().st_mtime > last_check.get(watcher_dir, now):
                logger.debug(f"File change detected: {p}")
                if now - last_backup.get(p, (0,None))[0] > app.storage.user["autobackup_minage"]:
                    pb = Path(app.storage.user["autobackup_backupdir"]) / f"{p.stem}.{time.strftime('%Y-%m-%d_%H-%M-%S')}{p.suffix}"
                    logger.info(f"{p} changed, creating backup: {pb}")
                    pb.write_bytes(p.read_bytes())
                    last_backup[p] = (now, pb)
        last_check[watcher_dir] = now

        log.refresh()

    watcher = ui.timer(60, watcher_func, active=False)

    async def pick_dir(e: events.ClickEventArguments) -> None:
        key = "autobackup_workdir" if e.sender == workdir_picker else "autobackup_backupdir"
        result = await local_dir_picker(app.storage.user.get(key) or ".")
        if result is not None:
            input_element: ui.input = e.sender.parent_slot.parent  # type: ignore
            input_element.value = str(result)

    def dir_changed() -> None:
        nonlocal watcher_dir
        if not app.storage.user.get("autobackup_enabled"):
            watcher_dir = None
            watcher.active = False
            return
        p = app.storage.user.get("autobackup_workdir")
        if not p or not Path(p).is_dir():
            watcher_dir = None
            watcher.active = False
            return
        if watcher_dir == Path(p):
            return
        info(f"Now watching {p} for .synth file changes")
        watcher_dir = Path(p)
        last_check[Path(p)] = time.time()
    dir_changed()

    with ui.row():
        ui.switch("Enable Autobackup", value=False, on_change=dir_changed).classes("my-auto").bind_value(watcher, "active").bind_value(app.storage.user, "autobackup_enabled")
        with ui.number("Check interval", value=60, suffix="s", min=15).props('input-style="text-align: right"').classes("w-20").bind_value(watcher, "interval").bind_value(app.storage.user, "autobackup_interval"):
            ui.tooltip("Amount of time between checks")
        with ui.number("Minimum age", value=300, suffix="s").props('input-style="text-align: right"').classes("w-20").bind_value(app.storage.user, "autobackup_minage"):
            ui.tooltip("If > 0, backups are not created if the last backup was less than X seconds ago")
        with ui.input("Editor working directory", validation={"Not a directory": _isdir}, on_change=dir_changed).classes("w-96").bind_value(app.storage.user, "autobackup_workdir"):
            workdir_picker = ui.button(on_click=pick_dir, icon="pageview").props("outline").classes("my-auto")
            ui.tooltip("Directory with the .synth files you want to monitor")
        with ui.input("Backup directory", validation={"Not a directory": _isdir}, on_change=dir_changed).classes("w-96").bind_value(app.storage.user, "autobackup_backupdir"):
            backupdir_picker = ui.button(on_click=pick_dir, icon="archive").props("outline").classes("my-auto")
            ui.tooltip("Directory to save the backups to")

    @ui.refreshable
    def log() -> None:
        for _, b in sorted(last_backup.values(), key=lambda tb: tb[0], reverse=True):
            ui.label(str(b))

    ui.label("Last backup:").classes("my-4")
    with ui.card().classes("w-full"):
            log()

autobackup_tab = GUITab(
    name="autobackup",
    label="AutoBackup",
    icon="manage_history",
    content_func=_autobackup_tab,
)
