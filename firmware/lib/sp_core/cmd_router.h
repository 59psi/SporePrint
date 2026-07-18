#pragma once
//
// cmd_router — exact-match dispatch for inbound `sporeprint/<id>/cmd/<x>`
// topics.
//
// The old lighting node subscribed `cmd/#` and pattern-matched suffixes in
// each callback, which both double-dispatched scene frames and would have
// let a channel named "config" shadow the config endpoint. This router is
// the single source of truth: a suffix resolves to exactly one target, and
// reserved endpoint names are rejected at channel-config time
// (channel_name_valid in channel_runtime.h).
//
// Native-safe: no Arduino headers.

#include <stddef.h>
#include <string.h>

#include "channel_runtime.h"

namespace sp {

enum class CmdTarget : uint8_t {
    None = 0,   // unknown suffix — drop
    Config,     // cmd/config
    Scene,      // cmd/scene (only when a dim bank exists)
    Channel,    // cmd/<channel-name> — channel_index is set
};

struct CmdRoute {
    CmdTarget target = CmdTarget::None;
    int channel_index = -1;
};

class CmdRouter {
public:
    // Register channels by name (call after channel configs validate).
    void reset() { count_ = 0; has_scene_ = false; }
    void enable_scene(bool on) { has_scene_ = on; }
    bool add_channel(const char* name, int index) {
        if (count_ >= kMaxChannels) return false;
        if (!channel_name_valid(name)) return false;
        names_[count_] = name;
        indices_[count_] = index;
        ++count_;
        return true;
    }

    // Resolve the suffix after "cmd/". Exact match only.
    CmdRoute route(const char* suffix) const {
        CmdRoute r;
        if (suffix == nullptr || suffix[0] == '\0') return r;
        if (strcmp(suffix, "config") == 0) {
            r.target = CmdTarget::Config;
            return r;
        }
        if (has_scene_ && strcmp(suffix, "scene") == 0) {
            r.target = CmdTarget::Scene;
            return r;
        }
        for (size_t i = 0; i < count_; ++i) {
            if (strcmp(suffix, names_[i]) == 0) {
                r.target = CmdTarget::Channel;
                r.channel_index = indices_[i];
                return r;
            }
        }
        return r;
    }

    static constexpr size_t kMaxChannels = 8;

private:
    const char* names_[kMaxChannels] = {nullptr};
    int indices_[kMaxChannels] = {0};
    size_t count_ = 0;
    bool has_scene_ = false;
};

// Extract the command suffix from a raw inbound MQTT topic for node `id`.
// The device receives `sporeprint/<id>/cmd/#`; the suffix after `.../cmd/` is
// what CmdRouter::route() resolves. Returns a pointer INTO `topic` at the
// suffix, or nullptr when the topic isn't a command for this node, the suffix
// is empty (bare `.../cmd/`), or the suffix is nested (contains '/'). Extracted
// from mqtt_link.cpp so this prefix-strip — the seam that feeds route() — is
// host-tested instead of trapped in Arduino-only code where an off-by-one would
// silently route every command to None.
inline const char* cmd_suffix(const char* topic, const char* id) {
    if (topic == nullptr || id == nullptr) return nullptr;
    const char kHead[] = "sporeprint/";
    const size_t kHeadLen = sizeof(kHead) - 1;
    if (strncmp(topic, kHead, kHeadLen) != 0) return nullptr;
    const char* p = topic + kHeadLen;
    size_t id_len = strlen(id);
    if (strncmp(p, id, id_len) != 0) return nullptr;
    p += id_len;
    const char kCmd[] = "/cmd/";
    const size_t kCmdLen = sizeof(kCmd) - 1;
    if (strncmp(p, kCmd, kCmdLen) != 0) return nullptr;
    p += kCmdLen;
    if (p[0] == '\0') return nullptr;                 // bare .../cmd/
    if (strchr(p, '/') != nullptr) return nullptr;    // nested suffix
    return p;
}

}  // namespace sp
