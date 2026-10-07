"""PlatformIO pre-script: embed the firmware version (docs#28).

SPOREPRINT_FW_VERSION reaches the images as a C string macro, taken from:

  1. the SPOREPRINT_FW_VERSION environment variable, when set and non-empty
     (the release workflow exports it from the firmware-vX.Y.Z tag), else
  2. firmware/VERSION.txt (kept in lockstep with the Pi server and cloud by
     the parent repo's scripts/bump.sh), else
  3. "dev".

Before this, the build flag expanded ${sysenv.SPOREPRINT_FW_VERSION}
directly, so every documented local build (`pio run -t upload -e node_esp32`,
or the Builder ZIP) defined the macro as "" — the #ifndef "dev" fallback in
main.cpp never fired and nodes heartbeated firmware_version "".

It also defines the rest of the image's build identity, which the signed
OTA manifest check reads (lib/sp_device/ota_build.h):

  SP_FW_ARTIFACT                  the PlatformIO env being built — what a
                                  node manifest's "artifact" must name
  SPOREPRINT_OTA_PUBKEY_B64       from the environment variable of that name:
                                  base64 of the 32-byte Ed25519 release key
                                  (the key the Pi pins). Unset = the image
                                  accepts no manifests. A malformed value
                                  fails the build rather than shipping an
                                  image that silently ignores manifests.
  SPOREPRINT_OTA_REQUIRE_MANIFEST 1 when the environment variable of that name
                                  is 1/true/yes (refuse unsigned pushes), else 0
"""

import os
import re

Import("env")  # noqa: F821 — SCons global injected by PlatformIO

# Anything outside this set would only be a typo in a tag or VERSION.txt; it
# is replaced rather than spliced into a C string literal.
_ALLOWED = re.compile(r"[^0-9A-Za-z._+-]")
# 32 bytes of standard base64 with its one '=' of padding.
_PUBKEY_B64 = re.compile(r"[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=")
# ota_manifest.py's artifact grammar.
_ARTIFACT = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


def _resolve(project_dir):
    value = os.environ.get("SPOREPRINT_FW_VERSION", "").strip()
    if value:
        return value, "SPOREPRINT_FW_VERSION"
    try:
        with open(os.path.join(project_dir, "VERSION.txt"), encoding="utf-8") as f:
            value = f.read().strip()
    except OSError:
        value = ""
    if value:
        return value, "VERSION.txt"
    return "dev", "default"


version, source = _resolve(env.subst("$PROJECT_DIR"))  # noqa: F821
version = _ALLOWED.sub("_", version)[:32]
env.Append(  # noqa: F821
    CPPDEFINES=[("SPOREPRINT_FW_VERSION", env.StringifyMacro(version))]  # noqa: F821
)
print("SporePrint firmware version: %s (from %s)" % (version, source))

artifact = env.subst("$PIOENV")  # noqa: F821
if not _ARTIFACT.fullmatch(artifact):
    artifact = ""  # never a manifest artifact: manifests are then refused
pubkey = os.environ.get("SPOREPRINT_OTA_PUBKEY_B64", "").strip()
if pubkey and not _PUBKEY_B64.fullmatch(pubkey):
    raise SystemExit(
        "SPOREPRINT_OTA_PUBKEY_B64 is not the base64 of a 32-byte Ed25519 key"
    )
require = os.environ.get("SPOREPRINT_OTA_REQUIRE_MANIFEST", "").strip().lower()
require_manifest = 1 if require in ("1", "true", "yes") else 0
env.Append(  # noqa: F821
    CPPDEFINES=[
        ("SP_FW_ARTIFACT", env.StringifyMacro(artifact)),  # noqa: F821
        ("SPOREPRINT_OTA_PUBKEY_B64", env.StringifyMacro(pubkey)),  # noqa: F821
        ("SPOREPRINT_OTA_REQUIRE_MANIFEST", require_manifest),
    ]
)
print(
    "SporePrint OTA manifests: %s (artifact %s)"
    % (
        ("required" if require_manifest else "accepted") if pubkey else "no key built in",
        artifact or "-",
    )
)
