from io import BytesIO
import logging
from typing import Optional

from fastapi import Response
from nicegui import app, events, ui

from .. import synth_format

logger = logging.getLogger("SMH-GUI")
download_content: BytesIO = BytesIO()
wiki_base = "https://github.com/adosikas/synth_mapping_helper/wiki"

@app.get("/download")
def download():
    download_content.seek(0)
    return Response(download_content.read())

def wiki_reference(page: str) -> ui.badge:
    b = ui.badge("?").style("cursor: help")
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
        logger.error(msg)
        ui.notify(msg, type="warning")
    return None

def add_suffix(filename: str, suffix: str) -> str:
    return f"{filename.removesuffix('.synth')}_{suffix}.synth"