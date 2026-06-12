#pragma once
//
// coredump_uploader — boot-time panic-dump drain. If the previous run left
// an ELF dump in the `coredump` flash partition, read it in 512-byte
// chunks, base64-encode, publish to sporeprint/<id>/coredump/chunk as
// {seq,total,size,b64_data}, and erase ONLY after every chunk published —
// a mid-stream broker hiccup leaves the partition intact for retry next
// boot. v2 publishes through the streamed path so the ~744-byte chunk
// payloads actually arrive parseable (v1 truncated every one at 512).

#include "mqtt_link.h"

namespace sp_device {
namespace coredump {

// Returns true when there was no dump, or the dump fully uploaded+erased.
bool upload_if_present(MqttLink& link);

}  // namespace coredump
}  // namespace sp_device
