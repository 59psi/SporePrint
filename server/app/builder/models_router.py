import io
import logging
import re
import time
import zipfile
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse

router = APIRouter()
log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_MODELS_DIR = Path("/models") if Path("/models").exists() else _REPO_ROOT / "models"
# Shared OpenSCAD helpers (heat-set inserts, board dimension tables). Only
# files under here are ever inlined into a single-file model download.
_MODELS_LIB_SUBDIR = "lib"
_MODELS_BUNDLE_ROOT = "sporeprint-models"
# Nesting limit for lib → lib includes. The shipped libs are one level deep;
# this only stops a runaway chain.
_INLINE_MAX_DEPTH = 8
# A whole-line OpenSCAD include statement: `include <path>` with an optional
# trailing `;` and `// comment`. Includes buried mid-line are not rewritten.
_SCAD_INCLUDE_RE = re.compile(
    r"^(?P<indent>[ \t]*)include[ \t]*<(?P<path>[^<>\r\n]+)>[ \t]*;?[ \t]*(?://.*)?$"
)
_DOCS_DIR = Path("/docs") if Path("/docs").exists() else _REPO_ROOT / "docs"
_FIRMWARE_DIR = Path("/firmware") if Path("/firmware").exists() else _REPO_ROOT / "firmware"

# Allow-list of firmware roots we expose — prevents traversal via /api/builder/firmware/..
# v4.2 layout: one unified node image + a camera image, with the shared
# code split into native-safe libraries (sp_core/sp_drivers) and the
# Arduino adapter layer (sp_device).
_FIRMWARE_ROOTS = ("src/node", "src/cam", "boards",
                   "lib/sp_core", "lib/sp_drivers", "lib/sp_device")

# Map of bundleable slug → (source root, human label, is_library).
#   is_library=False → image bundle; includes the shared libs, boards/ and
#                      platformio.ini
#   is_library=True  → just that library + platformio.ini
# Legacy v1 slugs (climate_node/relay_node/lighting_node) alias to the
# unified node bundle so older docs and bookmarks keep working.
_BUNDLE_NODES: dict[str, tuple[str, str, bool]] = {
    "node":          ("src/node",        "Unified node",   False),
    "cam":           ("src/cam",         "Camera node",    False),
    "climate_node":  ("src/node",        "Unified node",   False),
    "relay_node":    ("src/node",        "Unified node",   False),
    "lighting_node": ("src/node",        "Unified node",   False),
    "cam_node":      ("src/cam",         "Camera node",    False),
    "sp_core":       ("lib/sp_core",     "Core library",   True),
    "sp_drivers":    ("lib/sp_drivers",  "Driver library", True),
    "full":          ("",                "All firmware",   False),
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


class ScadInlineError(Exception):
    """A model's lib/ include chain can't be flattened (missing file, cycle, too deep)."""


def _is_within(path: Path, root: Path) -> bool:
    """True when `path` (already resolved) lies inside the resolved `root`."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _block_comment_after(line: str, in_block: bool) -> bool:
    """Return whether a `/* ... */` comment is still open at the end of `line`.

    Tracks `//` line comments and double-quoted strings so a `/*` inside
    either doesn't open a block. Good enough for OpenSCAD source; it only
    decides whether an `include` line is real code or commented out.
    """
    i, n = 0, len(line)
    in_str = False
    while i < n:
        if in_block:
            end = line.find("*/", i)
            if end < 0:
                return True
            in_block = False
            i = end + 2
            continue
        c = line[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif line.startswith("//", i):
            return False
        elif line.startswith("/*", i):
            in_block = True
            i += 2
            continue
        i += 1
    return in_block


def _resolve_lib_include(base_dir: Path, include_path: str, lib_root: Path) -> Path | None:
    """Resolve an include target the way OpenSCAD does (relative to the
    including file) and return it only if it lands inside models/lib/.

    Anything else — a sibling model, an absolute path, `../` escapes, a
    system library like MCAD — returns None and is left untouched.
    """
    rel = include_path.strip()
    if not rel.endswith(".scad"):
        return None
    candidate = (base_dir / rel).resolve()
    if not _is_within(candidate, lib_root):
        return None
    return candidate


def _inline_scad(path: Path, lib_root: Path, *, _stack: tuple[Path, ...] = (),
                 _seen: set[Path] | None = None) -> str:
    """Return `path`'s source with every `include <lib/NAME.scad>` statement
    replaced by that file's (recursively inlined) content.

    - Only files that resolve inside `lib_root` are inlined.
    - Each lib file is inlined once; a repeat include becomes a comment (the
      libs hold only constants, functions and modules, so including them a
      second time changes nothing but OpenSCAD's overwrite warnings).
    - A cycle, a missing lib file or nesting deeper than _INLINE_MAX_DEPTH
      raises ScadInlineError.
    """
    seen: set[Path] = set() if _seen is None else _seen
    stack = _stack + (path,)
    text = path.read_text(encoding="utf-8")
    out: list[str] = []
    in_block = False
    for line in text.splitlines(keepends=True):
        starts_in_block = in_block
        in_block = _block_comment_after(line, in_block)
        match = None if starts_in_block else _SCAD_INCLUDE_RE.match(line.rstrip("\r\n"))
        if match is None:
            out.append(line)
            continue
        target = _resolve_lib_include(path.parent, match["path"], lib_root)
        if target is None:
            out.append(line)
            continue

        label = f"{_MODELS_LIB_SUBDIR}/{target.relative_to(lib_root).as_posix()}"
        indent = match["indent"]
        if target in stack:
            chain = " -> ".join(p.name for p in stack + (target,))
            raise ScadInlineError(f"include cycle: {chain}")
        if target in seen:
            out.append(f"{indent}// ── {label} already inlined above ──\n")
            continue
        if len(stack) > _INLINE_MAX_DEPTH:
            raise ScadInlineError(f"include nesting deeper than {_INLINE_MAX_DEPTH} at {label}")
        if not target.is_file():
            raise ScadInlineError(f"{path.name} includes {label}, which does not exist")

        seen.add(target)
        body = _inline_scad(target, lib_root, _stack=stack, _seen=seen)
        if body and not body.endswith("\n"):
            body += "\n"
        out.append(f"{indent}// ── inlined from {label} ──\n")
        out.append(body)
        out.append(f"{indent}// ── end of inlined {label} ──\n")
    return "".join(out)


def _model_path(filename: str) -> Path:
    """Validate a top-level model filename and return its path (400/404 on failure)."""
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename or "\\" in filename:
        raise HTTPException(400, "Invalid filename")
    filepath = _MODELS_DIR / safe_name
    if filepath.suffix != ".scad" or not filepath.is_file():
        raise HTTPException(404, "Model not found")
    # A symlinked model must still live inside the models directory.
    if not _is_within(filepath.resolve(), _MODELS_DIR.resolve()):
        raise HTTPException(404, "Model not found")
    return filepath


def _build_models_bundle() -> bytes:
    """ZIP of every top-level model + models/lib/ (+ README), laid out as in
    the repo so the original `include <lib/...>` lines resolve unchanged."""
    models_dir = _MODELS_DIR
    if not models_dir.is_dir():
        raise HTTPException(404, "Models not found")
    models_root = models_dir.resolve()
    lib_dir = models_dir / _MODELS_LIB_SUBDIR

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        def add(f: Path, arc_rel: str) -> None:
            if f.is_file() and _is_within(f.resolve(), models_root):
                zf.write(f, f"{_MODELS_BUNDLE_ROOT}/{arc_rel}")

        for f in sorted(models_dir.glob("*.scad")):
            add(f, f.name)
        if lib_dir.is_dir():
            for f in sorted(lib_dir.rglob("*.scad")):
                add(f, f"{_MODELS_LIB_SUBDIR}/{f.relative_to(lib_dir).as_posix()}")
        add(models_dir / "README.md", "README.md")
    return buf.getvalue()


@router.get("/models")
async def list_models():
    """List available OpenSCAD 3D print model files (top level only — the
    shared helpers under models/lib/ are not printable models)."""
    return _cached_list(_MODELS_DIR, ".scad", _models_cache)


@router.get("/models-bundle.zip")
async def download_models_bundle():
    """Download every model plus models/lib/ as one ZIP."""
    data = _build_models_bundle()
    return StreamingResponse(
        iter([data]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{_MODELS_BUNDLE_ROOT}.zip"',
            "Content-Length": str(len(data)),
        },
    )


@router.get("/models/{filename}")
async def download_model(filename: str):
    """Download an OpenSCAD model as a single self-contained file.

    Every `include <lib/NAME.scad>` is replaced by the content of
    models/lib/NAME.scad, so the file renders on its own without the lib/
    folder next to it.
    """
    filepath = _model_path(filename)
    lib_root = (_MODELS_DIR / _MODELS_LIB_SUBDIR).resolve()
    try:
        source = _inline_scad(filepath.resolve(), lib_root)
    except ScadInlineError as exc:
        log.error("Model %s cannot be flattened: %s", filepath.name, exc)
        raise HTTPException(500, f"Model {filepath.name} cannot be flattened: {exc}")
    return Response(
        content=source.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filepath.name}"'},
    )


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
    """Build an in-memory ZIP for an image, a library, or the full firmware.

    - `full`            → the entire firmware/ tree (both images + libs)
    - sp_core/sp_drivers → just that library + platformio.ini
    - node/cam (+v1 aliases) → the image's src + all libs + boards/ +
      partition tables + platformio.ini — self-contained, no git clone
    """
    if node not in _BUNDLE_NODES:
        raise HTTPException(404, "Unknown node")
    node_rel, _label, is_library = _BUNDLE_NODES[node]
    env = "cam" if node_rel == "src/cam" else "node_esp32"

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

        def add_build_files() -> None:
            for name in ("platformio.ini", "partitions.csv",
                         "partitions_8mb.csv", "VERSION.txt"):
                p = _FIRMWARE_DIR / name
                if p.is_file():
                    zf.write(p, f"firmware/{name}")

        if node == "full":
            for root_rel in _FIRMWARE_ROOTS:
                add_tree(_FIRMWARE_DIR / root_rel, f"firmware/{root_rel}")
            add_build_files()
            readme = (
                "# SporePrint — full firmware bundle\n\n"
                "Contains both images (unified node + camera), the shared\n"
                "libraries, and board profiles. Unzip, then flash from the\n"
                "`firmware/` directory:\n\n"
                "```bash\n"
                "cd firmware\n"
                "pio run -t upload -e node_esp32      # WROOM-32 node\n"
                "pio run -t upload -e node_esp32s3    # ESP32-S3 node\n"
                "pio run -t upload -e cam             # AI-Thinker camera\n"
                "```\n\n"
                "Full source: https://github.com/59psi/SporePrint/tree/main/firmware\n"
            )
            zf.writestr("firmware/README.md", readme)
        else:
            root = _FIRMWARE_DIR / node_rel
            if not root.is_dir():
                raise HTTPException(404, "Source not found")

            if is_library:
                add_tree(root, f"firmware/{node_rel}")
                add_build_files()
                readme = (
                    f"# SporePrint — {node} library\n\n"
                    f"Drop this library into an existing SporePrint firmware\n"
                    f"tree to update only the shared code:\n\n"
                    f"```bash\n"
                    f"unzip sporeprint-{node}.zip\n"
                    f"cp -R firmware/{node_rel} <your-firmware>/lib/\n"
                    f"```\n"
                )
                zf.writestr(f"firmware/{node_rel}/README.md", readme)
            else:
                # Image bundle — src + every library + board profiles, so
                # the ZIP builds standalone.
                add_tree(root, f"firmware/{node_rel}")
                for lib_rel in ("lib/sp_core", "lib/sp_drivers",
                                "lib/sp_device"):
                    add_tree(_FIRMWARE_DIR / lib_rel, f"firmware/{lib_rel}")
                add_tree(_FIRMWARE_DIR / "boards", "firmware/boards")
                add_build_files()
                readme = (
                    f"# SporePrint — {node} firmware\n\n"
                    f"Unzip this archive and flash with PlatformIO:\n\n"
                    f"```bash\n"
                    f"cd firmware\n"
                    f"pio run -t upload -e {env}\n"
                    f"```\n\n"
                    f"On first boot the node opens the 'SporePrint-Setup'\n"
                    f"WiFi portal for provisioning.\n\n"
                    f"Full source: https://github.com/59psi/SporePrint/tree/main/firmware\n"
                )
                zf.writestr(f"firmware/{node_rel}/README.md", readme)

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
