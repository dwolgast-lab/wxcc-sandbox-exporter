import pytest
from wxcc_export import export_flows
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


def test_list_flows_passes_an_explicit_page_size(transport):
    transport.add("GET /ORG1/project/ORG1/flows?flowType=FLOW"
                  "&includePagination=true&size=100",
                  body={"data": [{"id": "f1", "name": "Main"}]})
    flows, err = export_flows.list_flows(make(transport), "ORG1", "FLOW")
    assert flows[0]["id"] == "f1"
    assert err is None
    # The API default size is 10; relying on it silently truncates.
    assert "size=100" in transport.calls[0]["url"]


def test_list_flows_surfaces_the_error_instead_of_going_empty(transport):
    # A 403/network/500 on the listing call must NOT look like "zero flows" -
    # a partial export must never look like a complete one (see archive.py).
    transport.add("GET /ORG1/project/ORG1/flows?flowType=FLOW"
                  "&includePagination=true&size=100", status=403, body={})
    rows, err = export_flows.list_flows(make(transport), "ORG1", "FLOW")
    assert rows == []
    assert err is not None
    assert "403" in err


def test_export_flow_returns_the_document(transport):
    transport.add("GET /ORG1/project/ORG1/v2/flows/f1:export?flowType=FLOW",
                  body={"name": "Main", "nodes": []})
    doc, err = export_flows.export_flow(make(transport), "ORG1", "f1", "FLOW")
    assert doc["name"] == "Main"
    assert err is None


def test_export_flow_reports_an_error_without_raising(transport):
    transport.add("GET /ORG1/project/ORG1/v2/flows/f1:export?flowType=FLOW",
                  status=404, body={"message": "gone"})
    doc, err = export_flows.export_flow(make(transport), "ORG1", "f1", "FLOW")
    assert doc is None
    assert "404" in err


def test_export_all_flows_collects_both_types(transport):
    transport.add("GET /ORG1/project/ORG1/flows?flowType=FLOW"
                  "&includePagination=true&size=100",
                  body={"data": [{"id": "f1", "name": "Main"}]})
    transport.add("GET /ORG1/project/ORG1/v2/flows/f1:export?flowType=FLOW",
                  body={"name": "Main"})
    transport.add(f"GET /ORG1/project/ORG1/flows?flowType={export_flows.SUBFLOW_TYPE}"
                  "&includePagination=true&size=100",
                  body={"data": [{"id": "s1", "name": "Sub"}]})
    transport.add(f"GET /ORG1/project/ORG1/v2/flows/s1:export"
                  f"?flowType={export_flows.SUBFLOW_TYPE}", body={"name": "Sub"})
    out = export_flows.export_all_flows(make(transport), "ORG1")
    assert list(out["flows"]) == ["f1"]
    assert list(out["subflows"]) == ["s1"]
    assert out["errors"] == []


def test_export_all_flows_records_a_failed_flow_and_keeps_going(transport):
    transport.add("GET /ORG1/project/ORG1/flows?flowType=FLOW"
                  "&includePagination=true&size=100",
                  body={"data": [{"id": "f1"}, {"id": "f2"}]})
    transport.add("GET /ORG1/project/ORG1/v2/flows/f1:export?flowType=FLOW",
                  status=500, body={})
    transport.add("GET /ORG1/project/ORG1/v2/flows/f2:export?flowType=FLOW",
                  body={"name": "Two"})
    transport.add(f"GET /ORG1/project/ORG1/flows?flowType={export_flows.SUBFLOW_TYPE}"
                  "&includePagination=true&size=100", body={"data": []})
    out = export_flows.export_all_flows(make(transport), "ORG1")
    assert list(out["flows"]) == ["f2"]
    assert len(out["errors"]) == 1


def test_export_all_flows_records_an_error_when_a_listing_fails(transport):
    # Before the fix: a 403 on the FLOW listing became [] silently, so
    # export_all_flows returned {"flows": {}, "subflows": {}, "errors": []} -
    # a failed export indistinguishable from a tenant with no flows.
    transport.add("GET /ORG1/project/ORG1/flows?flowType=FLOW"
                  "&includePagination=true&size=100", status=403, body={})
    transport.add(f"GET /ORG1/project/ORG1/flows?flowType={export_flows.SUBFLOW_TYPE}"
                  "&includePagination=true&size=100", body={"data": []})
    out = export_flows.export_all_flows(make(transport), "ORG1")
    assert out["flows"] == {}
    assert len(out["errors"]) == 1
    assert "FLOW" in out["errors"][0]
    assert "403" in out["errors"][0]


def test_list_functions_uses_the_v1_org_path(transport):
    transport.add("GET /v1/ORG1/functions?page=0&size=100",
                  body={"data": [{"id": "fn1", "name": "lookup"}]})
    rows, err = export_flows.list_functions(make(transport))
    assert rows[0]["id"] == "fn1"
    assert err is None


def test_export_function_posts_to_the_export_verb(transport):
    transport.add("POST /v1/ORG1/functions/fn1:export", body={"code": "x"})
    doc, err = export_flows.export_function(make(transport), "fn1")
    assert doc == {"code": "x"} and err is None
    assert transport.calls[0]["method"] == "POST"


def test_export_all_functions_records_errors(transport):
    transport.add("GET /v1/ORG1/functions?page=0&size=100",
                  body={"data": [{"id": "fn1"}]})
    transport.add("POST /v1/ORG1/functions/fn1:export", status=400,
                  body={"message": "bad"})
    out = export_flows.export_all_functions(make(transport))
    assert out["functions"] == {}
    assert len(out["errors"]) == 1


def test_export_all_functions_records_an_error_when_the_listing_fails(transport):
    # Same failure mode as flows: a 403 on the listing must not read as "no
    # functions" with an empty errors list.
    transport.add("GET /v1/ORG1/functions?page=0&size=100", status=403, body={})
    out = export_flows.export_all_functions(make(transport))
    assert out["functions"] == {}
    assert len(out["errors"]) == 1
    assert "403" in out["errors"][0]


def test_subflow_type_is_not_a_guess():
    # This value MUST come from the Task 5 probe. A module-level sentinel means
    # the probe has not been run, and export must refuse rather than guess.
    assert export_flows.SUBFLOW_TYPE != export_flows.UNRESOLVED, (
        "SUBFLOW_TYPE is still the unresolved sentinel - run scripts/probe.py "
        "and record U2 in docs/api-notes.md before implementing this task."
    )
