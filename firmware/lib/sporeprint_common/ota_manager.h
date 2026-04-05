#pragma once

#include <Arduino.h>
#include <ArduinoOTA.h>
#include "config_store.h"

class OTAManager {
public:
    OTAManager(ConfigStore& config, const char* hostname);
    void begin();
    void loop();

private:
    ConfigStore& _config;
    String _hostname;
};
