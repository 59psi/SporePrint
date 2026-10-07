"""Public material says nothing about the private cloud's internals.

This repo is public. Its docs, changelogs, scripts and tests may say that a
private cloud exists and what the Pi exchanges with it, but not the private
repository's name, its pull-request numbers, or the cloud's own incidents
and internal fixes: a lockstep release with no Pi-side change says only
that. The source-map note in the 5.1.0 entry also stays a bare statement of
what ships.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()

# Built by concatenation so this file does not match itself.
_PRIVATE_REPO = re.compile("sporeprint" + r"-cloud\b", re.IGNORECASE)
_PRIVATE_PR = re.compile(r"\bcloud#\d+|\bsporeprint" + r"-cloud\s*(?:PR\s*)?#\d+", re.IGNORECASE)
_CLOUD_CHANGELOG = re.compile(
    r"cloud repo's CHANGELOG|cloud CHANGELOG|parent repo's `CHANGELOG\.md`", re.IGNORECASE
)
# Cloud-side incidents and internal fixes that lockstep entries once listed.
_CLOUD_INTERNALS = (
    "healthcheck on the v4.0.1 deploy",
    "KVCache",
    "SSRF guard on `/devices/pair`",
    "price-ID build-arg",
    "AI quota race lock",
    "development fixtures and comments included",
)

_TEXT_SUFFIXES = {".md", ".py", ".txt", ".yml", ".yaml", ".toml", ".ini", ".sh", ".json", ".cfg", ".svg", ".h", ".cpp"}


def _public_files() -> list[Path]:
    """Every tracked or untracked (not ignored) text file, minus the compiled
    dashboard and lockfiles."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        out = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file()]
    files = []
    for rel in out:
        p = ROOT / rel
        if rel.startswith(("ui/dist/", ".claude/")) or p.name in {"uv.lock", "CLAUDE.md"}:
            continue
        if p.suffix in _TEXT_SUFFIXES and p.is_file() and p.resolve() != SELF:
            files.append(p)
    return files


def test_public_files_never_name_the_private_repo_or_its_prs():
    hits = {}
    for p in _public_files():
        text = p.read_text(encoding="utf-8", errors="ignore")
        found = [m.group(0) for rx in (_PRIVATE_REPO, _PRIVATE_PR) for m in rx.finditer(text)]
        if found:
            hits[str(p.relative_to(ROOT))] = sorted(set(found))
    assert not hits, f"public files name the private repo or its PRs: {hits}"


def test_changelog_keeps_cloud_internals_out():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert not _CLOUD_CHANGELOG.findall(text), "point at no cloud changelog: say 'Lockstep version bump'"
    leaked = [phrase for phrase in _CLOUD_INTERNALS if phrase in text]
    assert not leaked, f"CHANGELOG describes cloud-side internals: {leaked}"


def test_the_matchers_match():
    assert _PRIVATE_PR.search("see cloud#9999")
    assert _PRIVATE_REPO.search("SporePrint" + "-Cloud")
    assert not _PRIVATE_REPO.search("sporeprint cloud connector")
    assert _CLOUD_CHANGELOG.search("see the cloud CHANGELOG for v3.4.1")
