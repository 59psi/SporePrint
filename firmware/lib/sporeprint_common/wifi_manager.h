#pragma once

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include "config_store.h"

class WiFiManager {
public:
    WiFiManager(ConfigStore& config);

    void begin();
    bool isConnected();
    String getIP();
    int getRSSI();

private:
    ConfigStore& _config;
    bool _connected = false;
    unsigned long _lastRetry = 0;
    int _retryDelay = 1000;

    bool _tryConnect();
    void _startCaptivePortal();
};
