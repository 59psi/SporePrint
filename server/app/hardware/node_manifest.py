"""Signed release manifests for node firmware pushes (Pi → ESP32).

A node image release can carry the same signed manifest the Pi server's own
OTA uses (``app/cloud/ota_manifest.py``, schema v1, the same Ed25519 key the
Pi pins as ``SPOREPRINT_OTA_PUBKEY_B64``), with ``artifact`` = the image's
PlatformIO env (``node_esp32``, ``cam``, ...) and ``sha256``/``size`` of its
``firmware.bin``.

``POST /api/hardware/nodes/{id}/ota`` takes it as two optional files,
``manifest`` and ``manifest_sig``. The Pi then:

1. verifies it here — signature by the pinned key, canonical form, the
   uploaded image's sha256 and size, and a version not older than the node's
   heartbeat ``firmware_version`` — and refuses the push (400) otherwise;
2. sends it to the node on ``cmd/ota_manifest`` {manifest_b64, sig_b64}
   (signed like every command) before inviting the node, and waits for the
   node's ``manifest_armed`` / ``manifest_rejected`` OTA event
   (``ota_push``). A node built with the verify key re-checks everything,
   binds the push to the signed sha256 and refuses any other image; a
   rejection stops the push. A node without manifest support (older
   firmware, or an image built without the key) does not confirm, and the
   push goes ahead verified by the Pi only — the status says which.

The firmware half: firmware/lib/sp_core/ota_manifest.h + ota_gate.h.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from ..cloud import ota_manifest
from ..cloud.ota import OTAError, _load_pinned_pubkey
from ..cloud.version import version_triple

# The node takes the manifest inside one command frame, which must stay under
# its 1024-byte inbound cap with the signature, topic, nonce, ts and HMAC
# beside it (app/mqtt.py _NODE_INBOUND_FRAME_CAP). Real manifests are ~300 B.
MAX_NODE_MANIFEST_BYTES = 480

# cmd/<suffix> on the node (firmware/lib/sp_core/ota_gate.h kOtaManifestSuffix).
CMD_SUFFIX = "ota_manifest"


class NodeManifestError(ValueError):
    """The manifest does not authorize this image for this node."""


@dataclass(frozen=True)
class NodeManifest:
    manifest: dict
    manifest_b64: str
    sig_b64: str

    def command(self) -> dict:
        """The cmd/ota_manifest body."""
        return {"manifest_b64": self.manifest_b64, "sig_b64": self.sig_b64}


def check_node_manifest(manifest_bytes: bytes, signature: bytes, image: bytes,
                        node_firmware_version: str | None) -> NodeManifest:
    """Verify a node image's signed manifest against the uploaded image."""
    if len(manifest_bytes) > MAX_NODE_MANIFEST_BYTES:
        raise NodeManifestError(
            f"manifest is {len(manifest_bytes)} bytes; a node takes at most "
            f"{MAX_NODE_MANIFEST_BYTES}")
    try:
        pubkey = _load_pinned_pubkey()
    except OTAError as e:
        raise NodeManifestError(f"no OTA verify key pinned on this Pi: {e}") from None
    try:
        manifest = ota_manifest.verify(manifest_bytes, signature, pubkey)
    except ota_manifest.ManifestError as e:
        raise NodeManifestError(str(e)) from None
    if manifest["artifact"] == ota_manifest.ARTIFACT_PI_SERVER:
        raise NodeManifestError("this manifest is for the Pi server, not a node image")
    if manifest["size"] != len(image) or manifest["sha256"] != hashlib.sha256(image).hexdigest():
        raise NodeManifestError(
            f"the uploaded image is not the one the manifest signs "
            f"({manifest['artifact']} {manifest['version']})")
    running = version_triple(node_firmware_version or "")
    wanted = version_triple(manifest["version"])
    if running is not None and wanted is not None and wanted < running:
        raise NodeManifestError(
            f"manifest version {manifest['version']} is older than the node's "
            f"firmware {node_firmware_version}")
    return NodeManifest(
        manifest=manifest,
        manifest_b64=base64.b64encode(manifest_bytes).decode("ascii"),
        sig_b64=base64.b64encode(signature).decode("ascii"),
    )
