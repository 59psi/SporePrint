"""GitHub Actions workflows (.github/workflows) — release supply-chain guards.

The release workflow builds and publishes the firmware growers flash, so:
  * a workflow_dispatch release must build the requested tag, not main;
  * only the job that publishes may hold a write token, and no checkout may
    persist it where PlatformIO / library build scripts could read it;
  * third-party actions are pinned to immutable commit SHAs.
"""

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
RELEASE = WORKFLOWS / "firmware-release.yml"
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


def test_release_write_token_is_scoped_to_the_release_job():
    wf = _load(RELEASE)
    assert wf["permissions"] == {"contents": "read"}
    for name, job in wf["jobs"].items():
        perms = job.get("permissions", {})
        if name == "release":
            assert perms.get("contents") == "write"
        else:
            assert perms.get("contents") != "write", name


def test_dispatch_release_builds_the_requested_tag():
    # The release-key job resolves the tag (dispatch input, else the pushed
    # tag) and checks it; the build checks out exactly that tag.
    wf = _load(RELEASE)
    checkouts = [s for _, s in _steps({"jobs": {"build": wf["jobs"]["build"]}})
                 if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert checkouts, "build job must check out the source"
    ref = checkouts[0].get("with", {}).get("ref", "")
    assert ref == "refs/tags/${{ needs.release-key.outputs.tag }}", ref
    meta = next(s for s in wf["jobs"]["release-key"]["steps"] if s.get("id") == "meta")
    assert meta["env"]["INPUT_TAG"] == "${{ inputs.tag }}"
    assert meta["env"]["REF_NAME"] == "${{ github.ref_name }}"
