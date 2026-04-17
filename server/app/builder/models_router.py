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

# Map of bundleable node slug → (source root, human label). The shared
# sporeprint_common library + platformio.ini are included in every per-node
# bundle so the archive is a complete, self-contained PlatformIO project.
_BUNDLE_NODES: dict[str, tuple[str, str]] = {
    "climate_node": ("src/climate_node", "Climate node"),
    "relay_node": ("src/relay_node", "Relay node"),
    "lighting_node": ("src/lighting_node", "Lighting node"),
    "cam_node": ("src/cam_node", "Camera node"),
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
            # Only top-level node firmware gets a per-node bundle. The shared
            # `sporeprint_common` library is always packed INTO those bundles.
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

    _firmware_cache["data"] = groups
    _firmware_cache["ts"] = now
    return groups


def _build_node_bundle(node: str) -> bytes:
    """Build an in-memory ZIP for a single node — includes the node's source,
    the shared sporeprint_common lib, and the top-level platformio.ini so the
    archive is a complete PlatformIO project."""
    if node not in _BUNDLE_NODES:
        raise HTTPException(404, "Unknown node")
    node_rel, _label = _BUNDLE_NODES[node]
    node_root = _FIRMWARE_DIR / node_rel
    if not node_root.is_dir():
        raise HTTPException(404, "Node source not found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        def add_tree(src_root: Path, arc_prefix: str) -> None:
            if not src_root.exists():
                return
            for f in sorted(src_root.rglob("*")):
                if not f.is_file():
                    continue
                if f.suffix not in _BUNDLE_SUFFIXES:
                    continue
                arc = f"{arc_prefix}/{f.relative_to(src_root)}"
                zf.write(f, arc)

        add_tree(node_root, f"firmware/{node_rel}")
        add_tree(_FIRMWARE_DIR / "lib/sporeprint_common", "firmware/lib/sporeprint_common")

        pio = _FIRMWARE_DIR / "platformio.ini"
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
