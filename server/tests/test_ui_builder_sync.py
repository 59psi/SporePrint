"""The compiled Pi dashboard (ui/dist) must read the Builder data live from
this server, and its built-in fallback must match what this server serves.

The dashboard source is in the private monorepo. Its Builder page fetches
/api/builder/tiers (+ /tiers/{id}), /models, /diagrams and /firmware, and
falls back per resource to a copy generated from this repo at build time
(design/src/data/builder.generated.ts, by the private repo's
scripts/port_builder.py). scripts/sync_ui_builder_data.py reads that copy out
of the minified bundle. These tests fail when:

  - the bundle regresses to the stale static Builder (no live requests, the
    404 GitHub paths hardware/3d or hardware/wiring, the false "slicer-ready
    STL exports" claim), or calls a Builder route this server does not serve;
  - the fallback's tiers differ from hardware_guides.py, or its models,
    diagrams or firmware envs differ from what this server lists — i.e. a BOM,
    model header, diagram or platformio.ini change that the dashboard does
    not carry. Fix: rebuild ui/dist in the private repo, or run
    `cd server && uv run python ../scripts/sync_ui_builder_data.py` to
    refresh just the fallback data.
"""
import importlib.util
import re
import shutil
from pathlib import Path

import pytest

from app.builder.hardware_guides import TIERS
from app.main import app as server_app

REPO = Path(__file__).resolve().parents[2]
DIST = REPO / "ui" / "dist"
FIX = "Run: cd server && uv run python ../scripts/sync_ui_builder_data.py (or rebuild ui/dist)"


def _load_sync():
    spec = importlib.util.spec_from_file_location(
        "sync_ui_builder_data", REPO / "scripts" / "sync_ui_builder_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def sync():
    return _load_sync()


@pytest.fixture(scope="module")
def bundle_js(sync):
    return sync.bundle_path().read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def fallback(sync, bundle_js):
    try:
        return sync.read_fallback(bundle_js)
    except LookupError as exc:
        pytest.fail(f"ui/dist carries no readable built-in Builder data ({exc}); "
                    "rebuild ui/dist from the private repo")


def _first_difference(have: list, want: list, key: str) -> str:
    if len(have) != len(want):
        return f"{len(have)} entries in the bundle, {len(want)} on the server"
    for a, b in zip(have, want):
        if a != b:
            fields = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
            return f"{a.get(key, b.get(key))!r} differs in {fields}"
    return "no difference"


# ── the bundle is the live-data dashboard ─────────────────────────────


def test_bundle_reads_the_builder_api_live(sync, bundle_js):
    problems = sync.structural_problems(bundle_js)
    assert not problems, "ui/dist is not the live-data Builder:\n" + "\n".join(problems)


def test_bundle_only_calls_builder_routes_this_server_serves(sync, bundle_js):
    served = set(server_app.openapi()["paths"])
    called = set(sync.LIVE_ENDPOINTS) | {
        "/api/builder/tiers/{tier_id}",
        "/api/builder/models/{filename}",
        "/api/builder/models-bundle.zip",
        "/api/builder/diagrams/{filename}",
        "/api/builder/firmware/bundle/{node}",
    }
    assert called <= served, sorted(called - served)
    # Every literal /api/builder/<x> the bundle names maps to one of them.
    for literal in set(re.findall(r"/api/builder/[A-Za-z0-9_./-]+", bundle_js)):
        first = literal.removeprefix("/api/builder/").split("/")[0]
        assert any(p.startswith(f"/api/builder/{first}") for p in served), literal


def test_dist_ships_only_referenced_assets():
    # nginx serves ui/dist as-is (ui/Dockerfile): index.html + hashed assets/.
    html = (DIST / "index.html").read_text(encoding="utf-8")
    referenced = set(re.findall(r'/assets/([^"\']+)', html))
    assert referenced, "index.html references no assets"
    for name in referenced:
        assert (DIST / "assets" / name).is_file(), f"index.html references missing {name}"
    texts = html + "".join((DIST / "assets" / n).read_text(encoding="utf-8")
                           for n in referenced if n.endswith((".js", ".css")))
    for f in (DIST / "assets").iterdir():
        if f.name in referenced:
            continue
        is_map = f.suffix == ".map" and f.name.removesuffix(".map") in referenced
        assert is_map or f.name in texts, f"stale asset left in ui/dist: {f.name}"


# ── the built-in fallback matches this server ─────────────────────────


def test_fallback_tiers_match_hardware_guides(sync, fallback):
    want = sync.expected_tiers()
    assert fallback["tiers"] == want, (
        "ui/dist's built-in BOM is stale: "
        + _first_difference(fallback["tiers"], want, "id") + ". " + FIX)


def test_fallback_models_and_diagrams_match_the_server(sync, fallback):
    for name, want, key in (("models", sync.expected_models(), "filename"),
                            ("diagrams", sync.expected_diagrams(), "filename")):
        have, want = sync._without_size(fallback[name]), sync._without_size(want)
        assert have == want, f"ui/dist's built-in {name} are stale: " \
            + _first_difference(have, want, key) + ". " + FIX


def test_fallback_firmware_envs_match_platformio(sync, fallback):
    # The /api/builder/firmware listing carries no envs, so the page always
    # uses these to decide which images a tier needs.
    assert fallback["firmware"] == sync.expected_firmware_envs(), FIX
    every_env = {e for envs in fallback["firmware"].values() for e in envs}
    for tier in TIERS:
        assert set(tier.firmware_targets) <= every_env, tier.id


def test_fallback_links_resolve(fallback):
    models = fallback["models"]
    assert {m["filename"] for m in models} == {p.name for p in (REPO / "models").glob("*.scad")}
    for m in models:
        # The Pi's self-contained download (lib/ inlined); a raw GitHub .scad
        # does not render on its own.
        assert m["url"] == f"/api/builder/models/{m['filename']}", m
        assert m["sourceUrl"] == f"https://github.com/59psi/SporePrint/blob/main/models/{m['filename']}", m
        assert "stlUrl" not in m, m
    assert [d["tierId"] for d in fallback["diagrams"]] == [t.id for t in TIERS]
    for d in fallback["diagrams"]:
        assert (REPO / "docs" / d["filename"]).is_file(), d
        assert d["url"] == f"/api/builder/diagrams/{d['filename']}", d
        assert d["sourceUrl"] == f"https://github.com/59psi/SporePrint/blob/main/docs/{d['filename']}", d


def test_fallback_totals_match_the_bom(fallback):
    # The page prices a line as packPrice once (one pack covers the quantity),
    # otherwise priceApprox x quantity; for one chamber that is parts_cost().
    def usd(s):
        return float(s.lstrip("$").replace(",", ""))

    for tier, ui in zip(TIERS, fallback["tiers"], strict=True):
        total = sum(usd(c["packPrice"]) if c.get("packPrice") else usd(c["priceApprox"]) * c["quantity"]
                    for c in ui["components"])
        assert total == pytest.approx(tier.parts_cost(), abs=0.005), tier.id
        shared = sum(1 for c in ui["components"] if c["shared"])
        assert shared == sum(1 for c in tier.components if c.shared), tier.id


def _ui_component(c: dict) -> dict:
    # pi-ui src/lib/builder-data.ts mapComponent().
    out = {k: c[k] for k in ("name", "role", "quantity", "url", "category")}
    out.update(priceApprox=c["price_approx"], notes=c.get("notes") or "")
    if c.get("pack_price"):
        out["packPrice"] = c["pack_price"]
    if isinstance(c.get("shared"), bool):
        out["shared"] = c["shared"]
    return out


def test_fallback_equals_the_live_api(client, fallback, sync, bundle_js):
    """What the page shows offline is what it shows live (pi-ui's mappers)."""
    summary = client.get("/api/builder/tiers").json()
    live_tiers = []
    for s in summary:
        t = client.get(f"/api/builder/tiers/{s['id']}").json()
        components = [_ui_component(c) for c in t["components"]]
        live_tiers.append({
            "id": t["id"], "name": t["name"], "tagline": t["tagline"],
            "estimatedCost": t["estimated_cost"],
            "componentCount": sum(c["quantity"] for c in components),
            "bestFor": t["best_for"], "speciesSupport": t["species_support"],
            "whatYouGet": t["what_you_get"],
            "capabilityGroups": [{"title": g["title"], "items": g["items"]} for g in t["capability_groups"]],
            "limitations": t["limitations"],
            "components": components,
            "wiring": [{"fromDevice": w["from_device"], "fromPin": w["from_pin"], "toDevice": w["to_device"],
                        "toPin": w["to_pin"], "note": w.get("note") or ""} for w in t["wiring"]],
            "wiringDiagram": t["wiring_diagram"],
            "firmwareTargets": t["firmware_targets"],
            "setupSteps": t["setup_steps"],
        })
        assert s["component_count"] == live_tiers[-1]["componentCount"], s["id"]
    assert live_tiers == fallback["tiers"], _first_difference(fallback["tiers"], live_tiers, "id")

    live_models = [{"filename": m["filename"], "title": m["title"], "description": m["description"],
                    "url": m["url"], "sourceUrl": m["source_url"]}
                   for m in client.get("/api/builder/models").json()]
    assert live_models == sync._without_size(fallback["models"])

    listed = {d["filename"]: d["url"] for d in client.get("/api/builder/diagrams").json()}
    for d in fallback["diagrams"]:
        assert listed.get(d["filename"]) == d["url"], d

    groups = {g["path"]: g for g in client.get("/api/builder/firmware").json()}
    for path in fallback["firmware"]:
        image = path.removeprefix("src/")
        assert groups[path].get("bundle_url") == f"/api/builder/firmware/bundle/{image}", path
        assert f'"/api/builder/firmware/bundle/{image}"' in bundle_js, path


# ── the checker itself catches regressions ────────────────────────────


def _mutate_block(sync, js: str, name: str, pattern: str, repl: str) -> str:
    start, end, _ = sync._locate(js, name)
    block, n = re.subn(pattern, repl, js[start:end], count=1)
    assert n == 1, (name, pattern)
    return js[:start] + block + js[end:]


@pytest.mark.parametrize("mutation, problem", [
    (lambda js: js.replace('"/api/builder/tiers"', '"/api/builder/tierz"'), "/api/builder/tiers"),
    (lambda js: js.replace("/api/builder/tiers/${", "/api/builder/tierz/${"), "/api/builder/tiers/{id}"),
    (lambda js: js.replace('"/api/builder/models"', '"/static/models"'), "/api/builder/models"),
    (lambda js: js.replace('"/api/builder/diagrams"', '"/static/diagrams"'), "/api/builder/diagrams"),
    (lambda js: js + ';x="https://github.com/59psi/SporePrint/tree/main/hardware/3d"', "hardware/3d"),
    (lambda js: js + ';x="https://github.com/59psi/SporePrint/blob/main/hardware/wiring/t1.svg"',
     "hardware/wiring"),
    (lambda js: js + ';x="parametric OpenSCAD source · slicer-ready STL exports"', "slicer-ready"),
])
def test_checker_flags_a_stale_static_bundle(sync, bundle_js, mutation, problem):
    mutated = mutation(bundle_js)
    assert mutated != bundle_js
    problems = sync.structural_problems(mutated)
    assert any(problem in p or problem.lower() in p.lower() for p in problems), problems


@pytest.mark.parametrize("block, pattern, repl", [
    ("tiers", r'("?priceApprox"?:\s*")\$', r"\1$1"),
    ("tiers", r'("?shared"?:\s*)(!0|true)', r"\1!1"),
    ("models", r'("?title"?:\s*")', r"\1Old "),
    ("diagrams", r'("?filename"?:\s*"wiring-tier1-)', r"\1old-"),
    ("firmware:src/node", r',\s*"node_esp32s3_n32r16v"', ""),
])
def test_checker_flags_stale_fallback_data(sync, bundle_js, block, pattern, repl):
    mutated = _mutate_block(sync, bundle_js, block, pattern, repl)
    assert sync.structural_problems(mutated) == []
    assert block in sync.stale_blocks(mutated)


def test_size_labels_alone_are_not_stale(sync, bundle_js):
    mutated = _mutate_block(sync, bundle_js, "models", r'("?sizeKb"?:\s*)[\d.]+', r"\g<1>999.9")
    assert sync.stale_blocks(mutated) == []


@pytest.fixture()
def dist_copy(sync, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    shutil.copytree(DIST, dist)
    monkeypatch.setattr(sync, "DIST", dist)
    return dist


def test_refresh_rewrites_stale_data_and_renames_the_bundle(sync, bundle_js, dist_copy):
    old = sync.bundle_path()
    stale_js = _mutate_block(sync, bundle_js, "tiers", r'("?priceApprox"?:\s*")\$', r"\1$1")
    stale_js = _mutate_block(sync, stale_js, "firmware:src/cam", r'"cam"', '"cam_old"')
    old.write_text(stale_js, encoding="utf-8")
    assert sorted(sync.check()[1]) == ["firmware:src/cam", "tiers"]

    assert "refreshed" in sync.write()

    new = sync.bundle_path()
    assert new != old and not old.exists()
    assert sync.check() == ([], [])
    assert (dist_copy / "assets" / f"{new.name}.map").is_file()
    assert not (dist_copy / "assets" / f"{old.name}.map").exists()
    assert new.read_text(encoding="utf-8").rstrip().endswith(f"//# sourceMappingURL={new.name}.map")
    assert sync.read_fallback(new.read_text(encoding="utf-8"))["tiers"] == sync.expected_tiers()
    assert "already matches" in sync.write()


def test_refresh_refuses_a_structurally_stale_bundle(sync, bundle_js, dist_copy):
    path = sync.bundle_path()
    path.write_text(bundle_js.replace('"/api/builder/tiers"', '"/api/builder/tierz"'), encoding="utf-8")
    with pytest.raises(SystemExit, match="Rebuild it in the private monorepo"):
        sync.write()
    assert path.exists()


def test_js_literal_reader_handles_esbuild_output(sync):
    src = (r"""x=[{a:!0,b:!1,"c-d":.5,e:'it\'s',f:`x\`y`,g:void 0,h:null,i:"é\x41\u{1F344}","""
           r"""j:-2,k:1e3,l:[],m:{},n:"🍄",o:"a\nb"},]""")
    start = src.index("[")
    value, end = sync.parse_js_literal(src, start)
    assert end == len(src)
    assert value == [{"a": True, "b": False, "c-d": 0.5, "e": "it's", "f": "x`y", "g": None, "h": None,
                      "i": "éA\U0001F344", "j": -2, "k": 1000.0, "l": [], "m": {},
                      "n": "\U0001F344", "o": "a\nb"}]
    for bad in ("[{...a}]", "[foo]", "[`${x}`]", '["open'):
        with pytest.raises(sync.JsLiteralError):
            sync.parse_js_literal(bad, 0)
