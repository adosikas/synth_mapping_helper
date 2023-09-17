from io import BytesIO
import logging
from typing import Optional

from fastapi import Response
from nicegui import app, events, ui

from .. import synth_format

__all__ = [
    "logger", "download_content", "wiki_base",
    "error", "warning", "info",
    "wiki_reference", "try_load_synth_file", "add_suffix",
]

logger = logging.getLogger("SMH-GUI")
download_content: BytesIO = BytesIO()
wiki_base = "https://github.com/adosikas/synth_mapping_helper/wiki"

@app.get("/download")
def download():
    download_content.seek(0)
    return Response(download_content.read())

def error(msg: str, exc: Optional[Exception]=None) -> None:
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
        return synth_format.import_file(BytesIO(e.content.read()))
    except Exception as exc:
        msg = f"Error reading {e.name} as SynthFile: {exc!r}"
        e.sender.reset()
        error(msg)
    return None

def add_suffix(filename: str, suffix: str) -> str:
    return f"{filename.removesuffix('.synth')}_{suffix}.synth"