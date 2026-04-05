#pragma once

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "config_store.h"

#define MQTT_MAX_SUBSCRIPTIONS 16

typedef void (*MqttCallback)(const char* topic, JsonDocument& doc);

class MqttManager {
public:
    MqttManager(ConfigStore& config, const char* nodeType, const char* nodeId);

    void begin();
    void loop();
    bool isConnected();

    void publish(const char* topic, JsonDocument& doc, bool retain = false);
    void publish(const char* topic, const char* payload, bool retain = false);
    void subscribe(const char* topicPattern, MqttCallback callback);

    String getNodeId();
    String buildTopic(const char* suffix);

private:
    ConfigStore& _config;
    WiFiClient _wifiClient;
    PubSubClient _mqtt;
    String _nodeType;
    String _nodeId;
    String _clientId;
    unsigned long _lastReconnect = 0;

    struct Subscription {
        String topic;
        MqttCallback callback;
    };
    Subscription _subs[MQTT_MAX_SUBSCRIPTIONS];
    int _subCount = 0;

    void _connect();
    static void _staticCallback(char* topic, byte* payload, unsigned int length);
    void _handleMessage(char* topic, byte* payload, unsigned int length);

    static MqttManager* _instance;
};
