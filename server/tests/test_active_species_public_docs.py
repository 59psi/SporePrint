"""Public docs never name an active-category species, and say what that
category is for wherever they describe it.

The active profiles ship in the code (`server/app/species/profiles.py`), and
the dashboard shows them with an education-and-research notice. The public
material around the code (README, docs/, changelogs) stays generic: it gives
the category and its count, never a species, strain, genus or compound name.
The names checked here come from the profiles themselves, so a new active
profile is covered the day it is added.
"""

import re
import subprocess
from pathlib import Path

from app.species.profiles import BUILTIN_PROFILES

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
SPECIES_REF = ROOT / "docs" / "species-reference.md"
FEATURE_STATUS = ROOT / "docs" / "feature-status.md"

# The dashboard's notice, word for word, so the README and the product say
# the same thing.
NOTICE = (
    "For education and research purposes only. Some species may be controlled where you live; "
    "you are responsible for following local law."
)

# Compound and slang names that would name the category without naming a profile.
_GENERIC = ("psilocybin", "psilocin", "magic mushroom")


def _active_terms() -> set[str]:
    terms: set[str] = set(_GENERIC)
    for p in BUILTIN_PROFILES:
        if p.category != "active":
            continue
        for name in (p.common_name, p.scientific_name, p.strain or ""):
            # "A / B (C)" names three things.
            terms.update(part.strip() for part in re.split(r"[/()]", name))
        terms.update(p.scientific_name.split())  # genus and epithet alone
    return {t for t in terms if len(t) > 3}


def _names_in(text: str, terms: set[str]) -> list[str]:
    return sorted(
        t for t in terms if re.search(rf"(?<![A-Za-z]){re.escape(t)}(?![A-Za-z])", text, re.IGNORECASE)
    )


def _public_docs() -> list[Path]:
    """Every tracked Markdown file, plus everything under docs/. CLAUDE.md is
    the operator's git-ignored spec and may name them."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "*.md", "docs"], cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.split()
        paths = [ROOT / p for p in out]
    except (OSError, subprocess.CalledProcessError):
        paths = [*ROOT.glob("*.md"), *(ROOT / "docs").rglob("*")]
    return sorted(
        p for p in set(paths)
        if p.is_file() and p.name != "CLAUDE.md" and p.suffix in {".md", ".svg", ".json", ".txt"}
    )


def test_the_names_come_from_the_active_profiles():
    active = [p for p in BUILTIN_PROFILES if p.category == "active"]
    assert active, "no active profiles: drop this test or the category"
    terms = _active_terms()
    for p in active:
        assert p.scientific_name in terms and p.scientific_name.split()[0] in terms
    # Word-bounded and case-blind: a term inside a longer word is not a hit.
    assert _names_in("THE TERM.", {"term"}) == ["term"]
    assert _names_in("terminal", {"term"}) == []


def test_no_public_doc_names_an_active_species():
    terms = _active_terms()
    docs = _public_docs()
    assert README in docs and SPECIES_REF in docs
    hits = {
        str(p.relative_to(ROOT)): found
        for p in docs
        if (found := _names_in(p.read_text(encoding="utf-8", errors="ignore"), terms))
    }
    assert not hits, f"public docs name active species (say 'active' and the count instead): {hits}"


def test_readme_species_section_carries_the_notice():
    text = README.read_text(encoding="utf-8")
    start = re.search(r"^## Species Library$", text, re.MULTILINE)
    assert start, "README has no '## Species Library' section"
    section = text[start.end():]
    section = section[: section.index("\n---")]
    flat = re.sub(r"\s+", " ", section)
    assert re.search(r"\*\*Active\*\* \(\d+\) -- species that are controlled or restricted in many jurisdictions", flat)
    assert NOTICE in flat
    # the Terms §7 EDUCATIONAL_USE text, verbatim
    assert "not encouragement to cultivate, possess, or use any controlled organism" in flat


def test_reference_docs_say_education_and_research_only():
    for doc in (SPECIES_REF, FEATURE_STATUS):
        flat = re.sub(r"\s+", " ", doc.read_text(encoding="utf-8"))
        assert "for education and research purposes only" in flat, doc.name
        assert "you are responsible for following local law" in flat, doc.name


def test_dashboard_bundle_carries_the_notice_the_readme_promises():
    """README and CHANGELOG say the dashboard's species library and wizard
    show the notice; `ui/dist` is the dashboard nginx serves. This is a
    release gate: when it fails, rebuild the dashboard and sync `ui/dist`."""
    assets = ROOT / "ui" / "dist" / "assets"
    bundles = sorted(assets.glob("*.js"))
    assert bundles, "ui/dist/assets has no JavaScript bundle"
    assert any(NOTICE in b.read_text(encoding="utf-8", errors="ignore") for b in bundles), (
        "ui/dist predates the education-and-research notice: rebuild the dashboard and sync ui/dist"
    )
