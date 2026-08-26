import json

import pytest
from wxcc_export.client import ApiClient, ApiError

BASE = "https://api.wxcc-us1.cisco.com"


def make(transport, org_id="ORG1"):
    return ApiClient(BASE, "TOKEN", org_id=org_id, transport=transport)


def test_url_substitutes_the_org_id(transport):
    c = make(transport)
    assert c.url("organization/{orgId}/v2/team") == f"{BASE}/organization/ORG1/v2/team"


def test_url_raises_when_org_id_is_needed_but_unknown(transport):
    c = ApiClient(BASE, "TOKEN", org_id=None, transport=transport)
    with pytest.raises(ApiError) as exc:
        c.url("organization/{orgId}/v2/team")
    assert "WXCC_ORG_ID" in str(exc.value)


def test_authorization_header_is_sent(transport):
    transport.add("GET /organization/ORG1/v2/team", body={"data": []})
    make(transport).json("GET", "organization/{orgId}/v2/team")
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer TOKEN"


def test_json_parses_the_body(transport):
    transport.add("GET /organization/ORG1/v2/team", body={"data": [{"id": "t1"}]})
    status, body = make(transport).json("GET", "organization/{orgId}/v2/team")
    assert status == 200
    assert body["data"][0]["id"] == "t1"


def test_json_returns_text_when_the_body_is_not_json(transport):
    transport.add("GET /ping", body="pong", content_type="text/plain")
    status, body = make(transport).json("GET", "ping")
    assert (status, body) == (200, "pong")


def test_list_all_follows_meta_links_next(transport):
    transport.add("GET /organization/ORG1/v2/team",
                  body={"data": [{"id": "a"}],
                        "meta": {"links": {"next": "/organization/ORG1/v2/team?page=1"}}})
    transport.add("GET /organization/ORG1/v2/team?page=1",
                  body={"data": [{"id": "b"}], "meta": {"links": {}}})
    items = make(transport).list_all("organization/{orgId}/v2/team")
    assert [i["id"] for i in items] == ["a", "b"]


def test_list_all_stops_on_a_page_without_a_next_link(transport):
    transport.add("GET /organization/ORG1/v2/team", body={"data": [{"id": "a"}]})
    assert len(make(transport).list_all("organization/{orgId}/v2/team")) == 1


def test_list_all_accepts_a_bare_array_response(transport):
    # Some Calling endpoints return a top-level list rather than meta+data.
    transport.add("GET /telephony/config/announcements", body=[{"id": "a"}])
    assert make(transport).list_all("telephony/config/announcements") == [{"id": "a"}]


def test_list_all_raises_on_an_error_page(transport):
    transport.add("GET /organization/ORG1/v2/team", status=403,
                  body={"message": "forbidden"})
    with pytest.raises(ApiError) as exc:
        make(transport).list_all("organization/{orgId}/v2/team")
    assert exc.value.status == 403


def test_retry_on_429_then_success(transport, monkeypatch):
    monkeypatch.setattr("wxcc_export.client.time.sleep", lambda _s: None)
    transport.add("GET /organization/ORG1/v2/team", status=429, body={"m": "slow down"})
    transport.add("GET /organization/ORG1/v2/team", body={"data": []})
    status, _ = make(transport).json("GET", "organization/{orgId}/v2/team")
    assert status == 200
    assert len(transport.calls) == 2


def test_retry_gives_up_after_the_limit(transport, monkeypatch):
    monkeypatch.setattr("wxcc_export.client.time.sleep", lambda _s: None)
    for _ in range(6):
        transport.add("GET /organization/ORG1/v2/team", status=429, body={})
    status, _ = make(transport).json("GET", "organization/{orgId}/v2/team")
    assert status == 429


def test_get_bytes_returns_the_raw_body_and_content_type(transport):
    transport.add("GET /audio", body=b"RIFFdata", content_type="audio/wav")
    status, data, ctype = make(transport).get_bytes("audio")
    assert (status, data, ctype) == (200, b"RIFFdata", "audio/wav")


def test_multipart_sets_a_boundary_content_type(transport):
    transport.add("POST /upload", body={"ok": True})
    make(transport).multipart("POST", "upload",
                              [("file", "a.wav", "audio/wav", b"RIFF")])
    ctype = transport.calls[0]["headers"]["Content-Type"]
    assert ctype.startswith("multipart/form-data; boundary=")


def test_multipart_body_contains_the_named_parts(transport):
    transport.add("POST /upload", body={"ok": True})
    make(transport).multipart("POST", "upload", [
        ("file", "a.wav", "audio/wav", b"RIFF"),
        ("info", None, "application/json", b'{"n":1}'),
    ])
    data = transport.calls[0]["data"]
    assert b'name="file"; filename="a.wav"' in data
    assert b'name="info"' in data
    assert b'{"n":1}' in data
