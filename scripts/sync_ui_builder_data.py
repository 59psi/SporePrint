#!/usr/bin/env python3
"""Verify (and, when only its data is stale, refresh) the compiled dashboard's
Builder page in ui/dist against this server.

The dashboard source lives in the private monorepo (frontend/packages/pi-ui;
Builder data in @sporeprint/design). Its Builder page reads the Pi LIVE:

  GET /api/builder/tiers + /api/builder/tiers/{id}   BOM, wiring, setup steps
  GET /api/builder/models                            3D models (self-contained .scad)
  GET /api/builder/diagrams                          docs/wiring-tier*.svg
  GET /api/builder/firmware                          firmware ZIPs + files

and falls back, per resource, to a BUILT-IN copy compiled into the bundle when
a request fails. That copy is generated from this repo by the private repo's
scripts/port_builder.py (into design/src/data/builder.generated.ts):

  tiers     <- server/app/builder/hardware_guides.py (TIERS)
  models    <- the /api/builder/models listing (title/description from each
               models/*.scad header)
  diagrams  <- docs/wiring-tier*.svg, one per tier
  + the firmware images' PlatformIO envs <- firmware/platformio.ini (the
    /api/builder/firmware listing has no envs, so the page ALWAYS uses these
    to decide which images a tier needs)

This script checks two things in ui/dist:

  structure  the bundle calls the live endpoints above and carries none of the
             stale static Builder's tells (the 404 GitHub paths hardware/3d and
             hardware/wiring, the false "slicer-ready STL exports" claim, the
             old /*sp-sync:*/ patch markers). Only a rebuild in the private
             repo fixes these.
  data       the built-in fallback equals what this server would serve. Model
             and diagram sizes (sizeKb, a display label) are not compared, so
             regenerating an SVG does not need a dashboard rebuild.

Usage (needs the server's environment for the BOM imports):
    cd server && uv run python ../scripts/sync_ui_builder_data.py --check   # verify; exit 1 on any problem
    cd server && uv run python ../scripts/sync_ui_builder_data.py           # verify; refresh stale data

Without --check, stale DATA blocks are rewritten in place with this server's
data (as compact JSON) and the bundle is renamed to a fresh content hash so
browsers that cached the old file refetch it. That is the stop-gap for a BOM
or model change landing here before the private repo rebuilds the dashboard;
the real fix is `python3 scripts/port_builder.py` + a pi-ui rebuild there (see
README "Development"). A structural problem is never patched: the script
exits 1 and asks for that rebuild.

server/tests/test_ui_builder_sync.py runs these checks, so a BOM, model or
firmware-env change that the dashboard does not carry fails the test suite.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SERVER = REPO / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from app.builder.hardware_guides import TIERS  # noqa: E402
from app.builder.models_router import MODELS_REPO_URL, _list_models  # noqa: E402
from app.builder.service import platformio_image_envs  # noqa: E402

DIST = REPO / "ui" / "dist"
DOCS = REPO / "docs"
PLATFORMIO_INI = REPO / "firmware" / "platformio.ini"
GITHUB_BLOB = "https://github.com/59psi/SporePrint/blob/main"
MODELS_BUNDLE_URL = "/api/builder/models-bundle.zip"
_BUNDLE_REF = re.compile(r"/assets/(index-[A-Za-z0-9_-]+)\.js")

# Tier id -> its wiring diagram's filename prefix under docs/ (the same map as
# pi-ui's DIAGRAM_PREFIX and the private repo's port_builder.py).
_DIAGRAM_PREFIX = {
    "bare_bones": "wiring-tier1-",
    "recommended": "wiring-tier2-",
    "all_the_things": "wiring-tier3-",
}
# Firmware image -> its source dir, as the bundle's built-in BUILDER_FIRMWARE
# entries carry it (`path`) and GET /api/builder/firmware groups it.
_IMAGE_PATHS = {"node": "src/node", "cam": "src/cam"}

# GET endpoints the Builder page must call (method-less: the bundle only GETs).
# A literal "/api/builder/x" string, plus the per-tier detail request built
# as `/api/builder/tiers/${id}` (or "/api/builder/tiers/" + id).
LIVE_ENDPOINTS = (
    "/api/builder/tiers",
    "/api/builder/models",
    "/api/builder/diagrams",
    "/api/builder/firmware",
)
_TIER_DETAIL = re.compile(r"/api/builder/tiers/(?:\$\{|[\"'`]\s*\+)")
# Tells of the stale static Builder (pre-2026-10 bundles): neither GitHub path
# exists in this repo, no STL exports ship, and the sp-sync markers belong to
# this script's old patch-the-static-copy mode.
_STALE_TELLS = (
    ("hardware/3d", re.compile(r"hardware/3d")),
    ("hardware/wiring", re.compile(r"hardware/wiring")),
    ("the 'slicer-ready STL exports' claim", re.compile(r"slicer-ready", re.I)),
    ("the old /*sp-sync:*/ patch markers", re.compile(r"/\*/?sp-sync:")),
)

# Locators for the built-in fallback blocks (esbuild emits bare keys; a block
# this script refreshed has JSON-quoted keys).
_Q = "[\"'`]"


def _key(name: str) -> str:
    return rf'"?{name}"?\s*:\s*'


_BLOCKS = {
    "tiers": re.compile(rf"\[\s*\{{\s*{_key('id')}{_Q}bare_bones{_Q}\s*,\s*{_key('name')}"),
    "models": re.compile(rf"\[\s*\{{\s*{_key('filename')}{_Q}[^\"'`]+\.scad{_Q}\s*,\s*{_key('title')}"),
    "diagrams": re.compile(rf"\[\s*\{{\s*{_key('tierId')}{_Q}bare_bones{_Q}"),
}


def _firmware_envs_locator(path: str) -> re.Pattern:
    return re.compile(rf"{_key('path')}{_Q}{re.escape(path)}{_Q}\s*,\s*{_key('envs')}(?=\[)")


# ── expected data (what this server serves) ───────────────────────────


def _component(c) -> dict:
    out = {
        "name": c.name,
        "role": c.role,
        "quantity": c.quantity,
        "priceApprox": c.price_approx,
        "url": c.url,
        "category": c.category,
        "notes": c.notes,
    }
    if c.pack_price:
        # One pack covers `quantity`: the line costs packPrice once.
        out["packPrice"] = c.pack_price
    out["shared"] = bool(c.shared)
    return out


def expected_tiers() -> list[dict]:
    """TIERS in the design package's BuilderTier shape (port_builder.py)."""
    return [
        {
            "id": t.id,
            "name": t.name,
            "tagline": t.tagline,
            "estimatedCost": t.estimated_cost,
            "componentCount": sum(c.quantity for c in t.components),
            "bestFor": t.best_for,
            "speciesSupport": t.species_support,
            "whatYouGet": list(t.what_you_get),
            "capabilityGroups": [{"title": g.title, "items": list(g.items)} for g in t.capability_groups],
            "limitations": list(t.limitations),
            "components": [_component(c) for c in t.components],
            "wiring": [
                {"fromDevice": w.from_device, "fromPin": w.from_pin,
                 "toDevice": w.to_device, "toPin": w.to_pin, "note": w.note}
                for w in t.wiring
            ],
            "wiringDiagram": t.wiring_diagram,
            "firmwareTargets": list(t.firmware_targets),
            "setupSteps": list(t.setup_steps),
        }
        for t in TIERS
    ]


def expected_models() -> list[dict]:
    """GET /api/builder/models in the BuilderModelFile shape."""
    return [
        {
            "filename": m["filename"],
            "title": m["title"],
            "description": m["description"],
            "url": m["url"],
            "sourceUrl": m["source_url"],
            "sizeKb": round(m["size_bytes"] / 1024, 1),
        }
        for m in _list_models()
    ]


def expected_diagrams() -> list[dict]:
    """One docs/wiring-tier*.svg per tier, in the BuilderWiringDiagram shape."""
    out = []
    for t in TIERS:
        prefix = _DIAGRAM_PREFIX[t.id]
        matches = sorted(DOCS.glob(f"{prefix}*.svg"))
        if len(matches) != 1:
            raise SystemExit(f"expected one docs/{prefix}*.svg, found {[p.name for p in matches]}")
        svg = matches[0]
        out.append({
            "tierId": t.id,
            "label": svg.stem.removeprefix(prefix),
            "filename": svg.name,
            "url": f"/api/builder/diagrams/{svg.name}",
            "sourceUrl": f"{GITHUB_BLOB}/docs/{svg.name}",
            "sizeKb": round(svg.stat().st_size / 1024, 1),
        })
    return out


def expected_firmware_envs() -> dict[str, list[str]]:
    """Image source dir -> its PlatformIO envs ({"src/node": [...], ...})."""
    envs = platformio_image_envs(PLATFORMIO_INI)
    return {path: envs[image] for image, path in _IMAGE_PATHS.items()}


def expected() -> dict:
    return {
        "tiers": expected_tiers(),
        "models": expected_models(),
        "diagrams": expected_diagrams(),
        "firmware": expected_firmware_envs(),
    }


# ── a minimal reader for the minified JS literals ─────────────────────


class JsLiteralError(ValueError):
    pass


_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_NUMBER = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_SIMPLE_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v"}


def parse_js_literal(src: str, pos: int) -> tuple[object, int]:
    """Parse the JS literal (array/object/string/number/bool/null) at src[pos].

    Covers what esbuild emits for static data: bare or quoted keys, '/"/`
    strings with JS escapes, `!0`/`!1` booleans, `.5`-style numbers, null and
    `void 0`. Anything else (a spread, an identifier, a `${}` template) raises
    JsLiteralError. Returns (value, index just past it).
    """
    return _Reader(src).value(pos)


class _Reader:
    def __init__(self, src: str) -> None:
        self.src = src

    def _ws(self, i: int) -> int:
        while i < len(self.src) and self.src[i] in " \t\r\n":
            i += 1
        return i

    def _fail(self, i: int, what: str) -> JsLiteralError:
        return JsLiteralError(f"{what} at {i}: {self.src[i:i + 40]!r}")

    def value(self, i: int) -> tuple[object, int]:
        i = self._ws(i)
        if i >= len(self.src):
            raise self._fail(i, "unexpected end")
        ch = self.src[i]
        if ch == "[":
            return self._array(i + 1)
        if ch == "{":
            return self._object(i + 1)
        if ch in "\"'`":
            return self._string(i)
        for word, val in (("!0", True), ("!1", False), ("true", True), ("false", False),
                          ("null", None), ("void 0", None)):
            if self.src.startswith(word, i) and not self._ident_char(i + len(word)):
                return val, i + len(word)
        m = _NUMBER.match(self.src, i)
        if m:
            text = m.group()
            return (float(text) if any(c in text for c in ".eE") else int(text)), m.end()
        raise self._fail(i, "not a literal")

    def _ident_char(self, i: int) -> bool:
        return i < len(self.src) and (self.src[i].isalnum() or self.src[i] in "_$")

    def _array(self, i: int) -> tuple[list, int]:
        out: list = []
        i = self._ws(i)
        if self.src.startswith("]", i):
            return out, i + 1
        while True:
            val, i = self.value(i)
            out.append(val)
            i = self._ws(i)
            if self.src.startswith(",", i):
                i = self._ws(i + 1)
                if self.src.startswith("]", i):  # trailing comma
                    return out, i + 1
                continue
            if self.src.startswith("]", i):
                return out, i + 1
            raise self._fail(i, "expected , or ]")

    def _object(self, i: int) -> tuple[dict, int]:
        out: dict = {}
        i = self._ws(i)
        if self.src.startswith("}", i):
            return out, i + 1
        while True:
            i = self._ws(i)
            if self.src.startswith("...", i):
                raise self._fail(i, "object spread")
            if i < len(self.src) and self.src[i] in "\"'`":
                key, i = self._string(i)
            else:
                m = _IDENT.match(self.src, i) or _NUMBER.match(self.src, i)
                if not m:
                    raise self._fail(i, "expected a key")
                key, i = m.group(), m.end()
            i = self._ws(i)
            if not self.src.startswith(":", i):
                raise self._fail(i, "expected :")
            out[key], i = self.value(i + 1)
            i = self._ws(i)
            if self.src.startswith(",", i):
                i = self._ws(i + 1)
                if self.src.startswith("}", i):
                    return out, i + 1
                continue
            if self.src.startswith("}", i):
                return out, i + 1
            raise self._fail(i, "expected , or }")

    def _string(self, i: int) -> tuple[str, int]:
        quote = self.src[i]
        i += 1
        parts: list[str] = []
        while True:
            if i >= len(self.src):
                raise self._fail(i, "unterminated string")
            ch = self.src[i]
            if ch == quote:
                break
            if quote == "`" and self.src.startswith("${", i):
                raise self._fail(i, "template substitution")
            if ch != "\\":
                parts.append(ch)
                i += 1
                continue
            if i + 1 >= len(self.src):
                raise self._fail(i, "unterminated string")
            esc = self.src[i + 1]
            i += 2
            if esc in _SIMPLE_ESCAPES:
                parts.append(_SIMPLE_ESCAPES[esc])
            elif esc == "0" and not self.src[i:i + 1].isdigit():
                parts.append("\0")
            elif esc == "x":
                parts.append(chr(int(self.src[i:i + 2], 16)))
                i += 2
            elif esc == "u" and self.src.startswith("{", i):
                end = self.src.index("}", i)
                parts.append(chr(int(self.src[i + 1:end], 16)))
                i = end + 1
            elif esc == "u":
                parts.append(chr(int(self.src[i:i + 4], 16)))
                i += 4
            elif esc == "\r":  # line continuation (\r\n or \r)
                if self.src.startswith("\n", i):
                    i += 1
            elif esc in "\n\u2028\u2029":  # line continuation
                pass
            else:
                parts.append(esc)
        text = "".join(parts)
        # Re-pair UTF-16 surrogates written as two \uXXXX escapes.
        text = text.encode("utf-16", "surrogatepass").decode("utf-16")
        if quote == "`":
            text = text.replace("\r\n", "\n")
        return text, i + 1


# ── reading the bundle ────────────────────────────────────────────────


def bundle_path() -> Path:
    html = (DIST / "index.html").read_text(encoding="utf-8")
    m = _BUNDLE_REF.search(html)
    if not m:
        raise SystemExit("ui/dist/index.html references no /assets/index-*.js bundle")
    path = DIST / "assets" / f"{m.group(1)}.js"
    if not path.is_file():
        raise SystemExit(f"ui/dist/index.html references {path.name}, which is missing")
    return path


def _locate(js: str, name: str) -> tuple[int, int, object]:
    """(start, end, parsed value) of one fallback block; raises LookupError."""
    if name.startswith("firmware:"):
        path = name.split(":", 1)[1]
        hits = list(_firmware_envs_locator(path).finditer(js))
        starts = [m.end() for m in hits]
    else:
        hits = list(_BLOCKS[name].finditer(js))
        starts = [m.start() for m in hits]
    if len(starts) != 1:
        raise LookupError(f"found the built-in '{name}' block {len(starts)} times, expected once")
    try:
        value, end = parse_js_literal(js, starts[0])
    except JsLiteralError as exc:
        raise LookupError(f"could not read the built-in '{name}' block: {exc}") from exc
    return starts[0], end, value


def read_fallback(js: str) -> dict:
    """The bundle's built-in Builder data, parsed (raises LookupError)."""
    out: dict = {name: _locate(js, name)[2] for name in _BLOCKS}
    out["firmware"] = {path: _locate(js, f"firmware:{path}")[2] for path in _IMAGE_PATHS.values()}
    return out


def _without_size(items: list) -> list:
    return [{k: v for k, v in d.items() if k != "sizeKb"} if isinstance(d, dict) else d for d in items]


def structural_problems(js: str) -> list[str]:
    """What only a rebuild of pi-ui (private repo) can fix."""
    problems = []
    for endpoint in LIVE_ENDPOINTS:
        if not re.search(rf"[\"'`]{re.escape(endpoint)}[\"'`]", js):
            problems.append(f"the Builder never requests {endpoint} (no live data)")
    if not _TIER_DETAIL.search(js):
        problems.append("the Builder never requests /api/builder/tiers/{id} (no live BOM)")
    for label, pattern in _STALE_TELLS:
        if pattern.search(js):
            problems.append(f"the bundle contains {label} (stale static Builder)")
    for needle, what in ((MODELS_REPO_URL, "the models 'browse repo' link"),
                         (MODELS_BUNDLE_URL, "the models ZIP link")):
        if needle not in js:
            problems.append(f"{what} ({needle}) is missing")
    for name in (*_BLOCKS, *(f"firmware:{p}" for p in _IMAGE_PATHS.values())):
        try:
            _locate(js, name)
        except LookupError as exc:
            problems.append(str(exc))
    return problems


def stale_blocks(js: str, want: dict | None = None) -> list[str]:
    """Names of the built-in data blocks that differ from this server's data.

    Blocks that cannot be located are structural problems, not listed here.
    """
    want = want or expected()
    stale = []
    for name in _BLOCKS:
        try:
            have = _locate(js, name)[2]
        except LookupError:
            continue
        if name == "tiers":
            same = have == want["tiers"]
        else:
            same = isinstance(have, list) and _without_size(have) == _without_size(want[name])
        if not same:
            stale.append(name)
    for path, envs in want["firmware"].items():
        try:
            if _locate(js, f"firmware:{path}")[2] != envs:
                stale.append(f"firmware:{path}")
        except LookupError:
            continue
    return stale


def _js(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def refresh(js: str, names: list[str], want: dict | None = None) -> str:
    """Rewrite the named data blocks with this server's data."""
    want = want or expected()
    for name in names:
        start, end, _ = _locate(js, name)
        if name.startswith("firmware:"):
            payload = want["firmware"][name.split(":", 1)[1]]
        else:
            payload = want[name]
        js = js[:start] + _js(payload) + js[end:]
    return js


def check() -> tuple[list[str], list[str]]:
    """(structural problems, stale data blocks) of ui/dist; both [] = good."""
    js = bundle_path().read_text(encoding="utf-8")
    return structural_problems(js), stale_blocks(js)


def write() -> str:
    """Refresh stale data blocks and rename the bundle to its new hash."""
    path = bundle_path()
    js = path.read_text(encoding="utf-8")
    structural = structural_problems(js)
    if structural:
        raise SystemExit(_rebuild_message(structural))
    want = expected()
    stale = stale_blocks(js, want)
    if not stale:
        return f"{path.name}: Builder fallback already matches this server"
    js = refresh(js, stale, want)
    if stale_blocks(js, want) or structural_problems(js):
        raise SystemExit("refresh did not converge; rebuild ui/dist from the private repo")
    old_stem = path.stem
    new_stem = "index-" + hashlib.sha256(js.encode("utf-8")).hexdigest()[:8]
    js = js.replace(f"//# sourceMappingURL={old_stem}.js.map", f"//# sourceMappingURL={new_stem}.js.map")
    (path.parent / f"{new_stem}.js").write_text(js, encoding="utf-8")
    old_map = path.parent / f"{old_stem}.js.map"
    if old_map.exists():
        old_map.rename(path.parent / f"{new_stem}.js.map")
    path.unlink()
    html_path = DIST / "index.html"
    html = html_path.read_text(encoding="utf-8")
    html_path.write_text(html.replace(f"/assets/{old_stem}.js", f"/assets/{new_stem}.js"), encoding="utf-8")
    return f"refreshed {', '.join(stale)}: {old_stem}.js -> {new_stem}.js"


def _rebuild_message(structural: list[str]) -> str:
    return (
        "ui/dist's Builder page is not the live-data dashboard:\n  - "
        + "\n  - ".join(structural)
        + "\nRebuild it in the private monorepo: python3 scripts/port_builder.py "
        "--public-repo <this repo>, then `pnpm --filter @sporeprint/pi-ui build` and "
        "rsync -a --delete frontend/packages/pi-ui/dist/ <this repo>/ui/dist/"
    )


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        structural, stale = check()
        if structural:
            print(_rebuild_message(structural))
        if stale:
            print("ui/dist Builder fallback is stale: " + ", ".join(stale)
                  + "\nRefresh: cd server && uv run python ../scripts/sync_ui_builder_data.py")
        if structural or stale:
            sys.exit(1)
        print("ui/dist Builder reads the Pi live; its built-in fallback matches this server")
    else:
        print(write())
