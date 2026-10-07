import io
import logging
import re
import time
import zipfile
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse

from .service import platformio_image_envs, platformio_references

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
_BUNDLE_SUFFIXES = {".c", ".cpp", ".h", ".hpp", ".ino", ".ini", ".md", ".txt"}
# PlatformIO library manifests: they declare each lib's dependencies and build
# flags (sp_drivers' -I.), so a bundle without them builds differently from
# the tested tree (or not at all).
_BUNDLE_NAMES = {"library.json"}
# Source files the per-file endpoint and listing expose under _FIRMWARE_ROOTS.
_SOURCE_SUFFIXES = {".cpp", ".h", ".hpp", ".ino", ".ini"}
# Files at the firmware root every build needs, besides what platformio.ini
# itself references (partition tables, extra_scripts).
_ROOT_BUILD_FILES = ("platformio.ini", "VERSION.txt")

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


# Public GitHub location of the model sources (shown as "browse repo").
MODELS_REPO_URL = "https://github.com/59psi/SporePrint/tree/main/models"
_MODEL_DESCRIPTION_MAX = 240


def _model_header(path: Path) -> tuple[str, str]:
    """(title, description) from a model's leading comment block.

    Every model opens with `// SporePrint <Title>` followed by a one-paragraph
    summary that ends at the first blank `//` line. Reading it from the file
    keeps the Builder's Models list from drifting out of date (it used to be a
    hand-maintained list in the UI that still described the old designs).
    """
    title, desc_lines = path.stem, []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            lines = [next(fh, "") for _ in range(16)]
    except OSError:
        return title, ""
    comments = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped.startswith("//"):
            break
        comments.append(stripped[2:].strip())
    if comments and comments[0]:
        title = re.sub(r"^SporePrint\s+", "", comments[0]) or title
    for text in comments[1:]:
        if not text or text.startswith("─") or text.startswith("──"):
            break
        desc_lines.append(text)
    description = " ".join(" ".join(desc_lines).split())
    if len(description) > _MODEL_DESCRIPTION_MAX:
        cut = description[:_MODEL_DESCRIPTION_MAX]
        end = cut.rfind(". ")
        description = cut[: end + 1] if end > 80 else cut.rstrip() + "…"
    return title, description


def _list_models() -> list[dict]:
    now = time.time()
    if now - _models_cache["ts"] < _CACHE_TTL and _models_cache["data"]:
        return _models_cache["data"]
    data = []
    if _MODELS_DIR.exists():
        for f in sorted(_MODELS_DIR.glob("*.scad")):
            title, description = _model_header(f)
            data.append({
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                # Self-contained download: lib/ includes are inlined.
                "url": f"/api/builder/models/{f.name}",
                "title": title,
                "description": description,
                "source_url": f"{MODELS_REPO_URL}/{f.name}".replace("/tree/", "/blob/"),
            })
    _models_cache["data"] = data
    _models_cache["ts"] = now
    return data


def _bundleable(f: Path) -> bool:
    return f.suffix in _BUNDLE_SUFFIXES or f.name in _BUNDLE_NAMES


def _servable_source(f: Path) -> bool:
    """A file the listing / per-file endpoint may expose under _FIRMWARE_ROOTS."""
    return f.suffix in _SOURCE_SUFFIXES or f.name in _BUNDLE_NAMES


def _firmware_build_files() -> tuple[list[Path], list[Path]]:
    """(files, dirs), resolved, that a PlatformIO build of this tree needs
    besides the image/library sources: platformio.ini, VERSION.txt, every
    partition table, and whatever platformio.ini references — extra_scripts,
    partition tables, embedded files, -I include dirs. Read from the ini, so a
    newly added script or table is bundled without a code change. A
    reference resolving outside the firmware dir is never followed."""
    root = _FIRMWARE_DIR.resolve()
    ref_files, ref_dirs = platformio_references(_FIRMWARE_DIR / "platformio.ini")
    names = (set(_ROOT_BUILD_FILES) | ref_files
             | {p.name for p in _FIRMWARE_DIR.glob("partitions*.csv")})
    files = []
    for rel in sorted(names):
        p = (_FIRMWARE_DIR / rel).resolve()
        if p.is_file() and _is_within(p, root):
            files.append(p)
    dirs = []
    for rel in sorted(ref_dirs):
        d = (_FIRMWARE_DIR / rel).resolve()
        if d.is_dir() and d != root and _is_within(d, root):
            dirs.append(d)
    return files, dirs


def _build_file_rels() -> set[str]:
    """Firmware-relative paths of _firmware_build_files()' files."""
    root = _FIRMWARE_DIR.resolve()
    return {p.relative_to(root).as_posix() for p in _firmware_build_files()[0]}


def _flash_instructions(envs: list[str]) -> str:
    """README body: how to build/flash `envs`, including the version note."""
    try:
        ini_text = (_FIRMWARE_DIR / "platformio.ini").read_text(encoding="utf-8")
    except OSError:
        ini_text = ""
    lines = ["```bash", "cd firmware"]
    if "${sysenv.SPOREPRINT_FW_VERSION}" in ini_text:
        lines.append('export SPOREPRINT_FW_VERSION="$(cat VERSION.txt)"')
        version_note = (
            "platformio.ini reads the firmware version from SPOREPRINT_FW_VERSION: "
            "export it as above, or heartbeats report an empty firmware_version."
        )
    else:
        version_note = (
            "The firmware version heartbeats report is read from VERSION.txt at "
            "build time; set SPOREPRINT_FW_VERSION to override it."
        )
    lines += [f"pio run -t upload -e {env}" for env in envs]
    lines.append("```")
    body = "\n".join(lines) + "\n\n"
    if len(envs) > 1:
        body = "Run the line for your board:\n\n" + body
    return body + version_note + "\n"


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
    shared helpers under models/lib/ are not printable models).

    Each entry carries `title` and `description` read from the model's own
    header comment, `url` (self-contained download with lib/ inlined) and
    `source_url` (the file on GitHub)."""
    return _list_models()


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

    Returns every .cpp / .h / .ino / .ini (and library.json manifest) under
    each allow-listed firmware root, with size + download URL, plus a
    "platformio.ini" group holding the build files at the firmware root
    (platformio.ini, VERSION.txt, partition tables, extra_scripts). Files
    outside the allow-list are never exposed so an attacker can't read build
    artifacts or secrets.
    """
    now = time.time()
    if now - _firmware_cache["ts"] < _CACHE_TTL and _firmware_cache["data"]:
        return _firmware_cache["data"]

    groups: list[dict] = []

    for root_rel in _FIRMWARE_ROOTS:
        root = _FIRMWARE_DIR / root_rel
        if not root.exists():
            continue
        files = []
        for f in sorted(root.rglob("*")):
            if not f.is_file() or not _servable_source(f):
                continue
            rel = f.relative_to(_FIRMWARE_DIR).as_posix()
            files.append({
                "filename": rel,
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

    if (_FIRMWARE_DIR / "platformio.ini").exists():
        fw_root = _FIRMWARE_DIR.resolve()
        build_files = sorted(_firmware_build_files()[0],
                             key=lambda p: (p.name != "platformio.ini", p.as_posix()))
        groups.append({
            "node": "platformio.ini",
            "path": "platformio.ini",
            "files": [{
                "filename": p.relative_to(fw_root).as_posix(),
                "size_bytes": p.stat().st_size,
                "url": f"/api/builder/firmware/{p.relative_to(fw_root).as_posix()}",
            } for p in build_files],
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
    - sp_core/sp_drivers → just that library + the root build files
    - node/cam (+v1 aliases) → the image's src + all libs + boards/ + the
      root build files — self-contained, no git clone

    Every library ships with its library.json manifest, and the root build
    files are platformio.ini, VERSION.txt, every partition table and whatever
    platformio.ini references (extra_scripts, -I dirs), so the bundle builds
    exactly like the tested tree.
    """
    if node not in _BUNDLE_NODES:
        raise HTTPException(404, "Unknown node")
    node_rel, _label, is_library = _BUNDLE_NODES[node]
    image_envs = platformio_image_envs(_FIRMWARE_DIR / "platformio.ini")
    fw_root = _FIRMWARE_DIR.resolve()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        written: set[str] = set()

        def write(f: Path, arc: str) -> None:
            if arc not in written:
                written.add(arc)
                zf.write(f, arc)

        def add_tree(src_root: Path, arc_prefix: str) -> None:
            if not src_root.exists():
                return
            for f in sorted(src_root.rglob("*")):
                if not f.is_file() or not _bundleable(f):
                    continue
                if not _is_within(f.resolve(), fw_root):
                    continue  # a symlink out of the firmware tree
                write(f, f"{arc_prefix}/{f.relative_to(src_root).as_posix()}")

        def add_build_files() -> None:
            files, dirs = _firmware_build_files()
            for f in files:
                write(f, f"firmware/{f.relative_to(fw_root).as_posix()}")
            for d in dirs:
                add_tree(d, f"firmware/{d.relative_to(fw_root).as_posix()}")

        if node == "full":
            for root_rel in _FIRMWARE_ROOTS:
                add_tree(_FIRMWARE_DIR / root_rel, f"firmware/{root_rel}")
            add_build_files()
            readme = (
                "# SporePrint — full firmware bundle\n\n"
                "Contains both images (unified node + AI-Thinker ESP32-CAM\n"
                "camera), the shared libraries, and board profiles. Unzip,\n"
                "then flash from the `firmware/` directory.\n\n"
                + _flash_instructions(image_envs["node"] + image_envs["cam"])
                + "\nFull source: https://github.com/59psi/SporePrint/tree/main/firmware\n"
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
                envs = image_envs["cam" if node_rel == "src/cam" else "node"]
                readme = (
                    f"# SporePrint — {node} firmware\n\n"
                    f"Unzip this archive and flash with PlatformIO.\n\n"
                    + _flash_instructions(envs)
                    + "\nOn first boot the node opens the 'SporePrint-Setup'\n"
                    "WiFi portal for provisioning.\n\n"
                    "Full source: https://github.com/59psi/SporePrint/tree/main/firmware\n"
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

    # Allow-list: the root build files (platformio.ini, VERSION.txt, partition
    # tables, extra_scripts), or a source file / library.json under
    # _FIRMWARE_ROOTS.
    rel_str = target.relative_to(_FIRMWARE_DIR.resolve()).as_posix()
    if rel_str not in _build_file_rels():
        if not _servable_source(target):
            raise HTTPException(400, "Unsupported file type")
        if not any(rel_str.startswith(f"{root}/") for root in _FIRMWARE_ROOTS):
            raise HTTPException(404, "File not found")

    return FileResponse(str(target), media_type="text/plain",
                        headers={"Content-Disposition": f"attachment; filename={target.name}"})
