"""GitHub Actions workflows (.github/workflows) — supply-chain guards for every
workflow: no checkout persists the token where PlatformIO / library build
scripts could read it, third-party actions are pinned to immutable commit
SHAs, and PlatformIO is installed at an exact version. The release
workflow's own properties (which tag it builds, which job holds a write
token or the signing key) are pinned in test_firmware_release_workflow.py.
"""

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
ALL_WORKFLOWS = sorted(WORKFLOWS.glob("*.yml"))


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _steps(wf: dict):
    for job_name, job in wf["jobs"].items():
        for step in job.get("steps", []):
            yield job_name, step


@pytest.mark.parametrize("path", ALL_WORKFLOWS, ids=lambda p: p.name)
def test_actions_are_pinned_to_commit_shas(path):
    for job, step in _steps(_load(path)):
        uses = step.get("uses")
        if uses and not uses.startswith("./"):
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", uses), f"{job}: {uses}"


@pytest.mark.parametrize("path", ALL_WORKFLOWS, ids=lambda p: p.name)
def test_checkouts_do_not_persist_the_token(path):
    for job, step in _steps(_load(path)):
        if str(step.get("uses", "")).startswith("actions/checkout@"):
            assert step.get("with", {}).get("persist-credentials") is False, job


@pytest.mark.parametrize("path", ALL_WORKFLOWS, ids=lambda p: p.name)
def test_platformio_is_version_pinned(path):
    for job, step in _steps(_load(path)):
        for m in re.finditer(r"pip install ([^\n]*)", step.get("run", "")):
            for pkg in m.group(1).split():
                if pkg.startswith("platformio"):
                    assert re.fullmatch(r"platformio==\d+\.\d+\.\d+", pkg), f"{job}: {pkg}"
