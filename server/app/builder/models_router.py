import io
import time
import zipfile
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

router = APIRouter()

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_MODELS_DIR = Path("/models") if Path("/models").exists() else _REPO_ROOT / "models"
_DOCS_DIR = Path("/docs") if Path("/docs").exists() else _REPO_ROOT / "docs"
_FIRMWARE_DIR = Path("/firmware") if Path("/firmware").exists() else _REPO_ROOT / "firmware"

# Allow-list of firmware roots we expose — prevents traversal via /api/builder/firmware/..
_FIRMWARE_ROOTS = ("src/climate_node", "src/relay_node", "src/lighting_node",
                   "src/cam_node", "lib/sporeprint_common")

# Map of bundleable node slug → (source root, human label, is_library).
#   is_library=False → per-node bundle; includes shared lib + platformio.ini
#   is_library=True  → just the shared library + platformio.ini (no node source)
# The "sporeprint_common" bundle is for users who already have their own
# custom node firmware and only want to pick up library updates. The "full"
# bundle is the entire firmware tree in one archive.
_BUNDLE_NODES: dict[str, tuple[str, str, bool]] = {
    "climate_node":     ("src/climate_node",       "Climate node",    False),
    "relay_node":       ("src/relay_node",         "Relay node",      False),
    "lighting_node":    ("src/lighting_node",      "Lighting node",   False),
    "cam_node":         ("src/cam_node",           "Camera node",     False),
    "sporeprint_common": ("lib/sporeprint_common", "Shared library",  True),
    "full":             ("",                        "All firmware",    False),
}
_BUNDLE_SUFFIXES = {".cpp", ".h", ".hpp", ".ino", ".ini", ".md", ".txt"}

_models_cache: dict = {"data": [], "ts": 0}
_diagrams_cache: dict = {"data": [], "ts": 0}
_firmware_cache: dict = {"data": [], "ts": 0}
_CACHE_TTL = 60


def _cached_list(directory: Path, suffix: str, cache: dict) -> list[dict]:
    now = time.time()
    if now - cache["ts"] < _CACHE_TTL and cache["data"]:
        return cache["data"]
    if not directory.exists():
        cache["data"] = []
    else:
        url_segment = "models" if suffix == ".scad" else "diagrams"
        cache["data"] = [
            {"filename": f.name, "size_bytes": f.stat().st_size, "url": f"/api/builder/{url_segment}/{f.name}"}
            for f in sorted(directory.glob(f"*{suffix}"))
        ]
    cache["ts"] = now
    return cache["data"]


@router.get("/models")
async def list_models():
    """List available OpenSCAD 3D print model files."""
    return _cached_list(_MODELS_DIR, ".scad", _models_cache)


@router.get("/models/{filename}")
async def download_model(filename: str):
    """Download an OpenSCAD model file."""
    # Sanitize filename to prevent path traversal
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    filepath = _MODELS_DIR / safe_name
    if not filepath.exists() or not filepath.suffix == ".scad":
        raise HTTPException(404, "Model not found")
    return FileResponse(str(filepath), media_type="text/plain",
                        headers={"Content-Disposition": f"attachment; filename={safe_name}"})


@router.get("/diagrams")
async def list_diagrams():
    """List available SVG wiring and architecture diagrams."""
    return _cached_list(_DOCS_DIR, ".svg", _diagrams_cache)


@router.get("/diagrams/{filename}")
async def get_diagram(filename: str):
    """Serve an SVG diagram."""
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    filepath = _DOCS_DIR / safe_name
    if not filepath.exists() or filepath.suffix != ".svg":
        raise HTTPException(404, "Diagram not found")
    return FileResponse(str(filepath), media_type="image/svg+xml")


@router.get("/firmware")
async def list_firmware():
    """List firmware source files grouped by node.

    Returns every .cpp / .h / .ino / .ini under each allow-listed firmware
    root, with size + download URL. Files outside the allow-list are never
    exposed so an attacker can't read build artifacts or secrets.
    """
    now = time.time()
    if now - _firmware_cache["ts"] < _CACHE_TTL and _firmware_cache["data"]:
        return _firmware_cache["data"]

    allowed_suffixes = {".cpp", ".h", ".hpp", ".ino", ".ini"}
    groups: list[dict] = []

    for root_rel in _FIRMWARE_ROOTS:
        root = _FIRMWARE_DIR / root_rel
        if not root.exists():
            continue
        files = []
        for f in sorted(root.rglob("*")):
            if not f.is_file() or f.suffix not in allowed_suffixes:
                continue
            rel = f.relative_to(_FIRMWARE_DIR)
            files.append({
                "filename": str(rel),
                "size_bytes": f.stat().st_size,
                "url": f"/api/builder/firmware/{rel}",
            })
        if files:
            node = root_rel.split("/")[-1]
            group: dict = {"node": node, "path": root_rel, "files": files}
            if node in _BUNDLE_NODES:
                group["bundle_url"] = f"/api/builder/firmware/bundle/{node}"
                group["bundle_filename"] = f"sporeprint-{node}.zip"
            groups.append(group)

    pio = _FIRMWARE_DIR / "platformio.ini"
    if pio.exists():
        groups.append({
            "node": "platformio.ini",
            "path": "platformio.ini",
            "files": [{
                "filename": "platformio.ini",
                "size_bytes": pio.stat().st_size,
                "url": "/api/builder/firmware/platformio.ini",
            }],
        })

    # Full-firmware bundle is a synthetic group that appears at the top —
    # no file list, just a download-all ZIP.
    if groups:
        groups.insert(0, {
            "node": "full",
            "path": "firmware/ (all nodes)",
            "files": [],
            "bundle_url": "/api/builder/firmware/bundle/full",
            "bundle_filename": "sporeprint-firmware-all.zip",
        })

    _firmware_cache["data"] = groups
    _firmware_cache["ts"] = now
    return groups


def _build_node_bundle(node: str) -> bytes:
    """Build an in-memory ZIP for a node, the shared library, or full firmware.

    - `full`               → the entire firmware/ tree (all 4 nodes + lib + platformio.ini)
    - `sporeprint_common`  → just the shared library + platformio.ini
    - <node>               → the node's src + shared library + platformio.ini
    """
    if node not in _BUNDLE_NODES:
        raise HTTPException(404, "Unknown node")
    node_rel, _label, is_library = _BUNDLE_NODES[node]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        def add_tree(src_root: Path, arc_prefix: str) -> None:
            if not src_root.exists():
                return
            for f in sorted(src_root.rglob("*")):
                if not f.is_file() or f.suffix not in _BUNDLE_SUFFIXES:
                    continue
                arc = f"{arc_prefix}/{f.relative_to(src_root)}"
                zf.write(f, arc)

        pio = _FIRMWARE_DIR / "platformio.ini"

        if node == "full":
            # Pack everything — all node source, shared lib, platformio.ini
            for root_rel in _FIRMWARE_ROOTS:
                add_tree(_FIRMWARE_DIR / root_rel, f"firmware/{root_rel}")
            if pio.is_file():
                zf.write(pio, "firmware/platformio.ini")
            readme = (
                "# SporePrint — full firmware bundle\n\n"
                "Contains every node's source plus the shared library. Unzip, then\n"
                "flash each node from the `firmware/` directory:\n\n"
                "```bash\n"
                "cd firmware\n"
                "pio run -t upload -e climate_node\n"
                "pio run -t upload -e relay_node\n"
                "pio run -t upload -e lighting_node\n"
                "pio run -t upload -e cam_node\n"
                "```\n\n"
                "Full source: https://github.com/59psi/SporePrint/tree/main/firmware\n"
            )
            zf.writestr("firmware/README.md", readme)
        else:
            root = _FIRMWARE_DIR / node_rel
            if not root.is_dir():
                raise HTTPException(404, "Source not found")

            if is_library:
                # Library-only bundle — no node src, just the lib and platformio.ini
                add_tree(root, f"firmware/{node_rel}")
                if pio.is_file():
                    zf.write(pio, "firmware/platformio.ini")
                readme = (
                    f"# SporePrint — {node} (shared library)\n\n"
                    f"Drop this library into an existing SporePrint firmware tree to update\n"
                    f"only the shared code — your custom node source is untouched.\n\n"
                    f"```bash\n"
                    f"# Assuming you have your own firmware/ with src/<node>/ customizations:\n"
                    f"unzip sporeprint-{node}.zip\n"
                    f"cp -R firmware/lib/sporeprint_common <your-firmware>/lib/\n"
                    f"cd <your-firmware>\n"
                    f"pio run -t upload -e <your_node>\n"
                    f"```\n"
                )
                zf.writestr(f"firmware/{node_rel}/README.md", readme)
            else:
                # Per-node bundle — node src + shared library + platformio.ini
                add_tree(root, f"firmware/{node_rel}")
                add_tree(_FIRMWARE_DIR / "lib/sporeprint_common",
                         "firmware/lib/sporeprint_common")
                if pio.is_file():
                    zf.write(pio, "firmware/platformio.ini")
                readme = (
                    f"# SporePrint — {node} firmware\n\n"
                    f"Unzip this archive and flash with PlatformIO:\n\n"
                    f"```bash\n"
                    f"cd firmware\n"
                    f"pio run -t upload -e {node}\n"
                    f"```\n\n"
                    f"Full source: https://github.com/59psi/SporePrint/tree/main/firmware\n"
                )
                zf.writestr(f"firmware/src/{node}/README.md", readme)

    return buf.getvalue()


@router.get("/firmware/bundle/{node}")
async def download_firmware_bundle(node: str):
    """Stream a ZIP bundle containing the node's source + shared lib + platformio.ini."""
    data = _build_node_bundle(node)
    filename = f"sporeprint-{node}.zip"
    return StreamingResponse(
        iter([data]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )


@router.get("/firmware/{path:path}")
async def get_firmware_file(path: str):
    """Serve a firmware source file. Path must resolve inside an allow-listed root."""
    if ".." in path or path.startswith("/"):
        raise HTTPException(400, "Invalid path")
    target = (_FIRMWARE_DIR / path).resolve()
    try:
        target.relative_to(_FIRMWARE_DIR.resolve())
    except ValueError:
        raise HTTPException(400, "Invalid path")
    if not target.is_file():
        raise HTTPException(404, "File not found")
    if target.suffix not in {".cpp", ".h", ".hpp", ".ino", ".ini"}:
        raise HTTPException(400, "Unsupported file type")

    # Enforce allow-listed roots — platformio.ini or under _FIRMWARE_ROOTS
    rel = target.relative_to(_FIRMWARE_DIR.resolve())
    rel_str = str(rel)
    if rel_str != "platformio.ini" and not any(rel_str.startswith(root) for root in _FIRMWARE_ROOTS):
        raise HTTPException(404, "File not found")

    return FileResponse(str(target), media_type="text/plain",
                        headers={"Content-Disposition": f"attachment; filename={target.name}"})
