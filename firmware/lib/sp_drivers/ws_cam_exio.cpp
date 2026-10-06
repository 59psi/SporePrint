#include "ws_cam_exio.h"

namespace sp {

bool WsCamExio::camera_power_on() {
    const uint8_t dir[2] = {kRegDirection, kOutputs};
    if (!bus_.write(kAddr, dir, sizeof(dir))) return false;
    const uint8_t out[2] = {kRegOutput, kCameraOnLevels};
    return bus_.write(kAddr, out, sizeof(out));
}

}  // namespace sp
