from dataclasses import dataclass
import datetime
from io import BytesIO
from contextlib import contextmanager
import json
import logging
from typing import Any, Callable, Generator, Optional

from fastapi import Response
from nicegui import app, events, ui
from nicegui.storage import PersistentDict
import pyperclip

from .. import synth_format, __version__

__all__ = [
    "logger", "wiki_base",
    "GUITab",
    "error", "warning", "info",
    "wiki_reference", "try_load_synth_file", "add_suffix",
    "ParseInputError", "PrettyError", "handle_errors",
    "read_clipboard", "write_clipboard", "safe_clipboard_data",
]

logger = logging.getLogger("SMH-GUI")
wiki_base = "https://github.com/adosikas/synth_mapping_helper/wiki"

last_error: Optional[tuple[str, Exception, Any, Any, datetime]] = None

@dataclass
class GUITab:
    name: str
    label: str
    icon: str
    content_func: Callable

    def get_settings(self) -> dict[str, Any]:
        return {
            s_id.removeprefix(self.name + "_"): v
            for s_id, v in app.storage.user.items()
            if s_id.startswith(self.name)
        }

    def delete_settings(self) -> None:
        count = 0
        for s_id in list(app.storage.user):
            if s_id.startswith(self.name):
                count += 1
                del app.storage.user[s_id]
        logger.info(f"Deleted {count} settings for {self.label} tab")

class PrettyJSONResponse(Response):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return json.dumps(content, indent=2).encode("utf-8")

@app.get("/error_report", response_class=PrettyJSONResponse)
def error_report():
    if last_error is None:
        out = {
            "version": __version__,
            "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "msg": "No error yet"
        }
    else:
        msg, exc, context, data, time = last_error
        out = {
            "version": __version__,
            "time": time.isoformat(),
            "message": msg,
        }
        if exc is not None:
            out["exception"] = repr(exc)
            if exc.__cause__ is not None:
                out["exception_cause"] = repr(exc.__cause__)
        if context is not None:
            out["context"] = context
        if data is not None:
            out["data"] = data
    return out

def error(msg: str, exc: Optional[Exception]=None, context: Any = None, data: Any=None) -> None:
    global last_error
    last_error = (msg, exc, context, data, datetime.datetime.now(datetime.timezone.utc))
    logger.error(msg)
    if exc is not None:
        logger.debug("Stacktrace:", exc_info=exc)
    ui.notify(msg, type="negative", progress=True, group=False, caption=repr(exc) if exc is not None else None)

def warning(msg: str) -> None:
    logger.warning(msg)
    ui.notify(msg, type="warning", progress=True, group=False)

def info(msg: str, caption: Optional[str]=None) -> None:
    logger.info(msg)
    ui.notify(msg, type="positive", progress=True, caption=caption)

def wiki_reference(page: str, invert_colors: bool = False) -> ui.badge:
    b = ui.badge("?").style("cursor: help")
    if invert_colors:
        b.props("color=white text-color=primary")
    # .stop to stop event bubbling up to containers (ie button or switch)
    b.on("click.stop", lambda _ : ui.open(f"{wiki_base}/{page}", new_tab=True))
    with b:
        ui.tooltip(f"Open wiki: {page}")
    return b

def try_load_synth_file(e: events.UploadEventArguments) -> Optional[synth_format.SynthFile]:
    try:
        data = synth_format.import_file(BytesIO(e.content.read()))
    except Exception as exc:
        msg = f"Error reading {e.name} as SynthFile"
        e.sender.reset()
        error(msg, exc)
        return None
    if data.errors:
        warning("There was invalid data in the file, affected items were REMOVED:")
        for diff, errors in data.errors.items():
            for jpe, time in errors:
                warning(f"{diff}@{time}: {jpe}")
    return data

def add_suffix(filename: str, suffix: str) -> str:
    if not suffix:
        return filename
    return f"{filename.removesuffix('.synth')}_{suffix}.synth"

class ParseInputError(ValueError):
    def __init__(self, input_id: str, value: Any, exc: Optional[ValueError]=None, context: Any = None) -> None:
        self.input_id = input_id
        self.value = value
        self.exc = exc
        self.context = context

class PrettyError(RuntimeError):
    def __init__(self, msg: str, exc: Optional[Exception]=None, context: Any = None, data: Any = None) -> None:
        self.msg = msg
        self.exc = exc
        self.context = context
        self.data = data

# decorator for pretty error handling
def handle_errors(func: Callable) -> Callable:
    # Usage:
    #   @handle_errors
    #   def _do_stuff(...):
    #     try:
    #       ...
    #     except ... as ...:
    #       raise PrettyError(...)
    #   ui.button(on_click=_do_stuff)
    # Lambdas:
    #   ui.button(on_click=handle_errors(lambda ...))
    def _wrapped_func(*args, **kwargs) -> Any:
        try:
            return func(*args, **kwargs)
        except ParseInputError as pie:
            error(msg=f"Error parsing {pie.input_id} value: {pie.value!r}", exc=pie.exc, context=pie.context, data=pie.value)
        except PrettyError as pe:
            error(msg=pe.msg, exc=pe.exc, context=pe.context, data=pe.data)
        except Exception as exc:
            error(msg="Unexpected error. Please report this so a more useful message can show here.", exc=exc)
    return _wrapped_func

# wrappers, for when I decide to use the browser clipboard
def read_clipboard() -> str:
    return pyperclip.paste()

def write_clipboard(text: str) -> None:
    pyperclip.copy(text)

# like synth_format.clipboard_data, but reporting errors
@contextmanager
def safe_clipboard_data(use_original: bool = False, realign_start: bool = True, write: bool = True) -> Generator[Optional[synth_format.ClipboardDataContainer], None, None]:
    try:
        clipboard_in = read_clipboard()
    except RuntimeError as re:
        raise PrettyError(msg=f"Error reading clipboard", exc=re)
    if not clipboard_in:
        raise PrettyError(msg="Clipboard does not contain any data")
    if not clipboard_in.startswith("{") or not clipboard_in.endswith("}"):
        raise PrettyError(msg="Clipboard does not contain JSON data")
    try:
        data = synth_format.ClipboardDataContainer.from_json(clipboard_in, use_original=use_original)
    except ValueError as ve:
        raise PrettyError(msg=f"Error reading data in clipboard", exc=ve, data=clipboard_in)

    # don't catch any errors here, so clipboard is not written to on error
    yield data

    if not write:
        return

    try:
        clipboard_out = data.to_clipboard_json(realign_start=realign_start)
    except ValueError as ve:
        raise PrettyError(msg=f"Error outputting data for clipboard", exc=ve)
    try:
        write_clipboard(clipboard_out)
    except RuntimeError as re:
        raise PrettyError(msg=f"Error writing clipboard", exc=re)
