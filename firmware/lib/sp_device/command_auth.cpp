#include "command_auth.h"

#include <string.h>
#include <time.h>

#include <string>

#include "coredump_drain.h"     // sp::kCoredumpAckSuffix
#include "coredump_uploader.h"  // coredump::on_ack
#include "log_forward.h"        // SP_LOG
#include "ota_gate.h"           // sp::kOtaManifestSuffix
#include "sha256.h"             // sp::hmac_sha256_host

namespace sp_device {

bool verify_command(MqttLink& link, NodeConfig& cfg, sp::KvStore& kv,
                    sp::ReplayGuard& guard, const char* raw, size_t raw_len,
                    const char* suffix) {
    std::string topic = link.topic("cmd/");
    topic += suffix;
    const sp::CmdAuthResult r = sp::command_auth_decision(
        raw, raw_len, cfg.hmac_key.c_str(), cfg.hmac_key.size(),
        (uint64_t)time(nullptr), sp::hmac_sha256_host, topic.c_str(), &guard,
        cfg.hmac_key_prev.c_str(), cfg.hmac_key_prev.size());
    // Which key verified, while a rotation is under way (hmac_verify.h).
    if (r.decision == sp::CmdAuthDecision::Accept && r.with_prev_key) {
        SP_LOG(LOG_WARN,
               "[SEC] cmd/%s verified with the PREVIOUS signing key - the old "
               "key stays valid until the Pi signs with the new one",
               suffix);
    } else if (sp::retire_prev_key(r, cfg.hmac_key_prev, kv)) {
        SP_LOG(LOG_INFO,
               "[SEC] cmd/%s verified with the new signing key - "
               "previous key retired",
               suffix);
    }
    switch (r.decision) {
        case sp::CmdAuthDecision::AcceptUnsigned:
            SP_LOG(LOG_WARN,
                   "[SEC] hmac_key not provisioned — accepting unsigned cmd/%s",
                   suffix);
            return true;
        case sp::CmdAuthDecision::RejectClockUnsynced:
            SP_LOG(LOG_WARN, "[SEC] Rejecting cmd/%s: clock not synced", suffix);
            return false;
        case sp::CmdAuthDecision::Reject:
            SP_LOG(LOG_WARN, "[SEC] Rejecting cmd/%s: %s", suffix,
                   sp::verify_status_str(r.status));
            return false;
        case sp::CmdAuthDecision::Accept:
            return true;
    }
    return false;
}

bool coredump_ack_verifiable(const NodeConfig& cfg) {
    return cfg.hmac_key.empty() || (uint64_t)time(nullptr) >= sp::kMinValidEpoch;
}

CmdPrologue command_prologue(MqttLink& link, NodeConfig& cfg, sp::KvStore& kv,
                             sp::ReplayGuard& guard, OtaService* ota,
                             const char* suffix, const char* raw,
                             size_t raw_len, JsonDocument& doc) {
    if (!verify_command(link, cfg, kv, guard, raw, raw_len, suffix))
        return CmdPrologue::Rejected;
    // The Pi stored the panic dump this image uploaded (coredump_uploader.h).
    // A reserved name, so no channel can shadow it (channel_runtime.cpp).
    if (strcmp(suffix, sp::kCoredumpAckSuffix) == 0) {
        coredump::on_ack(doc);
        return CmdPrologue::Handled;
    }
    // A signed release manifest for the push that follows (ota_service.h).
    if (strcmp(suffix, sp::kOtaManifestSuffix) == 0) {
        if (ota != nullptr) ota->on_manifest(doc);
        return CmdPrologue::Handled;
    }
    return CmdPrologue::Route;
}

}  // namespace sp_device
