import configparser
import io
import json
import logging
import re
import time
import zipfile
from pathlib import Path

import anthropic

from ..config import settings
from ..db import get_db
from ..vision.service import claude_response_text, claude_stop_reason

log = logging.getLogger(__name__)

# A 9-section guide with firmware + OpenSCAD code, plus the model's thinking,
# overran the old 4096 cap. This is above the SDK's non-streaming ceiling, so
# the request is streamed.
_GUIDE_MAX_TOKENS = 32_000

_REPO_ROOT = Path(__file__).resolve().parents[3]
# The trees the Builder serves. docker-compose mounts each read-only at the
# root (/firmware, /models, /docs); a bare-metal install reads the checkout.
_FIRMWARE_DIR = Path("/firmware") if Path("/firmware").exists() else _REPO_ROOT / "firmware"
_MODELS_DIR = Path("/models") if Path("/models").exists() else _REPO_ROOT / "models"
_DOCS_DIR = Path("/docs") if Path("/docs").exists() else _REPO_ROOT / "docs"

# PlatformIO envs per firmware image, used when platformio.ini can't be read
# (tests/test_cross_cluster_builder.py keeps it equal to the shipped ini's).
_DEFAULT_IMAGE_ENVS = {
    "node": ["node_esp32", "node_esp32s3", "node_esp32s3_n32r16v"],
    "cam": ["cam", "cam_esp32s3", "cam_xiao_esp32s3", "cam_waveshare_s3"],
}


# ─── platformio.ini ──────────────────────────────────────────────────────


def _read_platformio_ini(ini: Path) -> configparser.ConfigParser | None:
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        if not cp.read(ini, encoding="utf-8"):
            return None
    except (configparser.Error, OSError, UnicodeDecodeError) as e:
        log.warning("Cannot parse %s: %s", ini, e)
        return None
    return cp


def _ini_tokens(value: str) -> list[str]:
    """Whitespace/comma separated values, minus ${...} interpolations."""
    return [t for t in re.split(r"[\s,]+", value) if t and "${" not in t]


# An `extra_configs` ini is published (zipped into the Builder bundles, served
# by the per-file endpoint) only when it reads as shared build config. A local
# override ini is a common PlatformIO pattern for an OTA --auth password in
# upload_flags, an upload_port, or WiFi / MQTT credentials in build_flags, and
# the firmware dir is mounted into the server as-is. Such a file isn't needed
# for a bundle to build: its glob then matches nothing.
_PRIVATE_CONFIG_NAME = re.compile(
    r"secret|private|local|override|credential|passw|token|auth|user", re.I)
_PRIVATE_CONFIG_KEYS = frozenset({"upload_flags", "upload_port", "upload_command",
                                  "monitor_port", "test_port"})
_SECRET_TEXT = re.compile(r"passw|secret|token|api[_-]?key|psk|--auth|\bauth\b", re.I)


def _private_option(key: str, value: str) -> bool:
    """True for an ini option that may carry operator secrets or local
    settings: an upload / port option, or a credential-like key or value."""
    return (key in _PRIVATE_CONFIG_KEYS or bool(_SECRET_TEXT.search(key))
            or bool(_SECRET_TEXT.search(value or "")))


def _is_private_config(ini: Path) -> bool:
    """True when an extra_configs ini may carry operator secrets or local
    settings: a telling file name, a _private_option (comments are not read),
    or content that can't be parsed and so can't be vetted."""
    if _PRIVATE_CONFIG_NAME.search(ini.stem):
        return True
    cp = _read_platformio_ini(ini)
    if cp is None:
        return True
    for section in cp.sections():
        for key, value in cp.items(section):
            if _private_option(key, value):
                return True
    return False


# The root platformio.ini is published too (per-file endpoint, every bundle),
# and a bundle cannot build without it, so it is screened option by option
# instead of withheld whole. Same parsing rules as configparser (`#` / `;`
# full-line comments, `=` or `:`, continuation lines indented deeper than
# their option).
_INI_COMMENT = re.compile(r"^\s*[#;]")
_INI_SECTION = re.compile(r"^\s*\[[^\]\r\n]*\]")
_INI_OPTION = re.compile(r"^(?P<indent>[ \t]*)(?P<key>[^=:\s#;\[][^=:]*?)[ \t]*[=:][ \t]*(?P<value>.*)$")


def _withheld_line(indent: str, key: str) -> str:
    return (f"{indent}; {key}: withheld by the SporePrint server (it may hold credentials "
            "or local settings; keep those in a local extra_configs ini)\n")


def _commented_private_option(line: str) -> str | None:
    """The key of a commented-out private option (`; upload_flags = --auth=…`)."""
    m = _INI_OPTION.match(line.strip()[1:].strip())
    if m and _private_option(m["key"].strip().lower(), m["value"]):
        return m["key"].strip().lower()
    return None


def published_platformio_ini(text: str) -> tuple[str, list[str]]:
    """(platformio.ini as the Builder publishes it, the keys withheld).

    Every option _private_option flags (an OTA --auth password in
    upload_flags, an upload_port, credentials in build_flags), with its
    continuation lines, and every commented-out one, is replaced by a comment
    saying it was withheld; everything else is kept byte for byte, so a clean
    file is published unchanged. The PlatformIO pattern for such settings is
    a local extra_configs ini, which is never published (_is_private_config).
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    withheld: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or _INI_SECTION.match(line):
            out.append(line)
            i += 1
            continue
        if _INI_COMMENT.match(line):
            key = _commented_private_option(line)
            if key:
                withheld.append(key)
                out.append(_withheld_line(line[: len(line) - len(line.lstrip())], key))
            else:
                out.append(line)
            i += 1
            continue
        m = _INI_OPTION.match(line.rstrip("\r\n"))
        if m is None:
            # Not an option: configparser would refuse the file. Kept unless
            # it reads like a credential.
            if _SECRET_TEXT.search(line):
                withheld.append("(unparsed line)")
                out.append(_withheld_line("", "(unparsed line)"))
            else:
                out.append(line)
            i += 1
            continue
        indent = len(m["indent"])
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if (nxt.strip() and not _INI_COMMENT.match(nxt)
                    and len(nxt) - len(nxt.lstrip()) <= indent):
                break
            j += 1
        # Blank and comment lines after the value belong to what follows.
        while j > i + 1 and (not lines[j - 1].strip() or _INI_COMMENT.match(lines[j - 1])):
            j -= 1
        block = lines[i:j]
        key = m["key"].strip().lower()
        value = "\n".join([m["value"], *(b.strip() for b in block[1:]
                                         if b.strip() and not _INI_COMMENT.match(b))])
        if _private_option(key, value):
            withheld.append(key)
            out.append(_withheld_line(m["indent"], key))
        else:
            for b in block:
                inner = _commented_private_option(b) if _INI_COMMENT.match(b) else None
                if inner:
                    withheld.append(inner)
                    out.append(_withheld_line(b[: len(b) - len(b.lstrip())], inner))
                else:
                    out.append(b)
        i = j
    return "".join(out), withheld


_logged_withheld: set[tuple[str, ...]] = set()


def _published_ini_bytes(ini: Path) -> bytes:
    """The root platformio.ini's published bytes (published_platformio_ini)."""
    raw = ini.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    published, withheld = published_platformio_ini(text)
    if withheld:
        key = tuple(withheld)
        if key not in _logged_withheld:
            _logged_withheld.add(key)
            log.warning("Builder: withheld %s from the published %s (credentials or local "
                        "settings); keep those in a local extra_configs ini",
                        ", ".join(withheld), ini)
        return published.encode("utf-8")
    return raw


def platformio_references(ini: Path, *, project: Path | None = None,
                          _seen: set[Path] | None = None) -> tuple[set[str], set[str]]:
    """(files, directories) platformio.ini names, relative to its project dir.

    Files: partition tables, extra_scripts (pre:/post: stripped), embedded
    files, and the configs `[platformio] extra_configs` globs pull in — which
    are parsed for the same references (the firmware attaches its version
    pre-script through scripts/*.ini) — except one that may hold secrets or
    local settings (_is_private_config), which is neither returned nor
    followed. Directories: -I include dirs in
    build_flags and lib_extra_dirs. Source dirs selected by build_src_filter
    are the caller's business (each bundle carries its own image). Paths are
    returned as written; callers must keep them inside the project.
    """
    project = ini.parent if project is None else project
    seen = set() if _seen is None else _seen
    seen.add(ini.resolve())
    cp = _read_platformio_ini(ini)
    files: set[str] = set()
    dirs: set[str] = set()
    if cp is None:
        return files, dirs
    for section in cp.sections():
        for key, value in cp.items(section):
            tokens = _ini_tokens(value)
            if key in ("board_build.partitions", "board_build.embed_files",
                       "board_build.embed_txtfiles"):
                files.update(tokens)
            elif key == "extra_scripts":
                files.update(re.sub(r"^(pre|post):", "", t) for t in tokens)
            elif key == "build_flags":
                dirs.update(re.findall(r"-I\s*([^\s-]\S*)", " ".join(tokens)))
            elif key == "lib_extra_dirs":
                dirs.update(tokens)
            elif key == "extra_configs":
                for pattern in tokens:
                    try:
                        matches = sorted(project.glob(pattern))
                    except (ValueError, NotImplementedError):  # absolute pattern
                        continue
                    for match in matches:
                        if not match.is_file() or _is_private_config(match):
                            continue
                        try:
                            rel = match.relative_to(project).as_posix()
                        except ValueError:
                            continue
                        files.add(rel)
                        if match.resolve() not in seen:
                            more_files, more_dirs = platformio_references(
                                match, project=project, _seen=seen)
                            files |= more_files
                            dirs |= more_dirs
    return files, dirs


def _ini_option(cp: configparser.ConfigParser, section: str, key: str, _depth: int = 0) -> str | None:
    """`key` from `section`, following PlatformIO `extends` (a few levels)."""
    if not cp.has_section(section) or _depth > 8:
        return None
    if cp.has_option(section, key):
        return cp.get(section, key)
    for parent in _ini_tokens(cp.get(section, "extends", fallback="")):
        value = _ini_option(cp, parent, key, _depth + 1)
        if value is not None:
            return value
    return None


def platformio_image_envs(ini: Path) -> dict[str, list[str]]:
    """{"node": [env, ...], "cam": [env, ...]} from each env's build_src_filter."""
    cp = _read_platformio_ini(ini)
    if cp is None:
        return {k: list(v) for k, v in _DEFAULT_IMAGE_ENVS.items()}
    envs: dict[str, list[str]] = {"node": [], "cam": []}
    for section in cp.sections():
        if not section.startswith("env:"):
            continue
        src_filter = _ini_option(cp, section, "build_src_filter") or ""
        for image in re.findall(r"\+<([^>/]+)/?>", src_filter):
            if image in envs:
                envs[image].append(section[len("env:"):])
    return {k: v or list(_DEFAULT_IMAGE_ENVS[k]) for k, v in envs.items()}


# ─── Builder files: errors ───────────────────────────────────────────────
#
# The file helpers below run blocking filesystem work (listings, include
# inlining, ZIP building); routers call them through asyncio.to_thread and
# map these errors to HTTP statuses (models_router.py).


class BuilderFileError(Exception):
    """A Builder file request that cannot be served."""


class InvalidBuilderPathError(BuilderFileError):
    """A filename or path the Builder refuses outright (HTTP 400)."""


class BuilderFileNotFoundError(BuilderFileError):
    """No such model, diagram, firmware file or bundle source (HTTP 404)."""


class ScadInlineError(BuilderFileError):
    """A model's lib/ include chain can't be flattened (missing file, cycle, too deep)."""


def _is_within(path: Path, root: Path) -> bool:
    """True when `path` (already resolved) lies inside the resolved `root`."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


_CACHE_TTL = 60
_models_cache: dict = {"data": [], "ts": 0}
_diagrams_cache: dict = {"data": [], "ts": 0}
_firmware_cache: dict = {"data": [], "ts": 0}


# ─── Builder files: 3D models ────────────────────────────────────────────

# Shared OpenSCAD helpers (heat-set inserts, board dimension tables). Only
# files under here are ever inlined into a single-file model download.
_MODELS_LIB_SUBDIR = "lib"
_MODELS_BUNDLE_ROOT = "sporeprint-models"
MODELS_BUNDLE_FILENAME = f"{_MODELS_BUNDLE_ROOT}.zip"
# Nesting limit for lib → lib includes. The shipped libs are one level deep;
# this only stops a runaway chain.
_INLINE_MAX_DEPTH = 8
# A whole-line OpenSCAD include statement: `include <path>` with an optional
# trailing `;` and `// comment`. Includes buried mid-line are not rewritten.
_SCAD_INCLUDE_RE = re.compile(
    r"^(?P<indent>[ \t]*)include[ \t]*<(?P<path>[^<>\r\n]+)>[ \t]*;?[ \t]*(?://.*)?$"
)
# Public GitHub location of the model sources (shown as "browse repo").
MODELS_REPO_URL = "https://github.com/59psi/SporePrint/tree/main/models"
_MODEL_DESCRIPTION_MAX = 240


def model_header(path: Path) -> tuple[str, str, bool]:
    """(title, description, truncated) from a model's leading comment block.

    Every model opens with `// SporePrint <Title>` followed by a one-paragraph
    summary that ends at the first blank `//` line. Reading it from the file
    keeps the Builder's Models list from drifting out of date (it used to be a
    hand-maintained list in the UI that still described the old designs).

    A summary longer than _MODEL_DESCRIPTION_MAX is cut: at a sentence end
    past character 80 when there is one, else mid-word with "…". `truncated`
    says it was cut either way — the sentence-end cut leaves no mark in the
    text — so the Builder can offer the rest of the paragraph.
    """
    title, desc_lines = path.stem, []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            lines = [next(fh, "") for _ in range(16)]
    except OSError:
        return title, "", False
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
    truncated = len(description) > _MODEL_DESCRIPTION_MAX
    if truncated:
        cut = description[:_MODEL_DESCRIPTION_MAX]
        end = cut.rfind(". ")
        description = cut[: end + 1] if end > 80 else cut.rstrip() + "…"
    return title, description, truncated


def list_models() -> list[dict]:
    """GET /api/builder/models: every top-level models/*.scad (cached)."""
    now = time.time()
    if now - _models_cache["ts"] < _CACHE_TTL and _models_cache["data"]:
        return _models_cache["data"]
    data = []
    if _MODELS_DIR.exists():
        for f in sorted(_MODELS_DIR.glob("*.scad")):
            title, description, truncated = model_header(f)
            data.append({
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                # Self-contained download: lib/ includes are inlined.
                "url": f"/api/builder/models/{f.name}",
                "title": title,
                "description": description,
                # The description stops short of the header paragraph.
                "description_truncated": truncated,
                "source_url": f"{MODELS_REPO_URL}/{f.name}".replace("/tree/", "/blob/"),
            })
    _models_cache["data"] = data
    _models_cache["ts"] = now
    return data


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


def model_path(filename: str) -> Path:
    """A top-level model's path; InvalidBuilderPathError / BuilderFileNotFoundError."""
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename or "\\" in filename:
        raise InvalidBuilderPathError("Invalid filename")
    filepath = _MODELS_DIR / safe_name
    if filepath.suffix != ".scad" or not filepath.is_file():
        raise BuilderFileNotFoundError("Model not found")
    # A symlinked model must still live inside the models directory.
    if not _is_within(filepath.resolve(), _MODELS_DIR.resolve()):
        raise BuilderFileNotFoundError("Model not found")
    return filepath


def flattened_model(filename: str) -> tuple[str, str]:
    """(file name, source with every lib/ include inlined) of a model, so the
    download renders on its own. ScadInlineError when it can't be flattened."""
    filepath = model_path(filename)
    lib_root = (_MODELS_DIR / _MODELS_LIB_SUBDIR).resolve()
    return filepath.name, _inline_scad(filepath.resolve(), lib_root)


def build_models_bundle() -> bytes:
    """ZIP of every top-level model + models/lib/ (+ README), laid out as in
    the repo so the original `include <lib/...>` lines resolve unchanged."""
    models_dir = _MODELS_DIR
    if not models_dir.is_dir():
        raise BuilderFileNotFoundError("Models not found")
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


# ─── Builder files: wiring and architecture diagrams ────────────────────


def list_diagrams() -> list[dict]:
    """GET /api/builder/diagrams: every docs/*.svg (cached)."""
    now = time.time()
    if now - _diagrams_cache["ts"] < _CACHE_TTL and _diagrams_cache["data"]:
        return _diagrams_cache["data"]
    if not _DOCS_DIR.exists():
        _diagrams_cache["data"] = []
    else:
        _diagrams_cache["data"] = [
            {"filename": f.name, "size_bytes": f.stat().st_size,
             "url": f"/api/builder/diagrams/{f.name}"}
            for f in sorted(_DOCS_DIR.glob("*.svg"))
        ]
    _diagrams_cache["ts"] = now
    return _diagrams_cache["data"]


def diagram_path(filename: str) -> Path:
    """A docs/ SVG's path; InvalidBuilderPathError / BuilderFileNotFoundError."""
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename:
        raise InvalidBuilderPathError("Invalid filename")
    filepath = _DOCS_DIR / safe_name
    if not filepath.exists() or filepath.suffix != ".svg":
        raise BuilderFileNotFoundError("Diagram not found")
    return filepath


# ─── Builder files: firmware sources and bundles ─────────────────────────

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


def _published_build_file(path: Path) -> bytes:
    """A root build file's bytes as published: the root platformio.ini
    screened by published_platformio_ini, anything else as it is."""
    if path == (_FIRMWARE_DIR / "platformio.ini").resolve():
        return _published_ini_bytes(path)
    return path.read_bytes()


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


def list_firmware() -> list[dict]:
    """GET /api/builder/firmware: firmware source files grouped by node (cached).

    Every .cpp / .h / .ino / .ini (and library.json manifest) under each
    allow-listed firmware root, with size + download URL, plus a
    "platformio.ini" group holding the build files at the firmware root
    (platformio.ini, VERSION.txt, partition tables, extra_scripts) and a
    synthetic "full" group first (the download-all ZIP). Files outside the
    allow-list are never exposed so a caller can't read build artifacts or
    secrets.
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
                # The size of what is served (a screened platformio.ini can
                # differ from the file on disk).
                "size_bytes": len(_published_build_file(p)),
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


def build_node_bundle(node: str) -> bytes:
    """Build an in-memory ZIP for an image, a library, or the full firmware.

    - `full`            → the entire firmware/ tree (both images + libs)
    - sp_core/sp_drivers → just that library + the root build files
    - node/cam (+v1 aliases) → the image's src + all libs + boards/ + the
      root build files — self-contained, no git clone

    Every library ships with its library.json manifest, and the root build
    files are platformio.ini (screened by published_platformio_ini),
    VERSION.txt, every partition table and whatever platformio.ini references
    (extra_scripts, -I dirs), so the bundle builds exactly like the tested
    tree. BuilderFileNotFoundError for an unknown slug, or when the firmware
    tree (or the slug's source dir) is missing — never a README-only ZIP.
    """
    if node not in _BUNDLE_NODES:
        raise BuilderFileNotFoundError("Unknown node")
    node_rel, _label, is_library = _BUNDLE_NODES[node]
    if node == "full":
        if not any((_FIRMWARE_DIR / root_rel).is_dir() for root_rel in _FIRMWARE_ROOTS):
            raise BuilderFileNotFoundError("Firmware not found")
    elif not (_FIRMWARE_DIR / node_rel).is_dir():
        raise BuilderFileNotFoundError("Source not found")
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
            ini = (_FIRMWARE_DIR / "platformio.ini").resolve()
            for f in files:
                arc = f"firmware/{f.relative_to(fw_root).as_posix()}"
                if f != ini:
                    write(f, arc)
                elif arc not in written:
                    # The screened copy, with the file's own timestamp and mode.
                    written.add(arc)
                    zf.writestr(zipfile.ZipInfo.from_file(f, arc), _published_build_file(f),
                                compress_type=zipfile.ZIP_DEFLATED)
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


def firmware_file(path: str) -> tuple[str, bytes]:
    """(file name, bytes) of a firmware file the Builder serves.

    Only the root build files (platformio.ini, screened by
    published_platformio_ini; VERSION.txt; partition tables; extra_scripts)
    or a source file / library.json under _FIRMWARE_ROOTS. Raises
    InvalidBuilderPathError (traversal, unsupported type) or
    BuilderFileNotFoundError.
    """
    if ".." in path or path.startswith("/"):
        raise InvalidBuilderPathError("Invalid path")
    root = _FIRMWARE_DIR.resolve()
    target = (_FIRMWARE_DIR / path).resolve()
    if not _is_within(target, root):
        raise InvalidBuilderPathError("Invalid path")
    if not target.is_file():
        raise BuilderFileNotFoundError("File not found")

    rel_str = target.relative_to(root).as_posix()
    build_files = {p.relative_to(root).as_posix(): p for p in _firmware_build_files()[0]}
    if rel_str in build_files:
        return target.name, _published_build_file(build_files[rel_str])
    if not _servable_source(target):
        raise InvalidBuilderPathError("Unsupported file type")
    if not any(rel_str.startswith(f"{r}/") for r in _FIRMWARE_ROOTS):
        raise BuilderFileNotFoundError("File not found")
    return target.name, target.read_bytes()


# ─── Builder's Assistant system context ──────────────────────────────────

# What the shipped firmware actually supports. Kept in step with
# firmware/boards/board_profile_*.h, sp_core/personality.h, sp_core/
# scene_table.h and config/mosquitto/acl.conf by
# tests/test_cross_cluster_builder.py. A guide built on the wrong camera, a
# reserved GPIO or a topic the broker ACL denies cannot work.
_HARDWARE_CONTRACT = """## Firmware Images and Boards (PlatformIO envs)
- Unified node — one image for every sensor/actuator node: {node_envs}. ESP32-WROOM-32 DevKit is the canonical board; ESP32-S3-DevKitC-1 builds are bench-verification pending. The channel-bank personality is chosen in the setup portal:
  - climate: sensors only, no channels
  - relay: 4 switch channels fae, exhaust, circulation, aux (25 kHz PWM, pwm 0-255; aux drives the misting pump and cuts off after 60 s unless cmd/config max_on_sec raises it)
  - lighting: 4 dim channels white, blue, red, far_red (10-bit level 0-1023) plus scenes colonization_dark, pinning_daylight, fruiting_standard, cordyceps_blue, lions_mane_gentle
- Sensors autodetected on the I2C bus at boot: SHT3x/SHT4x temp+RH (0x44/0x45), AHT20/AHT21/AHT25 temp+RH (0x38, used when no SHT is fitted), SCD4x CO2 (0x62) or SCD30 (0x61), BH1750 lux (0x23/0x5C), BME280/BMP280 pressure (0x76/0x77, telemetry pressure_hpa). Optional peripherals, enabled in the setup portal or by cmd/config {{"peripherals": {{"mhz19": bool, "hx711": bool, "reed": bool, "reed_inv": bool}}}}: MH-Z19C CO2 (UART), HX711 load-cell scale, door reed switch (reed_inv inverts a door contact wired on its NO terminal and applies live; changing mhz19/hx711/reed reboots the node).
- Camera node — envs {cam_envs}. `cam` is the AI-Thinker ESP32-CAM, the camera the BOM recommends: its image sensor is OV2640 (the BOM AITRIP 2-pack) or OV3660 (current HiLetgo/Aideepen packs) or OV5640, auto-detected at boot, and it has a flash LED. The other cam envs build the same image for the ESP32-S3 camera boards earlier BOMs listed: cam_esp32s3 = Freenove ESP32-S3-WROOM CAM, cam_xiao_esp32s3 = Seeed XIAO ESP32S3 Sense, cam_waveshare_s3 = Waveshare ESP32-S3-CAM-OVxxxx (no flash LED on any of them; bench verification pending). ESP32-S3 camera boards are supported for hardware an operator already owns — never recommend buying one (other ESP32-S3-CAM listings use other pin maps); a second camera is another AI-Thinker ESP32-CAM.

## Reserved GPIOs — never assign these to new hardware
ESP32-WROOM-32 node (node_esp32):
- I2C sensor bus SDA 21, SCL 22 (add new I2C sensors on this bus at a free address)
- Channel-bank MOSFET gates 25, 26, 27, 14
- HX711 load cell DOUT 32, SCK 33
- Door reed switch 35 (input-only, external pull-up)
- MH-Z19C CO2 on UART2 RX 16, TX 17
- BOOT / factory reset 0
- Also off-limits: 6-11 (SPI flash); strapping pins 2, 5, 12, 15 need care; 34-39 are input-only with no pull-ups
- Usually free: 4, 13, 18, 19, 23 (4 and 13 are ADC2: no analogRead while WiFi is on, and the node always runs WiFi) and 34, 36, 39 as inputs (ADC1: use these for analog sensors)
ESP32-S3-DevKitC-1 node (node_esp32s3 and variants): SDA 8, SCL 9; channels 4, 5, 6, 7; HX711 10/11; reed 12; MH-Z19C RX 16 / TX 17; BOOT 0. Avoid 0, 3, 45, 46 (strapping), 19, 20 (USB), 26-37 (flash/PSRAM), 38 (RGB LED on DevKitC-1 v1.1), 43, 44 (UART0: the Serial log and the USB-UART bridge), 47, 48 (1.8 V I/O on the N32R16V; 48 is the RGB LED on DevKitC-1 v1.0). Usually free: 1, 2, 13, 14, 15, 18, 21, 39, 40, 41, 42 (1 and 2 are the only free ADC1 pins: use them for analog sensors; 13, 14, 15 and 18 are ADC2, unreliable while WiFi is on). The channel bank uses LEDC channels 0-3 on one timer; nothing else may claim LEDC on this board.
AI-Thinker ESP32-CAM (cam): every camera pin is in use (0, 5, 18, 19, 21, 22, 23, 25, 26, 27, 32, 34, 35, 36, 39), the flash LED 4 and factory reset 13 — there are no spare GPIOs; put new sensors and actuators on a node.
ESP32-S3 camera boards (cam_esp32s3, cam_xiao_esp32s3, cam_waveshare_s3): camera pins per firmware/boards/board_profile_esp32s3cam.h, BOOT 0 is the reset button — no GPIOs are offered for new hardware; put new sensors and actuators on a node.

## MQTT Contract (topics under sporeprint/{{node_id}}/)
Node → Pi. The broker ACL (config/mosquitto/acl.conf) lets a node publish ONLY these, under its own id — anything else is silently dropped:
- `telemetry` — JSON {{ts, temp_f, temp_c, humidity, co2_ppm, lux, dew_point_f, weight_g, door_open, ...}}; ts is Unix epoch seconds once NTP-synced (uptime seconds before); frames flushed from the offline buffer carry "replay": true. A lighting bank also publishes its channel levels here as {{ts, report: "dim_levels", <channel>: level 0-1023, ...}}: live state, never stored or evaluated by rules
- `telemetry/{{channel}}` — one channel's switch state {{channel, state, pwm, trigger}}; trigger is command | report | timer (a duration_sec ran out) | safety_cutoff (max-on backstop, safe mode, OTA start)
- `status` — retained online/offline (also the LWT); `status/heartbeat` — {{uptime_sec, free_heap, firmware_version, wifi_rssi, ...}}
- `health` — per-component health; the only place a node lists its channel names
- `alert` — {{type, value, message, sensor}}
- `ota` — OTA lifecycle events
- `logs` — forwarded log batches (write-only)
- `coredump/chunk` — panic-dump upload (write-only); {{seq, total, size, b64_data, coredump_id}}, the node keeps the dump in flash until the Pi acks that id
Pi → node (the node subscribes cmd/#, matches the suffix exactly, and verifies the HMAC signature once provisioned with a key):
- `cmd/{{channel}}` — {{state: "on"|"off", pwm, level, duration_sec, ramp_sec}}; "off" always wins, and the Pi never sends pwm/level with "off"; "on" with duration_sec is a pulse the node ends itself, "on" without one holds until an "off" (or the node's max-on backstop) and ends a pulse still running
- `cmd/scene` — {{scene: <name>}} (lighting personality only)
- `cmd/config` — {{read_interval_ms, publish_interval_ms, calibrate_co2, tare, calibrate_scale, max_on_sec: {{<channel>: seconds}}, peripherals: {{...}}}}
- `cmd/coredump_ack` — {{coredump_id}}, sent by the Pi only after the dump is stored on disk; the node then erases it
- `cmd/ota_manifest` — {{manifest_b64, sig_b64}}, a signed release manifest the Pi sends before an OTA push; an image built with the verify key then flashes only that exact image
- Camera: {{capture: true, flash: bool}} takes a frame now; {{server_url: ...}} sets the upload URL. Frames are HTTP POSTed as raw JPEG to /api/vision/frame with X-Node-Id, X-Timestamp (only when NTP-synced) and X-Camera-Sensor.
A new node topic needs BOTH a `pattern write sporeprint/%u/<topic>` line in config/mosquitto/acl.conf AND a handler branch in server/app/mqtt.py; prefer adding keys to the telemetry JSON (older servers ignore unknown keys). Shelly/Tasmota smart plugs stay on their own shellies/# and tasmota/# trees.
"""


def _hardware_contract() -> str:
    envs = platformio_image_envs(_FIRMWARE_DIR / "platformio.ini")
    return _HARDWARE_CONTRACT.format(
        node_envs=", ".join(f"`{e}`" for e in envs["node"]),
        cam_envs=", ".join(f"`{e}`" for e in envs["cam"]),
    )


def _node_line(n: dict) -> str:
    line = (f"- **{n['node_id']}** ({n['node_type']}) — {n.get('status') or '?'}, "
            f"FW {n.get('firmware_version') or '?'}, IP {n.get('ip_address') or '?'}")
    try:
        config = json.loads(n.get("config") or "{}")
    except (TypeError, ValueError):
        config = {}
    sensor = config.get("camera_sensor") if isinstance(config, dict) else None
    if isinstance(sensor, str) and sensor:
        line += f", camera sensor {sensor.upper()}"
    return line


async def _build_system_context() -> str:
    """Build a context doc of current system state for the Builder's Assistant."""
    context_parts = ["# SporePrint System State\n"]

    # Registered hardware nodes
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM hardware_nodes ORDER BY node_id")
        nodes = [dict(r) for r in await cursor.fetchall()]
        if nodes:
            context_parts.append("## Registered Hardware Nodes")
            context_parts.extend(_node_line(n) for n in nodes)
            context_parts.append("")

        # Smart plugs
        cursor = await db.execute("SELECT * FROM smart_plugs ORDER BY plug_id")
        plugs = [dict(r) for r in await cursor.fetchall()]
        if plugs:
            context_parts.append("## Smart Plugs")
            for p in plugs:
                context_parts.append(
                    f"- **{p['plug_id']}** ({p['plug_type']}) — {p.get('device_role') or 'unknown role'}, "
                    f"MQTT: {p['mqtt_topic_prefix']}"
                )
            context_parts.append("")

    context_parts.append(_hardware_contract())
    context_parts.append("""## Available Power Supply Voltages
- 5V (USB/buck converter)
- 12V (LED strips, fans, solenoids)
- 3.3V (ESP32 logic)

## Operator Equipment
- Bambu Lab H2D 3D printer (OpenSCAD parametric designs)
- Flow hood, agar work capability
- IRLZ44N MOSFETs in stock
- Noctua fans, peristaltic pumps available
""")

    return "\n".join(context_parts)


def _guide_error(code: str, message: str, **extra) -> dict:
    """An error result. `code` lets the router pick the HTTP status:
    not_configured → 503; refusal / truncated / empty / upstream_error → 502."""
    return {"error": message, "code": code, **extra}


async def generate_guide(request: str, constraints: str = "") -> dict:
    """Generate a detailed hardware integration guide using Claude."""
    if not settings.claude_api_key:
        return _guide_error("not_configured", "Claude API key not configured")

    system_context = await _build_system_context()

    system_prompt = f"""You are the SporePrint Builder's Assistant — an expert embedded systems engineer
and mycologist helping the operator add new hardware to their automated mushroom grow closet.

{system_context}

When the operator describes what they want to add, generate a DETAILED implementation guide
with these sections (use markdown headers):

## 1. Parts List
Specific components, model numbers, approximate cost. Be specific about ratings.

## 2. Wiring Diagram
ASCII diagram showing ESP32 GPIO connections, voltage levels, required passive components
(resistors, capacitors, flyback diodes for solenoids, etc.). Use only GPIOs the reserved list
above leaves free.

## 3. Firmware Changes
Complete PlatformIO code snippets: sensor driver initialization, MQTT topics, command handler,
NVS configuration keys. Match existing code style from the sp_core/sp_device libraries.

## 4. MQTT Integration
New topics, payload formats, QoS levels. Follow the MQTT contract above, including the ACL
and server/app/mqtt.py changes any new topic needs.

## 5. Backend Integration
New telemetry parser additions, API endpoints if needed, automation rule templates.

## 6. 3D-Printable Mount
OpenSCAD parametric design for Bambu Lab printer. Include mounting holes and dimensions
for the specific components.

## 7. Automation Rules
Pre-built YAML-style rule templates using the new hardware.

## 8. Safety Notes
Current ratings, thermal limits, waterproofing needs, failsafes required.

## 9. Test Procedure
Step-by-step verification checklist.

Be thorough, practical, and specific. The operator is experienced with ESP32 and electronics."""

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.claude_api_key)

        user_msg = f"Request: {request}"
        if constraints:
            user_msg += f"\n\nConstraints: {constraints}"

        async with client.messages.stream(
            model=settings.claude_model,
            max_tokens=_GUIDE_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        ) as stream:
            message = await stream.get_final_message()

        stop_reason = claude_stop_reason(message)
        if stop_reason == "refusal":
            return _guide_error("refusal", "Claude declined to generate this guide (refusal)")
        guide_text = claude_response_text(message)
        if stop_reason == "max_tokens":
            # A guide cut off mid-section must not be saved as if complete.
            log.warning("Builder guide truncated at max_tokens; not saved")
            return _guide_error(
                "truncated",
                "The guide was cut off at the output limit and was not saved. "
                "Try narrowing the request.",
                truncated=True,
                request=request,
                constraints=constraints,
                guide=guide_text,
            )
        if not guide_text.strip():
            return _guide_error("empty", "Claude returned an empty guide")

        # Save guide
        guide_id = await _save_guide(request, constraints, guide_text)

        return {
            "guide_id": guide_id,
            "request": request,
            "constraints": constraints,
            "guide": guide_text,
            "generated_at": time.time(),
        }

    except Exception as e:
        log.error("Builder guide generation failed: %s", e)
        return _guide_error("upstream_error", str(e))


async def _save_guide(request: str, constraints: str, guide: str) -> int:
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO builder_guides (request, constraints, guide, created_at) VALUES (?, ?, ?, ?)",
            (request, constraints, guide, time.time()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_guides() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, request, constraints, created_at FROM builder_guides ORDER BY created_at DESC"
        )
        return [dict(r) for r in await cursor.fetchall()]


async def get_guide(guide_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM builder_guides WHERE id = ?", (guide_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
