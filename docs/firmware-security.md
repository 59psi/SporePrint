# Firmware security — command signing, TLS, provisioning, OTA

The v2 security model for the unified node image (`node_esp32` /
`node_esp32s3` / `node_esp32s3_n32r16v`) and the camera image (`cam`).

## Threat model

LAN-resident attacker: anything that can reach the Pi's MQTT broker or
sniff WiFi. The Pi is the trust root; the cloud reaches nodes only through
the Pi's signed-command relay. Physical access is out of scope: secure boot
and flash encryption are **not supported** by this build (see below).

| Attacker capability | Defense |
|---|---|
| Publish actuator commands with broker access | **HMAC-SHA256 signed frames** — canonical-JSON signature + ±30 s window; key provisioned via the captive portal (no compile-time path) |
| Replay a captured command | The ±30 s `ts` window, plus a **replay guard**: a second delivery of the same signed frame on the same topic inside the window is rejected. A keyed node rejects commands entirely until NTP has synced (point NTP at the Pi for airgapped rooms) |
| Redirect a captured command to another channel or node | **Topic binding**: the Pi signs the full `sporeprint/<node>/cmd/<suffix>` topic into every frame, and the node rejects a frame whose signed `topic` differs from the topic it arrived on |
| Impersonate the broker / rogue AP | **Opt-in TLS (8883)** with the Pi's CA pinned trust-on-first-use, and only after a TLS connection with it succeeds; a missing CA is never silent, and the heartbeat's `ca_fp` shows which CA a node trusts (see Secure MQTT) |
| Redirect camera uploads to an attacker host | `server_url` allow-list — RFC1918 applies to genuine IPv4 literals only ("10.attacker.com" is rejected); `https://` uploads require the pinned Pi CA |
| Brute-force the OTA password over LAN | 12-char minimum, no default — OTA stays disabled until provisioned |
| Flash arbitrary firmware once the OTA password is known | **Not defended** — secure boot is not available in the Arduino build |
| Extract credentials from a stolen node | **Not defended** — flash encryption is not available in the Arduino build |

## Signed commands

Every `sporeprint/<node>/cmd/*` frame the Pi publishes is signed with
`SPOREPRINT_MQTT_HMAC_KEY` (`install.sh` generates it; `./scripts/provision-node.sh`
prints it, `--rotate` replaces it). The signature covers every JSON member except
`signature` itself, in canonical form. Besides the command, the Pi adds:

- `ts` — epoch seconds; the node accepts ±30 s.
- `topic` — the full topic the frame is published on. Current firmware rejects
  a frame whose signed `topic` differs from its arrival topic.
- `nonce` — 16 hex characters (64 random bits), so two legitimate identical
  commands in the same second (on/off/on) are distinct frames and not mistaken
  for a replay.

The node's replay guard remembers each accepted (topic, MAC) pair — 32 slots,
kept for twice the window — and rejects a second delivery (`replayed frame` in
its log). Rejected frames are never remembered.

Compatibility: every firmware canonicalizes all members, so firmware that
predates topic binding verifies these frames unchanged and simply ignores
`topic` and `nonce`. A frame that would reach the node's 1024-byte inbound cap
is sent signed but without the binding, and the Pi logs a WARNING. The
canonical form is pinned by shared golden vectors
(`server/tests/fixtures/signing_vectors.json`, byte-identical copy under
`firmware/test/fixtures/`) asserted by the firmware's native suite, the Pi's
pytest suite, and CI fixture-parity checks. Any other signer of node-bound
frames (for example a private-cloud relay) should add the same members.

Migration posture:
- A node with **no** signing key accepts commands but logs
  `[SEC] hmac_key not provisioned — accepting unsigned cmd/...` on every one —
  an unprovisioned fleet is loud, never silent. It accepts signed frames too.
- A node **with** the key (portal field "Command signing key") rejects
  unsigned, forged, stale, replayed and redirected frames.
- On the Pi, `SPOREPRINT_MQTT_REQUIRE_SIGNING` decides what happens when it has
  **no** key: `auto` (default) refuses to publish unsigned commands once the
  Pi is cloud-paired, `always` always refuses, `never` sends them unsigned.
  A refused publish makes the node-command endpoint return 503.

## Secure MQTT (TLS)

Ticking **Secure MQTT** in the portal makes the node fetch the Pi's CA from
`GET /api/provision/ca` (public even when `SPOREPRINT_API_KEY` is set) and
connect on 8883 with it. **It verifies before it pins:** the fetched CA is
only a candidate, held in RAM, until a TLS connection with it gets the
broker's CONNACK. Only then is it written to NVS (`broker_ca`, then the
verified marker `broker_ca_ok`), and from then on the pin is final — a later
failure never downgrades a verified node, so an impostor broker cannot force
plaintext. A failed trial persists nothing: the node goes back to plaintext
(or stays off MQTT with **Require TLS**), backs off, and tries again. A CA an
older image pinned without this check has no marker and gets the same trial.
Re-pinning a verified CA takes a factory reset. Verification follows the
broker host name:

- Use `sporeprint.local` (recommended) or an IP the Pi's certificate lists.
  `install.sh` puts every Pi IPv4 into the certificate as both an `IP:` and a
  `DNS:` SAN, because mbedTLS 2.28 on the ESP32 only matches DNS-type entries.
  When the Pi's IP changes, re-running `install.sh` re-issues the server
  certificate from the **same** CA, so pinned nodes are unaffected.

With Secure MQTT ticked and **no** verified CA pinned yet (the Pi was
unreachable during provisioning, or the trial failed), the node:
- by default falls back to plaintext **loudly**: an ERROR log line, a node
  alert of type `tls_downgrade` (value = the plaintext port, sent on entry,
  then hourly, and at once when the reason changes; the message names the
  reason: no CA yet, certificate name mismatch or another CA, nothing on
  8883, TLS error, login refused), `tls:false` and `tls_fallback:true` in its
  heartbeat, and fetch-and-try retries after 1, 2, 4 and 8 min, then every
  15 min. A verified trial moves the running link to TLS with no reboot;
- with **Require TLS** ticked (NVS `tls_req`), stays **off MQTT** instead —
  the 10-minute safe mode switches its channels off — while it keeps retrying.

It never connects with TLS but no verification. Every heartbeat carries `tls`
and `board`, so you can see which transport and image each node really runs,
and a TLS node also sends `ca_fp`: the lowercase hex SHA-256 of the CA PEM it
uses, to compare with the Pi's own `ca.crt`
(`sha256sum config/mosquitto/certs/ca.crt`). A node that pinned another CA
(a LAN impostor answered its trust-on-first-use fetch) shows a different
`ca_fp`.

## Provisioning and physical gestures

- Credentials, the node id, the signing key and the OTA password are entered
  only in the `SporePrint-Setup` captive portal and stored in NVS. The node id
  must equal the MQTT username (the broker ACL scopes each node by it).
- A provisioned node whose settings have connected before no longer reopens
  the open setup AP when WiFi fails: it boots offline and retries every 60 s.
- Opening the portal on purpose is physical: hold BOOT (node) or short GPIO 13
  to GND (camera — there is no button on that pin) for 3–10 s, then release.
  More than 10 s factory-resets. While the button is held, the device starts
  no MQTT connect, CA fetch or capture.

## Failure containment

- Channel outputs are forced OFF at the top of boot, before Serial, and again
  when an OTA starts.
- The watchdog arms only after provisioning (the setup portal can never be
  killed by it).
- Switch channels carry a max-on backstop an explicit duration cannot exceed:
  30 min on `fae` / `exhaust` / `circulation`, **60 s on `aux`** (its pump
  duty); lighting channels have none. `cmd/config {"max_on_sec": {"<channel>":
  N}}` changes it per channel and persists it in NVS.
- An explicit `"state":"off"` always wins over `pwm`/`level` in the same
  command, and never leaves a timer armed. (The Pi also strips `pwm`/`level`
  from every OFF it sends, because older firmware treated
  `{"state":"off","pwm":N}` as ON.)
- 10 minutes without MQTT → every channel off (safe mode); the node never
  reboots itself for link loss.
- Empty command payloads are rejected, never defaulted to ON.
- Panic coredumps persist in flash and upload to the Pi on the next boot.

## OTA

- **Password:** `lib/sp_device/ota_service.cpp` refuses to start ArduinoOTA
  when the NVS password is empty or shorter than 12 characters.
- **Events:** start / success / error land on `sporeprint/<node>/ota`, so a
  half-applied OTA is visible even without secure boot.
- **Rollback:** a freshly flashed OTA image is on probation until MQTT has been
  connected continuously for 60 s. A crash, watchdog reset or power loss
  before then boots the previous image. An operator restart confirms the new
  image only if it reached MQTT during that boot. Rollback needs a bootloader
  built with rollback support, which is this framework's default.
- **Integrity:** ArduinoOTA and the Pi's OTA push check the image MD5. There is
  no signature check on node images (see below).

## Secure boot v2 + flash encryption — not supported

Earlier versions of this page described enabling secure boot and flash
encryption with `-DCONFIG_SECURE_*` build flags. **That recipe does not work
and must not be followed:**

- The firmware builds with `framework = arduino` (the `[esp32_base]` section
  of `firmware/platformio.ini`). The Arduino-ESP32 core ships its ESP-IDF
  libraries **and its bootloader precompiled**, from an `sdkconfig` in which
  `CONFIG_SECURE_BOOT` and `CONFIG_SECURE_FLASH_ENC_ENABLED` are not set.
  `-D` build flags cannot change a precompiled bootloader or library, so
  nothing gets enabled and no eFuse is burned — while the node looks
  "secured".
- `signedupload` is not a PlatformIO target.
- The OTA code referenced there (`OTAManager`, `ota_manager.cpp`) is the v1
  firmware; v2 uses `lib/sp_device/ota_service.cpp`.

Supporting it would mean a different build: Arduino as an ESP-IDF component
(`framework = arduino, espidf`) with an `sdkconfig.defaults` that enables
`CONFIG_SECURE_BOOT_V2_ENABLED` and `CONFIG_SECURE_FLASH_ENC_ENABLED`, OTA
images signed with `espsecure.py sign_data --version 2`, a partition table
with room for the signature, and an OTA path that verifies it. Enabling these
**irrevocably** burns eFuses, and a mistake bricks the board. None of this is
implemented or tested in this repo; don't improvise it on a production node.

## v4 cloud-side OTA pubkey landing zone

The cloud added a `PUT /settings/ota-pubkey` endpoint in v4. It lets an
operator register the public half of an image-signing key with the cloud, so
the cloud-web admin surface can verify OTA payloads end-to-end before
publishing them. The private key never leaves the operator's machine — only
the public verifier ships. The endpoint persists into the operator's
`profiles` row and is read by the cloud's `ota_push` before signing the delta.
If no pubkey is registered, the cloud falls back to the per-device HMAC-only
flow. Because the node firmware itself cannot verify image signatures (see
above), this protects the cloud → Pi hop, not the Pi → node flash.

This is independent of web-push (browser) VAPID keys, which sign
cloud-→-browser notifications and have nothing to do with firmware. The
two key systems are namespaced separately (`CLOUD_VAPID_*` vs
per-user `ota_pubkey`).

## What's still open

- A secure-boot / flash-encryption build (the ESP-IDF component route above)
  and signed node OTA images.
- Per-node HMAC keys (currently a single shared key across all nodes
  paired to one Pi).
- Erasing a node's coredump only after the Pi acknowledges it (the Pi-side ack
  is not implemented yet).
