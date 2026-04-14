import pytest

from app.contamination.library import CONTAMINANTS, IDENTIFICATION_SYSTEM_PROMPT


def test_library_has_seven_contaminants():
    assert len(CONTAMINANTS) == 7


def test_all_contaminants_have_required_fields():
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


def test_danger_levels_are_valid():
    valid = {"critical", "high", "medium"}
    for c in CONTAMINANTS:
        assert c["danger_level"] in valid, f"{c['id']} has invalid danger_level"


def test_trichoderma_has_two_stages():
    trich = next(c for c in CONTAMINANTS if c["id"] == "trichoderma")
    assert len(trich["stages"]) == 2
    assert trich["stages"][0]["name"] == "Early white"
    assert trich["stages"][1]["name"] == "Green sporulation"


def test_contaminant_ids_are_unique():
    ids = [c["id"] for c in CONTAMINANTS]
    assert len(ids) == len(set(ids))


def test_system_prompt_is_nonempty():
    assert len(IDENTIFICATION_SYSTEM_PROMPT) > 100
    assert "contamination_detected" in IDENTIFICATION_SYSTEM_PROMPT
    assert "contaminants" in IDENTIFICATION_SYSTEM_PROMPT
    assert "health_assessment" in IDENTIFICATION_SYSTEM_PROMPT
    assert "recommendations" in IDENTIFICATION_SYSTEM_PROMPT


def test_library_list_endpoint(client):
    resp = client.get("/api/contamination/library")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 7
    ids = {c["id"] for c in data}
    assert "trichoderma" in ids
    assert "cobweb" in ids
    assert "black_mold" in ids
    assert "bacterial" in ids
    assert "lipstick_mold" in ids
    assert "penicillium" in ids
    assert "wet_spot" in ids


def test_library_detail_endpoint(client):
    resp = client.get("/api/contamination/library/trichoderma")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "trichoderma"
    assert data["common_name"] == "Green Mold"
    assert data["danger_level"] == "high"
    assert len(data["stages"]) == 2


def test_library_detail_404(client):
    resp = client.get("/api/contamination/library/nonexistent")
    assert resp.status_code == 404
