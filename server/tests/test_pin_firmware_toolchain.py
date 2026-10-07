"""scripts/pin_firmware_toolchain.py: the release build's PlatformIO platform
and packages are checked against firmware/toolchain.lock.json.

The script downloads the platform zip platformio.ini names and each locked
package, refuses any whose SHA-256 differs from the lock, and points the build
at the checked local copies; after the build it refuses a PlatformIO core
holding anything installed from an unchecked URL.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "firmware" / "toolchain.lock.json"
INI = ROOT / "firmware" / "platformio.ini"

_spec = importlib.util.spec_from_file_location("pin_firmware_toolchain", ROOT / "scripts" / "pin_firmware_toolchain.py")
pft = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pft)

PLATFORM_URL = "https://example.test/platform-espressif32.zip"
PKG_URL = "https://example.test/esp32-core.tar.xz"
OTHER_URL = "https://example.test/other.zip"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _platform_zip(packages: dict, penv_deps: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("platform-espressif32-1.0/platform.json",
                   json.dumps({"name": "espressif32", "version": "1.0", "packages": packages}))
        z.writestr("platform-espressif32-1.0/platform.py", "")
        if penv_deps is not None:
            z.writestr("platform-espressif32-1.0/builder/penv_setup.py",
                       f"import os\n\npython_deps = {penv_deps!r}\n\ndef f():\n    pass\n")
    return buf.getvalue()


@pytest.fixture
def served(monkeypatch):
    """Serve URLs from a dict instead of the network."""
    files: dict[str, bytes] = {}

    def urlopen(url, timeout=None):
        if url not in files:
            raise OSError(f"404 {url}")
        return io.BytesIO(files[url])

    monkeypatch.setattr(pft.urllib.request, "urlopen", urlopen)
    return files


def _setup(tmp_path: Path, served: dict, *, pkg_bytes=b"core", lock_pkg_sha=None,
           platform_pkg_url=PKG_URL) -> tuple[Path, Path]:
    platform = _platform_zip({
        "framework-arduinoespressif32": {"version": platform_pkg_url},
        "tool-other": {"version": OTHER_URL},
    })
    served[PLATFORM_URL] = platform
    served[PKG_URL] = pkg_bytes
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({
        "platform": {"url": PLATFORM_URL, "sha256": _sha(platform)},
        "packages": {"framework-arduinoespressif32": {
            "url": PKG_URL, "sha256": lock_pkg_sha or _sha(b"core")}},
        "core_packages_not_in_builds": {"contrib-piohome": "https://example.test/piohome.tar.gz"},
        "core_registry_packages": {"tool-scons": "Core's own SCons"},
    }))
    ini = tmp_path / "platformio.ini"
    ini.write_text(f"[esp32_base]\nplatform = {PLATFORM_URL}\nboard = esp32dev\n\n"
                   "[env:native]\nplatform = native\n")
    return lock, ini


def test_prepare_points_the_build_at_checked_local_copies(tmp_path, served):
    lock, ini = _setup(tmp_path, served)
    platform_dir = pft.prepare(lock, ini, tmp_path / "dest")
    text = ini.read_text()
    assert f"platform = {platform_dir.resolve().as_uri()}\n" in text
    assert "platform = native" in text and PLATFORM_URL not in text
    packages = json.loads((platform_dir / "platform.json").read_text())["packages"]
    local = packages["framework-arduinoespressif32"]["version"]
    assert local.startswith("file://") and Path(local[len("file://"):]).read_bytes() == b"core"
    # An unlocked package is left alone; the post-build check catches its use.
    assert packages["tool-other"]["version"] == OTHER_URL


def test_prepare_refuses_a_replaced_package_and_leaves_the_ini(tmp_path, served):
    lock, ini = _setup(tmp_path, served, pkg_bytes=b"tampered")
    before = ini.read_text()
    with pytest.raises(pft.PinError, match="does not match the lock"):
        pft.prepare(lock, ini, tmp_path / "dest")
    assert ini.read_text() == before
    assert not list((tmp_path / "dest" / "downloads").glob("esp32-core*"))


def test_prepare_refuses_a_replaced_platform(tmp_path, served):
    lock, ini = _setup(tmp_path, served)
    served[PLATFORM_URL] = _platform_zip({})
    with pytest.raises(pft.PinError, match="does not match the lock"):
        pft.prepare(lock, ini, tmp_path / "dest")


def test_prepare_refuses_a_lock_the_platform_disagrees_with(tmp_path, served):
    lock, ini = _setup(tmp_path, served, platform_pkg_url="https://example.test/newer.tar.xz")
    with pytest.raises(pft.PinError, match="update the lock"):
        pft.prepare(lock, ini, tmp_path / "dest")


def test_prepare_refuses_an_ini_naming_another_platform(tmp_path, served):
    lock, ini = _setup(tmp_path, served)
    ini.write_text("[esp32_base]\nplatform = https://example.test/other-platform.zip\n")
    with pytest.raises(pft.PinError):
        pft.prepare(lock, ini, tmp_path / "dest")


def _core(tmp_path: Path, installs: dict[str, str | None]) -> Path:
    """A core whose packages came from these URIs (None: the PlatformIO
    registry, which records an owner and no URI)."""
    core = tmp_path / "core"
    for name, uri in installs.items():
        d = core / "packages" / name
        d.mkdir(parents=True)
        spec = {"uri": uri} if uri is not None else {"owner": "platformio", "name": name, "uri": None}
        (d / ".piopm").write_text(json.dumps({"name": name, "spec": spec}))
    return core


def test_check_allows_only_checked_files_and_the_listed_core_packages(tmp_path, served):
    lock, _ = _setup(tmp_path, served)
    good = _core(tmp_path / "a", {
        "framework-arduinoespressif32": "file:///tmp/esp32-core.tar.xz",
        "toolchain-xtensa-esp-elf": "file:///core/tools/toolchain-xtensa-esp-elf",
        "contrib-piohome": "https://example.test/piohome.tar.gz",
    })
    assert pft.check_core(good, lock) == []
    bad = _core(tmp_path / "b", {
        "tool-other": OTHER_URL,
        "contrib-piohome": "https://example.test/another-piohome.tar.gz",
    })
    assert len(pft.check_core(bad, lock)) == 2


def test_check_allows_only_the_listed_registry_packages(tmp_path, served):
    """PlatformIO Core installs its own SCons from the PlatformIO registry
    (no URI in its .piopm) for every build; that is allowed by name, and
    any other registry package is reported."""
    lock, _ = _setup(tmp_path, served)
    assert pft.check_core(_core(tmp_path / "a", {"tool-scons": None}), lock) == []
    bad = pft.check_core(_core(tmp_path / "b", {"tool-scons": None, "tool-cmake": None}), lock)
    assert bad == ["tool-cmake: the PlatformIO registry (platformio), not in core_registry_packages"]


# ─── The platform's penv ─────────────────────────────────────────────────


def _reqs(tmp_path: Path, pins: dict[str, str]) -> Path:
    path = tmp_path / "requirements-penv.txt"
    path.write_text("# header\n" + "".join(
        f"{n}=={v} \\\n    --hash=sha256:{'0' * 64}\n    # via x\n" for n, v in pins.items()))
    return path


def test_prepare_refuses_a_platform_whose_penv_wants_an_unpinned_package(tmp_path, served):
    lock, ini = _setup(tmp_path, served)
    platform = _platform_zip({"framework-arduinoespressif32": {"version": PKG_URL}},
                             penv_deps={"rich-click": ">=1.8", "Esp_IDF.Size": ">=2", "new-dep": ">=1"})
    served[PLATFORM_URL] = platform
    data = json.loads(lock.read_text())
    data["platform"]["sha256"] = _sha(platform)
    lock.write_text(json.dumps(data))
    reqs = _reqs(tmp_path, {"rich-click": "1.9.9", "esp-idf-size": "2.3.2"})
    before = ini.read_text()
    with pytest.raises(pft.PinError, match="new-dep"):
        pft.prepare(lock, ini, tmp_path / "dest", reqs)
    assert ini.read_text() == before
    # Pinned (names compared PEP 503-normalized): prepared.
    reqs = _reqs(tmp_path, {"rich_click": "1.9.9", "esp-idf-size": "2.3.2", "new.dep": "1.0"})
    pft.prepare(lock, ini, tmp_path / "dest", reqs)


def _dist(site: Path, name: str, version: str, direct_url: str | None = None) -> None:
    info = site / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
    if direct_url:
        (info / "direct_url.json").write_text(json.dumps({"url": direct_url, "dir_info": {"editable": True}}))


def test_check_penv_allows_exactly_the_pins_and_the_checked_esptool(tmp_path):
    core = tmp_path / "core"
    esptool_pkg = core / "packages" / "tool-esptoolpy"
    esptool_pkg.mkdir(parents=True)
    site = core / "penv" / "lib" / "python3.12" / "site-packages"
    reqs = _reqs(tmp_path, {"cryptography": "50.0.2", "rich-click": "1.9.9"})
    _dist(site, "cryptography", "50.0.2")
    _dist(site, "rich_click", "1.9.9")
    _dist(site, "pip", "26.2.1")
    _dist(site, "esptool", "5.4.0", esptool_pkg.resolve().as_uri())
    assert pft.check_penv(core, reqs) == []

    _dist(site, "surprise", "1.0")
    bad = pft.check_penv(core, reqs)
    assert bad == ["surprise 1.0: requirements-penv.txt pins nothing"]


def test_check_penv_refuses_a_drifted_version_and_an_esptool_from_an_index(tmp_path):
    core = tmp_path / "core"
    (core / "packages" / "tool-esptoolpy").mkdir(parents=True)
    site = core / "penv" / "lib" / "python3.12" / "site-packages"
    reqs = _reqs(tmp_path, {"cryptography": "50.0.2"})
    _dist(site, "cryptography", "51.0.0")
    _dist(site, "esptool", "5.4.0")
    bad = pft.check_penv(core, reqs)
    assert "cryptography 51.0.0: requirements-penv.txt pins 50.0.2" in bad
    assert any(b.startswith("esptool 5.4.0: not the checked tool-esptoolpy package") for b in bad)


def test_the_committed_python_locks_pin_every_package_with_a_hash():
    for name in ("requirements-pio.txt", "requirements-penv.txt"):
        text = (ROOT / "firmware" / name).read_text()
        reqs = [b for b in re.split(r"\n(?=[^\s#])", text) if b and not b.startswith("#")]
        assert reqs, name
        for block in reqs:
            assert re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*==\S+ \\$", block.splitlines()[0]), block.splitlines()[0]
            assert re.search(r"--hash=sha256:[0-9a-f]{64}", block), block.splitlines()[0]
    assert pft.pinned_requirements(ROOT / "firmware" / "requirements-pio.txt")["platformio"] == "6.2.0"


def test_the_penv_lock_covers_the_platforms_python_deps():
    """requirements-penv.in lists the platform's penv_setup.py python_deps
    (prepare re-checks against the downloaded platform itself)."""
    inputs = (ROOT / "firmware" / "requirements-penv.in").read_text()
    wanted = {pft.normalize(m.group(1)) for m in re.finditer(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)", inputs, re.M)}
    pins = pft.pinned_requirements(ROOT / "firmware" / "requirements-penv.txt")
    assert {"pioarduino", "esp-idf-size", "esp-coredump", "littlefs-python", "cryptography",
            "uv", "setuptools"} <= wanted
    assert wanted - {"esptool"} <= set(pins)
    assert "esptool" not in pins


# ─── The committed lock ───────────────────────────────────────────────────


def test_the_lock_pins_the_platform_platformio_ini_names():
    lock = pft.load_lock(LOCK)
    urls = set(re.findall(r"^platform\s*=\s*(https://\S+)$", INI.read_text(), re.M))
    assert urls == {lock["platform"]["url"]}
    assert lock["platform"]["url"].endswith(".zip")


def test_the_lock_names_the_registry_scons_the_core_installs():
    lock = pft.load_lock(LOCK)
    assert set(lock["core_registry_packages"]) == {"tool-scons"}
    assert "core_registry_packages" in lock["_comment"]


def test_the_lock_covers_what_a_build_installs():
    lock = pft.load_lock(LOCK)
    assert {"framework-arduinoespressif32", "framework-arduinoespressif32-libs",
            "toolchain-xtensa-esp-elf", "tool-esptoolpy", "tool-esp_install",
            "tool-scons"} <= set(lock["packages"])
    for entry in lock["packages"].values():
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])


def test_the_penv_header_documents_its_accepted_advisories():
    """requirements-penv.txt pins starlette below 1.0 (pioarduino's cap) and
    ecdsa, both with published advisories; the header says why that is
    accepted, and this fails once the pins move so the note is revisited."""
    penv = ROOT / "firmware" / "requirements-penv.txt"
    pins = pft.pinned_requirements(penv)
    header = penv.read_text().split("\n" + next(iter(sorted(pins))), 1)[0]
    if pins.get("starlette", "1").startswith("0."):
        assert "starlette (capped below 1.0" in header
    if "ecdsa" in pins:
        assert "ecdsa (no fixed release" in header
    assert "Known advisories" in header and "Dependabot alerts on this file are" in header
