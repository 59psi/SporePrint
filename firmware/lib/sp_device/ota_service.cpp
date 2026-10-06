#include "ota_service.h"

#include <ESPmDNS.h>
#include <Update.h>
#include <WiFi.h>
#include <esp_random.h>

#include <string.h>
#include <time.h>

#include "base64_codec.h"
#include "ota_manifest.h"
#include "task_wdt.h"

namespace sp_device {

namespace {

// The espota command numbers are the core's Update targets.
static_assert(U_FLASH == sp::espota::kCmdFlash, "espota flash command");
static_assert(U_FLASHFS == sp::espota::kCmdFilesystem,
              "espota filesystem command");

// Transfer loop, as 2.x ArduinoOTA ran it: wait up to 1 s for each chunk,
// re-ack the last count up to 3 times before giving up, read at most one TCP
// segment per pass.
constexpr uint32_t kChunkWaitMs = 1000;
constexpr int kChunkRetries = 3;
constexpr size_t kChunkBytes = 1460;

// NVS: the version of the newest manifest-verified update (anti-rollback).
constexpr const char* kNvsOtaFloor = "ota_floor";
// A cmd frame is < 1024 bytes, so its base64 manifest is < 768 raw bytes.
constexpr size_t kManifestBufBytes = 768;

}  // namespace

void OtaService::publish_event(const char* event, const char* extra_key,
                               const char* extra_val, const char* extra_key2,
                               const char* extra_val2) {
    if (!link_.connected()) return;
    JsonDocument doc;
    doc["event"] = event;
    doc["ts"] = (long)time(nullptr);
    if (extra_key != nullptr) doc[extra_key] = extra_val;
    if (extra_key2 != nullptr) doc[extra_key2] = extra_val2;
    link_.publish(link_.topic("ota").c_str(), doc);
}

void OtaService::configure_manifests(const OtaManifestConfig& cfg) {
    manifest_cfg_ = cfg;
    pubkey_ok_ = false;
    const char* b64 = cfg.pubkey_b64 != nullptr ? cfg.pubkey_b64 : "";
    size_t n = 0;
    if (b64[0] != '\0') {
        pubkey_ok_ = sp::base64_decode(b64, strlen(b64), pubkey_, sizeof(pubkey_),
                                       &n) &&
                     n == sp::kOtaPubkeyBytes;
        if (!pubkey_ok_)
            Serial.println("[OTA] built-in manifest key is not 32 bytes of "
                           "base64 - signed manifests disabled");
    }
    if (cfg.require && !pubkey_ok_) {
        // Requiring what can never verify would lock out every push.
        Serial.println("[OTA] manifests required but no verify key built in - "
                       "requirement ignored");
        manifest_cfg_.require = false;
    }
    if (pubkey_ok_)
        Serial.printf("[OTA] signed manifests: %s (artifact %s)\n",
                      manifest_cfg_.require ? "REQUIRED" : "accepted",
                      cfg.artifact != nullptr && cfg.artifact[0] != '\0'
                          ? cfg.artifact
                          : "unknown");
}

void OtaService::reject_manifest(const char* reason) {
    gate_.disarm();  // a rejected manifest never leaves an older arming live
    Serial.printf("[OTA] manifest rejected: %s\n", reason);
    publish_event("manifest_rejected", "reason", reason);
}

void OtaService::on_manifest(JsonDocument& doc) {
    if (!pubkey_ok_) {
        reject_manifest("manifest_no_key");
        return;
    }
    const char* mb64 = doc["manifest_b64"] | "";
    const char* sb64 = doc["sig_b64"] | "";
    static uint8_t manifest[kManifestBufBytes];
    uint8_t sig[sp::kOtaSignatureBytes];
    size_t mlen = 0, slen = 0;
    if (!sp::base64_decode(mb64, strlen(mb64), manifest, sizeof(manifest),
                           &mlen) ||
        mlen == 0 ||
        !sp::base64_decode(sb64, strlen(sb64), sig, sizeof(sig), &slen) ||
        slen != sizeof(sig)) {
        reject_manifest("manifest_malformed");
        return;
    }
    sp::OtaManifest m;
    const sp::ManifestStatus st =
        sp::verify_manifest(manifest, mlen, sig, pubkey_, &m);
    if (st != sp::ManifestStatus::Ok) {
        reject_manifest(sp::manifest_status_str(st));
        return;
    }
    std::string floor;
    if (manifest_cfg_.kv != nullptr)
        floor = manifest_cfg_.kv->get_string(kNvsOtaFloor, "");
    const sp::ManifestPolicy pol =
        sp::manifest_policy(m, manifest_cfg_.artifact, manifest_cfg_.fw_version,
                            floor.c_str());
    if (pol != sp::ManifestPolicy::Ok) {
        reject_manifest(sp::manifest_policy_str(pol));
        return;
    }
    gate_.arm(m, millis());
    Serial.printf("[OTA] manifest armed: %s %s (%llu bytes)\n", m.artifact,
                  m.version, (unsigned long long)m.size);
    publish_event("manifest_armed", "version", m.version, "sha256", m.sha256);
}

bool OtaService::begin() {
    if (pass_.length() == 0) {
        Serial.println("[OTA] DISABLED — no ota_pass provisioned (portal field).");
        return false;
    }
    // Brute-force over the MD5-challenge auth on LAN runs ~1k guesses/sec;
    // 12 mixed chars keeps the space >2^60.
    if (pass_.length() < 12) {
        Serial.printf("[OTA] DISABLED — ota_pass too short (%u chars, need >=12).\n",
                      (unsigned)pass_.length());
        return false;
    }
    sp::espota::password_digest(pass_.c_str(), pass_digest_);
    pass_ = String();  // only the digest is needed from here on

    if (!udp_.begin(sp::espota::kPort)) {
        Serial.printf("[OTA] DISABLED — UDP %u bind failed.\n",
                      (unsigned)sp::espota::kPort);
        return false;
    }
    // "<hostname>.local" + the _arduino._tcp service (auth required), as
    // ArduinoOTA advertised them — network upload tools discover nodes so.
    MDNS.begin(hostname_.c_str());
    MDNS.enableArduino(sp::espota::kPort, true);

    armed_ = true;
    Serial.printf("[OTA] Ready. Hostname: %s\n", hostname_.c_str());
    return true;
}

void OtaService::loop() {
    if (!armed_) return;
    const int n = udp_.parsePacket();
    if (n > 0) {
        char buf[sp::espota::kMaxDatagram];
        const int got = udp_.read(buf, sizeof(buf));
        if (got > 0) on_datagram(buf, (size_t)got);
    }
    udp_.clear();  // always: an oversize or empty datagram must not linger
}

void OtaService::reply(const char* text, const char* arg) {
    udp_.beginPacket(udp_.remoteIP(), udp_.remotePort());
    udp_.print(text);
    if (arg != nullptr) udp_.print(arg);
    udp_.endPacket();
}

void OtaService::on_datagram(const char* data, size_t len) {
    if (state_ == State::Idle) {
        sp::espota::Invitation inv;
        if (!sp::espota::parse_invitation(data, len, &inv)) return;  // not ours
        invitation_ = inv;
        uint8_t rnd[sp::espota::kNonceBytes];
        esp_fill_random(rnd, sizeof(rnd));
        sp::espota::nonce_hex(rnd, nonce_);
        reply("AUTH ", nonce_);
        state_ = State::WaitAuth;
        return;
    }

    // WaitAuth: exactly one datagram answers the challenge. Anything else —
    // including a re-sent invitation — drops back to idle without a reply,
    // as 2.x ArduinoOTA did (the Pi push re-invites on a fresh socket).
    state_ = State::Idle;
    sp::espota::AuthReply answer;
    switch (sp::espota::parse_auth_reply(data, len, &answer)) {
        case sp::espota::AuthParse::NotAuth:
            Serial.println("[OTA] expected the auth answer - invitation dropped");
            return;
        case sp::espota::AuthParse::BadParams:
            Serial.println("[OTA] malformed auth answer - invitation dropped");
            return;
        case sp::espota::AuthParse::Ok:
            break;
    }
    const bool ok =
        sp::espota::response_matches(pass_digest_, nonce_, answer);
    nonce_[0] = '\0';  // one answer per challenge
    if (!ok) {
        reply("Authentication Failed");
        fail("auth_failed");
        return;
    }
    reply("OK");
    peer_ip_ = udp_.remoteIP();
    run_update();
}

void OtaService::fail(const char* reason) {
    Serial.printf("[OTA] Error: %s\n", reason);
    publish_event("error", "reason", reason);
}

void OtaService::run_update() {
    const int cmd = invitation_.cmd;
    const uint32_t size = invitation_.size;
    // Signed-manifest gate, before anything is erased or switched off.
    const sp::OtaGate::Begin gate =
        gate_.begin(millis(), cmd, size, manifest_cfg_.require);
    switch (gate) {
        case sp::OtaGate::Begin::Unverified:
        case sp::OtaGate::Begin::Verified:
            break;
        default:
            fail(sp::ota_gate_begin_str(gate));
            return;
    }
    const bool verified = gate == sp::OtaGate::Begin::Verified;
    // Copied now: the arming is consumed, and the event outlives it.
    char manifest_version[sp::kOtaVersionMaxLen + 1] = {0};
    if (verified)
        strncpy(manifest_version, gate_.manifest().version,
                sizeof(manifest_version) - 1);
    if (!Update.begin(size, cmd)) {
        Serial.printf("[OTA] Begin ERROR: %s\n", Update.errorString());
        fail("begin_failed");
        return;
    }
    Update.setMD5(invitation_.md5);

    const char* type = (cmd == U_FLASH) ? "firmware" : "filesystem";
    Serial.printf("[OTA] Start updating %s (%u bytes, %s)\n", type,
                  (unsigned)size, sp::ota_gate_begin_str(gate));
    // Safe state first: outputs off before the synchronous flash stops the
    // loop (and with it every channel timer) for the whole upload.
    if (start_fn_ != nullptr) start_fn_(start_ctx_);
    publish_event("start", "type", type);

    WiFiClient client;
    if (!client.connect(peer_ip_, invitation_.port)) {
        Update.abort();
        gate_.disarm();
        fail("connect_failed");
        return;
    }

    static uint8_t buf[kChunkBytes];
    uint32_t total = 0;
    size_t written = 0;
    int retries = 0;
    while (!Update.isFinished() && client.connected()) {
        int available = client.available();
        const uint32_t wait_start = millis();
        while (available <= 0 && millis() - wait_start < kChunkWaitMs) {
            delay(1);  // network wait inside the synchronous upload
            available = client.available();
        }
        if (available <= 0) {
            if (written > 0 && retries++ < kChunkRetries) {
                client.print((unsigned)written);  // re-ack: the ack was lost
                continue;
            }
            Update.abort();
            gate_.disarm();
            client.stop();
            fail("receive_failed");
            return;
        }
        retries = 0;
        const size_t want =
            (size_t)available < kChunkBytes ? (size_t)available : kChunkBytes;
        const int got = client.read(buf, want);
        if (got <= 0) {
            delay(1);
            continue;
        }
        written = Update.write(buf, (size_t)got);
        if (written == 0) {
            Serial.printf("[OTA] Write ERROR: %s\n", Update.errorString());
            break;  // Update.end() below reports it
        }
        gate_.update(buf, written);  // hashed only when manifest-verified
        // The whole upload legitimately outlasts the loop WDT — this is one
        // of the two sanctioned pet sites outside loop(), and only progress
        // pets it (every wait above is bounded; a loop that stops making
        // progress still meets the watchdog).
        pet_task_wdt();
        client.print((unsigned)written);  // the lockstep ack the client waits on
        total += written;
        if (size >= 100)
            Serial.printf("[OTA] Progress: %u%%\r",
                          (unsigned)(total / (size / 100)));
    }

    pet_task_wdt();
    // A manifest-verified image is finalized only if every flashed byte
    // hashes to the signed sha256 (and the count is the signed size).
    if (verified && Update.isFinished() &&
        gate_.finish() != sp::OtaGate::End::Match) {
        Update.abort();
        client.print("ERR manifest_sha256_mismatch");
        client.stop();
        fail("manifest_sha256_mismatch");
        return;
    }
    gate_.disarm();
    // end(): every byte arrived, the MD5 matches the invitation's, the image
    // verifies, and it is set as the next boot image (pending verification —
    // sp_device/image_rollback.h confirms it after 60 s of MQTT).
    if (!Update.end()) {
        fail("end_failed");
        Update.printError(client);
        client.stop();
        return;
    }
    client.print("OK");
    client.stop();
    delay(10);
    Serial.println("\n[OTA] Update complete.");
    if (verified) {
        // Anti-rollback: no later manifest may go below this version.
        if (manifest_cfg_.kv != nullptr)
            manifest_cfg_.kv->set_string(kNvsOtaFloor, manifest_version);
        publish_event("success", "manifest", manifest_version);
    } else {
        publish_event("success");
    }
    delay(100);  // let Serial / MQTT flush before the reboot
    ESP.restart();
}

}  // namespace sp_device
