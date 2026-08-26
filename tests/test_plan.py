import pytest
from wxcc_export import plan
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


def test_order_puts_a_dependency_before_its_dependent():
    ordered = plan.order_entities(["team", "site", "multimedia-profile"])
    assert ordered.index("multimedia-profile") < ordered.index("site")
    assert ordered.index("site") < ordered.index("team")


def test_order_pulls_in_nothing_that_was_not_requested():
    # Ordering must not silently widen the import to unrequested entities.
    assert set(plan.order_entities(["team", "site"])) == {"team", "site"}


def test_order_is_stable_for_independent_entities():
    a = plan.order_entities(["skill", "work-type"])
    b = plan.order_entities(["skill", "work-type"])
    assert a == b


def test_order_handles_the_full_entity_set():
    ordered = plan.order_entities(list(plan.registry.CC_ENTITIES))
    for entity, spec in plan.registry.CC_ENTITIES.items():
        for dep in spec["deps"]:
            assert ordered.index(dep) < ordered.index(entity)


def test_order_raises_on_a_cycle(monkeypatch):
    fake = {"a": {"deps": ["b"]}, "b": {"deps": ["a"]}}
    monkeypatch.setattr(plan.registry, "CC_ENTITIES", fake)
    with pytest.raises(plan.CircularDependency):
        plan.order_entities(["a", "b"])


def test_index_existing_keys_case_insensitively(transport):
    transport.add("GET /organization/ORG1/v2/site",
                  body={"data": [{"id": "s1", "name": "Denver"}]})
    idx = plan.index_existing(make(transport), "site")
    assert idx["denver"]["id"] == "s1"


def test_index_existing_is_empty_when_the_list_fails(transport):
    transport.add("GET /organization/ORG1/v2/site", status=403, body={})
    assert plan.index_existing(make(transport), "site") == {}


def test_classify_creates_a_new_name():
    out = plan.classify([{"id": "s1", "name": "Boulder"}], {}, "skip")
    assert out[0]["action"] == "create"


def test_classify_skips_a_name_that_already_exists():
    existing = {"denver": {"id": "s9", "name": "Denver"}}
    out = plan.classify([{"id": "s1", "name": "Denver"}], existing, "skip")
    assert out[0]["action"] == "skip"
    assert out[0]["existing"]["id"] == "s9"


def test_classify_skip_still_records_the_mapping_target():
    # A skipped object still exists in the target, so references to the source
    # id must remap onto the EXISTING object rather than dangle.
    existing = {"denver": {"id": "s9"}}
    out = plan.classify([{"id": "s1", "name": "Denver"}], existing, "skip")
    assert out[0]["existing"]["id"] == "s9"


def test_classify_update_on_conflict():
    existing = {"denver": {"id": "s9"}}
    out = plan.classify([{"id": "s1", "name": "Denver"}], existing, "update")
    assert out[0]["action"] == "update"


def test_classify_rename_on_conflict_suffixes_the_name():
    existing = {"denver": {"id": "s9"}}
    out = plan.classify([{"id": "s1", "name": "Denver"}], existing, "rename")
    assert out[0]["action"] == "rename"
    assert out[0]["item"]["name"] == "Denver (imported)"


def test_classify_rename_avoids_a_second_collision():
    existing = {"denver": {"id": "s9"}, "denver (imported)": {"id": "s8"}}
    out = plan.classify([{"id": "s1", "name": "Denver"}], existing, "rename")
    assert out[0]["item"]["name"] == "Denver (imported 2)"


def test_classify_reports_an_item_with_no_name():
    out = plan.classify([{"id": "s1"}], {}, "skip")
    assert out[0]["action"] == "skip"
    assert "no name" in out[0]["reason"]


def test_classify_rejects_an_unknown_conflict_policy():
    with pytest.raises(ValueError):
        plan.classify([{"id": "s1", "name": "X"}], {}, "explode")
