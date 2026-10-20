"""Builder files: 3D models, wiring diagrams, firmware sources and bundles.

A thin router over builder/service.py: the listing, include-inlining and
ZIP-building there is blocking filesystem work, so every call runs in a
worker thread, and its errors map to HTTP statuses here.
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse

from . import service
from .service import BuilderFileError, BuilderFileNotFoundError, InvalidBuilderPathError, ScadInlineError

router = APIRouter()
log = logging.getLogger(__name__)


def _http_error(exc: BuilderFileError) -> HTTPException:
    if isinstance(exc, BuilderFileNotFoundError):
        return HTTPException(404, str(exc))
    if isinstance(exc, InvalidBuilderPathError):
        return HTTPException(400, str(exc))
    return HTTPException(500, str(exc))


def _zip_response(data: bytes, filename: str) -> StreamingResponse:
    return StreamingResponse(
        iter([data]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )


@router.get("/models")
async def list_models():
    """List available OpenSCAD 3D print model files (top level only — the
    shared helpers under models/lib/ are not printable models).

    Each entry carries `title` and `description` read from the model's own
    header comment (`description_truncated` when the description is cut
    short of it), `url` (self-contained download with lib/ inlined) and
    `source_url` (the file on GitHub)."""
    return await asyncio.to_thread(service.list_models)


@router.get("/models-bundle.zip")
async def download_models_bundle():
    """Download every model plus models/lib/ as one ZIP."""
    try:
        data = await asyncio.to_thread(service.build_models_bundle)
    except BuilderFileError as exc:
        raise _http_error(exc)
    return _zip_response(data, service.MODELS_BUNDLE_FILENAME)


@router.get("/models/{filename}")
async def download_model(filename: str):
    """Download an OpenSCAD model as a single self-contained file.

    Every `include <lib/NAME.scad>` is replaced by the content of
    models/lib/NAME.scad, so the file renders on its own without the lib/
    folder next to it.
    """
    try:
        name, source = await asyncio.to_thread(service.flattened_model, filename)
    except ScadInlineError as exc:
        log.error("Model %s cannot be flattened: %s", filename, exc)
        raise HTTPException(500, f"Model {filename} cannot be flattened: {exc}")
    except BuilderFileError as exc:
        raise _http_error(exc)
    return Response(
        content=source.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/diagrams")
async def list_diagrams():
    """List available SVG wiring and architecture diagrams."""
    return await asyncio.to_thread(service.list_diagrams)


@router.get("/diagrams/{filename}")
async def get_diagram(filename: str):
    """Serve an SVG diagram."""
    try:
        filepath = service.diagram_path(filename)
    except BuilderFileError as exc:
        raise _http_error(exc)
    return FileResponse(str(filepath), media_type="image/svg+xml")


@router.get("/firmware")
async def list_firmware():
    """List firmware source files grouped by node.

    Returns every .cpp / .h / .ino / .ini (and library.json manifest) under
    each allow-listed firmware root, with size + download URL, plus a
    "platformio.ini" group holding the build files at the firmware root
    (platformio.ini, VERSION.txt, partition tables, extra_scripts). Files
    outside the allow-list are never exposed so an attacker can't read build
    artifacts or secrets.
    """
    return await asyncio.to_thread(service.list_firmware)


@router.get("/firmware/bundle/{node}")
async def download_firmware_bundle(node: str):
    """Stream a ZIP bundle containing the node's source + shared lib + platformio.ini."""
    try:
        data = await asyncio.to_thread(service.build_node_bundle, node)
    except BuilderFileError as exc:
        raise _http_error(exc)
    return _zip_response(data, f"sporeprint-{node}.zip")


@router.get("/firmware/{path:path}")
async def get_firmware_file(path: str):
    """Serve a firmware source file. Path must resolve inside an allow-listed root."""
    try:
        name, data = await asyncio.to_thread(service.firmware_file, path)
    except BuilderFileError as exc:
        raise _http_error(exc)
    return Response(content=data, media_type="text/plain",
                    headers={"Content-Disposition": f"attachment; filename={name}"})
