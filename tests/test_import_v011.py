"""Regression tests for the six import defects found from a real dry run on
2026-09-25 (ericstewart-6xpy archive imported into ericstewart-0xrm)."""

import json
import zipfile

from wxcc_export import archive, export_flows, idmap, importer
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"
PROJ = export_flows.FLOWS_PROJECT_ID
FLOW_IMPORT = f"POST /ORG1/project/{PROJ}/v2/flows:import?overwrite=false&flowType=FLOW"
FLOW_LIST = (f"GET /ORG1/project/{PROJ}/flows?flowType=FLOW"
             "&includePagination=true&size=100")


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


class Reader:
    """Just enough of ArchiveReader for run_import."""

    def __init__(self, cc=None, flows=None, source_org="SRCORG"):
        self._cc = cc or {}
        self._flows = {"flows": flows or {}, "subflows": {}}
        self.manifest = {"source": {"orgId": source_org}}

    def entity_items(self, entity):
        return self._cc.get(entity, [])

    def flows(self, bucket):
        return self._flows.get(bucket, {})

    def functions(self):
        return {}

    def calling_items(self, name):
        return []

    def source_ids(self):
        ids = {i["id"] for items in self._cc.values() for i in items}
        ids |= set(self._flows["flows"])
        return ids | {self.manifest["source"]["orgId"]}


def bodies(transport, method):
    return [json.loads(c["data"]) for c in transport.calls
            if c["method"] == method and c["data"]]


# --- 1. a dry run shows what it WOULD do --------------------------------------

def test_dry_run_counts_planned_creates_instead_of_zero(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    res = importer.import_entity(make(transport), "site",
                                 [{"id": "s1", "name": "Denver"}],
                                 idmap.IdMap(), "skip", confirm=False)
    assert res.would_create == ["s1"]
    assert "1 would be created" in res.summary()


def test_dry_run_does_not_report_references_to_objects_it_would_create(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    transport.add("GET /organization/ORG1/v2/team", body={"data": []})
    reader = Reader(cc={"site": [{"id": "s1", "name": "Denver"}],
                        "team": [{"id": "t1", "name": "Billing", "siteId": "s1"}]})
    results = importer.run_import(make(transport), make(transport), reader,
                                  ["cc:site", "cc:team"], "skip", False, "TGTORG")
    assert results["team"].dangling == set()


# --- 2. only real archive ids count as dangling --------------------------------

def test_names_and_catalog_ids_are_not_dangling_references():
    m = idmap.IdMap()
    m.known_source_ids = {"11111111-1111-1111-1111-111111111111"}
    payload = {"queueId": "11111111-1111-1111-1111-111111111111",
               "name": "GetQueueInfo_d81", "event": "ContactAniUpdated",
               "activityId": "5fabaf1f8bf5b65b82f0706f"}
    assert m.unmapped(payload) == {"11111111-1111-1111-1111-111111111111"}


def test_a_mapped_archive_id_is_not_dangling():
    m = idmap.IdMap()
    m.known_source_ids = {"q1"}
    m.record("q1", "q9")
    assert m.unmapped({"queueId": "q1"}) == set()


# --- 3. bookkeeping never reaches the API; the org id is remapped --------------

def test_default_basis_is_never_sent_on_create(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    transport.add("POST /organization/ORG1/site", status=201, body={"id": "s9"})
    transport.add("GET /organization/ORG1/site/s9", body={"id": "s9", "name": "Denver"})
    res = importer.import_entity(
        make(transport), "site",
        [{"id": "s1", "name": "Denver", "likely_default": False,
          "default_basis": "createdTime-heuristic"}],
        idmap.IdMap(), "skip", confirm=True)
    assert "default_basis" not in bodies(transport, "POST")[0]
    assert res.unverified == []


def test_source_org_id_in_a_flow_is_rewritten_to_the_target_org(transport):
    transport.add(FLOW_IMPORT, status=200, body={"id": "F9"})
    transport.add(FLOW_LIST, body={"data": [{"id": "F9", "name": "Main"}]})
    reader = Reader(flows={"f1": {"meta": {"name": "Main"},
                                  "document": {"name": "Main", "orgId": "SRCORG"}}})
    importer.run_import(make(transport), make(transport), reader,
                        ["flows:flows"], "skip", True, "TGTORG")
    assert bodies(transport, "POST")[0]["orgId"] == "TGTORG"


# --- 4. users are a manual step, not a failure --------------------------------

def test_read_only_users_are_a_manual_step_not_a_failure(transport):
    transport.add("GET /organization/ORG1/v2/user", body={"data": []})
    res = importer.import_entity(make(transport), "user",
                                 [{"id": "u1", "email": "ann@example.com"}],
                                 idmap.IdMap(), "skip", confirm=True)
    assert res.failed == []
    assert [m["id"] for m in res.manual] == ["u1"]
    assert "by hand" in res.summary()
    assert all(c["method"] == "GET" for c in transport.calls)


def test_team_members_are_remapped_to_users_already_in_the_target(transport):
    transport.add("GET /organization/ORG1/v2/user",
                  body={"data": [{"id": "U9", "email": "ann@example.com"}]})
    transport.add("GET /organization/ORG1/v2/team", body={"data": []})
    reader = Reader(cc={"user": [{"id": "u1", "email": "ann@example.com"}],
                        "team": [{"id": "t1", "name": "Billing",
                                  "userIds": ["u1"]}]})
    results = importer.run_import(make(transport), make(transport), reader,
                                  ["cc:team", "cc:user"], "skip", False, "TGTORG")
    assert results["team"].dangling == set()


# --- 5. entry-point <-> flow cycle ----------------------------------------------

def _ep_routes(transport):
    transport.add("GET /organization/ORG1/v2/entry-point", body={"data": []})
    transport.add("POST /organization/ORG1/entry-point", status=201,
                  body={"id": "e9", "name": "Main EP"})
    transport.add("GET /organization/ORG1/entry-point/e9",
                  body={"id": "e9", "name": "Main EP", "flowTagId": "Latest"})
    transport.add("PUT /organization/ORG1/entry-point/e9", status=200,
                  body={"id": "e9"})


def test_entry_point_is_created_without_flow_then_linked_after_flows(transport):
    _ep_routes(transport)
    transport.add(FLOW_IMPORT, status=200, body={"id": "F9"})
    transport.add(FLOW_LIST, body={"data": [{"id": "F9", "name": "Main"}]})
    reader = Reader(
        cc={"entry-point": [{"id": "e1", "name": "Main EP", "flowId": "f1",
                             "flowTagId": "Latest"}]},
        flows={"f1": {"meta": {"name": "Main"}, "document": {"name": "Main"}}})
    results = importer.run_import(make(transport), make(transport), reader,
                                  ["cc:entry-point", "flows:flows"],
                                  "skip", True, "TGTORG")
    writes = [c for c in transport.calls if c["method"] in ("POST", "PUT")]
    assert "flowId" not in json.loads(writes[0]["data"])       # EP created first
    assert writes[-1]["method"] == "PUT" and writes[-1]["url"].endswith("/entry-point/e9")
    assert bodies(transport, "PUT")[-1]["flowId"] == "F9"
    links = results["entry-point:links"]
    assert links.updated == ["e9"] and links.failed == []


def test_flow_id_is_mapped_by_name_when_import_returns_no_id(transport):
    _ep_routes(transport)
    transport.add(FLOW_IMPORT, status=200, body={})
    transport.add(FLOW_LIST, body={"data": [{"id": "F7", "name": "Main"}]})
    reader = Reader(
        cc={"entry-point": [{"id": "e1", "name": "Main EP", "flowId": "f1"}]},
        flows={"f1": {"meta": {"name": "Main"}, "document": {"name": "Main"}}})
    importer.run_import(make(transport), make(transport), reader,
                        ["cc:entry-point", "flows:flows"], "skip", True, "TGTORG")
    assert bodies(transport, "PUT")[-1]["flowId"] == "F7"


def test_entry_point_whose_flow_was_not_imported_is_reported(transport):
    _ep_routes(transport)
    reader = Reader(
        cc={"entry-point": [{"id": "e1", "name": "Main EP", "flowId": "f1"}]},
        flows={"f1": {"meta": {"name": "Main"}, "document": {"name": "Main"}}})
    results = importer.run_import(make(transport), make(transport), reader,
                                  ["cc:entry-point"], "skip", True, "TGTORG")
    links = results["entry-point:links"]
    assert links.failed and "f1" in links.failed[0]["detail"]
    assert not [c for c in transport.calls if c["method"] == "PUT"]


def test_dry_run_plans_the_flow_link_without_writing(transport):
    transport.add("GET /organization/ORG1/v2/entry-point", body={"data": []})
    reader = Reader(
        cc={"entry-point": [{"id": "e1", "name": "Main EP", "flowId": "f1"}]},
        flows={"f1": {"meta": {"name": "Main"}, "document": {"name": "Main"}}})
    results = importer.run_import(make(transport), make(transport), reader,
                                  ["cc:entry-point", "flows:flows"],
                                  "skip", False, "TGTORG")
    assert results["entry-point:links"].would_update == ["e1"]
    assert all(c["method"] == "GET" for c in transport.calls)
    assert not any(r.dangling for r in results.values())


# --- 6. flow files are native Flow Designer documents --------------------------

def _write(tmp_path):
    p = tmp_path / "t-export.zip"
    archive.write_export(
        p, source={"orgId": "O1", "orgName": "src"}, cc={}, children={}, audio={},
        flows={"flows": {"f1": {"meta": {"id": "f1", "name": "Main Flow"},
                                "document": {"id": "f1", "name": "Main Flow"}}},
               "subflows": {"s1": {"meta": {"id": "s1", "name": "Queue_Record"},
                                   "document": {"id": "s1", "name": "Queue_Record"}}},
               "errors": [], "projectId": PROJ},
        functions={"functions": {"fn1": {"meta": {"id": "fn1", "name": "parse"},
                                         "document": {"name": "parse"}}},
                   "errors": []},
        calling={}, users={})
    return p


def test_each_flow_file_is_the_native_document_named_like_flow_designer(tmp_path):
    with zipfile.ZipFile(_write(tmp_path)) as z:
        doc = json.loads(z.read("flows/subflows/Queue_Record.json"))
        assert doc == {"id": "s1", "name": "Queue_Record"}
        assert "flows/flows/Main_Flow.json" in z.namelist()
        assert json.loads(z.read("flows/functions/parse.json"))["name"] == "parse"


def test_reader_returns_flows_keyed_by_id_from_the_new_layout(tmp_path):
    r = archive.ArchiveReader(_write(tmp_path))
    assert r.flows("subflows") == {"s1": {"meta": {"id": "s1", "name": "Queue_Record"},
                                          "document": {"id": "s1", "name": "Queue_Record"}}}
    assert set(r.functions()) == {"fn1"}
    r.close()


def test_reader_still_reads_a_schema_1_archive(tmp_path):
    p = tmp_path / "old-export.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("manifest.json", json.dumps({"schemaVersion": 1, "sections": {},
                                                "source": {"orgId": "O1"}}))
        z.writestr("flows/flows/f1.json", json.dumps(
            {"meta": {"id": "f1"}, "document": {"name": "Main"}}))
    r = archive.ArchiveReader(p)
    assert r.flows("flows")["f1"]["document"] == {"name": "Main"}
    r.close()


def test_source_ids_cover_every_object_in_the_archive(tmp_path):
    r = archive.ArchiveReader(_write(tmp_path))
    assert {"f1", "s1", "fn1", "O1"} <= r.source_ids()
    r.close()


def test_two_flows_with_the_same_file_name_do_not_overwrite_each_other(tmp_path):
    p = tmp_path / "t-export.zip"
    archive.write_export(
        p, source={"orgId": "O1", "orgName": "src"}, cc={}, children={}, audio={},
        flows={"flows": {"f1": {"meta": {}, "document": {"name": "A B"}},
                         "f2": {"meta": {}, "document": {"name": "A_B"}}},
               "subflows": {}, "errors": [], "projectId": PROJ},
        functions={"functions": {}, "errors": []}, calling={}, users={})
    r = archive.ArchiveReader(p)
    assert {k: v["document"]["name"] for k, v in r.flows("flows").items()} ==         {"f1": "A B", "f2": "A_B"}
    r.close()


# --- found by re-running the real archive after the six fixes ------------------

def test_dial_numbers_are_matched_by_number_not_skipped_as_nameless(transport):
    transport.add("GET /organization/ORG1/v2/dial-number", body={"data": []})
    res = importer.import_entity(make(transport), "dial-number",
                                 [{"id": "d1", "dialledNumber": "+15551230000"}],
                                 idmap.IdMap(), "skip", confirm=False)
    assert res.would_create == ["d1"] and res.skipped == []


def test_a_flow_is_not_a_dangling_reference_to_itself(transport):
    m = idmap.IdMap()
    m.known_source_ids = {"f1"}
    reader = Reader(flows={"f1": {"meta": {"name": "Main"},
                                  "document": {"id": "f1", "name": "Main"}}})
    res = importer.import_flows(make(transport), reader, "flows", m, confirm=False)
    assert res.dangling == set()


def test_entry_points_are_ordered_after_the_audio_they_play():
    from wxcc_export import plan
    order = plan.order_entities(["entry-point", "audio-file", "desktop-layout", "team"])
    assert order.index("audio-file") < order.index("entry-point")
    # layouts first; their teamIds are deferred (team <-> layout cycle)
    assert order.index("desktop-layout") < order.index("team")
