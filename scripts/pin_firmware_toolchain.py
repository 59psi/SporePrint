#!/usr/bin/env python3
"""Fetch the PlatformIO platform and its build packages, checked by SHA-256.

firmware/platformio.ini names the pioarduino platform by a GitHub release
asset URL, and the platform's platform.json names its framework and tool
packages the same way. PlatformIO checks none of them against a hash, and a
release asset can be replaced. The release workflow therefore runs this
script before `pio run`:

  prepare   downloads the platform zip and every package that
            firmware/toolchain.lock.json lists, refuses any whose SHA-256
            differs from the lock, unpacks the platform, points those
            packages in its platform.json at the checked local files
            (file://), and points every `platform =` line of platformio.ini
            at the checked platform folder.
  check     after the build, refuses a PlatformIO core in which a package
            was installed from any http(s) URL or from the PlatformIO
            registry: everything must have come from a checked file, except
            the lock's core_packages_not_in_builds (PlatformIO Core's own PIO
            Home front end, which no build reads) at exactly their URLs, and
            the lock's core_registry_packages (PlatformIO Core's own SCons,
            which Core installs from the PlatformIO registry for every build;
            the registry checksums it, the lock does not pin it). The
            toolchain binaries arrive through Espressif's idf_tools.py, which
            checks each download against the SHA-256 in the tools.json of its
            (checked) package. Library dependencies (lib_deps) also come from
            the PlatformIO registry, into the project, not the core; they are
            pinned by version in platformio.ini, not by this lock.

The platform's own Python virtualenv (penv) is pinned by
firmware/requirements-penv.txt (every package with its SHA-256). The
workflow installs it before the build and builds offline for uv, so the
platform's builder/penv_setup.py finds what it wants already there:

  prepare   also refuses a platform whose penv_setup.py wants a package
            requirements-penv.txt does not pin.
  check     also refuses a penv holding a distribution that
            requirements-penv.txt does not pin at that exact version
            (esptool excepted: it is installed from the checked
            tool-esptoolpy package, which must be where it points).

Usage:
  python scripts/pin_firmware_toolchain.py prepare --dest DIR [--ini firmware/platformio.ini]
  python scripts/pin_firmware_toolchain.py check --core-dir DIR
  python scripts/pin_firmware_toolchain.py hash FILE...   # SHA-256 for the lock

`prepare` rewrites --ini in place (the release runner's throwaway checkout).
On a working checkout pass a copy, and build from a fresh PLATFORMIO_CORE_DIR
with that copy: `check` passes only on a core populated that way, never on
one that installed the platform and frameworks from their release URLs.

To move to a new platform release: change the URL in platformio.ini, put the
new URL and its SHA-256 in the lock, and update the package entries from the
new platform.json (the script refuses a lock whose package URLs differ from
the platform's).
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "firmware" / "toolchain.lock.json"
DEFAULT_INI = ROOT / "firmware" / "platformio.ini"
DEFAULT_PENV_REQS = ROOT / "firmware" / "requirements-penv.txt"
REQ_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s\\;]+)", re.M)
PLATFORM_RE = re.compile(r"^(platform\s*=\s*)(https://\S+\.zip)\s*$", re.M)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PinError(Exception):
    pass


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_lock(path: Path) -> dict:
    lock = json.loads(path.read_text())
    entries = [lock["platform"], *lock["packages"].values()]
    for entry in entries:
        if not entry["url"].startswith("https://"):
            raise PinError(f"lock: {entry['url']} is not an https URL")
        if not SHA256_RE.match(entry["sha256"]):
            raise PinError(f"lock: {entry['url']} has no valid sha256")
    return lock


def ini_platform_urls(ini_text: str) -> set[str]:
    return {m.group(2) for m in PLATFORM_RE.finditer(ini_text)}


def fetch(url: str, sha256: str, dest: Path) -> Path:
    """Download url into dest (reusing a file already there with the right
    hash) and return its path; refuse it unless its SHA-256 is sha256."""
    dest.mkdir(parents=True, exist_ok=True)
    name = url.rstrip("/").rsplit("/", 1)[-1]
    target = dest / name
    if target.exists() and sha256_of(target) == sha256:
        return target
    partial = target.with_name(target.name + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as out:
        shutil.copyfileobj(response, out, 1 << 20)
    actual = sha256_of(partial)
    if actual != sha256:
        partial.unlink()
        raise PinError(f"{url}: sha256 {actual} does not match the lock ({sha256})")
    partial.replace(target)
    return target


def normalize(name: str) -> str:
    """PEP 503 project name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned_requirements(path: Path) -> dict[str, str]:
    """{normalized name: version} of a `name==version --hash=…` file."""
    pins = {normalize(m.group(1)): m.group(2) for m in REQ_RE.finditer(path.read_text())}
    if not pins:
        raise PinError(f"{path.name}: no pinned requirements")
    return pins


def penv_python_deps(platform_dir: Path) -> set[str]:
    """The package names the platform's builder/penv_setup.py installs
    (its module-level `python_deps` dict), or an empty set without one."""
    setup = platform_dir / "builder" / "penv_setup.py"
    if not setup.exists():
        return set()
    for node in ast.parse(setup.read_text()).body:
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "python_deps"
                                                 for t in node.targets)):
            deps = ast.literal_eval(node.value)
            return {normalize(name) for name in deps}
    raise PinError(f"{setup}: no python_deps found")


def unpack_platform(archive: Path, dest: Path) -> Path:
    out = dest / "platform"
    if out.exists():
        shutil.rmtree(out)
    with zipfile.ZipFile(archive) as z:
        for member in z.namelist():
            if member.startswith("/") or ".." in Path(member).parts:
                raise PinError(f"{archive.name}: unsafe path {member}")
        z.extractall(out)
    manifests = sorted(out.glob("*/platform.json")) + sorted(out.glob("platform.json"))
    if len(manifests) != 1:
        raise PinError(f"{archive.name}: expected one platform.json, found {len(manifests)}")
    return manifests[0].parent


def prepare(lock_path: Path, ini_path: Path, dest: Path,
            penv_reqs: Path = DEFAULT_PENV_REQS) -> Path:
    lock = load_lock(lock_path)
    ini_text = ini_path.read_text()
    urls = ini_platform_urls(ini_text)
    if urls != {lock["platform"]["url"]}:
        raise PinError(f"{ini_path.name} names {sorted(urls)}, the lock {lock['platform']['url']}")

    archive = fetch(lock["platform"]["url"], lock["platform"]["sha256"], dest / "downloads")
    platform_dir = unpack_platform(archive, dest)
    unpinned = sorted(penv_python_deps(platform_dir) - set(pinned_requirements(penv_reqs)))
    if unpinned:
        raise PinError(f"the platform's penv wants {', '.join(unpinned)}, which "
                       f"{penv_reqs.name} does not pin: regenerate it")
    manifest_path = platform_dir / "platform.json"
    manifest = json.loads(manifest_path.read_text())
    packages = manifest.get("packages", {})
    for name, entry in lock["packages"].items():
        if name not in packages:
            raise PinError(f"the platform has no package {name}")
        if packages[name].get("version") != entry["url"]:
            raise PinError(f"{name}: the platform wants {packages[name].get('version')}, "
                           f"the lock pins {entry['url']}: update the lock")
        local = fetch(entry["url"], entry["sha256"], dest / "downloads")
        packages[name]["version"] = local.resolve().as_uri()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    new_ini = PLATFORM_RE.sub(lambda m: m.group(1) + platform_dir.resolve().as_uri(), ini_text)
    ini_path.write_text(new_ini)
    return platform_dir


def check_core(core_dir: Path, lock_path: Path = DEFAULT_LOCK) -> list[str]:
    """Packages installed from anything but a checked local file: an http(s)
    or git URL other than the lock's core_packages_not_in_builds (at exactly
    their URLs), or the PlatformIO registry (no URI) for a package the lock's
    core_registry_packages does not name."""
    lock = load_lock(lock_path)
    allowed = lock.get("core_packages_not_in_builds", {})
    registry_ok = set(lock.get("core_registry_packages", {}))
    bad = []
    for piopm in sorted(core_dir.glob("packages/*/.piopm")) + sorted(core_dir.glob("platforms/*/.piopm")):
        meta = json.loads(piopm.read_text())
        spec = meta.get("spec") or {}
        url = str(spec.get("uri") or spec.get("url") or "")
        name = meta.get("name") or piopm.parent.name
        if re.match(r"^(https?|git\+)", url) and allowed.get(name) != url:
            bad.append(f"{piopm.parent.name}: {url}")
        elif not url and name not in registry_ok:
            owner = spec.get("owner") or "unknown owner"
            bad.append(f"{piopm.parent.name}: the PlatformIO registry ({owner}), not in core_registry_packages")
    return bad


def check_penv(core_dir: Path, penv_reqs: Path = DEFAULT_PENV_REQS) -> list[str]:
    """Distributions in the core's penv that requirements-penv.txt does not
    pin at that version. esptool must be the editable install of the
    core's (checked) tool-esptoolpy package; pip is the venv's own."""
    pins = pinned_requirements(penv_reqs)
    esptool_dir = (core_dir / "packages" / "tool-esptoolpy").resolve()
    bad = []
    for info in sorted(core_dir.glob("penv/lib/python*/site-packages/*.dist-info")):
        meta = (info / "METADATA").read_text(errors="replace")
        name = re.search(r"^Name:\s*(\S+)", meta, re.M)
        version = re.search(r"^Version:\s*(\S+)", meta, re.M)
        if not (name and version):
            bad.append(f"{info.name}: unreadable metadata")
            continue
        key, ver = normalize(name.group(1)), version.group(1)
        if key == "pip":
            continue
        if key == "esptool":
            direct = info / "direct_url.json"
            url = json.loads(direct.read_text()).get("url", "") if direct.exists() else ""
            if url.startswith("file://") and Path(url[len("file://"):]).resolve() == esptool_dir:
                continue
            bad.append(f"esptool {ver}: not the checked tool-esptoolpy package ({url or 'from an index'})")
            continue
        if pins.get(key) != ver:
            bad.append(f"{key} {ver}: {penv_reqs.name} pins {pins.get(key, 'nothing')}")
    return bad


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--dest", type=Path, required=True)
    p.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    p.add_argument("--ini", type=Path, default=DEFAULT_INI)
    p.add_argument("--penv-requirements", type=Path, default=DEFAULT_PENV_REQS)
    c = sub.add_parser("check")
    c.add_argument("--core-dir", type=Path, required=True)
    c.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    c.add_argument("--penv-requirements", type=Path, default=DEFAULT_PENV_REQS)
    h = sub.add_parser("hash")
    h.add_argument("files", type=Path, nargs="+")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            platform_dir = prepare(args.lock, args.ini, args.dest, args.penv_requirements)
            print(f"platform and {len(load_lock(args.lock)['packages'])} packages checked; "
                  f"{args.ini} now uses {platform_dir}")
        elif args.command == "check":
            bad = check_core(args.core_dir, args.lock)
            if bad:
                print("installed from an unchecked source:\n  " + "\n  ".join(bad), file=sys.stderr)
                return 1
            if (args.core_dir / "penv").exists():
                bad = check_penv(args.core_dir, args.penv_requirements)
                if bad:
                    print("penv holds unpinned Python packages:\n  " + "\n  ".join(bad), file=sys.stderr)
                    return 1
            print("every installed package came from a checked file "
                  "(or is a listed PlatformIO Core package)")
        else:
            for f in args.files:
                print(f"{sha256_of(f)}  {f}")
    except (PinError, OSError, KeyError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
