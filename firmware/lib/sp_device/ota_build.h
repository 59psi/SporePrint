#pragma once
//
// ota_build — the build-time identity the signed-manifest check uses
// (ota_service.h configure_manifests). Include it from a composition root
// (src/*/main.cpp), where scripts/fw_version.py's defines apply:
//
//   SP_FW_ARTIFACT                  the PlatformIO env (node_esp32, cam, ...)
//                                   — what a node manifest's "artifact" names
//   SPOREPRINT_OTA_PUBKEY_B64       base64 of the 32-byte Ed25519 key that
//                                   signs release manifests (the same key
//                                   format the Pi pins). Taken from the
//                                   build's environment; "" = this image
//                                   accepts no manifests (every local build
//                                   unless you export the key)
//   SPOREPRINT_OTA_REQUIRE_MANIFEST 1 = refuse any push without a verified
//                                   manifest (0 by default: the transition
//                                   releases accept unsigned pushes)
//
// The key is a build input on purpose: never NVS-over-MQTT, never a Pi
// setting — whoever controls the command channel must not choose the key
// that authorizes images.

#include "ota_service.h"

#ifndef SP_FW_ARTIFACT
#define SP_FW_ARTIFACT ""
#endif
#ifndef SPOREPRINT_OTA_PUBKEY_B64
#define SPOREPRINT_OTA_PUBKEY_B64 ""
#endif
#ifndef SPOREPRINT_OTA_REQUIRE_MANIFEST
#define SPOREPRINT_OTA_REQUIRE_MANIFEST 0
#endif

namespace sp_device {

inline OtaManifestConfig ota_manifest_build_config(sp::KvStore* kv,
                                                   const char* fw_version) {
    OtaManifestConfig c;
    c.pubkey_b64 = SPOREPRINT_OTA_PUBKEY_B64;
    c.require = SPOREPRINT_OTA_REQUIRE_MANIFEST != 0;
    c.artifact = SP_FW_ARTIFACT;
    c.fw_version = fw_version;
    c.kv = kv;
    return c;
}

}  // namespace sp_device
