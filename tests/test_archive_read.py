import json
import zipfile

import pytest
from wxcc_export import archive


def build(tmp_path, **over):
    p = tmp_path / "t-export.zip"
    args = dict(
        source={"orgId": "O1", "orgName": "src"},
        cc={"site": {"entity": "site", "count": 1,
                     "items": [{"id": "s1", "name": "Denver"}], "error": None},
            "team": {"entity": "team", "count": 0, "items": [], "error": None}},
        children={"address-book": {"ab1": {"parent_id": "ab1", "count": 1,
                                           "items": [{"id": "e1"}], "error": None}}},
        audio={"a1": {"bytes": b"RIFF", "name": "welcome.wav"}},
        flows={"flows": {"f1": {"meta": {"id": "f1"}, "document": {"name": "Main"}}},
               "subflows": {}, "errors": [], "projectId": "O1"},
        functions={"functions": {"fn1": {"meta": {"id": "fn1"},
                                         "document": {"code": "x"}}},
                   "errors": []},
        calling={"locations": [{"id": "L1"}],
                 "objects": {"hunt-groups": {"object": "hunt-groups", "count": 1,
                                             "items": [{"id": "H1"}], "error": None}},
                 "error": None},
        users={"rows": [{"email": "a@x.com"}], "csv": "email\na@x.com\n"},
    )
    args.update(over)
    archive.write_export(p, **args)
    return p


def test_reader_exposes_the_manifest(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert r.manifest["source"]["orgName"] == "src"
    r.close()


def test_reader_rejects_an_unknown_schema_version(tmp_path):
    p = tmp_path / "bad.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("manifest.json", json.dumps({"schemaVersion": 99}))
    with pytest.raises(archive.IncompatibleArchive) as exc:
        archive.ArchiveReader(p)
    assert "99" in str(exc.value)


def test_reader_rejects_a_zip_with_no_manifest(tmp_path):
    p = tmp_path / "bad.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(archive.IncompatibleArchive):
        archive.ArchiveReader(p)


def test_entity_items_returns_the_stored_rows(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert r.entity_items("site")[0]["name"] == "Denver"
    r.close()


def test_entity_items_of_an_absent_entity_is_empty(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert r.entity_items("skill") == []
    r.close()


def test_children_are_keyed_by_parent(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert r.children("address-book")["ab1"][0]["id"] == "e1"
    r.close()


def test_audio_blob_round_trips(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert r.audio_blob("a1") == b"RIFF"
    r.close()


def test_flows_are_readable_by_bucket(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert r.flows("flows")["f1"]["document"]["name"] == "Main"
    assert r.flows("subflows") == {}
    r.close()


def test_functions_are_readable(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert r.functions()["fn1"]["document"]["code"] == "x"
    r.close()


def test_calling_items_are_readable(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert r.calling_items("hunt-groups")[0]["id"] == "H1"
    r.close()


def test_available_selections_skips_empty_sections(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    keys = {s["key"] for s in archive.available_selections(r.manifest)}
    assert "cc:site" in keys
    assert "cc:team" not in keys           # count 0 - nothing to import
    r.close()


def test_available_selections_labels_the_spec_group(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    site = next(s for s in archive.available_selections(r.manifest)
                if s["key"] == "cc:site")
    assert site["group"] == "User Management"
    r.close()


def test_parse_selection_all_returns_everything_available(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    keys = archive.parse_selection("all", r.manifest)
    assert "cc:site" in keys and "flows:flows" in keys
    r.close()


def test_parse_selection_by_section(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    keys = archive.parse_selection("cc", r.manifest)
    assert all(k.startswith("cc:") for k in keys)
    r.close()


def test_parse_selection_accepts_explicit_keys(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert archive.parse_selection("cc:site,flows:functions", r.manifest) == [
        "cc:site", "flows:functions"]
    r.close()


def test_parse_selection_rejects_an_unknown_key(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    with pytest.raises(ValueError) as exc:
        archive.parse_selection("cc:nonsense", r.manifest)
    assert "cc:nonsense" in str(exc.value)
    r.close()
