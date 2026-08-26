import pytest
from wxcc_export import idmap, importer
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


def test_dry_run_writes_nothing(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    res = importer.import_entity(make(transport), "site",
                                 [{"id": "s1", "name": "Denver"}],
                                 idmap.IdMap(), "skip", confirm=False)
    assert res.created == []
    assert res.planned[0]["action"] == "create"
    assert all(c["method"] == "GET" for c in transport.calls)


def test_confirmed_create_posts_to_the_unversioned_path(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    transport.add("POST /organization/ORG1/site", status=201,
                  body={"id": "s9", "name": "Denver"})
    transport.add("GET /organization/ORG1/site/s9",
                  body={"id": "s9", "name": "Denver"})
    res = importer.import_entity(make(transport), "site",
                                 [{"id": "s1", "name": "Denver"}],
                                 idmap.IdMap(), "skip", confirm=True)
    assert res.created == ["s9"]
    posts = [c for c in transport.calls if c["method"] == "POST"]
    # POST v2/site is NOT the create endpoint.
    assert posts[0]["url"].endswith("/organization/ORG1/site")


def test_create_records_the_id_mapping(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    transport.add("POST /organization/ORG1/site", status=201, body={"id": "s9"})
    transport.add("GET /organization/ORG1/site/s9", body={"id": "s9"})
    m = idmap.IdMap()
    importer.import_entity(make(transport), "site",
                           [{"id": "s1", "name": "Denver"}], m, "skip",
                           confirm=True)
    assert m.get("s1") == "s9"


def test_skip_still_maps_the_source_id_to_the_existing_object(transport):
    transport.add("GET /organization/ORG1/v2/site",
                  body={"data": [{"id": "s9", "name": "Denver"}]})
    m = idmap.IdMap()
    res = importer.import_entity(make(transport), "site",
                                 [{"id": "s1", "name": "Denver"}], m, "skip",
                                 confirm=True)
    assert res.skipped == ["s1"]
    # Otherwise every reference to s1 would dangle.
    assert m.get("s1") == "s9"


def test_references_are_remapped_before_the_write(transport):
    transport.add("GET /organization/ORG1/v2/team", body={"data": []})
    transport.add("POST /organization/ORG1/team", status=201, body={"id": "t9"})
    transport.add("GET /organization/ORG1/team/t9", body={"id": "t9"})
    m = idmap.IdMap()
    m.record("s1", "s9")
    importer.import_entity(make(transport), "team",
                           [{"id": "t1", "name": "Billing", "siteId": "s1"}],
                           m, "skip", confirm=True)
    post = next(c for c in transport.calls if c["method"] == "POST")
    assert b'"siteId": "s9"' in post["data"]


def test_the_objects_own_id_is_not_sent_on_create(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    transport.add("POST /organization/ORG1/site", status=201, body={"id": "s9"})
    transport.add("GET /organization/ORG1/site/s9", body={"id": "s9"})
    importer.import_entity(make(transport), "site",
                           [{"id": "s1", "name": "Denver"}], idmap.IdMap(),
                           "skip", confirm=True)
    post = next(c for c in transport.calls if c["method"] == "POST")
    assert b'"id"' not in post["data"]


def test_a_failed_create_is_recorded_with_the_api_reason(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    transport.add("POST /organization/ORG1/site", status=400,
                  body={"message": "multimediaProfileId is required"})
    res = importer.import_entity(make(transport), "site",
                                 [{"id": "s1", "name": "Denver"}],
                                 idmap.IdMap(), "skip", confirm=True)
    assert res.created == []
    assert "multimediaProfileId" in res.failed[0]["detail"]


def test_one_failure_does_not_abort_the_rest(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    transport.add("POST /organization/ORG1/site", status=400, body={"m": "no"})
    transport.add("POST /organization/ORG1/site", status=201, body={"id": "s9"})
    transport.add("GET /organization/ORG1/site/s9", body={"id": "s9"})
    res = importer.import_entity(
        make(transport), "site",
        [{"id": "s1", "name": "A"}, {"id": "s2", "name": "B"}],
        idmap.IdMap(), "skip", confirm=True)
    assert len(res.failed) == 1 and res.created == ["s9"]


def test_verify_write_reports_a_silently_ignored_field(transport):
    transport.add("GET /organization/ORG1/site/s9",
                  body={"id": "s9", "name": "Denver", "active": False})
    missing = importer.verify_write(make(transport), "site", "s9",
                                    {"name": "Denver", "active": True})
    assert "active" in missing


def test_verify_write_is_clean_when_everything_landed(transport):
    transport.add("GET /organization/ORG1/site/s9",
                  body={"id": "s9", "name": "Denver", "active": True})
    assert importer.verify_write(make(transport), "site", "s9",
                                 {"name": "Denver", "active": True}) == []


def test_verify_write_ignores_server_assigned_fields(transport):
    transport.add("GET /organization/ORG1/site/s9",
                  body={"id": "s9", "name": "D", "createdTime": 123,
                        "version": 1})
    assert importer.verify_write(make(transport), "site", "s9",
                                 {"name": "D"}) == []


def test_an_unverified_write_is_surfaced_not_counted_as_success(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    transport.add("POST /organization/ORG1/site", status=201, body={"id": "s9"})
    transport.add("GET /organization/ORG1/site/s9",
                  body={"id": "s9", "name": "Denver", "active": False})
    res = importer.import_entity(make(transport), "site",
                                 [{"id": "s1", "name": "Denver",
                                   "active": True}],
                                 idmap.IdMap(), "skip", confirm=True)
    assert res.created == ["s9"]
    assert res.unverified and "active" in res.unverified[0]["fields"]


def test_dangling_references_are_reported(transport):
    transport.add("GET /organization/ORG1/v2/team", body={"data": []})
    res = importer.import_entity(
        make(transport), "team",
        [{"id": "t1", "name": "Billing",
          "siteId": "22222222-2222-2222-2222-222222222222"}],
        idmap.IdMap(), "skip", confirm=False)
    assert "22222222-2222-2222-2222-222222222222" in res.dangling


def test_a_read_only_entity_is_refused(transport):
    res = importer.import_entity(make(transport), "user",
                                 [{"id": "u1", "name": "Ann"}],
                                 idmap.IdMap(), "skip", confirm=True)
    assert res.failed[0]["detail"].startswith("user is read-only")
    assert transport.calls == []
