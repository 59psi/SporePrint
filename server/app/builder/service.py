import json
import logging
import time

from ..config import settings
from ..db import get_db

log = logging.getLogger(__name__)


async def _build_system_context() -> str:
    """Build a context doc of current system state for the Builder's Assistant."""
    context_parts = ["# SporePrint System State\n"]

    # Registered hardware nodes
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM hardware_nodes ORDER BY node_id")
        nodes = [dict(r) for r in await cursor.fetchall()]
        if nodes:
            context_parts.append("## Registered Hardware Nodes")
            for n in nodes:
                context_parts.append(
                    f"- **{n['node_id']}** ({n['node_type']}) — {n['status']}, "
                    f"FW {n.get('firmware_version', '?')}, IP {n.get('ip_address', '?')}"
                )
            context_parts.append("")

        # Smart plugs
        cursor = await db.execute("SELECT * FROM smart_plugs ORDER BY plug_id")
        plugs = [dict(r) for r in await cursor.fetchall()]
        if plugs:
            context_parts.append("## Smart Plugs")
            for p in plugs:
                context_parts.append(
                    f"- **{p['plug_id']}** ({p['plug_type']}) — {p.get('device_role', 'unknown role')}, "
                    f"MQTT: {p['mqtt_topic_prefix']}"
                )
            context_parts.append("")

    # GPIO allocation reference (known assignments)
    context_parts.append("""## Known GPIO Allocations
- Climate Node: I2C (SDA=21, SCL=22), SHT31 0x44, SCD40 0x62, BH1750 0x23
- Relay Node: GPIO 25 (fae), 26 (exhaust), 27 (circulation), 14 (aux) — all IRLZ44N
- Lighting Node: GPIO 25 (white), 26 (blue), 27 (red), 14 (far_red) — all IRLZ44N
- Camera Node: AI-Thinker pinout, flash GPIO 4

## MQTT Topic Convention
- sporeprint/{node_id}/telemetry — sensor data
- sporeprint/{node_id}/status — online/offline
- sporeprint/{node_id}/cmd/{channel} — commands
- sporeprint/{node_id}/alert — safety alerts

## Available Power Supply Voltages
- 5V (USB/buck converter)
- 12V (LED strips, fans, solenoids)
- 3.3V (ESP32 logic)

## Operator Equipment
- Bambu Lab H2D 3D printer (OpenSCAD parametric designs)
- Flow hood, agar work capability
- IRLZ44N MOSFETs in stock
- Noctua fans, peristaltic pumps available
""")

    return "\n".join(context_parts)


async def generate_guide(request: str, constraints: str = "") -> dict:
    """Generate a detailed hardware integration guide using Claude."""
    if not settings.claude_api_key:
        return {"error": "Claude API key not configured"}

    system_context = await _build_system_context()

    system_prompt = f"""You are the SporePrint Builder's Assistant — an expert embedded systems engineer
and mycologist helping the operator add new hardware to their automated mushroom grow closet.

{system_context}

When the operator describes what they want to add, generate a DETAILED implementation guide
with these sections (use markdown headers):

## 1. Parts List
Specific components, model numbers, approximate cost. Be specific about ratings.

## 2. Wiring Diagram
ASCII diagram showing ESP32 GPIO connections, voltage levels, required passive components
(resistors, capacitors, flyback diodes for solenoids, etc.)

## 3. Firmware Changes
Complete PlatformIO code snippets: sensor driver initialization, MQTT topics, command handler,
NVS configuration keys. Match existing code style from sporeprint_common library.

## 4. MQTT Integration
New topics, payload formats, QoS levels. Follow existing convention.

## 5. Backend Integration
New telemetry parser additions, API endpoints if needed, automation rule templates.

## 6. 3D-Printable Mount
OpenSCAD parametric design for Bambu Lab printer. Include mounting holes and dimensions
for the specific components.

## 7. Automation Rules
Pre-built YAML-style rule templates using the new hardware.

## 8. Safety Notes
Current ratings, thermal limits, waterproofing needs, failsafes required.

## 9. Test Procedure
Step-by-step verification checklist.

Be thorough, practical, and specific. The operator is experienced with ESP32 and electronics."""

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.claude_api_key)

        user_msg = f"Request: {request}"
        if constraints:
            user_msg += f"\n\nConstraints: {constraints}"

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )

        guide_text = message.content[0].text

        # Save guide
        guide_id = await _save_guide(request, constraints, guide_text)

        return {
            "guide_id": guide_id,
            "request": request,
            "constraints": constraints,
            "guide": guide_text,
            "generated_at": time.time(),
        }

    except Exception as e:
        log.error("Builder guide generation failed: %s", e)
        return {"error": str(e)}


async def _save_guide(request: str, constraints: str, guide: str) -> int:
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO builder_guides (request, constraints, guide, created_at) VALUES (?, ?, ?, ?)",
            (request, constraints, guide, time.time()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_guides() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, request, constraints, created_at FROM builder_guides ORDER BY created_at DESC"
        )
        return [dict(r) for r in await cursor.fetchall()]


async def get_guide(guide_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM builder_guides WHERE id = ?", (guide_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
