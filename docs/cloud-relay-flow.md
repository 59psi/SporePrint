# Cloud Relay Flow

Remote access flow: phone → cloud relay at sporeprint.ai → paired Pi on the operator's LAN. v3.3.1 added HMAC-SHA256 signing over the command frames; the Pi refuses unsigned frames.

```mermaid
sequenceDiagram
    autonumber
    participant App as Mobile App<br/>(Capacitor)
    participant Relay as Cloud Relay<br/>(sporeprint.ai)
    participant Pi as Raspberry Pi<br/>(FastAPI)
    participant ESP as ESP32 Node

    Note over App: Supabase JWT + RevenueCat tier in hand
    App->>Relay: Socket.IO connect<br/>auth = { jwt }
    Relay->>Relay: verify_jwt() · get_user_tier()<br/>get_user_devices()
    Relay-->>App: connected (joins device rooms)

    Note over Pi: On boot, with SPOREPRINT_CLOUD_TOKEN set
    Pi->>Relay: Socket.IO connect<br/>auth = { token, device_id }
    Relay->>Relay: validate_device_token()<br/>update_device_status('online')
    Relay-->>Pi: connected (joins device:<id> room)

    Note over App,Pi: Steady state — telemetry flowing Pi → Relay → App
    Pi-->>Relay: emit 'telemetry' { node_id, temp_f, ... }
    Relay-->>App: forward to room device:<id>

    Note over App,ESP: Premium: remote command
    App->>Relay: emit 'command'<br/>{ device_id, target, channel, payload, id }
    Relay->>Relay: tier == 'premium' · device owned by user<br/>sign_frame(device_token, frame) → + ts + signature
    Relay->>Pi: emit 'command' (signed)

    Pi->>Pi: verify_frame(cloud_token, frame)<br/>ts window · tier · id-replay · target registered
    alt Signature valid
        Pi->>ESP: mqtt_publish sporeprint/<node>/cmd/<channel>
        ESP-->>Pi: status update (next telemetry)
        Pi-->>Relay: emit 'command_result' { id, success: true }
        Relay-->>App: forward result
    else Signature missing or bad ts
        Pi-->>Relay: emit 'command_result' { id, success: false, error: 'Signature check failed' }
        Relay-->>App: forward error
    end
```

## What v3.3.1 enforces

| Check | Code | Failure mode |
|---|---|---|
| HMAC-SHA256 over canonical JSON | `server/app/cloud/signing.py::verify_frame` | command dropped with `signature mismatch` |
| `ts` within ±30 s of Pi wall-clock | same | `ts outside replay window` |
| `command_id` present, not replayed | `on_command` LRU set (1024 cap) | `Replayed command id` |
| `tier == 'premium'` | `on_command` | `Remote control requires premium tier` |
| Target matches registered `hardware_nodes.node_id` or `smart_plugs.plug_id` | `_target_is_registered()` | `Unknown target '<id>'` |
| `target` / `channel` match `^[a-zA-Z0-9_-]{1,64}$` | `_is_safe_target` / `_is_safe_channel` | `Invalid target or channel` |

Pre-v3.3.1 only the tier string was checked — a compromised cloud relay could have issued any command to any registered target. v3.3.1 closes that by making the Pi require a signature it can verify.

## External services referenced in this flow

- **Supabase** — JWT + user↔device mapping
- **Firebase FCM → APNs/Android** — push (not shown; triggered by Pi events that `forward_event()` to cloud)
- **RevenueCat** — tier source (webhook updates `profiles.tier`)
- **Anthropic** — Claude vision / grow advisor (separate path, not in this sequence)
