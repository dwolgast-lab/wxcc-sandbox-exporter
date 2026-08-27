import pytest
from wxcc_export import export_flows, idmap, importer
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"
SUB = export_flows.SUBFLOW_TYPE
PROJ = export_flows.FLOWS_PROJECT_ID


class FakeReader:
    def __init__(self, flows=None, subflows=None, functions=None, calling=None):
        self._flows = {"flows": flows or {}, "subflows": subflows or {}}
        self._functions = functions or {}
        self._calling = calling or {}

    def flows(self, bucket):
        return self._flows.get(bucket, {})

    def functions(self):
        return self._functions

    def calling_items(self, name):
        return self._calling.get(name, [])


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


def test_flow_dry_run_writes_nothing(transport):
    reader = FakeReader(flows={"f1": {"meta": {"name": "Main"},
                                      "document": {"name": "Main"}}})
    res = importer.import_flows(make(transport), reader, "flows",
                                idmap.IdMap(), overwrite=False, confirm=False)
    assert res.created == []
    assert transport.calls == []


def test_confirmed_flow_import_posts_the_document(transport):
    transport.add(f"POST /ORG1/project/{PROJ}/v2/flows:import"
                  f"?overwrite=false&flowType=FLOW",
                  status=200, body={"id": "F9"})
    reader = FakeReader(flows={"f1": {"meta": {"name": "Main"},
                                      "document": {"name": "Main"}}})
    res = importer.import_flows(make(transport), reader, "flows",
                                idmap.IdMap(), overwrite=False, confirm=True)
    assert res.created == ["F9"]


def test_flow_references_are_remapped(transport):
    transport.add(f"POST /ORG1/project/{PROJ}/v2/flows:import"
                  f"?overwrite=false&flowType=FLOW", status=200, body={"id": "F9"})
    m = idmap.IdMap()
    m.record("q1", "q9")
    reader = FakeReader(flows={"f1": {"meta": {"name": "Main"},
                                      "document": {"nodes": [{"queueId": "q1"}]}}})
    importer.import_flows(make(transport), reader, "flows", m,
                          overwrite=False, confirm=True)
    assert b'"queueId": "q9"' in transport.calls[0]["data"]


def test_subflow_import_uses_the_probe_confirmed_flow_type(transport):
    transport.add(f"POST /ORG1/project/{PROJ}/v2/flows:import"
                  f"?overwrite=false&flowType={SUB}", status=200, body={"id": "S9"})
    reader = FakeReader(subflows={"s1": {"meta": {}, "document": {"name": "Sub"}}})
    res = importer.import_flows(make(transport), reader, "subflows",
                                idmap.IdMap(), overwrite=False, confirm=True)
    assert res.created == ["S9"]
    assert f"flowType={SUB}" in transport.calls[0]["url"]


def test_a_failed_flow_import_is_recorded(transport):
    transport.add(f"POST /ORG1/project/{PROJ}/v2/flows:import"
                  f"?overwrite=false&flowType=FLOW", status=400,
                  body={"message": "unknown activity"})
    reader = FakeReader(flows={"f1": {"meta": {"name": "Main"}, "document": {}}})
    res = importer.import_flows(make(transport), reader, "flows",
                                idmap.IdMap(), overwrite=False, confirm=True)
    assert "unknown activity" in res.failed[0]["detail"]


def test_flow_dangling_references_are_reported(transport):
    reader = FakeReader(flows={"f1": {"meta": {}, "document": {
        "queueId": "22222222-2222-2222-2222-222222222222"}}})
    res = importer.import_flows(make(transport), reader, "flows",
                                idmap.IdMap(), overwrite=False, confirm=False)
    assert "22222222-2222-2222-2222-222222222222" in res.dangling


def test_function_import_sends_multipart(transport, monkeypatch):
    # The probe HAS resolved the field name in this test (mechanism test) -
    # the default constant, tested separately below, must stay the sentinel.
    monkeypatch.setattr(importer, "FUNCTION_IMPORT_FIELD", "file")
    transport.add("POST /v1/ORG1/functions:import?overwrite=false",
                  status=200, body={"id": "FN9"})
    reader = FakeReader(functions={"fn1": {"meta": {"name": "lookup"},
                                           "document": {"code": "x"}}})
    res = importer.import_functions(make(transport), reader, idmap.IdMap(),
                                    confirm=True)
    assert res.created == ["FN9"]
    ctype = transport.calls[0]["headers"]["Content-Type"]
    assert ctype.startswith("multipart/form-data")


def test_function_import_refuses_when_the_field_name_is_unresolved(
        transport, monkeypatch):
    monkeypatch.setattr(importer, "FUNCTION_IMPORT_FIELD", importer.UNRESOLVED)
    reader = FakeReader(functions={"fn1": {"meta": {}, "document": {}}})
    res = importer.import_functions(make(transport), reader, idmap.IdMap(),
                                    confirm=True)
    assert "U3" in res.failed[0]["detail"]
    assert transport.calls == []


def test_function_import_field_is_the_confirmed_value():
    """U3 was resolved from a REAL successful import against the live tenant.

    The part is named "file", carries a .json filename, and is typed
    application/octet-stream - NOT application/json, which is what this module
    originally sent.
    """
    assert importer.FUNCTION_IMPORT_FIELD == "file"
    assert importer.FUNCTION_IMPORT_PART_TYPE == "application/octet-stream"


def test_function_import_sends_a_json_filename_and_octet_stream(transport):
    transport.add("POST /v1/ORG1/functions:import?overwrite=false",
                  status=200, body={"id": "FN9"})
    reader = FakeReader(functions={"fn1": {"meta": {"name": "parse_call_data"},
                                           "document": {"name": "parse_call_data",
                                                        "sourceCode": "x"}}})
    res = importer.import_functions(make(transport), reader, idmap.IdMap(),
                                    confirm=True)
    assert res.created == ["FN9"]
    data = transport.calls[0]["data"]
    assert b'name="file"' in data
    assert b'filename="parse_call_data.json"' in data
    assert b"application/octet-stream" in data


def test_function_import_still_refuses_if_the_field_is_unset(transport, monkeypatch):
    # The refusal path must survive, so a future unresolved value cannot
    # silently become a guess.
    monkeypatch.setattr(importer, "FUNCTION_IMPORT_FIELD", importer.UNRESOLVED)
    reader = FakeReader(functions={"fn1": {"meta": {}, "document": {}}})
    res = importer.import_functions(make(transport), reader, idmap.IdMap(),
                                    confirm=True)
    assert "unresolved" in res.failed[0]["detail"]
    assert transport.calls == []


def test_calling_import_creates_an_org_scoped_object(transport):
    transport.add("GET /telephony/config/huntGroups", body={"items": []})
    transport.add("POST /telephony/config/locations/L1/huntGroups",
                  status=201, body={"id": "H9"})
    reader = FakeReader(calling={"hunt-groups": [
        {"id": "H1", "name": "Sales", "_locationId": "L1"}]})
    m = idmap.IdMap()
    m.record("L1", "L1")
    res = importer.import_calling(make(transport), reader, ["hunt-groups"],
                                  m, "skip", confirm=True)
    assert res["hunt-groups"].created == ["H9"]


def test_calling_import_skips_an_item_with_no_location(transport):
    transport.add("GET /telephony/config/huntGroups", body={"items": []})
    reader = FakeReader(calling={"hunt-groups": [{"id": "H1", "name": "Sales"}]})
    res = importer.import_calling(make(transport), reader, ["hunt-groups"],
                                  idmap.IdMap(), "skip", confirm=True)
    assert "no location" in res["hunt-groups"].failed[0]["detail"]


def test_calling_import_never_falls_back_to_the_source_tenants_location_id(
        transport):
    # The source item's location (SRC-LOC-1) was never imported/mapped into
    # the target. The importer must NOT fall back to the raw source id and
    # POST against the target tenant with it - it must dangle and fail.
    transport.add("GET /telephony/config/huntGroups", body={"items": []})
    transport.add("POST /telephony/config/locations/SRC-LOC-1/huntGroups",
                  status=201, body={"id": "H9"})
    reader = FakeReader(calling={"hunt-groups": [
        {"id": "H1", "name": "Sales", "_locationId": "SRC-LOC-1"}]})
    res = importer.import_calling(make(transport), reader, ["hunt-groups"],
                                  idmap.IdMap(), "skip", confirm=True)
    result = res["hunt-groups"]
    assert result.created == []
    assert "SRC-LOC-1" in result.dangling
    assert result.failed
    assert not any(c["method"] == "POST" for c in transport.calls)


def test_calling_import_indexes_existing_location_scoped_objects(transport):
    # schedules is scope=="location": the target's existing schedules must be
    # discovered by enumerating the target's OWN locations, so re-running an
    # import does not create a duplicate every time.
    transport.add("GET /locations", body={"items": [{"id": "TGT-L1", "name": "HQ"}]})
    transport.add("GET /telephony/config/locations/TGT-L1/schedules",
                  body={"items": [{"id": "SCH-EXIST", "name": "Business Hours"}]})
    reader = FakeReader(calling={"schedules": [
        {"id": "S1", "name": "Business Hours", "_locationId": "SRC-L1"}]})
    m = idmap.IdMap()
    m.record("SRC-L1", "TGT-L1")
    res = importer.import_calling(make(transport), reader, ["schedules"],
                                  m, "skip", confirm=True)
    result = res["schedules"]
    assert result.skipped == ["S1"]
    assert result.created == []
    assert not any(c["method"] == "POST" for c in transport.calls)


def test_calling_import_records_a_failed_location_enumeration(transport):
    # If the target's locations can't be enumerated, that must be visible in
    # the report - not a silently-empty index that creates duplicates.
    transport.add("GET /locations", status=500, body={"error": "boom"})
    reader = FakeReader(calling={"schedules": [
        {"id": "S1", "name": "Business Hours", "_locationId": "SRC-L1"}]})
    m = idmap.IdMap()
    m.record("SRC-L1", "TGT-L1")
    res = importer.import_calling(make(transport), reader, ["schedules"],
                                  m, "skip", confirm=True)
    result = res["schedules"]
    assert any("collision detection" in f["detail"].lower()
               for f in result.failed)


def test_calling_import_records_a_failed_org_scope_enumeration(transport):
    """A target-listing failure must never read as 'the target is empty'.

    The scope=='location' branch already reports this. The scope=='org' branch
    swallowed it, so a 500 while indexing the target silently became 'zero
    existing objects' and every re-run created another duplicate. 7 of the 12
    Calling objects are org-scope, so this was the majority of them.
    """
    transport.add("GET /telephony/config/huntGroups", status=500, body={})
    transport.add("POST /telephony/config/locations/NEWLOC/huntGroups",
                  status=201, body={"id": "H9"})
    reader = FakeReader(calling={"hunt-groups": [
        {"id": "H1", "name": "Sales", "_locationId": "OLDLOC"}]})
    m = idmap.IdMap()
    m.record("OLDLOC", "NEWLOC")
    res = importer.import_calling(make(transport), reader, ["hunt-groups"],
                                  m, "skip", confirm=True)["hunt-groups"]
    assert res.failed, "a failed target listing must be reported, not swallowed"
    assert "collision detection was unavailable" in res.failed[0]["detail"]
    assert "hunt-groups" in res.failed[0]["detail"]
