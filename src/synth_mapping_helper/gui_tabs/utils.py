import datetime
from io import BytesIO
import json
import logging
from typing import Any, Optional

from fastapi import Response
from nicegui import app, events, ui

from .. import synth_format, __version__

__all__ = [
    "logger", "download_content", "wiki_base",
    "error", "warning", "info",
    "wiki_reference", "try_load_synth_file", "add_suffix",
    "ParseInputError"
]

logger = logging.getLogger("SMH-GUI")
download_content: BytesIO = BytesIO()
wiki_base = "https://github.com/adosikas/synth_mapping_helper/wiki"

last_error: Optional[tuple[str, Exception, Any, Any]] = None

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
        msg, exc, settings, data = last_error
        out = {
            "version": __version__,
            "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "message": msg,
        }
        if exc is not None:
            out["exception"] = repr(exc)
            if exc.__cause__ is not None:
                out["exception_cause"] = repr(exc.__cause__)
        if settings is not None:
            out["settings"] = settings
        if data is not None:
            out["data"] = data
    return out

@app.get("/download")
def download():
    download_content.seek(0)
    return Response(download_content.read())

def error(msg: str, exc: Optional[Exception]=None, settings: Any = None, data: Any=None) -> None:
    global last_error
    last_error = (msg, exc, settings, data)
    logger.error(msg, exc_info=exc is not None)
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
    def __init__(self, input_id: str, value: Any) -> None:
        self.input_id = input_id
        self.value = value