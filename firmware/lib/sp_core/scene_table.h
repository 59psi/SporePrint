#pragma once
//
// scene_table — built-in lighting scenes for the dim channel bank.
//
// Names are wire contract: the Pi's automation rule templates reference
// "fruiting_standard", "colonization_dark", and "cordyceps_blue" verbatim
// (server/app/automation/templates.py), and the other two ship in docs.
// Levels are 10-bit per dim channel in bank order (white, blue, red,
// far_red). Do not rename without a Pi-side migration.
//
// Native-safe: no Arduino headers.

#include <stdint.h>
#include <string.h>

namespace sp {

constexpr int kSceneChannels = 4;

struct Scene {
    const char* name;
    uint16_t levels[kSceneChannels];  // white, blue, red, far_red
};

constexpr Scene kScenes[] = {
    {"colonization_dark", {0, 0, 0, 0}},
    {"pinning_daylight", {700, 200, 0, 0}},
    {"fruiting_standard", {800, 150, 100, 50}},
    {"cordyceps_blue", {0, 900, 0, 0}},
    {"lions_mane_gentle", {400, 100, 0, 0}},
};
constexpr int kSceneCount = (int)(sizeof(kScenes) / sizeof(kScenes[0]));

inline const Scene* find_scene(const char* name) {
    if (name == nullptr) return nullptr;
    for (const Scene& s : kScenes) {
        if (strcmp(s.name, name) == 0) return &s;
    }
    return nullptr;
}

}  // namespace sp
