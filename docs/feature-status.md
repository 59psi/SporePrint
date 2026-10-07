# Feature status

SporePrint was built from a design spec. This page lists what that spec asked
for and the code does not do yet, or does only in part, so that nobody (person
or coding agent) assumes a feature exists. What is built is documented in the
[README](../README.md), the [build guide](hardware-build-guide.md) and the
[firmware README](../firmware/README.md). When you build one of these, delete
or update its row in the same change.

**Not built**: nothing in the code does it. **Partial**: part of it ships;
the "Today" column says which part. **Not needed**: what ships makes the item
unnecessary.

## Where the spec's sections are documented now

Code comments and tests cite the spec by section ("§5c"). The spec itself is
retired; this is where each section's subject lives.

| Spec section | Now |
|---|---|
| §1 summary, §2 architecture and principles | README → Architecture, Security; [AGENTS.md](../AGENTS.md) |
| §3 Builder's Assistant | README → Hardware Builder; `server/app/builder/`; [its example hardware](#hardware-the-specs-builder-examples) |
| §4a–§4c species model, setpoints, custom profiles | [Species reference](species-reference.md) (the active species' tables stay out of public docs; those profiles are for education and research purposes only: some species may be controlled where you live, and you are responsible for following local law) |
| §5a–§5e firmware | [firmware README](../firmware/README.md), [firmware security](firmware-security.md), [drivers](../firmware/docs/drivers.md); the node wire contract (channels, scenes, `cmd/*` payloads, reserved GPIOs) is `_HARDWARE_CONTRACT` in `server/app/builder/service.py`, checked by `server/tests/test_cross_cluster_builder.py` |
| §6 automation rules engine | [Automation rules](automation-rules.md) |
| §6 telemetry, sessions, vision, notifications | README → Features, API Reference, MQTT Topics |
| §7 transcript export, §8 UI, §9 deployment | README → Features, UI Pages, Quick Start, Configuration |
| §10 build order | Done, except the rows below |
| §11 directory structure, §12 code conventions | README → Project Structure; [AGENTS.md](../AGENTS.md) |

## Firmware

| Spec item | Status | Today |
|---|---|---|
| Node publishes at MQTT QoS 1 | Partial | PubSubClient publishes at QoS 0. The LWT and the `cmd/#` subscription are QoS 1 |
| Offline telemetry buffer that survives a reboot | Partial | A 16 KB RAM FIFO (`sp_core/telemetry_buffer.h`), flushed on reconnect with `"replay": true` and lost on reboot |
| OTA through an HTTP push endpoint on the node | Not built | The Pi pushes over espota on port 3232 (`sp_device/ota_service.cpp`) |
| Physical override buttons with LEDs on the relay node | Not built | Overrides are set from the dashboard or `POST /api/automation/overrides` |
| `ramp_sec` fades on relay channels | Not built | Only the lighting (dim) channels ramp |
| 24 h lighting schedules stored on the node (NVS), replaced over MQTT | Not built | Photoperiods run on the Pi: the Photoperiod rules follow the profile's light hours in the Pi's `TZ`. The node keeps scenes and levels only |
| Camera MJPEG stream on `:81/stream` | Not built | Stills only: a UXGA frame every 15 min and on demand |
| On-demand high-resolution capture | Not needed | Every still is already full resolution (UXGA; VGA on a board without PSRAM) |

## Server

| Spec item | Status | Today |
|---|---|---|
| Local CNN first pass (TFLite MobileNetV2, SSIM frame differencing, escalation to Claude) | Not built | `vision/service.py` `analyze_frame_local()` is a stub. Claude auto-analysis is the only automatic contamination detector. No model runtime is installed; it is added to `server/pyproject.toml` with the code that loads it |
| Claude vision context: previous frame, telemetry snapshot, session timeline | Not built | Claude gets the current frame, the species and session context and the camera sensor |
| Active-learning retraining | Partial | Labels are stored (`POST /api/vision/frames/{id}/label`); nothing trains on them. `models/` holds only the enclosures |
| Vision metrics per species: etiolation alert (oysters), coral-growth alert (lion's mane), orange saturation (cordyceps), colour banding (turkey tail) | Not built | Claude's morphology notes and recommendations. Shiitake browning is tracked (`browning_percent`) |
| Temperature-swing scheduler driven by `temp_swing_delta_f` | Not built | The fixed Lion's Mane Night Cool rule ([species reference](species-reference.md#lions-mane-hericium-erinaceus)) |
| Session status `paused` | Not built | `active`, `completed` or `aborted` |
| INFO notifications batched hourly, with a daily summary | Not built | Each INFO message (same title or dedup key) is sent at most once an hour; there is no summary |
| Transcript JSON: per-sensor standard deviation and time out of range, hardware health | Not built | Min / max / avg / count per sensor per phase |
| Transcript markdown: inline sparkline SVGs and a recommendations section | Not built | Recommendations come from the Claude analysis (`POST /api/transcript/sessions/{id}/analyze`) |
| Builder guide generator with SVG wiring diagrams | Partial | `POST /api/builder/guide` writes a markdown guide with ASCII wiring and saves it (`GET /api/builder/guides`) |

## Dashboard

The dashboard source is in the private monorepo (`frontend/packages/pi-ui`);
this repo ships the build in `ui/dist`.

| Spec item | Status | Today |
|---|---|---|
| Live updates over Socket.IO | Not built | Pages load over REST and the Chambers page polls system metrics every 15 s. The server's Socket.IO events are there for other clients |
| Installable PWA | Not built | |
| Swipe between sessions on a phone | Not built | Phone drawer navigation and stacked layouts |
| Live camera view | Not built | Needs the MJPEG stream (Firmware) |
| Vision page: confirm or correct each Claude read | Partial | A manual contamination mark labels the camera's latest frame as an active-learning correction; there is no per-frame confirm |
| Automation rule editor | Not built | Rules list, enable toggles, overrides and firing history; rules are created and edited through `/api/automation/rules` |
| Species profile editor, from-scratch profile form, JSON import / export buttons | Not built | Through the API ([custom profiles](species-reference.md#custom-profiles)) |
| Session comparison | Partial | A/B experiments compare paired sessions; `GET /api/chambers/compare` is API only |
| Builder chat for the guide generator, with saved guides | Not built | The Builder page shows the hardware tiers; the generator is API only |

## Deployment

| Spec item | Status | Today |
|---|---|---|
| TLS on the web UI and API (self-signed) | Not built | HTTP on 3001 and 8000; only the broker has TLS (8883) |
| Nightly backup cron (SQLite `.backup` plus vision frames to USB or a NAS) | Not built | Back up by hand: README → Quick Start → Backups |

## Hardware (the spec's Builder examples)

The spec gave these as requests the Builder guide generator should handle.
The All the Things tier now ships the HX711 scale, the door reed switch, the
450 / 660 / 730 nm light channels and a second camera.

| Spec item | Status | Today |
|---|---|---|
| Peristaltic pump for substrate hydration between flushes | Partial | The All the Things pump sits on the relay `aux` channel; only the Mist (no humidifier) rule drives it, for humidity |
| Door reed switch pauses humidity while the closet is open | Partial | `door_open` is in telemetry and raises alert events; no built-in rule reads it |
| Peltier with an H-bridge for heating and cooling | Not built | The Peltier cooler is on a smart plug and only cools; heating is a separate heater plug |
| CO₂ injection solenoid from a compressed-CO₂ tank | Not built | |
| VOC / particulate sensor to smell contamination | Not built | |
| Motorized intake and exhaust dampers for FAE | Not built | FAE is fan PWM |
