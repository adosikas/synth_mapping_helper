# based on: https://github.com/zauberzeug/nicegui/blob/main/examples/local_file_picker/local_file_picker.py
import platform
from pathlib import Path
from typing import Optional

from nicegui import events, ui

class local_dir_picker(ui.dialog):

    def __init__(self, directory: str) -> None:
        """Local File Picker

        This is a simple file picker that allows you to select a file from the local filesystem where NiceGUI is running.

        :param directory: The directory to start in.
        :param upper_limit: The directory to stop at (None: no limit, default: same as the starting directory).
        """
        super().__init__()
        with self, ui.card():
            self.add_drives_toggle()
            self.path_input = ui.input(
                "Directory",
                on_change=lambda e: self.set_path(e.value),
                validation={"Not a directory": lambda v: v and Path(v).is_dir()}
            ).props("no-error-icon").classes("w-full")
            self.grid = ui.aggrid({
                'columnDefs': [{'field': 'name', 'headerName': 'Directory'}],
            }, html_columns=[0]).classes('w-96').on('cellClicked', lambda e: self.set_path(e.args['data']['path']))
            with ui.row().classes('w-full justify-end'):
                with ui.button('Cancel', on_click=self.close).props('outline'):
                    ui.tooltip(f"Keeps current path: {directory}")
                ui.button('Ok', on_click=lambda v: self.submit(self.path))
        self.set_path(directory)


    def add_drives_toggle(self):
        with ui.row():
            with ui.button(icon="home", on_click=lambda _: self.set_path("~")):
                ui.tooltip(f"User home: {Path('~').expanduser()}")
            with ui.button(icon="terminal", on_click=lambda _: self.set_path(str(Path().absolute()))):
                ui.tooltip(f"Current directory: {Path().absolute()}")
            if platform.system() == 'Windows':
                import win32api
                drives = win32api.GetLogicalDriveStrings().split('\000')[:-1]
                ui.toggle(drives, value=drives[0], on_change=lambda e: self.set_path(e.value))
            else:
                with ui.button("/", on_click=lambda _: self.set_path("/")):
                    ui.tooltip("Filesystem root")

    def set_path(self, p: str):
        pp = Path(p).expanduser().absolute()
        if p and pp.is_dir():
            self.path = pp
            self.path_input.value = str(pp)
            self.path_input.set_autocomplete(list(str(p) for p in pp.iterdir() if p.is_dir()))
            self._update_grid()

    def _update_grid(self) -> None:
        paths = list(p for p in self.path.iterdir() if p.is_dir())
        paths.sort(key=lambda p: p.name.lower())

        self.grid.options['rowData'] = [
            {
                'name': f'📁 <strong>{p.name}</strong>',
                'path': str(p),
            }
            for p in paths
        ]
        if self.path != self.path.parent:
            self.grid.options['rowData'].insert(0, {
                'name': '↖️ <strong>..</strong>',
                'path': str(self.path.parent),
            })
        self.grid.update()
