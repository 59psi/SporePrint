# Firmware security — OTA signing, secure boot, flash encryption

Context: Sentinel findings **H-2** (OTA has password but no firmware
signing) and **H-3** (NVS unencrypted) from `analysis/02-security.md`.

This document is the operator-facing guide. v3.4.9 landed the minimum
password-strength enforcement (OTA refuses <12-char passwords) and the
documented upgrade path; the full **flash encryption + secure boot v2 +
signed OTA** stack is an opt-in operator choice per node because it has
consequences that cannot be reversed.

## Threat model

| Attacker capability | Defense |
|---|---|
| Brute-force the OTA password over LAN | L-6 → 12-char minimum + refusal of default `"sporeprint"` |
| Flash arbitrary firmware once OTA password is known | **Secure boot v2** — device rejects unsigned firmware |
| Extract WiFi/MQTT/OTA creds from a stolen node | **Flash encryption** — NVS unreadable without the device's key |
| Roll back to an older (known-vulnerable) firmware | **Anti-rollback** (eFuse counter) |
| Physical bus tap to read JTAG | **Secure boot v2** — disables JTAG unless re-enabled with secret |

v3.4.9 defaults enable defense #1 only. The rest are opt-in with real
consequences (below). The v3.4.9 C-1 fix (MQTT HMAC verification)
provides compensating protection against the most likely exploit path
(attacker-with-broker-creds drives a relay) without requiring flash
encryption.

## Enabling secure boot v2 + flash encryption (per-project, one-time)

> ⚠️ **Read this entire section before starting.** Enabling these
> features **irrevocably** burns eFuses on the ESP32. A misstep bricks
> the device. Test on a spare unit first.

### Step 1 — generate the signing key

On a machine that will stay offline afterward:

```bash
# Secure boot v2 uses RSA-3072 or ECDSA-P256. ECDSA is smaller + faster.
openssl ecparam -name prime256v1 -genkey -out firmware/secure_boot_signing_key.pem
# Derive the public key that gets burned into eFuse.
espsecure.py digest_sbv2_public_key \
    --keyfile firmware/secure_boot_signing_key.pem \
    --output firmware/secure_boot_pub_digest.bin
```

**Store the `.pem` offline** (e.g. a hardware token, printed QR-ed key
in a safe). **You cannot recover it**. Every future OTA image must be
signed with the same key.

### Step 2 — enable in `platformio.ini`

Add to the shared `[env]` block (uncomment the guarded lines):

```ini
board_build.embed_files = secure_boot_pub_digest.bin
board_build.partitions = partitions_secure.csv
build_flags =
    ${env.build_flags}
    -DCONFIG_SECURE_BOOT=1
    -DCONFIG_SECURE_BOOT_V2_ENABLED=1
    -DCONFIG_SECURE_FLASH_ENC_ENABLED=1
    -DCONFIG_SECURE_SIGNED_ON_UPDATE=1
    -DCONFIG_SECURE_BOOT_SIGNING_KEY="secure_boot_signing_key.pem"
```

And create `firmware/partitions_secure.csv` matching the default
partition layout but with ota_data secured.

### Step 3 — first flash

```bash
pio run -e relay_node -t upload
# The first boot automatically:
#   1. Burns BLK2 eFuse with the public-key digest (permanent).
#   2. Burns FLASH_CRYPT_CNT eFuse (permanent).
#   3. Encrypts the flash (~40 seconds, device appears to hang).
#   4. Reboots into the encrypted firmware.
```

Subsequent `pio run -t upload` will fail because the bootloader no
longer accepts unsigned images. Flash via:

```bash
pio run -e relay_node -t signedupload    # applies the key automatically
```

### Step 4 — signed OTA

The `OTAManager` already calls `Update.setMD5()`. When secure boot is
enabled, `Update` additionally verifies the embedded signature against
the eFuse-stored public key. Callers don't need to change — the image
just needs to be signed with the same `.pem`:

```bash
espsecure.py sign_data \
    --keyfile firmware/secure_boot_signing_key.pem \
    --version 2 \
    --output firmware/.pio/build/relay_node/firmware.signed.bin \
    firmware/.pio/build/relay_node/firmware.bin
```

Or just flash via `pio run -t signedupload` and PlatformIO handles it.

### Step 5 — rollback protection (optional)

Enable only after you've successfully shipped one OTA with the new
setup, so a bad build can't permanently lock out newer firmware:

```ini
-DCONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=1
-DCONFIG_BOOTLOADER_APP_ANTI_ROLLBACK=1
```

Each signed build then needs an incrementing `secure_version` in the
app header — `bump.sh` can set this from `VERSION.txt`.

## Current v3.4.9 defaults (no operator action required)

- **OTA password minimum 12 chars** — `ota_manager.cpp` refuses to
  enable OTA if the NVS-stored password is shorter, empty, or the
  literal default.
- **MQTT HMAC signing** — commands land with a fresh signature every
  call; a compromised broker cred no longer grants arbitrary actuation.
- **OTA event publishing** — start/success/error events land on
  `sporeprint/<node>/ota`, so a half-applied OTA is visible cloud-side
  even without secure boot.

## v4 cloud-side OTA pubkey landing zone

The cloud added a `PUT /settings/ota-pubkey` endpoint in v4. Operators
who run flash-encrypted nodes can register the public side of their
secure-boot signing key with the cloud so the cloud-web admin surface
can verify OTA payloads end-to-end before publishing them. The private
key never leaves the operator's machine — only the public verifier
ships. The endpoint persists into the operator's `profiles` row and is
read by `cloud/app/devices/router.py::ota_push` before signing the
delta. If no pubkey is registered, the cloud falls back to per-device
HMAC-only flow as before.

This is independent of web-push (browser) VAPID keys, which sign
cloud-→-browser notifications and have nothing to do with firmware. The
two key systems are namespaced separately (`CLOUD_VAPID_*` vs
per-user `ota_pubkey`).

## What's still open for v3.5+

- Tooling around `scripts/provision-node.sh --with-secure-boot` that
  automates the per-node key-derivation + first-flash dance.
- Per-node HMAC keys (currently a single shared key across all nodes
  paired to one Pi).
- Rollback counter wired through `bump.sh`.
- Documentation on recovery from lost signing key (answer: there is
  none; treat the key like a hardware wallet seed).
