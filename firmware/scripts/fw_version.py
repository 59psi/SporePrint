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
"""

import os
import re

Import("env")  # noqa: F821 — SCons global injected by PlatformIO

# Anything outside this set would only be a typo in a tag or VERSION.txt; it
# is replaced rather than spliced into a C string literal.
_ALLOWED = re.compile(r"[^0-9A-Za-z._+-]")


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
