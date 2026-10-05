"""The compiled Pi dashboard (ui/dist) must show the server's current Builder
data: BOM tiers, 3D models, shared-line set and wiring-diagram links.

The dashboard source is in the private monorepo and renders a static copy of
that data; scripts/sync_ui_builder_data.py writes the server's data into the
bundle. These tests fail when hardware_guides.py, a model header or a wiring
diagram changes without re-running the sync — the drift that left the
dashboard showing a pre-audit BOM and 404 links.
"""
import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DIST = REPO / "ui" / "dist"


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
def bundle_js():
    html = (DIST / "index.html").read_text()
    m = re.search(r"/assets/(index-[A-Za-z0-9_-]+)\.js", html)
    assert m, "ui/dist/index.html references no bundle"
    path = DIST / "assets" / f"{m.group(1)}.js"
    assert path.exists(), f"{path.name} referenced by index.html is missing"
    return path.read_text()


def test_ui_builder_data_is_in_sync(sync):
    stale = sync.check()
    assert not stale, (
        f"ui/dist Builder data is stale ({', '.join(stale)}). "
        "Run: cd server && uv run python ../scripts/sync_ui_builder_data.py"
    )


def test_bundle_has_no_dead_github_paths(bundle_js):
    # Neither path exists in the public repo; both were 404s in the dashboard.
    assert "SporePrint/tree/main/hardware/3d" not in bundle_js
    assert "SporePrint/blob/main/hardware/wiring" not in bundle_js
    assert "slicer-ready STL exports" not in bundle_js


def test_wiring_diagram_links_resolve_to_shipped_svgs(sync):
    for d in sync._diagrams():
        name = d["href"].rsplit("/", 1)[-1]
        assert (REPO / "docs" / name).is_file(), d


def test_model_downloads_use_the_self_contained_endpoint(sync):
    models = sync._models()
    assert {m["filename"] for m in models} == {p.name for p in (REPO / "models").glob("*.scad")}
    assert all(m["url"] == f"/api/builder/models/{m['filename']}" for m in models)


def test_dashboard_totals_match_the_bom(sync):
    # The dashboard sums priceApprox x quantity; pack lines carry an effective
    # unit price so that sum equals the BOM's line cost.
    from app.builder.hardware_guides import TIERS
    for tier, ui in zip(TIERS, sync._tiers()):
        ui_total = sum(float(c["priceApprox"].lstrip("$")) * c["quantity"] for c in ui["components"])
        assert ui_total == pytest.approx(tier.parts_cost(), abs=0.05 * len(ui["components"])), tier.id
