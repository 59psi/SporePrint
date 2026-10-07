"""`sporeprint_contamination_events_total` must count real contamination.

Nothing in the app writes sessions.status = 'contaminated' — contamination
is recorded in `contamination_events` (identify detections + manual marks).
The exporter used to query only the session status, so the counter never
emitted a sample and Grafana alerts on it could never fire.
"""

from __future__ import annotations

import re

import pytest

from app.contamination.service import record_event
from app.db import get_db
from app.integrations.grafana.config import GrafanaConfig
from app.integrations.grafana.exporter import collect_samples


def _counter_value(body: str, chamber_id: str) -> float | None:
    m = re.search(
        rf'^sporeprint_contamination_events_total\{{chamber_id="{chamber_id}"\}} ([0-9.e+]+)$',
        body,
        re.MULTILINE,
    )
    return float(m.group(1)) if m else None


@pytest.fixture
async def chamber_with_session():
    async with get_db() as db:
        await db.execute("INSERT INTO chambers (id, name) VALUES (7, 'Tent B')")
        await db.execute(
            "INSERT INTO sessions (id, name, species_profile_id, chamber_id, status) "
            "VALUES (70, 'grow', 'blue-oyster', 7, 'active')"
        )
        await db.commit()


async def test_counts_contamination_events_by_chamber(chamber_with_session):
    await record_event(source="identify", session_id=70, chamber_id=7,
                       contamination_type="trich")
    await record_event(source="manual", session_id=70, chamber_id=7,
                       contamination_type="cobweb")
    body = (await collect_samples(GrafanaConfig(), version="t")).decode()
    assert _counter_value(body, "7") == 2.0


async def test_event_without_chamber_falls_back_to_session_chamber(chamber_with_session):
    await record_event(source="manual", session_id=70, chamber_id=None)
    body = (await collect_samples(GrafanaConfig(), version="t")).decode()
    assert _counter_value(body, "7") == 1.0


async def test_legacy_contaminated_status_session_still_counted_once(chamber_with_session):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO sessions (id, name, species_profile_id, chamber_id, status) "
            "VALUES (71, 'old', 'blue-oyster', 7, 'contaminated')"
        )
        await db.commit()
    body = (await collect_samples(GrafanaConfig(), version="t")).decode()
    assert _counter_value(body, "7") == 1.0
