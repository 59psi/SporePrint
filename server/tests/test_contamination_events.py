"""Tests for persisted contamination events + root-cause analysis."""

from app.chambers.models import ChamberCreate
from app.chambers.service import create_chamber
from app.contamination import service
from app.contamination.service import detection_from_identify
from app.sessions.models import SessionCreate
from app.sessions.service import create_session


async def _chamber():
    return (await create_chamber(ChamberCreate(name="C")))["id"]


async def _session():
    return (await create_session(SessionCreate(name="S", species_profile_id="blue_oyster")))["id"]


# ── detection_from_identify (identify → event extraction) ───────


def test_detection_positive_with_contaminant():
    result = {
        "contamination_detected": True,
        "contaminants": [
            {"classification": "trichoderma", "confidence": 0.94},
            {"classification": "cobweb", "confidence": 0.3},
        ],
        "health_assessment": "contaminated",
    }
    det = detection_from_identify(result)
    assert det == {"contamination_type": "trichoderma", "confidence": 0.94}


def test_detection_positive_no_contaminants_list():
    """contamination_detected true but empty contaminants — still positive."""
    result = {"contamination_detected": True, "contaminants": []}
    det = detection_from_identify(result)
    assert det == {"contamination_type": None, "confidence": None}


def test_detection_negative():
    result = {"contamination_detected": False, "contaminants": []}
    assert detection_from_identify(result) is None


def test_detection_parse_error_shape():
    assert detection_from_identify({"parse_error": True, "raw_response": "..."}) is None


def test_detection_non_dict():
    assert detection_from_identify(None) is None
    assert detection_from_identify("nope") is None


# ── record_event / list_events ──────────────────────────────────


async def test_record_manual_event():
    ev = await service.record_event(
        source="manual", contamination_type="cobweb", confidence=0.7, notes="wispy"
    )
    assert ev["id"] is not None
    assert ev["source"] == "manual"
    assert ev["contamination_type"] == "cobweb"
    assert ev["confidence"] == 0.7
    assert ev["root_cause"] is None
    assert ev["root_cause_recorded_at"] is None


async def test_record_identify_event():
    cid = await _chamber()
    ev = await service.record_event(
        source="identify", session_id=None, chamber_id=cid,
        contamination_type="trichoderma", confidence=0.94,
    )
    assert ev["source"] == "identify"
    assert ev["chamber_id"] == cid


async def test_list_events_newest_first():
    await service.record_event(source="manual", contamination_type="a")
    await service.record_event(source="manual", contamination_type="b")
    events = await service.list_events()
    assert len(events) == 2
    # Newest first (highest id first)
    assert events[0]["id"] > events[1]["id"]


async def test_list_events_filter_session():
    s1 = await _session()
    s2 = await _session()
    await service.record_event(source="manual", session_id=s1, contamination_type="a")
    await service.record_event(source="manual", session_id=s2, contamination_type="b")
    filtered = await service.list_events(session_id=s1)
    assert len(filtered) == 1
    assert filtered[0]["session_id"] == s1


async def test_list_events_filter_chamber():
    c1 = await _chamber()
    c2 = await _chamber()
    await service.record_event(source="manual", chamber_id=c1, contamination_type="a")
    await service.record_event(source="manual", chamber_id=c2, contamination_type="b")
    filtered = await service.list_events(chamber_id=c2)
    assert len(filtered) == 1
    assert filtered[0]["chamber_id"] == c2


# ── root-cause ──────────────────────────────────────────────────


async def test_set_root_cause():
    ev = await service.record_event(source="manual", contamination_type="trich")
    updated = await service.set_root_cause(ev["id"], "under-sterilised batch")
    assert updated["root_cause"] == "under-sterilised batch"
    assert updated["root_cause_recorded_at"] is not None


async def test_set_root_cause_unknown():
    assert await service.set_root_cause(9999, "whatever") is None


# ── API endpoints ───────────────────────────────────────────────


def test_create_event_endpoint(client):
    cid = client.post("/api/chambers", json={"name": "EP"}).json()["id"]
    resp = client.post(
        "/api/contamination/events",
        json={"chamber_id": cid, "contamination_type": "bacterial", "confidence": 0.6},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "manual"
    assert data["chamber_id"] == cid
    assert data["contamination_type"] == "bacterial"


def test_list_events_endpoint(client):
    s1 = client.post("/api/sessions", json={"name": "S1", "species_profile_id": "blue_oyster"}).json()["id"]
    s2 = client.post("/api/sessions", json={"name": "S2", "species_profile_id": "blue_oyster"}).json()["id"]
    client.post("/api/contamination/events", json={"session_id": s1, "contamination_type": "cobweb"})
    client.post("/api/contamination/events", json={"session_id": s2, "contamination_type": "trich"})

    resp = client.get("/api/contamination/events")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    resp = client.get(f"/api/contamination/events?session_id={s1}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["session_id"] == s1


def test_root_cause_endpoint(client):
    created = client.post(
        "/api/contamination/events", json={"contamination_type": "penicillium"}
    ).json()
    resp = client.post(
        f"/api/contamination/events/{created['id']}/root-cause",
        json={"root_cause": "airborne spore load, weak FAE"},
    )
    assert resp.status_code == 200
    assert resp.json()["root_cause"] == "airborne spore load, weak FAE"


def test_root_cause_endpoint_404(client):
    resp = client.post(
        "/api/contamination/events/9999/root-cause", json={"root_cause": "x"}
    )
    assert resp.status_code == 404


def test_root_cause_endpoint_missing_body(client):
    created = client.post("/api/contamination/events", json={}).json()
    resp = client.post(f"/api/contamination/events/{created['id']}/root-cause", json={})
    assert resp.status_code == 422
