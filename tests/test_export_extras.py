import csv
import io

from wxcc_export import export_cc
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


def test_export_children_keys_by_parent_id(transport):
    transport.add("GET /organization/ORG1/v2/address-book/ab1/entry",
                  body={"data": [{"id": "e1", "name": "Support"}]})
    out = export_cc.export_children(make(transport), "address-book", ["ab1"])
    assert out["ab1"]["count"] == 1
    assert out["ab1"]["items"][0]["name"] == "Support"


def test_export_children_records_a_failure_per_parent(transport):
    transport.add("GET /organization/ORG1/v2/address-book/ab1/entry",
                  status=403, body={})
    out = export_cc.export_children(make(transport), "address-book", ["ab1"])
    assert out["ab1"]["error"] is not None


def test_export_children_of_an_entity_without_children_is_empty(transport):
    assert export_cc.export_children(make(transport), "site", ["s1"]) == {}


def test_export_audio_binaries_downloads_by_url(transport):
    transport.add("GET /audio/a1.wav", body=b"RIFFdata", content_type="audio/wav")
    items = [{"id": "a1", "name": "welcome.wav", "url": "/audio/a1.wav"}]
    blobs, errors = export_cc.export_audio_binaries(make(transport), items)
    assert blobs["a1"] == b"RIFFdata"
    assert errors == []


def test_export_audio_binaries_records_a_failed_download(transport):
    transport.add("GET /audio/a1.wav", status=404, body=b"")
    items = [{"id": "a1", "name": "welcome.wav", "url": "/audio/a1.wav"}]
    blobs, errors = export_cc.export_audio_binaries(make(transport), items)
    assert blobs == {}
    assert "a1" in errors[0]


def test_export_audio_binaries_reports_an_item_with_no_download_url(transport):
    items = [{"id": "a1", "name": "welcome.wav"}]
    blobs, errors = export_cc.export_audio_binaries(make(transport), items)
    assert blobs == {}
    assert "no download url" in errors[0]


def test_users_manifest_resolves_ids_to_names():
    users = [{"id": "u1", "email": "a@x.com", "firstName": "Ann",
              "lastName": "Lee", "siteId": "s1", "teamIds": ["t1"],
              "skillProfileId": "sp1"}]
    lookup = {"site": {"s1": "Denver"}, "team": {"t1": "Billing"},
              "skill-profile": {"sp1": "Tier1"}}
    rows, csv_text = export_cc.build_users_manifest(users, lookup)
    assert rows[0]["site"] == "Denver"
    assert rows[0]["teams"] == "Billing"
    assert rows[0]["skillProfile"] == "Tier1"


def test_users_manifest_keeps_the_raw_id_when_the_name_is_unknown():
    users = [{"id": "u1", "email": "a@x.com", "siteId": "s9"}]
    rows, _ = export_cc.build_users_manifest(users, {"site": {}})
    assert rows[0]["site"] == "s9"


def test_users_manifest_csv_has_a_header_and_one_row_per_user():
    users = [{"id": "u1", "email": "a@x.com"}, {"id": "u2", "email": "b@x.com"}]
    _, csv_text = export_cc.build_users_manifest(users, {})
    parsed = list(csv.reader(io.StringIO(csv_text)))
    assert parsed[0][0] == "email"
    assert len(parsed) == 3


def test_users_manifest_handles_a_user_with_no_assignments():
    rows, _ = export_cc.build_users_manifest([{"id": "u1", "email": "a@x.com"}], {})
    assert rows[0]["site"] == ""
    assert rows[0]["teams"] == ""
