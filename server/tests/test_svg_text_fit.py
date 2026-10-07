"""Every label in the docs/ diagrams must fit inside its box.

The Builder's Wiring tab shows these SVGs; a label that pokes out of its
panel or sits on top of another reads as a broken diagram. The check renders
each SVG in headless Chrome (scripts/wiring_svg/fit_check.py) and is skipped
where no Chrome / Chromium is installed.
"""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SVGS = sorted((REPO / "docs").glob("*.svg"))


def _fit_check():
    spec = importlib.util.spec_from_file_location(
        "wiring_svg_fit_check", REPO / "scripts" / "wiring_svg" / "fit_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_FIT = _fit_check()
_CHROME = _FIT.find_chrome()


@pytest.mark.skipif(_CHROME is None, reason="no Chrome / Chromium to render the SVGs")
@pytest.mark.parametrize("svg", SVGS, ids=[p.name for p in SVGS])
def test_every_label_fits_its_box(svg):
    result = _FIT.check(svg, _CHROME)
    assert result["texts"] > 0, f"{svg.name}: no text measured"
    assert result["overflow"] == [], f"{svg.name}: labels outside their box: {result['overflow']}"
    assert result["overlaps"] == [], f"{svg.name}: overlapping labels: {result['overlaps']}"
