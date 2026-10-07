#!/usr/bin/env python3
"""Regenerate the per-tier wiring diagrams in docs/ from these generators.

    python3 scripts/wiring_svg/build.py            # rewrite docs/wiring-tier*.svg
    python3 scripts/wiring_svg/build.py --check    # exit 1 if docs/ differs

The three tier SVGs are GENERATED — edit gen_t1/2/3.py (layout), parts.py
(reusable boards, connectors, legends) or svglib.py (primitives), then
rebuild. Hand edits to the SVGs are lost on the next build, and
server/tests/test_wiring_svgs_generated.py fails when docs/ and the
generators disagree. Labels must match the BOM (server/app/builder/
hardware_guides.py) — server/tests/test_docs_consistency.py checks the
fuse ratings, wire gauges, WAGO parts and common-ground callouts.

docs/wiring-overall-system.svg and docs/architecture-overview.svg are
hand-maintained.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent.parent / "docs"
TARGETS = {
    "gen_t1.py": "wiring-tier1-bare-bones.svg",
    "gen_t2.py": "wiring-tier2-recommended.svg",
    "gen_t3.py": "wiring-tier3-all-the-things.svg",
}


def render(out_dir: Path) -> dict[str, Path]:
    """Run every generator into out_dir; returns {docs filename: rendered path}."""
    rendered = {}
    for script, name in TARGETS.items():
        out = out_dir / name
        subprocess.run([sys.executable, str(HERE / script), str(out)], cwd=HERE,
                       check=True, stdout=subprocess.DEVNULL)
        rendered[name] = out
    return rendered


def stale() -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        return [name for name, path in render(Path(tmp)).items()
                if path.read_bytes() != (DOCS / name).read_bytes()]


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        diff = stale()
        if diff:
            print("docs SVGs differ from their generators: " + ", ".join(diff))
            sys.exit(1)
        print("docs wiring SVGs match their generators")
    else:
        for name in render(DOCS):
            print("wrote docs/" + name)
