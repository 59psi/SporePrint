"""This repository is public: its code, tests and docs explain what the code
does and why in plain words. Labels from a private tracker or tool (an issue
id from another repo, a tool's name) mean nothing to a reader here, so none
may be used as the reason for a line.
"""

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Assembled from parts so this file never matches itself.
_PRIVATE_REFERENCE = re.compile("|".join((
    "arch" + "aeolog",                               # a private tool's name
    r"[Ss]enti" + r"nel [A-Z]?-?\d",                 # that tool's issue ids
    r"\b(?:srv|fw|deps|docs)-?[a-z-]*" + "#" + r"\d+",  # private tracker ids
    r"\(V\d+-\d+\)",                                 # private issue ids
    r"\bDe" + r"bt \d+\b",
    r"\banalysis/\d\d-",                             # a private repo's paths
)))

_SCANNED_SUFFIXES = {
    ".py", ".md", ".h", ".hpp", ".c", ".cpp", ".ini", ".csv", ".sh", ".yml",
    ".yaml", ".json", ".toml", ".conf", ".scad", ".txt", ".svg",
}
# Generated, vendored or third-party trees.
_SKIPPED_DIRS = {".git", ".venv", "node_modules", ".pio", "dist", "vendor",
                 "__pycache__", "data", ".pytest_cache", ".ruff_cache"}
_SKIPPED_FILES: set[Path] = set()


def _scanned_files():
    # Skipped trees are pruned before the walk enters them (server/.venv alone
    # holds tens of thousands of files).
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIPPED_DIRS]
        for name in filenames:
            path = Path(dirpath, name)
            rel = path.relative_to(ROOT)
            if (name not in _SKIPPED_DIRS and path.suffix in _SCANNED_SUFFIXES
                    and rel not in _SKIPPED_FILES and path.is_file()):
                yield rel


def test_no_private_tracker_or_tool_references():
    hits = []
    for rel in _scanned_files():
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if not _PRIVATE_REFERENCE.search(text):  # no pattern spans a line break
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if _PRIVATE_REFERENCE.search(line):
                hits.append(f"{rel}:{number}: {line.strip()[:120]}")
    assert hits == [], "explain the reason in plain words instead:\n" + "\n".join(hits)


def test_the_check_catches_each_kind_of_reference():
    for sample in (
        "the " + "arch" + "aeology's top item",
        "(sen" + "tinel S1)",
        "(fw-node" + "#11)",
        "srv-hw" + "#22 hardening",
        "docs" + "#28",
        "(V3" + "-2)",
        "v3.4.9 De" + "bt 5",
        "see `analysis/" + "02-security.md`",
    ):
        assert _PRIVATE_REFERENCE.search(sample), sample
    for fine in ("a senti" + "nel value", "firmware-security.md#secure-mqtt-tls",
                 "rule #4 of the list", "Debtor"):
        assert not _PRIVATE_REFERENCE.search(fine), fine
