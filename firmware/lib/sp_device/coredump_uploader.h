#pragma once
//
// coredump_uploader — drains a panic dump from the `coredump` flash partition
// to the Pi, and erases it only once the Pi has acknowledged storing it.
//
// begin() (setup, no network I/O) finds the dump and hashes it: the id is
// the lowercase hex SHA-256 of the dump bytes. loop() then streams it to
// sporeprint/<id>/coredump/chunk as {seq,total,size,b64_data,coredump_id}
// (512 raw bytes per chunk, a few chunks per pass, only while MQTT is up) —
// it never blocks the loop or delays boot. The Pi answers on
// cmd/coredump_ack {"coredump_id"} after the dump is safely on its disk;
// on_ack() (handed the frame after the caller's HMAC verification) erases
// the partition when the id matches the dump held. No ack → bounded retries,
// then the dump is kept in flash. Policy and protocol: sp_core/
// coredump_drain.h (host-tested in test_core_coredump).
//
// A Pi too old to acknowledge stores each upload as a new file and never
// acks: the node then uploads a dump at most 3 times per boot and 6 times in
// all (counted in NVS by id), and keeps it in flash until the next panic
// overwrites it. (The v2 uploader before this erased the partition as soon as
// the last QoS 0 chunk left the node.)

#include <ArduinoJson.h>

#include <stdint.h>

#include "kv_store.h"
#include "mqtt_link.h"

namespace sp_device {
namespace coredump {

// Find + hash the dump and load its NVS upload count. Call once in setup()
// after the MQTT link is constructed.
void begin(MqttLink& link, sp::KvStore& kv);

// Every loop pass. `ack_verifiable`: an ack would pass command verification
// now (no signing key provisioned, or the clock is NTP-synced).
void loop(uint32_t now_ms, bool ack_verifiable);

// An authenticated cmd/coredump_ack frame.
void on_ack(JsonDocument& doc);

// A dump is in flash and not yet acknowledged.
bool pending();

}  // namespace coredump
}  // namespace sp_device
