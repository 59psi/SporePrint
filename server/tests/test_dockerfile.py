"""server/Dockerfile — the image must ship what the test suite ran against.

A `pip install .` from pyproject ranges re-resolved dependencies on every
build, so the Pi could run starlette/fastapi/cryptography versions the suite
never saw. The image now installs uv.lock's pins, hash-checked.
"""

import fnmatch
import ipaddress
import json
import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"
DOCKERIGNORE = Path(__file__).resolve().parents[1] / ".dockerignore"


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


def test_forwarded_headers_are_trusted_from_one_address_only():
    """A CIDR (the old 172.16.0.0/12) includes the bridge gateways, and
    docker-proxy relays IPv6/loopback clients of the published :8000 from a
    gateway — letting them forge X-Forwarded-For and pick their own Socket.IO
    rate-limit bucket. Only the ui container's fixed address is trusted."""
    env = " ".join(rest for op, rest in _instructions() if op == "ENV")
    value = re.search(r"FORWARDED_ALLOW_IPS=(\S+)", env).group(1)
    assert "," not in value and "/" not in value, value
    ipaddress.ip_address(value)


# ── build context: runtime data never enters an image layer ───────────────

def _dockerignore_patterns() -> list[str]:
    lines = DOCKERIGNORE.read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def _segments_match(pattern: list[str], path: list[str]) -> bool:
    """Docker/Go filepath.Match per segment; `**` spans any number of them."""
    if not pattern:
        return not path
    if pattern[0] == "**":
        return any(_segments_match(pattern[1:], path[i:]) for i in range(len(path) + 1))
    return bool(path) and fnmatch.fnmatchcase(path[0], pattern[0]) and \
        _segments_match(pattern[1:], path[1:])


def _excluded_from_context(path: str) -> bool:
    """Whether `docker build` leaves `path` (relative to server/) out of the
    context: the last matching pattern wins; a match on a parent directory
    excludes everything below it."""
    parts = path.split("/")
    excluded = False
    for raw in _dockerignore_patterns():
        negate = raw.startswith("!")
        pattern = [p for p in raw.lstrip("!").strip("/").split("/") if p not in ("", ".")]
        if any(_segments_match(pattern, parts[:n]) for n in range(1, len(parts) + 1)):
            excluded = not negate
    return excluded


def test_runtime_data_is_never_copied_into_the_image():
    """Run from server/ (setup.sh, README), the relative defaults put the
    SQLite DB, the Fernet integration key and cloud.env (the cloud device
    token, which is also the command-signing HMAC key) under server/data/.
    A later `docker compose up --build` must not bake them into a layer via
    `COPY . .`."""
    for path in ("data", "data/db/sporeprint.db", "data/db/sporeprint.db-wal",
                 "data/db/.integration-key", "data/db/cloud.env",
                 "data/vision/frame.jpg", ".env", ".env.local"):
        assert _excluded_from_context(path), f"{path} would be copied into the image"


def test_the_app_itself_still_reaches_the_image():
    for path in ("app/main.py", "app/host_allow.py", "app/integrations/_registry.py",
                 "pyproject.toml", "uv.lock"):
        assert not _excluded_from_context(path), f"{path} is excluded from the build context"


def test_image_carries_the_zone_files_tz_needs():
    """compose passes TZ (install.sh writes the host's zone) so automation
    schedules run on the operator's clock. glibc resolves TZ through
    /usr/share/zoneinfo and silently falls back to UTC when the zone file is
    missing. The pinned Debian base ships tzdata today; the build must keep
    it that way if a future base drops it."""
    runs = " ".join(rest for op, rest in _instructions() if op == "RUN")
    assert "/usr/share/zoneinfo/" in runs, "no zoneinfo check in the image build"
    assert re.search(r"apt-get install\b[^;&|]*\btzdata\b", runs), "no tzdata fallback install"
