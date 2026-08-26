import json
import zipfile

import pytest
from wxcc_export import archive


def test_writer_stores_json_that_round_trips(tmp_path):
    p = tmp_path / "out.zip"
    w = archive.ArchiveWriter(p)
    w.add_json("cc/site.json", {"entity": "site", "items": [{"id": "s1"}]})
    w.close()
    with zipfile.ZipFile(p) as z:
        doc = json.loads(z.read("cc/site.json"))
    assert doc["items"][0]["id"] == "s1"


def test_writer_stores_raw_bytes(tmp_path):
    p = tmp_path / "out.zip"
    w = archive.ArchiveWriter(p)
    w.add_bytes("cc/audio/a1__welcome.wav", b"RIFF")
    w.close()
    with zipfile.ZipFile(p) as z:
        assert z.read("cc/audio/a1__welcome.wav") == b"RIFF"


def test_writer_rejects_a_path_that_escapes_the_archive(tmp_path):
    w = archive.ArchiveWriter(tmp_path / "out.zip")
    with pytest.raises(ValueError):
        w.add_text("../evil.txt", "x")
    w.close()


def test_manifest_records_the_schema_version_and_source():
    m = archive.build_manifest({"orgId": "O1", "orgName": "sandbox"}, {}, [])
    assert m["schemaVersion"] == archive.SCHEMA_VERSION
    assert m["source"]["orgName"] == "sandbox"


def test_manifest_carries_an_iso_timestamp():
    m = archive.build_manifest({"orgId": "O1"}, {}, [])
    assert m["exportedAt"].endswith("Z")


def test_manifest_lists_every_error():
    errs = [{"section": "calling", "object": "queues", "detail": "HTTP 403"}]
    assert archive.build_manifest({}, {}, errs)["errors"] == errs


def test_manifest_names_the_unsupported_objects():
    m = archive.build_manifest({}, {}, [])
    assert set(m["unsupported"]) == {"Channels", "Surveys"}


def test_unsupported_md_explains_each_object():
    text = archive.render_unsupported([])
    assert "Channels" in text and "Surveys" in text
    assert "Webex Connect" in text          # the actual reason, not a shrug


def test_unsupported_md_also_lists_runtime_errors():
    errs = [{"section": "cc", "object": "site", "detail": "HTTP 403 forbidden"}]
    text = archive.render_unsupported(errs)
    assert "site" in text and "403" in text


def test_unsupported_md_says_so_when_nothing_failed():
    text = archive.render_unsupported([])
    assert "No errors" in text


def test_write_export_produces_a_readable_archive(tmp_path):
    p = tmp_path / "sandbox-export.zip"
    manifest = archive.write_export(
        p,
        source={"orgId": "O1", "orgName": "sandbox", "subscriptionType": "TRIAL",
                "apiBase": "https://api.wxcc-us1.cisco.com"},
        cc={"site": {"entity": "site", "count": 1,
                     "items": [{"id": "s1", "name": "Denver"}], "error": None}},
        children={}, audio={},
        flows={"flows": {}, "subflows": {}, "errors": [], "projectId": "O1"},
        functions={"functions": {}, "errors": []},
        calling={"locations": [], "objects": {}, "error": None},
        users={"rows": [{"email": "a@x.com"}], "csv": "email\na@x.com\n"},
    )
    with zipfile.ZipFile(p) as z:
        names = set(z.namelist())
        assert "manifest.json" in names
        assert "UNSUPPORTED.md" in names
        assert "cc/site.json" in names
        assert "users/users.csv" in names
        stored = json.loads(z.read("manifest.json"))
    assert stored == manifest
    assert manifest["sections"]["cc"]["entities"]["site"]["count"] == 1


def test_write_export_promotes_entity_errors_into_the_manifest(tmp_path):
    p = tmp_path / "out.zip"
    manifest = archive.write_export(
        p, source={"orgId": "O1"},
        cc={"site": {"entity": "site", "count": 0, "items": [],
                     "error": "HTTP 403 forbidden"}},
        children={}, audio={},
        flows={"flows": {}, "subflows": {}, "errors": []},
        functions={"functions": {}, "errors": []},
        calling={"locations": [], "objects": {}, "error": None},
        users={"rows": [], "csv": ""},
    )
    assert any(e["object"] == "site" for e in manifest["errors"])


def test_write_export_stores_audio_bytes_under_a_collision_safe_name(tmp_path):
    p = tmp_path / "out.zip"
    archive.write_export(
        p, source={}, cc={}, children={},
        audio={"a1": {"bytes": b"RIFF", "name": "welcome.wav"}},
        flows={"flows": {}, "subflows": {}, "errors": []},
        functions={"functions": {}, "errors": []},
        calling={"locations": [], "objects": {}, "error": None},
        users={"rows": [], "csv": ""},
    )
    with zipfile.ZipFile(p) as z:
        assert "cc/audio/a1__welcome.wav" in z.namelist()
