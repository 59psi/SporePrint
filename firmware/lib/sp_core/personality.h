#pragma once
//
// personality — provision-time channel-bank presets and the node-type
// derivation used in heartbeats.
//
// The Pi's cloud command routing resolves nodes BY TYPE (climate / relay /
// lighting / camera), so a unified node must still report one of those
// strings — never "node". Derivation rule: an actuator personality wins
// (that's what command routing needs to find); sensors-only reports
// "climate". The full capability set rides in the additive `roles` array.
//
// Native-safe: no Arduino headers.

#include <string.h>

#include "channel_runtime.h"

namespace sp {

enum class Personality : uint8_t {
    Climate = 0,   // sensors only — no channel bank
    RelayBank,     // 4× switch channels: fae/exhaust/circulation/aux
    LightingBank,  // 4× dim channels: white/blue/red/far_red + scenes
};

inline const char* personality_str(Personality p) {
    switch (p) {
        case Personality::Climate:      return "climate";
        case Personality::RelayBank:    return "relay";
        case Personality::LightingBank: return "lighting";
    }
    return "climate";
}

inline bool personality_from_str(const char* s, Personality* out) {
    if (s == nullptr) return false;
    if (strcmp(s, "climate") == 0) { *out = Personality::Climate; return true; }
    if (strcmp(s, "relay") == 0) { *out = Personality::RelayBank; return true; }
    if (strcmp(s, "lighting") == 0) { *out = Personality::LightingBank; return true; }
    return false;
}

// Fill `out[4]` with the preset channel configs. Returns the channel count
// (0 for Climate). Names are wire contract — the Pi's automation rules and
// dashboards reference them verbatim.
inline int personality_channels(Personality p, ChannelConfig out[4]) {
    switch (p) {
        case Personality::Climate:
            return 0;
        case Personality::RelayBank: {
            const char* names[4] = {"fae", "exhaust", "circulation", "aux"};
            for (int i = 0; i < 4; ++i) {
                ChannelConfig c;
                strncpy(c.name, names[i], kChannelNameMax);
                c.mode = ChannelMode::Switch;
                c.max_on_ms = kDefaultMaxOnMs;
                out[i] = c;
            }
            return 4;
        }
        case Personality::LightingBank: {
            const char* names[4] = {"white", "blue", "red", "far_red"};
            for (int i = 0; i < 4; ++i) {
                ChannelConfig c;
                strncpy(c.name, names[i], kChannelNameMax);
                c.mode = ChannelMode::Dim;
                c.max_on_ms = 0;  // lights legitimately run 12 h
                out[i] = c;
            }
            return 4;
        }
    }
    return 0;
}

// Heartbeat `type` string (see header comment).
inline const char* node_type_str(Personality p) { return personality_str(p); }

}  // namespace sp
