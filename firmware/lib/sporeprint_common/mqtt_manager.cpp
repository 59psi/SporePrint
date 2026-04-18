#include "mqtt_manager.h"

MqttManager* MqttManager::_instance = nullptr;

MqttManager::MqttManager(ConfigStore& config, const char* nodeType, const char* nodeId)
    : _config(config), _mqtt(_wifiClient), _nodeType(nodeType), _nodeId(nodeId) {
    _instance = this;
    _clientId = "sporeprint-" + _nodeType + "-" + _nodeId;
}

void MqttManager::begin() {
    String host = _config.getString("host");
    if (host.length() == 0) host = "sporeprint.local";
    int port = _config.getInt("port");
    if (port == 0) port = 1883;

    _mqtt.setServer(host.c_str(), port);
    _mqtt.setBufferSize(1024);
    _mqtt.setCallback(_staticCallback);

    _connect();
}

void MqttManager::loop() {
    if (!_mqtt.connected()) {
        unsigned long now = millis();
        if (now - _lastReconnect > 5000) {
            _lastReconnect = now;
            _connect();
        }
    }
    _mqtt.loop();
}

bool MqttManager::isConnected() {
    return _mqtt.connected();
}

void MqttManager::_connect() {
    String lwtTopic = buildTopic("status");
    String lwtPayload = "{\"status\":\"offline\"}";

    // Credentials come from NVS — set via captive portal or provisioning tool.
    // NULL is passed when no user is configured so local dev brokers with
    // allow_anonymous=true still work.
    String user = _config.getString("mqtt_user");
    String pass = _config.getString("mqtt_pass");
    const char* userPtr = user.length() ? user.c_str() : NULL;
    const char* passPtr = pass.length() ? pass.c_str() : NULL;

    Serial.printf("[MQTT] Connecting as '%s' (user=%s)...\n",
                  _clientId.c_str(), userPtr ? userPtr : "<anonymous>");

    if (_mqtt.connect(_clientId.c_str(), userPtr, passPtr, lwtTopic.c_str(), 1, true, lwtPayload.c_str())) {
        Serial.println("[MQTT] Connected!");

        // Publish online status
        JsonDocument doc;
        doc["status"] = "online";
        doc["firmware"] = "0.1.0";
        doc["type"] = _nodeType;
        doc["id"] = _nodeId;
        publish(buildTopic("status").c_str(), doc, true);

        // Re-subscribe
        for (int i = 0; i < _subCount; i++) {
            _mqtt.subscribe(_subs[i].topic.c_str(), 1);
        }
    } else {
        Serial.printf("[MQTT] Failed, rc=%d\n", _mqtt.state());
    }
}

void MqttManager::publish(const char* topic, JsonDocument& doc, bool retain) {
    char buffer[512];
    size_t len = serializeJson(doc, buffer, sizeof(buffer));
    _mqtt.publish(topic, buffer, retain);
}

void MqttManager::publish(const char* topic, const char* payload, bool retain) {
    _mqtt.publish(topic, payload, retain);
}

void MqttManager::subscribe(const char* topicPattern, MqttCallback callback) {
    if (_subCount >= MQTT_MAX_SUBSCRIPTIONS) return;
    _subs[_subCount].topic = topicPattern;
    _subs[_subCount].callback = callback;
    _subCount++;
    if (_mqtt.connected()) {
        _mqtt.subscribe(topicPattern, 1);
    }
}

String MqttManager::getNodeId() {
    return _nodeId;
}

String MqttManager::buildTopic(const char* suffix) {
    return "sporeprint/" + _nodeId + "/" + suffix;
}

void MqttManager::_staticCallback(char* topic, byte* payload, unsigned int length) {
    if (_instance) {
        _instance->_handleMessage(topic, payload, length);
    }
}

void MqttManager::_handleMessage(char* topic, byte* payload, unsigned int length) {
    char json[512];
    size_t copyLen = min((unsigned int)(sizeof(json) - 1), length);
    memcpy(json, payload, copyLen);
    json[copyLen] = '\0';

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, json);
    if (err) {
        Serial.printf("[MQTT] JSON parse error: %s\n", err.c_str());
        return;
    }

    for (int i = 0; i < _subCount; i++) {
        // Simple topic matching (exact match or wildcard)
        if (String(topic) == _subs[i].topic || _subs[i].topic.endsWith("#")) {
            String prefix = _subs[i].topic.substring(0, _subs[i].topic.length() - 1);
            if (_subs[i].topic.endsWith("#") && String(topic).startsWith(prefix)) {
                _subs[i].callback(topic, doc);
            } else if (String(topic) == _subs[i].topic) {
                _subs[i].callback(topic, doc);
            }
        }
    }
}
