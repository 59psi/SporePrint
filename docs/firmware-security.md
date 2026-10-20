# Firmware security — command signing, TLS, provisioning, OTA

The v2 security model for the unified node image (`node_esp32` /
`node_esp32s3` / `node_esp32s3_n32r16v`) and the camera image (`cam`, and
its ESP32-S3 builds `cam_esp32s3` / `cam_xiao_esp32s3` / `cam_waveshare_s3`).

## Threat model

LAN-resident attacker: anything that can reach the Pi's MQTT broker or
sniff WiFi. The Pi is the trust root; the cloud reaches nodes only through
the Pi's signed-command relay. Physical access is out of scope: secure boot
and flash encryption are **not supported** by this build (see below).

| Attacker capability | Defense |
|---|---|
| Publish actuator commands with broker access | **HMAC-SHA256 signed frames** — canonical-JSON signature + ±30 s window; key provisioned via the captive portal (no compile-time path) |
| Replay a captured command | The ±30 s `ts` window, plus a **replay guard**: a second delivery of the same signed frame on the same topic inside the window is rejected. A keyed node rejects commands entirely until NTP has synced (point NTP at the Pi for airgapped rooms: `install.sh` sets chrony on the Pi to answer NTP from the LAN, from its own clock when it has no upstream) |
| Redirect a captured command to another channel or node | **Topic binding**: the Pi signs the full `sporeprint/<node>/cmd/<suffix>` topic into every frame, and the node rejects a frame whose signed `topic` differs from the topic it arrived on |
| Impersonate the broker / rogue AP | **Opt-in TLS (8883)** with the Pi's CA pinned trust-on-first-use, and only after a TLS connection with it succeeds; a missing CA is never silent, and the heartbeat's `ca_fp` shows which CA a node trusts (see Secure MQTT) |
| Redirect camera uploads to an attacker host | `server_url` allow-list — RFC1918 applies to genuine IPv4 literals only ("10.attacker.com" is rejected); `https://` uploads require the pinned Pi CA. An empty `server_url` only resets uploads to the Pi address typed in the setup portal |
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

### Rotating the key

`./scripts/provision-node.sh --rotate` writes a new key to `.env` and lists
the steps: re-key every node in its setup portal first, then apply the key
to the Pi server (`docker compose up -d server`; on a bare-metal install,
restart the service). A portal save that changes the key keeps the key it
replaces (NVS `hmac_key_prev`): a frame the new key does not verify is
checked again with the old one, through the same ±30 s window, topic
binding and replay guard, and the node logs `[SEC] cmd/... verified with
the PREVIOUS signing key` for it. The Pi signs with the old key until it
restarts with the new one, so it reaches every node throughout. The first
command the new key verifies retires the old key for good (`previous key
retired` in the node's log). A keyed node never accepts an unsigned frame,
during a rotation or not.

- A node keeps one previous key. Re-keyed again before the Pi has switched
  (a second `--rotate`), it drops the key the Pi still signs with and
  rejects the Pi's commands until the Pi switches. To print the key again,
  run the script without `--rotate`.
- A node keeps the old key until the Pi next commands it. To retire it at
  once on a node the Pi seldom commands (a climate node, a camera), send
  that node an empty command, which neither image acts on:

  ```bash
  curl -s -X POST http://<pi-ip>:3001/api/hardware/nodes/<node_id>/command \
    -H 'Content-Type: application/json' -d '{}'
  ```

  (with `-H 'Authorization: Bearer <your SPOREPRINT_API_KEY>'` in API-key
  mode).
- Firmware that predates this grace holds one key: it rejects every command
  (`signature mismatch`) between its re-key and the Pi's switch. Update it
  first, or re-key it last, right before applying the key to the Pi.

## Secure MQTT (TLS)

Ticking **Secure MQTT** in the portal makes the node fetch the Pi's CA from
`GET /api/provision/ca` (public even when `SPOREPRINT_API_KEY` is set) and
connect on 8883 with it. The fetch reads the whole HTTP response under one
deadline into a bounded buffer: a 200 without a `Content-Length` (the Pi
always sends one), or with one over 4000 bytes, is refused before its body is
read, so whatever answers on port 8000 cannot stall the node or fill its
memory. **It verifies before it pins:** the fetched CA is
only a candidate, held in RAM, until a TLS connection with it gets the
broker's CONNACK. Only then is it written to NVS (`broker_ca`, then the
verified marker `broker_ca_ok`, set only once the stored CA reads back as the
one that verified — a failed NVS write leaves no marker, and the next boot
tries again), and from then on the pin is final — a later
failure never downgrades a verified node, so an impostor broker cannot force
plaintext. A failed trial persists nothing: the node goes back to plaintext
(or stays off MQTT with **Require TLS**), backs off, and tries again. A CA an
older image pinned without this check has no marker and gets the same trial.
Re-pinning a verified CA takes a factory reset. Verification follows the
broker host name:

- Use `sporeprint.local` (recommended) or an IP the Pi's certificate lists.
  `install.sh` puts every Pi IPv4 into the certificate as both an `IP:` and a
  `DNS:` SAN: mbedTLS 2.28 in core-2.x images only matches DNS-type entries,
  while mbedTLS 3.6 in current (core 3.x) images also checks the IP entries.
  When the Pi's IP changes, re-running `install.sh` re-issues the server
  certificate from the **same** CA, so pinned nodes are unaffected. It does
  the same when the certificate is missing or expires within 30 days (it
  runs for five years). It never replaces the CA while `ca.crt` exists:
  only deleting `config/mosquitto/certs` starts a new one, and every node
  that pinned the old CA then needs a factory reset.

With Secure MQTT ticked and **no** verified CA pinned yet (the Pi was
unreachable during provisioning, or the trial failed), the node:
- by default falls back to plaintext **loudly**: an ERROR log line, a node
  alert of type `tls_downgrade` (value = the plaintext port, sent on entry,
  then hourly, and at once when the reason changes; the message names the
  reason: no CA yet, certificate name mismatch or another CA, nothing on
  8883, TLS error, login refused), `tls:false` and `tls_fallback:true` in its
  heartbeat, and fetch-and-check retries after 1, 2, 4 and 8 min, then every
  15 min. Each fetched CA is first checked with a bare TLS handshake to 8883
  while MQTT stays up on plaintext, so a certificate that does not verify
  never takes the node off MQTT; only a CA whose handshake verifies moves the
  running link to TLS, with no reboot, and is pinned once the broker accepts
  the login (a login refused on 8883 is retried hourly, as each try drops
  the plaintext link for a moment);
- with **Require TLS** ticked (NVS `tls_req`), stays **off MQTT** instead —
  the 10-minute safe mode switches its channels off — while it keeps retrying.

It never connects with TLS but no verification. Every heartbeat carries `tls`
and `board`, so you can see which transport and image each node really runs,
and a TLS node also sends `ca_fp`: the lowercase hex SHA-256 of the CA PEM it
uses. The Pi stores them with the node (`GET /api/hardware/nodes`: `tls`,
`tls_fallback`, `board`, `ca_fp`) and compares `ca_fp` with the CA it serves
(`sha256sum config/mosquitto/certs/ca.crt`): `ca_fp_match` is 1 when they
agree and 0 when not, and a mismatch is logged as a `[SEC]` warning. A node
that pinned another CA (a LAN impostor answered its trust-on-first-use
fetch) shows a different `ca_fp`.

## Provisioning and physical gestures

- Credentials, the node id, the signing key and the OTA password are entered
  only in the `SporePrint-Setup` captive portal and stored in NVS. The node id
  must equal the MQTT username (the broker ACL scopes each node by it).
- A provisioned node whose settings have connected before no longer reopens
  the open setup AP when WiFi fails: it boots offline and retries every 60 s.
- Opening the portal on purpose is physical: hold BOOT (node, and the
  ESP32-S3 camera boards) or short GPIO 13 to GND (AI-Thinker camera — there
  is no button on that pin) for 3–10 s, then release.
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
  N}}` changes it per channel and persists it in NVS. A max-on trip is
  reported with trigger `safety_cutoff` and counted in the health doc's
  `max_on_trips` (the stuck-channel signal); a timed pulse ending on schedule
  reports trigger `timer`. An explicit `"state":"on"` without a
  `duration_sec` holds until an off or the backstop, ending a pulse that is
  still timing out.
- An explicit `"state":"off"` always wins over `pwm`/`level` in the same
  command, and never leaves a timer armed. (The Pi also strips `pwm`/`level`
  from every OFF it sends, because older firmware treated
  `{"state":"off","pwm":N}` as ON.)
- 10 minutes without MQTT → every channel off (safe mode); the node never
  reboots itself for link loss.
- Empty command payloads are rejected, never defaulted to ON.
- Panic coredumps persist in flash and upload to the Pi once MQTT is up. The
  node erases a dump only when the Pi acknowledges it on `cmd/coredump_ack`
  (a signed command naming the dump's SHA-256), which the Pi sends only once
  the dump hashes to that id and is durably on disk. Without an ack it
  retries with backoff (3 uploads per boot, 6 per dump) and then keeps the
  dump in flash — a Pi too old to acknowledge never makes a node lose one.

## OTA

- **Listener:** `lib/sp_device/ota_service.cpp` serves network OTA on UDP/TCP
  3232 with the espota handshake the Pi's push speaks: an MD5
  challenge-response over the OTA password (`lib/sp_core/espota.h`). It
  keeps core 2.x's exchange byte for byte because Arduino-ESP32 3.x's own
  `ArduinoOTA` answers only a PBKDF2-SHA256 challenge, which Pis before
  2026-10 cannot answer. The strength is the same as on core 2.x. The Pi's
  push (`server/app/hardware/ota_push.py`) now answers both, as espota.py
  decides: a 32-hex nonce gets the MD5 digest, a 64-hex nonce the
  PBKDF2-HMAC-SHA256 one (10 000 rounds over sha256(password)). A firmware
  that uses the stock library can follow once every Pi it must accept pushes
  from runs a release newer than 5.0.0.
- **Password:** the listener does not start when the NVS password is empty
  or shorter than 12 characters.
- **Events:** start / success / error land on `sporeprint/<node>/ota`, so a
  half-applied OTA is visible even without secure boot.
- **Rollback:** a freshly flashed OTA image is on probation until MQTT has been
  connected continuously for 60 s. A crash, watchdog reset or power loss
  before then boots the previous image. An operator restart confirms the new
  image only if it reached MQTT during that boot. A confirm that itself fails
  (the OTA data write is refused) is tried again after more MQTT time,
  backing off to an hour, instead of leaving a working image to roll back at
  the next reset. A push that arrives while the image is on probation would
  overwrite the other slot, the only confirmed image: the node confirms the
  running image first if it reached MQTT this boot, and otherwise refuses
  the push (`image_on_probation`; power-cycle to boot the previous image,
  then push again). Every refusal of an authenticated push (this, the
  signed-manifest gate, an image too large for the slot) is answered
  `ERR <reason>` in place of the espota `OK`, so the Pi's push status says
  why. Rollback needs a bootloader
  built with rollback support, which is this framework's default, and which
  the core-2.x bootloader in every older node also has: a node updated from
  a 2.x image keeps that bootloader, so a failed first 3.x image still rolls
  back ([`firmware/README.md`](../firmware/README.md#updating-nodes-from-a-core-2x-image)).
- **Integrity:** the OTA service and the Pi's push check the image MD5 (a
  transport check, not a signature).
- **Push target:** espota has no way for the node to prove itself to the Pi,
  and the push goes to the IP the node's last heartbeat reported. So the Pi
  pushes only to a node that is online and was heard from in the last 10
  minutes (409 otherwise), refuses a host that answers the invitation
  without asking for the OTA password (every node with OTA enabled asks),
  and reports a push as done only once the node's own `success` event
  arrives on `sporeprint/<node>/ota`, which only the node's broker login can
  publish.
- **Signed manifests (optional):** an image built with
  `SPOREPRINT_OTA_PUBKEY_B64` in its build environment (the Ed25519 release
  key the Pi pins; `firmware/scripts/fw_version.py` compiles it in) accepts
  `cmd/ota_manifest {manifest_b64, sig_b64}`: the release manifest of
  `server/app/cloud/ota_manifest.py`, with `artifact` = the PlatformIO env
  and `sha256`/`size` of `firmware.bin`. The node checks the signature
  (vendored Monocypher, `lib/sp_core/vendor/monocypher`), the canonical
  form, its own env, and a version not older than the running image or the
  last manifest-verified update confirmed on the node (NVS `ota_floor`: it
  rises when that image passes its probation, not when it is flashed, so an
  image that fails and rolls back leaves the floor where it was). The next
  push must then
  be exactly that image: every flashed byte is hashed, and a mismatch is
  aborted before `Update.end()`. The Pi verifies the same manifest against
  the uploaded `.bin` first (`POST /api/hardware/nodes/{id}/ota` with
  `manifest` + `manifest_sig`), refuses a camera image for a climate, relay
  or lighting node and a node image for a camera, and sends the manifest
  once the push holds the callback port, right before the invitation: an
  arming lasts 5 minutes on the node, and a push queued behind others can
  wait longer than that. Unsigned pushes still flash unless the image
  was built with `SPOREPRINT_OTA_REQUIRE_MANIFEST=1`; images built without
  the key (local builds, Builder ZIPs) ignore manifests. The key is a build
  input, never a setting the command channel could change. This repo's
  firmware releases from `firmware-v5.1.0` on are built with it (next
  section); the older `firmware-v4.2.0` release is unsigned.

## Signed firmware releases

A `firmware-vX.Y.Z` tag runs `.github/workflows/firmware-release.yml`, which
publishes one `<env>.zip` per image env: `firmware.bin`, `bootloader.bin`,
`partitions.bin`, and `<env>.manifest.json` + `<env>.manifest.json.sig` (the
manifest above, `artifact` = the env, channel `stable`, signed with the
release key). Every image is built with the release verify key compiled in,
and the release notes print that key: it must equal the key the Pi pins.

The private key is the secret `OTA_SIGNING_KEY` (base64 of the 32-byte
Ed25519 key, the format `scripts/generate-ota-keypair.py` writes). Its public
half, the key every Pi pins as `SPOREPRINT_OTA_PUBKEY_B64`, is the repository
variable `OTA_PUBKEY_B64` (`gh variable set OTA_PUBKEY_B64 --body <key>`): a
release stops unless the secret's public half equals it, so a wrong secret
never ships images every Pi refuses. The build is the exposed part of a
release (PlatformIO downloads and runs platform and library build scripts),
so the key never reaches it, and the job that holds a write token never
holds the key:

| Job | Gets | Does |
|---|---|---|
| `release-key` | the private key, in one step | checks the tag (exactly `firmware-vX.Y.Z`), derives the **public** key, stops unless it equals `OTA_PUBKEY_B64`, and outputs only that; fails if the secret is missing |
| `native-tests` | no key | runs the firmware's host test suite (`pio test -e native`), diffs `signing_vectors.json` and `ota_manifest_vectors.json` against the server's copies and checks `lib/sp_core` and `lib/sp_drivers` for Arduino includes; `build` and `sign` wait for it, so a tag whose tests fail is never built or signed |
| `build` (one per env) | the public key and the tag's version | checks out the tag, refuses a tree whose `firmware/VERSION.txt` differs from the tag, installs PlatformIO and the platform's Python environment from hash-pinned requirements, fetches the PlatformIO platform and packages checked against `firmware/toolchain.lock.json`, builds with `SPOREPRINT_OTA_PUBKEY_B64` and `SPOREPRINT_FW_VERSION` with uv offline; no cache is restored |
| `sign` | the private key, in one step; a read-only token | signs each `firmware.bin` with `scripts/sign-ota-bundle.py` (key in a `0600` temp file, shredded on exit), zips, runs `scripts/verify_firmware_release.py` on every zip **without** the secret, and hands the zips on |
| `release` | a write token; never the key | runs the same check on the zips it received, then creates the release |

The two jobs that hold the key run no build tooling and only GitHub's own
actions (the one third-party action, which creates the release, runs in the
`release` job). `release-key`, `sign` and `release` install only
`cryptography` and its dependencies, as wheels, at the versions and hashes
`server/uv.lock` pins. The workflow runs only for a pushed `firmware-v*` tag
or a manual dispatch naming one (never for pull requests); every checkout
is `refs/tags/<tag>` without persisted credentials, and `release-key`
records the commit the tag names: `native-tests`, `build`, `sign` and
`release` each stop unless the tag still names that commit, so a tag moved
mid-run (between two environment approvals, say) releases nothing; the
token is read-only except in the `release` job; actions are pinned to
commit SHAs.
`server/tests/test_firmware_release_workflow.py` holds the workflow to all
of this, and runs the sign, zip and verify scripts themselves.

The platform and its packages: `firmware/platformio.ini` names the
pioarduino platform by a release-asset URL, and the platform names its
framework and tool packages the same way. PlatformIO checks none of them
against a hash, and a release asset can be replaced, so the `build` job
runs `scripts/pin_firmware_toolchain.py` before PlatformIO: it downloads the
platform zip and every package `firmware/toolchain.lock.json` lists, refuses
any whose SHA-256 differs from the lock, and points the build at the checked
copies. After the build it fails the job if anything was installed from an
unchecked URL or from the PlatformIO registry, with two exceptions the lock
names: PlatformIO Core's own PIO Home front end, which no build reads, at its
exact URL, and PlatformIO Core's own SCons, which Core installs from the
PlatformIO registry for every build (the registry checksums it; the lock does
not pin it). The library dependencies also come from the PlatformIO registry,
pinned by version in `platformio.ini`. The compilers and tools themselves come
through Espressif's `idf_tools.py`, which checks each download against the
SHA-256 in its (checked) package. The Python side is pinned the same way:
PlatformIO Core and its dependencies install from
`firmware/requirements-pio.txt`, and the platform's own virtualenv
(`~/.platformio/penv`) is created before the build from
`firmware/requirements-penv.txt`, both with `pip --require-hashes` (exact
versions, SHA-256 each). The platform's `penv_setup.py` then finds every
package it wants already installed, and the build runs with `UV_OFFLINE=1`,
so it cannot fetch another; `prepare` refuses a platform whose penv wants a
package the lock lacks, and the post-build check refuses a penv holding
anything unpinned. `requirements-penv.txt` pins two packages with known
advisories, accepted because that environment exists only on the ephemeral
release runner and serves nothing: starlette, which the platform's
pioarduino package caps below 1.0 and which only serves PIO Home (never
started by `pio run`), and ecdsa, which has no fixed release and backs
esptool's secure-boot signing, which the release build does not call.
Dependabot alerts on that file are expected; its header says how to treat
them. A signature says the release
workflow built the image; it does not vouch for the toolchain beyond these
checks. To move to a new platform release, change the URL in
`platformio.ini` and the lock together
(`python scripts/pin_firmware_toolchain.py hash <file>` prints a SHA-256).

`release-key` and `sign` run in the `firmware-release` environment. As a
repository secret the key works as it is, but anyone who can push a tag or
dispatch the workflow from a branch could then reach it. To close that, in
the repository settings: make `OTA_SIGNING_KEY` an environment secret of
`firmware-release` (and delete the repository secret), limit the
environment's deployment branches and tags to the `firmware-v*` tag pattern
only, optionally add required reviewers, and protect `firmware-v*` tags
with a tag ruleset that blocks updates and deletion. The environment checks
the ref the workflow runs from, not the `tag` input, so start a manual
re-run with **Use workflow from** set to the tag itself; allowing the
default branch instead would let any dispatch from it reach the key.

`scripts/verify_firmware_release.py` reads the manifest independently of
`server/app/cloud/ota_manifest.py` and, in the workflow, cross-checks it
with that file; both are pinned to the committed vectors
(`server/tests/fixtures/ota_manifest_vectors.json`). Per zip it requires
exactly the five files, a valid signature, the canonical v1 bytes, the env,
version, channel and the `firmware.bin` SHA-256 and size, a manifest small
enough for the node's command frame, ESP images for the env's chip, and the
verify key and version compiled into `firmware.bin` as whole strings (so
`15.1.0` does not pass for `5.1.0`). The env name is checked as present and
no other image env named: the linker may store a short name as the tail of a
longer string (`cam` is the end of the camera driver's `esp32 ll_cam`). To
check a download yourself, from a checkout of the release tag (add
`--env <env>` if the browser renamed the file):

```bash
python3 scripts/verify_firmware_release.py --pubkey-b64 <the key your Pi pins> \
    --version 5.1.0 node_esp32.zip
```

The signature covers `firmware.bin` only. `bootloader.bin` and
`partitions.bin` are never pushed over the air, so they carry no manifest;
the script checks only their chip and format.

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

The cloud added a `PUT /settings/ota-pubkey` endpoint in v4. It stores the
public half of the OTA signing key in the operator's `profiles` row, and the
cloud's `ota-push` copies it into the OTA command. **The Pi ignores that
copy.** It verifies the signed release manifest (`{version}.manifest.json` +
`.sig`, see `server/app/cloud/ota_manifest.py`) only with its locally pinned
key (`SPOREPRINT_OTA_PUBKEY_B64` / Settings → OTA verify key). A key taken
from the command channel would let whoever controls that channel sign their
own bundle. The manifest binds version, channel, sha256 and size: the Pi
refuses a channel other than its `SPOREPRINT_OTA_CHANNEL` and any version
older than its own unless `SPOREPRINT_OTA_ALLOW_DOWNGRADE` is set on the Pi.
This protects the cloud → Pi hop (Pi self-update), not the Pi → node flash:
node images are checked against the same kind of signed manifest only when
the image was built with the key (see above).

This is independent of web-push (browser) VAPID keys, which sign
cloud-→-browser notifications and have nothing to do with firmware. The
two key systems are namespaced separately (`CLOUD_VAPID_*` vs
per-user `ota_pubkey`).

## What's still open

- A secure-boot / flash-encryption build (the ESP-IDF component route above).
- Requiring manifests: release images still accept unsigned pushes
  (`SPOREPRINT_OTA_REQUIRE_MANIFEST` is not set) so that Pis without a pinned
  key keep updating nodes.
- Per-node HMAC keys (currently a single shared key across all nodes
  paired to one Pi).
