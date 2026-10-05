#!/usr/bin/env python3
"""Sync the compiled Pi dashboard's Builder page with the server's data.

The dashboard source lives in the private monorepo (frontend/packages/pi-ui,
data in @sporeprint/design). Its Builder page renders a STATIC copy of the
hardware tiers (Shopping / Wiring / Setup tabs), the 3D-model list and the
wiring-diagram links. That copy went stale: it showed a pre-audit BOM with no
cabling, "browse repo" and the diagram links pointed at GitHub paths that do
not exist (404), and the model downloads were raw GitHub files that cannot
render on their own now that models include lib/sp_inserts.scad.

Until the dashboard fetches /api/builder/tiers/{id} and /api/builder/models
at runtime, this script writes the server's CURRENT data into the compiled
bundle in ui/dist:

  tiers     <- server/app/builder/hardware_guides.py (TIERS)
  models    <- /api/builder/models listing (titles/descriptions from each
               .scad header, self-contained /api/builder/models/<file> URLs)
  shared    <- BOM lines flagged `shared` (not multiplied per chamber)
  diagrams  <- docs/wiring-tier*.svg, served by the Pi at /api/builder/diagrams
  + the Models tab header copy and its "browse repo" link

Each injected block is wrapped in /*sp-sync:NAME*/ ... /*/sp-sync:NAME*/
markers so re-running finds it again. The bundle is renamed to a fresh content
hash so browsers that cached the old file refetch it.

Usage (needs the server's environment for the BOM imports):
    cd server && uv run python ../scripts/sync_ui_builder_data.py           # rewrite ui/dist
    cd server && uv run python ../scripts/sync_ui_builder_data.py --check   # exit 1 if stale

server/tests/test_ui_builder_sync.py runs the --check logic, so a BOM or model
change that is not synced into ui/dist fails the test suite.
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
from app.builder.models import usd  # noqa: E402
from app.builder.models_router import MODELS_REPO_URL, _list_models  # noqa: E402

DIST = REPO / "ui" / "dist"
DOCS = REPO / "docs"
_BUNDLE_REF = re.compile(r"/assets/(index-[A-Za-z0-9_-]+)\.js")

# Tier id -> wiring diagram (docs/) the Wiring tab links to.
_DIAGRAM_PREFIX = {
    "bare_bones": "wiring-tier1-",
    "recommended": "wiring-tier2-",
    "all_the_things": "wiring-tier3-",
}

# First-run locators: patterns that identify each static block in the bundle
# as the private repo builds it. After the first sync the markers are used.
_FIRST_RUN = {
    "tiers": re.compile(r'=\[\{id:"bare_bones",name:"[^"]*",tagline:'),
    "models": re.compile(r'=\[\{filename:"[^"]+\.scad",description:'),
    "shared": re.compile(r'new Set\(\["Raspberry Pi 5 \(4GB\)"'),
    "diagrams": re.compile(r'=\[\{id:"bare_bones",label:"'),
    "models-copy": re.compile(r'children:"parametric OpenSCAD source[^"]*"'),
}
_OLD_BROWSE = 'href:"https://github.com/59psi/SporePrint/tree/main/hardware/3d"'
_NEW_BROWSE = f'href:{json.dumps(MODELS_REPO_URL)}'


def _js(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _component(c) -> dict:
    price = c.price_approx
    notes = c.notes
    if c.pack_price:
        # The dashboard totals price x quantity; show the effective unit price
        # so its sum matches the BOM's one-pack line cost.
        unit = usd(c.pack_price) / max(c.quantity, 1)
        price = f"${unit:.2f}"
        if c.pack_price not in notes:
            notes = f"Sold as a pack ({c.pack_price} covers all {c.quantity}). {notes}".strip()
    return {
        "name": c.name,
        "role": c.role,
        "quantity": c.quantity,
        "priceApprox": price,
        "url": c.url,
        "category": c.category,
        "notes": notes,
    }


def _tiers() -> list[dict]:
    return [
        {
            "id": t.id,
            "name": t.name,
            "tagline": t.tagline,
            "estimatedCost": t.estimated_cost,
            "componentCount": sum(c.quantity for c in t.components),
            "bestFor": t.best_for,
            "speciesSupport": t.species_support,
            "whatYouGet": t.what_you_get,
            "capabilityGroups": [g.model_dump() for g in t.capability_groups],
            "limitations": t.limitations,
            "components": [_component(c) for c in t.components],
            "wiring": [
                {"fromDevice": w.from_device, "fromPin": w.from_pin,
                 "toDevice": w.to_device, "toPin": w.to_pin, "note": w.note}
                for w in t.wiring
            ],
            "firmwareTargets": t.firmware_targets,
            "setupSteps": t.setup_steps,
        }
        for t in TIERS
    ]


def _models() -> list[dict]:
    out = []
    for m in _list_models():
        desc = m["title"] + (f" — {m['description']}" if m["description"] else "")
        out.append({"filename": m["filename"], "description": desc, "url": m["url"],
                    "sizeKb": round(m["size_bytes"] / 1024, 1)})
    return out


def _shared() -> list[str]:
    names: list[str] = []
    for t in TIERS:
        for c in t.components:
            if c.shared and c.name not in names:
                names.append(c.name)
    return names


def _diagrams() -> list[dict]:
    out = []
    for t in TIERS:
        prefix = _DIAGRAM_PREFIX[t.id]
        matches = sorted(DOCS.glob(f"{prefix}*.svg"))
        if len(matches) != 1:
            raise SystemExit(f"expected one docs/{prefix}*.svg, found {[p.name for p in matches]}")
        out.append({"id": t.id, "label": matches[0].stem.removeprefix(prefix),
                    "href": f"/api/builder/diagrams/{matches[0].name}"})
    return out


def _models_copy() -> str:
    # JSX children: text + a link to the one-click bundle.
    return (
        '["parametric OpenSCAD source · each .scad is self-contained (shared '
        'heat-set-insert helpers inlined) · render to STL in OpenSCAD · ",'
        'i.jsx("a",{href:"/api/builder/models-bundle.zip",className:"underline",'
        'children:"download all (.zip)"},"models-bundle")]'
    )


def _matching_bracket(src: str, start: int) -> int:
    """Index just past the bracket that closes src[start] ('[' or '(')."""
    pairs = {"[": "]", "(": ")", "{": "}"}
    stack = []
    i = start
    while i < len(src):
        ch = src[i]
        if ch in "\"'`":
            q = ch
            i += 1
            while src[i] != q:
                i += 2 if src[i] == "\\" else 1
        elif ch in pairs:
            stack.append(pairs[ch])
        elif ch in ")]}":
            if not stack or stack.pop() != ch:
                raise ValueError(f"unbalanced bracket at {i}")
            if not stack:
                return i + 1
        i += 1
    raise ValueError("unterminated block")


def _replace_block(js: str, name: str, payload: str) -> str:
    open_m, close_m = f"/*sp-sync:{name}*/", f"/*/sp-sync:{name}*/"
    wrapped = f"{open_m}{payload}{close_m}"
    if js.count(open_m) == 1:
        a = js.index(open_m)
        b = js.index(close_m, a) + len(close_m)
        return js[:a] + wrapped + js[b:]
    hits = list(_FIRST_RUN[name].finditer(js))
    if len(hits) != 1:
        raise SystemExit(f"sync: could not locate the '{name}' block exactly once ({len(hits)} hits)")
    m = hits[0]
    if name == "models-copy":
        a = m.start() + len("children:")
        return js[:a] + wrapped + js[m.end():]
    a = js.index("[", m.start())
    b = _matching_bracket(js, a)
    return js[:a] + wrapped + js[b:]


def render(js: str) -> str:
    js = _replace_block(js, "tiers", _js(_tiers()))
    js = _replace_block(js, "models", _js(_models()))
    js = _replace_block(js, "shared", _js(_shared()))
    js = _replace_block(js, "diagrams", _js(_diagrams()))
    js = _replace_block(js, "models-copy", _models_copy())
    if _OLD_BROWSE in js:
        js = js.replace(_OLD_BROWSE, _NEW_BROWSE)
    return js


def _bundle() -> tuple[Path, str]:
    html = (DIST / "index.html").read_text()
    m = _BUNDLE_REF.search(html)
    if not m:
        raise SystemExit("ui/dist/index.html references no /assets/index-*.js bundle")
    return DIST / "assets" / f"{m.group(1)}.js", html


def check() -> list[str]:
    """Names of the blocks that are out of date ([] = in sync)."""
    path, _ = _bundle()
    js = path.read_text()
    stale = []
    for name, payload in (("tiers", _js(_tiers())), ("models", _js(_models())),
                          ("shared", _js(_shared())), ("diagrams", _js(_diagrams())),
                          ("models-copy", _models_copy())):
        if f"/*sp-sync:{name}*/{payload}/*/sp-sync:{name}*/" not in js:
            stale.append(name)
    if _OLD_BROWSE in js or _NEW_BROWSE not in js:
        stale.append("browse-link")
    return stale


def write() -> str:
    path, html = _bundle()
    old_stem = path.stem
    js = render(path.read_text())
    if js == path.read_text():
        return f"{path.name} already in sync"
    new_stem = "index-" + hashlib.sha256(js.encode()).hexdigest()[:8]
    js = js.replace(f"//# sourceMappingURL={old_stem}.js.map", f"//# sourceMappingURL={new_stem}.js.map")
    (path.parent / f"{new_stem}.js").write_text(js)
    old_map = path.parent / f"{old_stem}.js.map"
    if old_map.exists():
        old_map.rename(path.parent / f"{new_stem}.js.map")
    path.unlink()
    (DIST / "index.html").write_text(html.replace(f"/assets/{old_stem}.js", f"/assets/{new_stem}.js"))
    return f"{old_stem}.js -> {new_stem}.js"


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        stale = check()
        if stale:
            print("ui/dist Builder data is stale: " + ", ".join(stale)
                  + "\nRun: cd server && uv run python ../scripts/sync_ui_builder_data.py")
            sys.exit(1)
        print("ui/dist Builder data is in sync")
    else:
        print(write())
