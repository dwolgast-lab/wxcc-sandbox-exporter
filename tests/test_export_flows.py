import pytest
from wxcc_export import export_flows
from wxcc_export.client import ApiClient, ApiError

BASE = "https://api.wxcc-us1.cisco.com"


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


# --- Flows: WORKING. projectId is a fixed, tenant-independent constant. ---
#
# An earlier revision of this file asserted flows were unreachable. That was
# wrong: the probe had been passing an org id (a 36-char UUID) where the route
# only matches a 24-char hex ObjectId, so it never matched the route and the
# gateway 404'd with an empty body. With the real project id the API returns
# 23 flows and 3 subflows on the live sandbox.

PROJ = "5e5c9ad6d61f870d6d778c1b"


def test_project_id_is_the_confirmed_constant():
    assert export_flows.FLOWS_PROJECT_ID == PROJ


def test_resolve_project_id_is_tenant_independent(transport):
    # Same value regardless of which org the client is pointed at.
    a = ApiClient(BASE, "T", org_id="ORG_A", transport=transport)
    b = ApiClient(BASE, "T", org_id="ORG_B", transport=transport)
    assert export_flows.resolve_project_id(a) == PROJ
    assert export_flows.resolve_project_id(b) == PROJ


def test_subflow_type_is_the_confirmed_value():
    # Confirmed live: flowType=SUBFLOW returns a set distinct from FLOW.
    assert export_flows.SUBFLOW_TYPE == "SUBFLOW"


def test_list_flows_passes_an_explicit_page_size(transport):
    transport.add(f"GET /ORG1/project/{PROJ}/flows?flowType=FLOW"
                  "&includePagination=true&size=100",
                  body={"data": [{"id": "f1", "name": "Main"}]})
    rows, err = export_flows.list_flows(make(transport), PROJ, "FLOW")
    assert err is None
    assert rows[0]["id"] == "f1"
    # The API default size is 10, which silently truncates.
    assert "size=100" in transport.calls[0]["url"]


def test_list_flows_surfaces_the_error_instead_of_going_empty(transport):
    transport.add(f"GET /ORG1/project/{PROJ}/flows?flowType=FLOW"
                  "&includePagination=true&size=100", status=403, body={})
    rows, err = export_flows.list_flows(make(transport), PROJ, "FLOW")
    assert rows == []
    assert err is not None and "403" in err


def test_export_flow_returns_the_document(transport):
    transport.add(f"GET /ORG1/project/{PROJ}/v2/flows/f1:export?flowType=FLOW",
                  body={"name": "Main", "nodes": [], "edges": []})
    doc, err = export_flows.export_flow(make(transport), PROJ, "f1", "FLOW")
    assert err is None and doc["name"] == "Main"


def test_export_flow_reports_an_error_without_raising(transport):
    transport.add(f"GET /ORG1/project/{PROJ}/v2/flows/f1:export?flowType=FLOW",
                  status=404, body={"message": "gone"})
    doc, err = export_flows.export_flow(make(transport), PROJ, "f1", "FLOW")
    assert doc is None and "404" in err


def test_export_all_flows_collects_both_buckets(transport):
    transport.add(f"GET /ORG1/project/{PROJ}/flows?flowType=FLOW"
                  "&includePagination=true&size=100",
                  body={"data": [{"id": "f1", "name": "Main"}]})
    transport.add(f"GET /ORG1/project/{PROJ}/v2/flows/f1:export?flowType=FLOW",
                  body={"name": "Main"})
    transport.add(f"GET /ORG1/project/{PROJ}/flows?flowType=SUBFLOW"
                  "&includePagination=true&size=100",
                  body={"data": [{"id": "s1", "name": "Sub"}]})
    transport.add(f"GET /ORG1/project/{PROJ}/v2/flows/s1:export?flowType=SUBFLOW",
                  body={"name": "Sub"})
    out = export_flows.export_all_flows(make(transport))
    assert list(out["flows"]) == ["f1"]
    assert list(out["subflows"]) == ["s1"]
    assert out["errors"] == []
    assert out["projectId"] == PROJ


def test_export_all_flows_records_a_failed_listing(transport):
    # A failed listing must NEVER read as "this tenant has no flows".
    transport.add(f"GET /ORG1/project/{PROJ}/flows?flowType=FLOW"
                  "&includePagination=true&size=100", status=403, body={})
    transport.add(f"GET /ORG1/project/{PROJ}/flows?flowType=SUBFLOW"
                  "&includePagination=true&size=100", body={"data": []})
    out = export_flows.export_all_flows(make(transport))
    assert out["flows"] == {}
    assert any("403" in e for e in out["errors"])


def test_export_all_flows_records_a_failed_flow_and_keeps_going(transport):
    transport.add(f"GET /ORG1/project/{PROJ}/flows?flowType=FLOW"
                  "&includePagination=true&size=100",
                  body={"data": [{"id": "f1"}, {"id": "f2"}]})
    transport.add(f"GET /ORG1/project/{PROJ}/v2/flows/f1:export?flowType=FLOW",
                  status=500, body={})
    transport.add(f"GET /ORG1/project/{PROJ}/v2/flows/f2:export?flowType=FLOW",
                  body={"name": "Two"})
    transport.add(f"GET /ORG1/project/{PROJ}/flows?flowType=SUBFLOW"
                  "&includePagination=true&size=100", body={"data": []})
    out = export_flows.export_all_flows(make(transport))
    assert list(out["flows"]) == ["f2"]
    assert len(out["errors"]) == 1


def test_list_functions_uses_the_v1_org_path_with_an_explicit_page_size(transport):
    transport.add("GET /v1/ORG1/functions?page=0&size=100",
                  body={"data": [{"id": "fn1", "name": "lookup"}]})
    rows, err = export_flows.list_functions(make(transport))
    assert rows[0]["id"] == "fn1"
    assert err is None
    # The API default size is 10; relying on it silently truncates.
    assert "size=100" in transport.calls[0]["url"]


def test_list_functions_surfaces_the_error_instead_of_going_empty(transport):
    transport.add("GET /v1/ORG1/functions?page=0&size=100", status=403, body={})
    rows, err = export_flows.list_functions(make(transport))
    assert rows == []
    assert err is not None
    assert "403" in err


def test_export_function_posts_to_the_export_verb(transport):
    transport.add("POST /v1/ORG1/functions/fn1:export", body={"code": "x"})
    doc, err = export_flows.export_function(make(transport), "fn1")
    assert doc == {"code": "x"} and err is None
    assert transport.calls[0]["method"] == "POST"


def test_export_function_reports_an_error_without_raising(transport):
    transport.add("POST /v1/ORG1/functions/fn1:export", status=404,
                  body={"message": "gone"})
    doc, err = export_flows.export_function(make(transport), "fn1")
    assert doc is None
    assert "404" in err


def test_export_all_functions_collects_functions(transport):
    transport.add("GET /v1/ORG1/functions?page=0&size=100",
                  body={"data": [{"id": "fn1", "name": "lookup"}]})
    transport.add("POST /v1/ORG1/functions/fn1:export",
                  body={"name": "lookup", "sourceCode": "return 1;"})
    out = export_flows.export_all_functions(make(transport))
    assert list(out["functions"]) == ["fn1"]
    assert out["functions"]["fn1"]["document"]["sourceCode"] == "return 1;"
    assert out["errors"] == []


def test_export_all_functions_records_a_failed_function_and_keeps_going(transport):
    transport.add("GET /v1/ORG1/functions?page=0&size=100",
                  body={"data": [{"id": "fn1"}, {"id": "fn2"}]})
    transport.add("POST /v1/ORG1/functions/fn1:export", status=500, body={})
    transport.add("POST /v1/ORG1/functions/fn2:export", body={"name": "Two"})
    out = export_flows.export_all_functions(make(transport))
    assert list(out["functions"]) == ["fn2"]
    assert len(out["errors"]) == 1


def test_export_all_functions_records_an_error_when_the_listing_fails(transport):
    # A 403 on the listing must not read as "no functions" with an empty
    # errors list - a partial export must never look like a complete one.
    transport.add("GET /v1/ORG1/functions?page=0&size=100", status=403, body={})
    out = export_flows.export_all_functions(make(transport))
    assert out["functions"] == {}
    assert len(out["errors"]) == 1
    assert "403" in out["errors"][0]
