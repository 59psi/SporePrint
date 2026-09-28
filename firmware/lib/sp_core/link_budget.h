#pragma once
//
// link_budget — the time budget of one synchronous MQTT connect attempt.
//
// MqttLink::connect_attempt() runs inside loop(), right after the single
// task-WDT pet, and blocks for DNS + TCP connect + (TLS handshake) + the
// CONNACK wait. With the arduino-esp32 2.x defaults that was up to
// 15 + 30 + 120 + 15 s against a 30 s panic WDT (fw-node#8): with Secure
// MQTT on and the Pi powered off, the node panic-rebooted about once a
// minute, rewriting the coredump sector every time.
//
// The transport timeouts below are applied in tls_transport.h
// (WiFiClientSecure::setTimeout / setHandshakeTimeout, both in SECONDS on
// core 2.x) and mqtt_link.cpp (PubSubClient::setSocketTimeout). DNS is not
// configurable: hostByName waits up to 15 s (lwIP gives up at ~14 s), so the
// other three are sized to fit beside it.
//
// Native-safe: no Arduino headers.

#include <stdint.h>

namespace sp {

constexpr uint32_t kLoopWdtTimeoutS = 30;  // esp_task_wdt_init in the node
constexpr uint32_t kLoopWdtMarginS = 3;    // rest of the loop pass + slack

constexpr uint32_t kDnsWorstCaseS = 15;        // WiFiGeneric::hostByName
constexpr uint32_t kTcpConnectTimeoutS = 3;    // plain + TLS (core plain default)
constexpr uint32_t kTlsHandshakeTimeoutS = 6;  // ECDHE on an ESP32 ≈ 1-2 s
constexpr uint32_t kMqttSocketTimeoutS = 3;    // PubSubClient CONNACK / reads

constexpr uint32_t kConnectAttemptWorstCaseS =
    kDnsWorstCaseS + kTcpConnectTimeoutS + kTlsHandshakeTimeoutS +
    kMqttSocketTimeoutS;

static_assert(kConnectAttemptWorstCaseS + kLoopWdtMarginS <= kLoopWdtTimeoutS,
              "one MQTT connect attempt must fit inside the loop task WDT");

// Runtime Pi-CA fetch (tls_policy.h, fw-node#2): Secure MQTT is on but no CA
// is pinned, so the node retries GET http://<pi>:8000/api/provision/ca from
// loop() on a backoff. One fetch blocks its pass for DNS + TCP connect + the
// HTTP read. (The boot-time fetch runs pre-WDT and keeps longer timeouts.)
// A fetch and an MQTT connect attempt together would NOT fit, so the
// composition roots never start a connect attempt in a pass that fetched
// (sp::mqtt_may_connect).
constexpr uint32_t kCaFetchConnectTimeoutS = 3;
constexpr uint32_t kCaFetchReadTimeoutS = 5;
constexpr uint32_t kCaFetchWorstCaseS =
    kDnsWorstCaseS + kCaFetchConnectTimeoutS + kCaFetchReadTimeoutS;

static_assert(kCaFetchWorstCaseS + kLoopWdtMarginS <= kLoopWdtTimeoutS,
              "one runtime CA fetch must fit inside the loop task WDT");

}  // namespace sp
