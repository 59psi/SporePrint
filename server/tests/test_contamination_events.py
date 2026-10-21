"""Persisted contamination events and their root cause, over the API.

* A manual event is recorded as such, with no root cause yet; one naming a
  session, chamber or frame that does not exist is a 422, never a foreign
  key 500.
* The list is newest first and filters by session and by chamber.
* A root cause is recorded with its time; an unknown event is a 404 and a
  missing cause a 422.

(Turning an identify reply into an event: test_contamination_identify.py.)
"""


def _event(client, **body) -> dict:
    resp = client.post("/api/contamination/events", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_manual_event_is_recorded_without_a_root_cause(client):
    cid = client.post("/api/chambers", json={"name": "EP"}).json()["id"]
    data = _event(client, chamber_id=cid, contamination_type="bacterial", confidence=0.6,
                  notes="slimy, sour")
    assert data["id"] is not None
    assert (data["source"], data["chamber_id"], data["contamination_type"], data["confidence"],
            data["notes"]) == ("manual", cid, "bacterial", 0.6, "slimy, sour")
    assert data["root_cause"] is None and data["root_cause_recorded_at"] is None


def test_events_list_newest_first_and_filter_by_session_and_chamber(client):
    s1 = client.post("/api/sessions", json={"name": "S1", "species_profile_id": "blue_oyster"}).json()["id"]
    s2 = client.post("/api/sessions", json={"name": "S2", "species_profile_id": "blue_oyster"}).json()["id"]
    c1 = client.post("/api/chambers", json={"name": "C1"}).json()["id"]
    first = _event(client, session_id=s1, chamber_id=c1, contamination_type="cobweb")
    second = _event(client, session_id=s2, contamination_type="trich")

    listed = client.get("/api/contamination/events").json()
    assert [e["id"] for e in listed] == [second["id"], first["id"]]
    assert [e["id"] for e in client.get(f"/api/contamination/events?session_id={s1}").json()] == [
        first["id"]]
    assert [e["id"] for e in client.get(f"/api/contamination/events?chamber_id={c1}").json()] == [
        first["id"]]


def test_a_root_cause_is_recorded_with_its_time(client):
    created = _event(client, contamination_type="penicillium")
    resp = client.post(
        f"/api/contamination/events/{created['id']}/root-cause",
        json={"root_cause": "airborne spore load, weak FAE"},
    )
    assert resp.status_code == 200
    assert resp.json()["root_cause"] == "airborne spore load, weak FAE"
    assert resp.json()["root_cause_recorded_at"] is not None


def test_a_root_cause_needs_a_known_event_and_a_cause(client):
    resp = client.post("/api/contamination/events/9999/root-cause", json={"root_cause": "x"})
    assert resp.status_code == 404
    created = _event(client)
    resp = client.post(f"/api/contamination/events/{created['id']}/root-cause", json={})
    assert resp.status_code == 422


def test_manual_event_with_unknown_references_is_422_not_500(client):
    for ref in ({"session_id": 9999}, {"chamber_id": 9999}, {"frame_id": 9999}):
        resp = client.post("/api/contamination/events", json={"contamination_type": "cobweb", **ref})
        assert resp.status_code == 422, resp.text  # was a FOREIGN KEY 500
        assert "9999" in resp.json()["detail"]
    assert client.get("/api/contamination/events").json() == []
