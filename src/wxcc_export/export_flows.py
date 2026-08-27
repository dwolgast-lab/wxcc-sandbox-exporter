"""Flows, subflows, and functions.

FLOWS: the `projectId` is a FIXED CONSTANT, the same on every tenant.

    5e5c9ad6d61f870d6d778c1b

It is NOT the org id, and it is not discoverable through the API - there is no
project-list endpoint. An earlier revision of this file concluded the Flows API
was "not served on the WxCC regional host at all" after eleven candidate base
paths all returned empty-body 404s. That conclusion was WRONG. The route is
fine; the probe was passing an org id (a 36-char UUID) where the route only
matches a 24-character hex ObjectId, so it never matched the route and the
gateway 404'd with no body. Confirmed live 2026-08-26:

    GET /{orgId}/project/5e5c9ad6d61f870d6d778c1b/flows?flowType=FLOW
        200, 23 flows
    GET /{orgId}/project/5e5c9ad6d61f870d6d778c1b/flows?flowType=SUBFLOW
        200, 3 subflows
    GET /{orgId}/project/{proj}/v2/flows/{flowId}:export?flowType=FLOW
        200, 26 KB of flow JSON (nodes, edges, variables, eventFlows, ...)

TRAP, verified: a well-formed but WRONG projectId returns `200 []`, not an
error. An empty flow list therefore does NOT prove the project id is right.
Only the constant above is known to return this tenant's flows.

Functions are a DIFFERENT service and are also confirmed working (U3):
  GET  /v1/{orgId}/functions             200 {"data":[...], "pageInfo":{...}}
  POST /v1/{orgId}/functions/{id}:export 200
    keys: description, inputs, language, name, outputs, runtime, sourceCode
Their :import endpoint takes multipart/form-data whose field name is still
UNRESOLVED, so import_functions refuses rather than guessing.
"""

from __future__ import annotations

import urllib.parse

from .client import ApiError

UNRESOLVED = "__UNRESOLVED__"

# U1 RESOLVED 2026-08-26: a fixed, tenant-independent project id. Verified
# live - it returned 23 flows and 3 subflows on org davidwolgast-8xgo.
FLOWS_PROJECT_ID = "5e5c9ad6d61f870d6d778c1b"

# U2 RESOLVED 2026-08-26: SUBFLOW returns a set distinct from FLOW (3 vs 23).
SUBFLOW_TYPE = "SUBFLOW"
FLOW_TYPE = "FLOW"
PAGE_SIZE = 100                 # the API default of 10 silently truncates


def resolve_project_id(client) -> str:
    """The flows project id.

    Deliberately ignores the client: this value is the same on every tenant.
    Kept as a function so a future tenant-specific discovery step has a seam.
    """
    return FLOWS_PROJECT_ID


def _flow_list_path(project_id: str, flow_type: str) -> str:
    q = urllib.parse.urlencode({"flowType": flow_type,
                                "includePagination": "true",
                                "size": PAGE_SIZE})
    return f"{{orgId}}/project/{project_id}/flows?{q}"


def list_flows(client, project_id: str,
               flow_type: str) -> tuple[list[dict], str | None]:
    """List flows of one type. Never raises: a failure is RETURNED.

    A silently-empty list would make a failed export indistinguishable from a
    tenant with no flows, which is the failure mode this project exists to
    avoid.
    """
    try:
        return client.list_all(_flow_list_path(project_id, flow_type)), None
    except ApiError as exc:
        return [], f"HTTP {exc.status}: {str(exc)[:200]}"
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def export_flow(client, project_id: str, flow_id: str,
                flow_type: str) -> tuple[dict | None, str | None]:
    path = (f"{{orgId}}/project/{project_id}/v2/flows/{flow_id}:export"
            f"?flowType={flow_type}")
    try:
        status, body = client.json("GET", path)
    except Exception as exc:
        return None, f"flow {flow_id}: {type(exc).__name__}: {exc}"
    if status != 200 or not isinstance(body, dict):
        return None, f"flow {flow_id}: export returned HTTP {status}"
    return body, None


def export_all_flows(client, project_id: str | None = None) -> dict:
    """Export every flow and subflow. A listing failure is recorded, not hidden."""
    project_id = project_id or FLOWS_PROJECT_ID
    out: dict = {"flows": {}, "subflows": {}, "errors": [],
                 "projectId": project_id}
    for bucket, flow_type in (("flows", FLOW_TYPE), ("subflows", SUBFLOW_TYPE)):
        rows, err = list_flows(client, project_id, flow_type)
        if err:
            out["errors"].append(f"listing {bucket} (flowType={flow_type}): {err}")
            continue
        for row in rows:
            flow_id = row.get("id")
            if not flow_id:
                continue
            doc, ferr = export_flow(client, project_id, flow_id, flow_type)
            if ferr:
                out["errors"].append(ferr)
            else:
                out[bucket][flow_id] = {"meta": row, "document": doc}
    return out


def list_functions(client) -> tuple[list[dict], str | None]:
    """List functions. Never raises: a failure is returned, not swallowed -
    a partial export must never look like a complete one."""
    try:
        return client.list_all(f"v1/{{orgId}}/functions?page=0&size={PAGE_SIZE}"), None
    except ApiError as exc:
        return [], f"HTTP {exc.status}: {str(exc)[:200]}"
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def export_function(client, fn_id: str) -> tuple[dict | None, str | None]:
    try:
        status, body = client.json("POST", f"v1/{{orgId}}/functions/{fn_id}:export")
    except Exception as exc:
        return None, f"function {fn_id}: {type(exc).__name__}: {exc}"
    if status != 200 or not isinstance(body, dict):
        return None, f"function {fn_id}: export returned HTTP {status}"
    return body, None


def export_all_functions(client) -> dict:
    out: dict = {"functions": {}, "errors": []}
    rows, list_err = list_functions(client)
    if list_err:
        out["errors"].append(f"functions: listing failed - {list_err}")
        return out
    for row in rows:
        fn_id = row.get("id")
        if not fn_id:
            continue
        doc, err = export_function(client, fn_id)
        if err:
            out["errors"].append(err)
        else:
            out["functions"][fn_id] = {"meta": row, "document": doc}
    return out
