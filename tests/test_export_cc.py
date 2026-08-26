import pytest
from wxcc_export import export_cc
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


def test_export_entity_returns_the_items(transport):
    transport.add("GET /organization/ORG1/v2/site",
                  body={"data": [{"id": "s1", "name": "Denver"}]})
    result = export_cc.export_entity(make(transport), "site")
    assert result["count"] == 1
    assert result["items"][0]["name"] == "Denver"
    assert result["error"] is None


def test_export_entity_records_an_http_error_without_raising(transport):
    transport.add("GET /organization/ORG1/v2/site", status=403,
                  body={"message": "forbidden"})
    result = export_cc.export_entity(make(transport), "site")
    assert result["count"] == 0
    assert "403" in result["error"]


def test_export_entity_error_is_never_silently_empty(transport):
    transport.add("GET /organization/ORG1/v2/site", status=500, body={})
    result = export_cc.export_entity(make(transport), "site")
    # A failed entity must not be indistinguishable from a genuinely empty one.
    assert result["error"] is not None
    assert result["items"] == []


def test_export_all_continues_past_a_failing_entity(transport):
    transport.add("GET /organization/ORG1/v2/site", status=403, body={})
    transport.add("GET /organization/ORG1/v2/team",
                  body={"data": [{"id": "t1", "name": "Billing"}]})
    out = export_cc.export_all(make(transport), ["site", "team"])
    assert out["site"]["error"] is not None
    assert out["team"]["count"] == 1


def test_export_all_reports_progress(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    seen = []
    export_cc.export_all(make(transport), ["site"],
                         on_progress=lambda e, r: seen.append(e))
    assert seen == ["site"]


def test_strip_volatile_removes_audit_fields():
    item = {"id": "s1", "name": "Denver", "version": 3,
            "createdTime": 1, "lastUpdatedTime": 2, "createdBy": "u"}
    out = export_cc.strip_volatile(item)
    assert "version" not in out and "lastUpdatedTime" not in out
    assert out["id"] == "s1" and out["name"] == "Denver"


def test_strip_volatile_keeps_created_time_for_the_default_heuristic():
    out = export_cc.strip_volatile({"id": "s1", "createdTime": 1700000000000})
    assert out["createdTime"] == 1700000000000


def test_tag_likely_defaults_marks_the_provisioning_cluster():
    base = 1700000000000                       # epoch millis
    items = [
        {"id": "a", "createdTime": base},
        {"id": "b", "createdTime": base + 5_000},        # +5s  -> default
        {"id": "c", "createdTime": base + 600_000},      # +10m -> not default
    ]
    tagged = export_cc.tag_likely_defaults(items)
    flags = {i["id"]: i["likely_default"] for i in tagged}
    assert flags == {"a": True, "b": True, "c": False}


def test_tag_likely_defaults_is_a_noop_without_created_time():
    items = [{"id": "a"}, {"id": "b"}]
    tagged = export_cc.tag_likely_defaults(items)
    assert all("likely_default" not in i for i in tagged)


def test_tag_likely_defaults_handles_an_empty_list():
    assert export_cc.tag_likely_defaults([]) == []
