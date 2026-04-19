import os
import subprocess
import time

from fastapi import APIRouter

from .service import get_system_metrics, get_mqtt_stats, get_client_list, get_task_statuses

router = APIRouter()


@router.get("/system")
async def system_health():
    return await get_system_metrics()


@router.get("/mqtt")
async def mqtt_health():
    return get_mqtt_stats()


@router.get("/clients")
async def connected_clients():
    return get_client_list()


@router.get("/tasks")
async def background_tasks():
    return get_task_statuses()


@router.get("/clock")
async def clock_drift():
    """v3.3.3 — expose Pi wall clock and chrony tracking state.

    The cloud relay signs every command frame with a `ts` field. If the Pi
    clock drifts more than 30 s from wall-clock truth every cloud-issued
    command fails with "ts outside replay window" and the failure surface
    is a user-reported support ticket. This endpoint makes drift directly
    observable:

      * ``pi_ts`` — current Pi epoch seconds. Compare against the caller's
        clock for a quick delta without needing chrony present.
      * ``chrony.*`` — ``chronyc -n tracking`` output parsed into the key
        fields (system_time, last_offset, rms_offset, update_interval,
        leap_status). Returns ``available: false`` if chrony is not
        installed or the socket is not accessible.

    Never returns secrets; safe for unauthenticated LAN scrape by a local
    Prometheus / UptimeRobot. CORS is LAN-scoped elsewhere in the app.
    """
    pi_ts = time.time()
    chrony: dict[str, object] = {"available": False}
    try:
        # -n: numeric addresses (no DNS), -c: comma-separated CSV mode.
        # 1.5 s is well inside any reasonable healthcheck budget.
        result = subprocess.run(
            ["chronyc", "-n", "tracking"],
            capture_output=True, text=True, timeout=1.5,
        )
        if result.returncode == 0:
            parsed: dict[str, str] = {}
            for line in result.stdout.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    parsed[k.strip().lower().replace(" ", "_")] = v.strip()
            chrony = {
                "available": True,
                "reference_id":        parsed.get("reference_id"),
                "stratum":             parsed.get("stratum"),
                "system_time_offset":  parsed.get("system_time"),
                "last_offset":         parsed.get("last_offset"),
                "rms_offset":          parsed.get("rms_offset"),
                "frequency":           parsed.get("frequency"),
                "residual_freq":       parsed.get("residual_freq"),
                "update_interval":     parsed.get("update_interval"),
                "leap_status":         parsed.get("leap_status"),
            }
    except FileNotFoundError:
        chrony = {"available": False, "reason": "chrony not installed"}
    except subprocess.TimeoutExpired:
        chrony = {"available": False, "reason": "chronyc timeout"}
    except Exception as e:
        chrony = {"available": False, "reason": type(e).__name__}

    return {
        "pi_ts": pi_ts,
        "pi_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(pi_ts)),
        "timezone": os.environ.get("TZ", "UTC"),
        "chrony": chrony,
    }
