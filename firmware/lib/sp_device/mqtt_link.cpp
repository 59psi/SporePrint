#include "mqtt_link.h"

#include "cmd_router.h"  // sp::cmd_suffix

namespace sp_device {

MqttLink* MqttLink::instance_ = nullptr;

void MqttLink::begin(const char* host, uint16_t port, const char* user,
                     const char* pass) {
    instance_ = this;
    host_ = host;
    port_ = port;
    user_ = user;
    pass_ = pass;
    mqtt_.setServer(host_.c_str(), port_);
    mqtt_.setBufferSize(kInboundCap + 128);  // inbound cap + header headroom
    mqtt_.setCallback(static_callback);
    connect_attempt();
}

void MqttLink::loop(uint32_t now_ms) {
    if (!mqtt_.connected()) {
        if (now_ms - last_attempt_ms_ > kRetryWindowMs) {
            last_attempt_ms_ = now_ms;
            connect_attempt();
        }
    }
    mqtt_.loop();
}

void MqttLink::connect_attempt() {
    std::string lwt_topic = topic("status");
    const char* lwt_payload = "{\"status\":\"offline\"}";
    const char* user_ptr = user_.empty() ? nullptr : user_.c_str();
    const char* pass_ptr = pass_.empty() ? nullptr : pass_.c_str();
    std::string client_id = "sporeprint-" + node_type_ + "-" + node_id_;

    Serial.printf("[MQTT] Connecting as '%s' (user=%s)...\n", client_id.c_str(),
                  user_ptr ? user_ptr : "<anonymous>");
    if (!mqtt_.connect(client_id.c_str(), user_ptr, pass_ptr, lwt_topic.c_str(),
                       1, true, lwt_payload)) {
        Serial.printf("[MQTT] Failed, rc=%d\n", mqtt_.state());
        return;
    }
    Serial.println("[MQTT] Connected.");
    if (ever_connected_) ++reconnects_;
    ever_connected_ = true;

    JsonDocument doc;
    doc["status"] = "online";
    doc["firmware"] = fw_version_.c_str();
    doc["type"] = node_type_.c_str();
    doc["id"] = node_id_.c_str();
    publish(topic("status").c_str(), doc, /*retain=*/true);

    mqtt_.subscribe(topic("cmd/#").c_str(), 1);
}

bool MqttLink::publish(const char* topic_name, JsonDocument& doc, bool retain) {
    if (!mqtt_.connected()) return false;
    size_t len = measureJson(doc);
    if (!mqtt_.beginPublish(topic_name, len, retain)) return false;
    // PubSubClient is a Print — the document streams straight into the
    // packet. No intermediate buffer exists to truncate.
    size_t written = serializeJson(doc, mqtt_);
    bool ok = mqtt_.endPublish() && written == len;
    if (!ok) Serial.printf("[MQTT] publish to %s failed\n", topic_name);
    return ok;
}

bool MqttLink::publish_raw(const char* topic_name, const char* payload,
                           bool retain) {
    if (!mqtt_.connected()) return false;
    return mqtt_.publish(topic_name, payload, retain);
}

void MqttLink::static_callback(char* topic, uint8_t* payload,
                               unsigned int length) {
    if (instance_) instance_->handle_message(topic, payload, length);
}

void MqttLink::handle_message(char* topic, uint8_t* payload,
                              unsigned int length) {
    if (length >= kInboundCap) {
        // Drop oversize frames explicitly — truncating produced garbled
        // JSON in v1 and the parse failure hid the real problem.
        Serial.printf("[MQTT] Dropping oversize frame on %s (%u bytes)\n", topic,
                      length);
        return;
    }
    // sporeprint/<id>/cmd/<suffix> → suffix (host-tested in test_core_channel).
    const char* suffix = sp::cmd_suffix(topic, node_id_.c_str());
    if (suffix == nullptr) return;  // not a command for this node

    char json[kInboundCap];
    memcpy(json, payload, length);
    json[length] = '\0';

    JsonDocument doc;
    // Deserialize through a const pointer: ArduinoJson's zero-copy mode
    // MUTATES a mutable char* input, which would corrupt the raw bytes the
    // HMAC verifier needs. The const view forces copy mode.
    DeserializationError err = deserializeJson(doc, (const char*)json);
    if (err) {
        Serial.printf("[MQTT] JSON parse error on %s: %s\n", topic, err.c_str());
        return;
    }
    if (cmd_fn_) cmd_fn_(suffix, json, (size_t)length, doc, cmd_ctx_);
}

}  // namespace sp_device
