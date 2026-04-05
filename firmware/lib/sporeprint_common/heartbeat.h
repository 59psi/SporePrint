#pragma once

#include <Arduino.h>
#include "mqtt_manager.h"

class Heartbeat {
public:
    Heartbeat(MqttManager& mqtt, unsigned long intervalMs = 300000);
    void loop();

private:
    MqttManager& _mqtt;
    unsigned long _interval;
    unsigned long _lastBeat = 0;
};
