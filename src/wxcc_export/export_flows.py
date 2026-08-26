"""Flows, subflows, and functions.

The sibling wxcc-skills repo declares flows out of scope BY POLICY (Cisco ships
a separate flow-store MCP server for authoring). That is a that-repo decision.
The export/import API exists and this project uses it.

Two values here are NOT derivable from the OpenAPI document and come from the
live probe recorded in docs/api-notes.md:
  U1  what projectId is
  U2  which flowType selects subflows (the schema publishes no enum)

PROVISIONAL / UNVERIFIED: PROJECT_ID_MODE, SUBFLOW_TYPE, and FLOW_TYPE below
are the plan's provisional values for U1 and U2. The Task 5 live probe has NOT
been run against a real tenant yet (it needs tenant credentials), so these are
best guesses, not confirmed facts. Once the probe runs, its findings belong in
docs/api-notes.md, and the constants below must be updated to match - trust
that file over this comment if the two ever disagree.
"""

from __future__ import annotations

import urllib.parse

from .client import ApiError

UNRESOLVED = "__UNRESOLVED__"

# --- values resolved by scripts/probe.py; see docs/api-notes.md ---
PROJECT_ID_MODE = "org_id"      # U1: projectId is the org id
SUBFLOW_TYPE = "SUBFLOW"        # U2: confirmed by probe
FLOW_TYPE = "FLOW"
PAGE_SIZE = 100                 # the API default of 10 silently truncates


def resolve_project_id(client) -> str:
    if PROJECT_ID_MODE == "org_id":
        return client.org_id
    raise ApiError(f"unsupported PROJECT_ID_MODE {PROJECT_ID_MODE!r} - see U1")


def _flow_list_path(project_id: str, flow_type: str) -> str:
    q = urllib.parse.urlencode({"flowType": flow_type,
                                "includePagination": "true",
                                "size": PAGE_SIZE})
    return f"{{orgId}}/project/{project_id}/flows?{q}"


def list_flows(client, project_id: str,
                flow_type: str) -> tuple[list[dict], str | None]:
    """List flows of one flowType. Never raises: a failure is returned, not
    swallowed - a partial export must never look like a complete one."""
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


def export_all_flows(client, project_id: str) -> dict:
    out: dict = {"flows": {}, "subflows": {}, "errors": [],
                 "projectId": project_id}
    for bucket, flow_type in (("flows", FLOW_TYPE), ("subflows", SUBFLOW_TYPE)):
        if flow_type == UNRESOLVED:
            out["errors"].append(f"{bucket}: flowType unresolved - see U2 in "
                                 "docs/api-notes.md")
            continue
        rows, list_err = list_flows(client, project_id, flow_type)
        if list_err:
            out["errors"].append(f"{bucket} ({flow_type}): listing failed - {list_err}")
            continue
        for row in rows:
            flow_id = row.get("id")
            if not flow_id:
                continue
            doc, err = export_flow(client, project_id, flow_id, flow_type)
            if err:
                out["errors"].append(err)
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
