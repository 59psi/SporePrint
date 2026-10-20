"""The contaminant library and the identify prompt.

* Every library entry carries the fields the UI renders, a danger level it
  knows, and a unique id (the detail route looks entries up by it).
* The identify system prompt asks Claude for the fields the route reads.
* /library lists all seven entries; /library/{id} returns one, 404 for an
  unknown id.
"""

from app.contamination.library import CONTAMINANTS, IDENTIFICATION_SYSTEM_PROMPT


def test_every_contaminant_has_the_fields_a_known_danger_level_and_a_unique_id():
    required = {
        "id",
        "common_name",
        "scientific_name",
        "appearance",
        "growth_speed",
        "smell",
        "danger_level",
        "stages",
        "action",
        "prevention",
        "common_causes",
    }
    for c in CONTAMINANTS:
        missing = required - set(c.keys())
        assert not missing, f"Contaminant {c.get('id', '?')} missing fields: {missing}"
        assert c["danger_level"] in {"critical", "high", "medium"}, c["id"]
    ids = [c["id"] for c in CONTAMINANTS]
    assert len(ids) == len(set(ids))


def test_identify_prompt_asks_for_the_fields_the_route_reads():
    for field in ("contamination_detected", "contaminants", "health_assessment", "recommendations"):
        assert field in IDENTIFICATION_SYSTEM_PROMPT


def test_library_list_endpoint(client):
    resp = client.get("/api/contamination/library")
    assert resp.status_code == 200
    assert {c["id"] for c in resp.json()} == {
        "trichoderma", "cobweb", "black_mold", "bacterial", "lipstick_mold", "penicillium", "wet_spot",
    }


def test_library_detail_endpoint(client):
    resp = client.get("/api/contamination/library/trichoderma")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "trichoderma"
    assert data["common_name"] == "Green Mold"
    assert data["danger_level"] == "high"
    assert [stage["name"] for stage in data["stages"]] == ["Early white", "Green sporulation"]
    assert client.get("/api/contamination/library/nonexistent").status_code == 404
