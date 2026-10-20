#include "mqtt_link.h"

#include <WiFi.h>

#include "chunked_writer.h"  // chunked publish
#include "cmd_router.h"      // sp::cmd_suffix
#include "link_budget.h"     // connect-attempt time budget vs the loop WDT
#include "log_forward.h"     // SP_LOG

namespace sp_device {

MqttLink* MqttLink::instance_ = nullptr;

namespace {
// Same bytes as the connect()-time LWT.
const char kOfflineStatus[] = "{\"status\":\"offline\"}";
}  // namespace

void MqttLink::begin(const char* host, uint16_t port, const char* user,
                     const char* pass, bool connect_now) {
    instance_ = this;
    host_ = host;
    port_ = port;
    user_ = user;
    pass_ = pass;
    mqtt_.setServer(host_.c_str(), port_);
    mqtt_.setBufferSize(kInboundCap + 128);  // inbound cap + header headroom
    // CONNACK wait (default 15 s) — part of the link_budget.h attempt budget.
    mqtt_.setSocketTimeout((uint16_t)sp::kMqttSocketTimeoutS);
    mqtt_.setCallback(static_callback);
    if (connect_now) connect_attempt();
    last_attempt_ms_ = millis();
}

void MqttLink::switch_transport(Client& transport, uint16_t port) {
    if (mqtt_.connected()) {
        publish_raw(topic("status").c_str(), kOfflineStatus, /*retain=*/true);
        mqtt_.disconnect();
    }
    mqtt_.setClient(transport);
    transport_ = &transport;
    port_ = port;
    mqtt_.setServer(host_.c_str(), port_);
    // Eligible for a connect attempt on the next allowed pass.
    last_attempt_ms_ = millis() - kRetryWindowMs - 1;
}

void MqttLink::loop(uint32_t now_ms, bool may_connect) {
    if (!mqtt_.connected() && may_connect) {
        if (now_ms - last_attempt_ms_ > kRetryWindowMs) {
            connect_attempt();
            // Stamp the END of the attempt: a failed one can block for
            // seconds (DNS / TCP / TLS timeouts), and stamping its start let
            // the next pass launch another at once — loop() spent nearly all
            // its time blocked while the broker was unreachable. Callers pass
            // a `now` taken at the top of the following pass, so it is never
            // earlier than this stamp.
            last_attempt_ms_ = millis();
        }
    }
    mqtt_.loop();
}

void MqttLink::connect_attempt() {
    // No STA link: a connect would only burn the DNS timeout inside loop().
    // WiFi recovery is the composition root's job (node: link watchdog).
    if (WiFi.status() != WL_CONNECTED) return;

    std::string lwt_topic = topic("status");
    const char* lwt_payload = kOfflineStatus;
    const char* user_ptr = user_.empty() ? nullptr : user_.c_str();
    const char* pass_ptr = pass_.empty() ? nullptr : pass_.c_str();
    std::string client_id = "sporeprint-" + node_type_ + "-" + node_id_;

    Serial.printf("[MQTT] Connecting as '%s' (user=%s)...\n", client_id.c_str(),
                  user_ptr ? user_ptr : "<anonymous>");
    ++attempts_;
    if (!mqtt_.connect(client_id.c_str(), user_ptr, pass_ptr, lwt_topic.c_str(),
                       1, true, lwt_payload)) {
        Serial.printf("[MQTT] Failed, rc=%d\n", mqtt_.state());
        return;
    }
    Serial.println("[MQTT] Connected.");
    ++successes_;
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
    const size_t len = measureJson(doc);
    if (!mqtt_.beginPublish(topic_name, len, retain)) return false;
    // The document streams into the packet in 256-byte transport writes —
    // ArduinoJson's per-character writes went out one TLS record, one TCP
    // segment (or, on a stalled socket, one 10 s write retry loop) each.
    sp::ChunkedWriter<PubSubClient> out(mqtt_);
    serializeJson(doc, out);
    if (!out.flush() || out.written() != len) {
        // The packet on the wire is incomplete: the stream is desynced, and
        // a stalled socket would block every further write. Drop the
        // connection at once (no DISCONNECT packet — that is one more write
        // into the same socket); the next allowed pass reconnects. Serial
        // only: a forwarded log line would be published in turn.
        Serial.printf("[MQTT] publish to %s failed (%u of %u bytes) - "
                      "dropping the connection\n",
                      topic_name, (unsigned)out.written(), (unsigned)len);
        transport_->stop();
        return false;
    }
    return mqtt_.endPublish();
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
        // JSON in v1 and the parse failure hid the real problem. Logged
        // through SP_LOG so the drop reaches the Pi's node log, not just the
        // serial console.
        SP_LOG(LOG_WARN, "[MQTT] Dropping oversize frame on %s (%u bytes, "
                         "cap %u)",
               topic, length, (unsigned)kInboundCap);
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
        SP_LOG(LOG_WARN, "[MQTT] JSON parse error on %s: %s", topic, err.c_str());
        return;
    }
    if (cmd_fn_) cmd_fn_(suffix, json, (size_t)length, doc, cmd_ctx_);
}

}  // namespace sp_device
