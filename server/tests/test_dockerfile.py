"""server/Dockerfile — the image must ship what the test suite ran against.

A `pip install .` from pyproject ranges re-resolved dependencies on every
build, so the Pi could run starlette/fastapi/cryptography versions the suite
never saw. The image now installs uv.lock's pins, hash-checked.
"""

import json
import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def _instructions() -> list[tuple[str, str]]:
    text = re.sub(r"\\\n", " ", DOCKERFILE.read_text())  # join continuations
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        op, _, rest = line.partition(" ")
        out.append((op.upper(), rest.strip()))
    return out


def test_base_image_pinned_by_patch_tag_and_digest():
    base = next(rest for op, rest in _instructions() if op == "FROM")
    assert re.fullmatch(r"python:3\.12\.\d+-slim@sha256:[0-9a-f]{64}", base), base


def test_dependencies_install_from_the_lockfile():
    ins = _instructions()
    copies = [rest for op, rest in ins if op == "COPY"]
    assert any("uv.lock" in c.split() for c in copies), "uv.lock never copied into the image"
    runs = " ".join(rest for op, rest in ins if op == "RUN")
    assert re.search(r"\buv==\d+\.\d+\.\d+\b", runs), "uv must be version-pinned"
    assert re.search(r"uv export\b[^&]*--locked", runs)  # stale lock fails the build
    assert "--no-emit-project" in runs
    assert "--require-hashes" in runs
    # No resolver run over pyproject ranges.
    assert not re.search(r"pip install[^&]*\s\.(\s|$)", runs), "pip install . re-resolves ranges"


def test_uvicorn_trusts_forwarded_headers_only_from_the_compose_network():
    ins = _instructions()
    env = " ".join(rest for op, rest in ins if op == "ENV")
    m = re.search(r"FORWARDED_ALLOW_IPS=(\S+)", env)
    assert m and m.group(1) not in ("*", "0.0.0.0/0"), "never trust every source"
    cmd = json.loads(next(rest for op, rest in ins if op == "CMD"))
    assert cmd[:2] == ["uvicorn", "app.main:socket_app"]
    assert "--proxy-headers" in cmd


def test_image_carries_the_zone_files_tz_needs():
    """compose passes TZ (install.sh writes the host's zone) so automation
    schedules run on the operator's clock. glibc resolves TZ through
    /usr/share/zoneinfo and silently falls back to UTC when the zone file is
    missing. The pinned Debian base ships tzdata today; the build must keep
    it that way if a future base drops it."""
    runs = " ".join(rest for op, rest in _instructions() if op == "RUN")
    assert "/usr/share/zoneinfo/" in runs, "no zoneinfo check in the image build"
    assert re.search(r"apt-get install\b[^;&|]*\btzdata\b", runs), "no tzdata fallback install"
