import asyncio
from contextlib import contextmanager
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
import datetime
from functools import wraps
from io import BytesIO
import json
import math
import logging
import traceback
from typing import Any, Callable, Generator, Optional

from fastapi import Response
from nicegui import app, events, ui, binding, run
from nicegui.storage import PersistentDict
import pyperclip

from .. import synth_format, utils, __version__

__all__ = [
    "logger", "wiki_base",
    "GUITab", "SMHInput",
    "error", "warning", "info",
    "wiki_reference", "try_load_synth_file", "add_suffix",
    "ParseInputError", "PrettyError", "handle_errors",
    "read_clipboard", "write_clipboard", "safe_clipboard_data",
]

logger = logging.getLogger("SMH-GUI")
wiki_base = "https://github.com/adosikas/synth_mapping_helper/wiki"

last_errors: list[tuple[str, Exception|None, Any, Any, datetime.datetime]] = []

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


class SMHInput(ui.input):
    def __init__(self,
        storage_id: Optional[str],
        label: str,
        default_value: str|float,
        tooltip: Optional[str] = None,
        suffix: Optional[str] = None,
        negate_icons: dict[int, str]|None = None,
        tab_id: Optional[str] = None,
        width: int = 12,
        height: int = 10,
        **input_kwargs: Any,
    ):
        super().__init__(label=label, value=str(default_value), validation=self._validate, **input_kwargs)
        if storage_id is not None:
            if tab_id is not None:
                storage_id = f"{tab_id}_{storage_id}"
            self.bind_value(app.storage.user, storage_id)
        self.classes(f"w-{width} h-{height}")
        self.props('dense input-style="text-align: right" no-error-icon')
        self.storage_id = storage_id
        self.default_value = default_value
        if suffix:
            self.props(f'suffix="{suffix}"')
        if tooltip is not None:
            self.tooltip(tooltip)
        if negate_icons is not None:
            negate_icons = {1: "add", 0: "close", -1: "remove"} | negate_icons
            def _negate(val: str|None) -> str|None:
                if not val:
                    return val
                if val.startswith("-"):
                    return val[1:]
                return "-" + val
            def _get_icon(val: str|None) -> str:
                if not val:  # empty string or None
                    return negate_icons[0]
                try:
                    v = utils.parse_number(val)
                except ValueError:
                    return "error"
                if v > 0:
                    return negate_icons[1]
                if v < 0:
                    return negate_icons[-1]
                return negate_icons[0]
            with self.add_slot("prepend"):
                self.icon = ui.icon("", color="primary").classes("border-2 rounded cursor-pointer").on(
                    "click", lambda e: self.set_value(_negate(self.value))
                ).bind_name_from(self, "value", _get_icon)
                ui.tooltip("Click to negate")
        with self.add_slot("error"):
            ui.element().style("visiblity: hidden")

    def _validate(self, value: Any) -> None|str:
        try:
            v = utils.parse_number(value)
            return None
        except ValueError:
            return ""

    @property
    def parsed_value(self) -> float:
        try:
            return utils.parse_number(self.value)
        except ValueError as ve:
            raise ParseInputError(input_id=self.storage_id or "input", value=self.value, exc=ve) from ve

class PrettyJSONResponse(Response):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return json.dumps(content, indent=2).encode("utf-8")

@app.get("/error_report", response_class=PrettyJSONResponse)
def error_report():
    out = {
        "version": __version__,
        "report_time": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ"),
        "errors": [],
    }
    for msg, exc, context, data, time in last_errors:
        err = {
            "time": time.strftime("%Y-%m-%dT%H-%M-%SZ"),
            "message": msg,
        }
        if exc is not None:
            err["exception"] = repr(exc)
            if exc.__cause__ is not None:
                err["exception_cause"] = repr(exc.__cause__)
            err["traceback"] = [l for tb in traceback.format_exception(exc, chain=True) for l in tb.splitlines()]
        if context is not None:
            err["context"] = context
        if data is not None:
            err["data"] = data
        out["errors"].append(err)
    return out

def error(msg: str, exc: Optional[Exception]=None, context: Any = None, data: Any=None) -> None:
    last_errors.append((msg, exc, context, data, datetime.datetime.now(datetime.timezone.utc)))
    logger.error(msg+(" " + repr(exc) if exc is not None else ""))
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
    b.on("click.stop", lambda _ : ui.navigate.to(f"{wiki_base}/{page}", new_tab=True))
    with b:
        ui.tooltip(f"Open wiki: {page}")
    return b

def try_load_synth_file(e: events.UploadEventArguments) -> Optional[synth_format.SynthFile]:
    try:
        data = synth_format.import_file(BytesIO(e.content.read()))
    except Exception as exc:
        msg = f"Error reading {e.name} as SynthFile"
        upl: ui.upload = e.sender  # type: ignore
        upl.reset()
        error(msg, exc)
        return None
    if data.errors:
        warning("There was invalid data in the file, affected items were REMOVED:")
        for diff, errors in data.errors.items():
            if len(errors) > 3:
                warning(f"{diff}: {len(errors)} errors. See the error report for details.")
            else:
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
    @contextmanager
    def _catch_errors():
        try:
            yield
        except ParseInputError as pie:
            error(msg=f"Error parsing {pie.input_id} value: {pie.value!r}", exc=pie.exc, context=pie.context, data=pie.value)
        except PrettyError as pe:
            error(msg=pe.msg, exc=pe.exc, context=pe.context, data=pe.data)
        except BrokenProcessPool as bpe:
            error(msg="Sound library error occurred. I am waiting for a fix for that. In the meantime, avoid this function.", exc=bpe)
            run.process_pool = run.ProcessPoolExecutor()  # attempt to restore process pool
        except Exception as exc:
            error(msg="Unexpected error. Please report this by clicking the report button in the top-right and sending me the report.", exc=exc)

    if asyncio.iscoroutinefunction(func):
        @wraps(func)
        async def _wrapped_async_func(*args, **kwargs) -> Any:
            with _catch_errors():
                return await func(*args, **kwargs)
        return _wrapped_async_func
    @wraps(func)
    def _wrapped_sync_func(*args, **kwargs) -> Any:
        with _catch_errors():
            return func(*args, **kwargs)
    return _wrapped_sync_func

# wrappers, for when I decide to use the browser clipboard
def read_clipboard() -> str:
    return pyperclip.paste()

def write_clipboard(text: str) -> None:
    pyperclip.copy(text)

# like synth_format.clipboard_data, but reporting errors
@contextmanager
def safe_clipboard_data(use_original: bool = False, realign_start: bool = True, write: bool = True) -> Generator[synth_format.ClipboardDataContainer, None, None]:
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
    except (KeyError, ValueError) as fje:
        raise PrettyError(msg="Error reading data in clipboard", exc=fje, data=clipboard_in)

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

class PreventDefaultKeyboard(ui.keyboard, component="prevent_default_keyboard.js"):
    def bind_active_from(self,
                        target_object: Any,
                        target_name: str = 'active',
                        backward: Callable[..., Any] = lambda x: x,
                        ) -> "Self":
        binding.bind_from(self, 'active', target_object, target_name, backward)
        return self
