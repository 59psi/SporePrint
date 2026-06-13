#pragma once
//
// mqtt_link — PubSubClient wrapper for the v2 node.
//
// The publish path STREAMS: beginPublish(topic, measureJson(doc), retain)
// then serializeJson(doc, client) — PubSubClient is a Print subclass, so
// the document serializes straight into the MQTT packet. There is no
// intermediate buffer to mis-size, which retires v1's defect class where a
// 512-byte serialize buffer silently truncated every log batch and
// coredump chunk into unparseable JSON.
//
// Inbound stays at a 1024-byte cap with an explicit oversize drop (logged,
// never truncated). Reconnect is non-blocking-ish: one connect attempt per
// 5 s window (PubSubClient's socket timeout bounds the attempt; the WDT
// budget accounts for it). LWT publishes a retained offline status; the
// connect callback re-publishes retained online status and re-subscribes.
//
// The transport Client* is injected so phase 6 can swap a WiFiClientSecure
// (TLS with pinned CA) in without touching this class.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>

#include <string>

namespace sp_device {

class MqttLink {
public:
    // `raw`/`raw_len` are the exact wire bytes — HMAC verification MUST run
    // on those, never on a re-serialized document (number/string lexeme
    // fidelity is what makes the canonicalizer byte-exact).
    using MessageFn = void (*)(const char* topic_suffix, const char* raw,
                               size_t raw_len, JsonDocument& doc, void* ctx);

    MqttLink(Client& transport, const char* node_id, const char* node_type,
             const char* fw_version)
        : mqtt_(transport),
          node_id_(node_id),
          node_type_(node_type),
          fw_version_(fw_version) {}

    void begin(const char* host, uint16_t port, const char* user,
               const char* pass);

    // Pump: reconnect window + PubSubClient loop. Call every loop pass.
    void loop(uint32_t now_ms);

    bool connected() { return mqtt_.connected(); }
    uint32_t reconnect_count() const { return reconnects_; }

    // Streamed publish. Returns false when disconnected or the write fails.
    bool publish(const char* topic, JsonDocument& doc, bool retain = false);
    bool publish_raw(const char* topic, const char* payload, bool retain = false);

    // Subscribe to sporeprint/<id>/cmd/# and route messages to `fn` with
    // the suffix after "cmd/".
    void on_command(MessageFn fn, void* ctx) {
        cmd_fn_ = fn;
        cmd_ctx_ = ctx;
    }

    std::string topic(const char* suffix) const {
        std::string t = "sporeprint/";
        t += node_id_;
        t += "/";
        t += suffix;
        return t;
    }

private:
    void connect_attempt();
    void handle_message(char* topic, uint8_t* payload, unsigned int length);
    static void static_callback(char* topic, uint8_t* payload,
                                unsigned int length);

    PubSubClient mqtt_;
    std::string node_id_;
    std::string node_type_;
    std::string fw_version_;
    std::string host_;
    uint16_t port_ = 1883;
    std::string user_;
    std::string pass_;
    uint32_t last_attempt_ms_ = 0;
    uint32_t reconnects_ = 0;
    bool ever_connected_ = false;
    MessageFn cmd_fn_ = nullptr;
    void* cmd_ctx_ = nullptr;

    static MqttLink* instance_;  // one link per node image
    static constexpr uint32_t kRetryWindowMs = 5000;
    static constexpr size_t kInboundCap = 1024;
};

}  // namespace sp_device
