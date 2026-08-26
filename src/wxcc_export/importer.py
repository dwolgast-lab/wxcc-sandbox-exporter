"""Execute an import plan against the target tenant.

Two rules this module exists to enforce:

1. Nothing is written without confirm=True. A dry run computes the identical
   plan and reports it.
2. Every confirmed write is RE-READ and diffed. This API can return 200 or 201
   while silently ignoring a field, so a status code is not evidence the change
   landed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import idmap as idmap_mod
from . import plan, registry
from .client import ApiError

# Set by the server on every object; never part of what we asked it to store.
SERVER_ASSIGNED = frozenset({
    "id", "createdTime", "createdAt", "lastUpdatedTime", "lastUpdatedBy",
    "createdBy", "version", "eTag", "etag", "organizationId", "orgId", "links",
})


@dataclass
class ImportResult:
    entity: str
    planned: list = field(default_factory=list)
    created: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    unverified: list = field(default_factory=list)
    dangling: set = field(default_factory=set)

    def summary(self) -> str:
        return (f"{self.entity}: {len(self.created)} created, "
                f"{len(self.updated)} updated, {len(self.skipped)} skipped, "
                f"{len(self.failed)} failed, "
                f"{len(self.unverified)} unverified")


def _reason(body: object) -> str:
    if isinstance(body, dict):
        for key in ("message", "error", "detail", "errorMessage", "reason"):
            if body.get(key):
                return str(body[key])[:300]
        return str(body)[:300]
    return str(body)[:300]


def verify_write(client, entity: str, new_id: str, sent: dict) -> list[str]:
    """Re-read the object and return the fields the server did not store."""
    try:
        status, body = client.json("GET", registry.item_path(entity, new_id))
    except Exception as exc:
        return [f"__reread_failed__: {type(exc).__name__}: {exc}"]
    if status != 200 or not isinstance(body, dict):
        return [f"__reread_failed__: HTTP {status}"]
    missing: list[str] = []
    for key, want in sent.items():
        if key in SERVER_ASSIGNED:
            continue
        got = body.get(key)
        if got != want:
            missing.append(key)
    return missing


def import_entity(client, entity: str, items: list[dict],
                  idmap_: idmap_mod.IdMap, on_conflict: str,
                  confirm: bool) -> ImportResult:
    result = ImportResult(entity=entity)
    spec = registry.CC_ENTITIES.get(entity, {})

    if not spec.get("writable", False):
        note = spec.get("note", "")
        result.failed.append({
            "id": None,
            "detail": f"{entity} is read-only through this API - "
                      f"nothing was written. {note}"})
        return result

    existing = plan.index_existing(client, entity)
    result.planned = plan.classify(items, existing, on_conflict)

    for step in result.planned:
        source = step["item"]
        source_id = source.get("id")
        action = step["action"]

        if action == "skip":
            if source_id and step.get("existing", {}) and step["existing"].get("id"):
                # The object IS in the target - point references at it, or every
                # reference to this source id dangles.
                idmap_.record(source_id, step["existing"]["id"])
            if source_id:
                result.skipped.append(source_id)
            continue

        payload = idmap_.substitute(idmap_mod.strip_identity(source))
        result.dangling |= idmap_.unmapped(payload)

        if not confirm:
            continue

        try:
            if action == "update":
                target_id = step["existing"]["id"]
                status, body = client.json(
                    "PUT", registry.item_path(entity, target_id), payload)
            else:
                status, body = client.json(
                    "POST", registry.create_path(entity), payload)
        except Exception as exc:
            result.failed.append({"id": source_id,
                                  "detail": f"{type(exc).__name__}: {exc}"})
            continue

        if status >= 400:
            result.failed.append({"id": source_id,
                                  "detail": f"HTTP {status}: {_reason(body)}"})
            continue

        new_id = (body or {}).get("id") if isinstance(body, dict) else None
        if action == "update":
            new_id = new_id or step["existing"]["id"]
            result.updated.append(new_id)
        else:
            if not new_id:
                result.failed.append({
                    "id": source_id,
                    "detail": f"HTTP {status} but the response carried no id, so "
                              "the object cannot be verified or referenced"})
                continue
            result.created.append(new_id)

        if source_id and new_id:
            idmap_.record(source_id, new_id)

        missing = verify_write(client, entity, new_id, payload)
        if missing:
            result.unverified.append({"id": new_id, "fields": missing})

    return result


def import_cc(client, reader, keys: list[str], on_conflict: str = "skip",
              confirm: bool = False, on_progress=None
              ) -> tuple[dict[str, ImportResult], idmap_mod.IdMap]:
    """Import the cc:* selections in dependency order, sharing one IdMap.

    Returns (results, idmap). The map is returned rather than discarded because
    flows, functions, and Calling are imported afterwards and MUST reuse it - a
    flow that routes to queue q1 needs the q1 -> q9 mapping this pass recorded.
    """
    entities = [k.split(":", 1)[1] for k in keys if k.startswith("cc:")]
    ordered = plan.order_entities(entities)
    shared = idmap_mod.IdMap()
    out: dict[str, ImportResult] = {}
    for entity in ordered:
        result = import_entity(client, entity, reader.entity_items(entity),
                               shared, on_conflict, confirm)
        out[entity] = result
        if on_progress:
            on_progress(entity, result)
    return out, shared


from . import export_flows

UNRESOLVED = "__UNRESOLVED__"

# U3, from docs/api-notes.md. If the probe did not resolve it, leave the
# sentinel: refusing is correct, guessing a field name is not.
FUNCTION_IMPORT_FIELD = UNRESOLVED
FUNCTION_IMPORT_FILENAME = "function.json"


def import_flows(client, reader, bucket: str, idmap_: idmap_mod.IdMap,
                 overwrite: bool = False, confirm: bool = False) -> ImportResult:
    """Import one bucket of flows.

    Callers must import 'subflows' BEFORE 'flows': a flow can invoke a subflow,
    never the reverse.
    """
    result = ImportResult(entity=f"flows:{bucket}")
    flow_type = (export_flows.FLOW_TYPE if bucket == "flows"
                 else export_flows.SUBFLOW_TYPE)
    if flow_type == UNRESOLVED:
        result.failed.append({"id": None,
                              "detail": "flowType unresolved - see U2 in "
                                        "docs/api-notes.md"})
        return result

    project_id = export_flows.resolve_project_id(client)
    path = (f"{{orgId}}/project/{project_id}/v2/flows:import"
            f"?overwrite={str(overwrite).lower()}&flowType={flow_type}")

    for flow_id, payload in reader.flows(bucket).items():
        document = idmap_.substitute((payload or {}).get("document") or {})
        result.dangling |= idmap_.unmapped(document)
        result.planned.append({"action": "create", "item": {"id": flow_id},
                               "existing": None,
                               "reason": f"import into project {project_id}"})
        if not confirm:
            continue
        try:
            status, body = client.json("POST", path, document)
        except Exception as exc:
            result.failed.append({"id": flow_id,
                                  "detail": f"{type(exc).__name__}: {exc}"})
            continue
        if status >= 400:
            result.failed.append({"id": flow_id,
                                  "detail": f"HTTP {status}: {_reason(body)}"})
            continue
        new_id = (body or {}).get("id") if isinstance(body, dict) else None
        result.created.append(new_id or flow_id)
        if new_id:
            idmap_.record(flow_id, new_id)
    return result


def import_functions(client, reader, idmap_: idmap_mod.IdMap,
                     overwrite: bool = False,
                     confirm: bool = False) -> ImportResult:
    """Import custom functions.

    Export returns JSON but import takes multipart/form-data - the API is
    asymmetric here. The part name comes from the live probe (U3); if it is
    still the sentinel this refuses rather than guessing.
    """
    result = ImportResult(entity="flows:functions")
    functions = reader.functions()

    if FUNCTION_IMPORT_FIELD == UNRESOLVED:
        if functions:
            result.failed.append({
                "id": None,
                "detail": "the multipart field name for functions:import is "
                          "unresolved (U3 in docs/api-notes.md). Run "
                          "scripts/probe.py; refusing to guess a field name."})
        return result

    path = f"v1/{{orgId}}/functions:import?overwrite={str(overwrite).lower()}"
    for fn_id, payload in functions.items():
        document = idmap_.substitute((payload or {}).get("document") or {})
        result.dangling |= idmap_.unmapped(document)
        result.planned.append({"action": "create", "item": {"id": fn_id},
                               "existing": None, "reason": "import function"})
        if not confirm:
            continue
        import json as _json
        parts = [(FUNCTION_IMPORT_FIELD, FUNCTION_IMPORT_FILENAME,
                  "application/json", _json.dumps(document).encode())]
        try:
            status, body = client.multipart("POST", path, parts)
        except Exception as exc:
            result.failed.append({"id": fn_id,
                                  "detail": f"{type(exc).__name__}: {exc}"})
            continue
        if status >= 400:
            result.failed.append({"id": fn_id,
                                  "detail": f"HTTP {status}: {_reason(body)}"})
            continue
        new_id = (body or {}).get("id") if isinstance(body, dict) else None
        result.created.append(new_id or fn_id)
        if new_id:
            idmap_.record(fn_id, new_id)
    return result


def import_calling(client, reader, names: list[str], idmap_: idmap_mod.IdMap,
                   on_conflict: str = "skip",
                   confirm: bool = False) -> dict[str, ImportResult]:
    """Import the Calling subset. Location-scoped objects need a location id."""
    out: dict[str, ImportResult] = {}
    for name in names:
        spec = registry.CALLING_OBJECTS[name]
        result = ImportResult(entity=f"calling:{name}")
        items = reader.calling_items(name)

        existing_rows: list[dict] = []
        if spec["scope"] == "org":
            try:
                existing_rows = client.list_all(spec["list"].replace("{locationId}", ""))
            except Exception as exc:
                # Same reasoning as the location branch below: an empty index
                # here is indistinguishable from "the target has none of these",
                # so every item would be re-created on every run. Report it.
                result.failed.append({
                    "id": None,
                    "detail": f"could not list existing {name} in the target "
                              "tenant, so collision detection was unavailable: "
                              f"{type(exc).__name__}: {exc}"})
                existing_rows = []
        else:
            # Location-scoped: there is no org-wide list endpoint, so the
            # target's index has to be built by enumerating the TARGET
            # tenant's own locations and listing the object under each one.
            try:
                target_locations = client.list_all(
                    registry.CALLING_OBJECTS["locations"]["list"])
                for loc in target_locations:
                    loc_id = loc.get("id")
                    if not loc_id:
                        continue
                    existing_rows.extend(client.list_all(
                        spec["list"].replace("{locationId}", loc_id)))
            except Exception as exc:
                # An empty index here would silently let every item be
                # re-created as a duplicate on every re-run - that has to be
                # visible in the report, not swallowed.
                result.failed.append({
                    "id": None,
                    "detail": f"could not enumerate existing {name} across "
                              "the target tenant's locations, so collision "
                              f"detection was unavailable: "
                              f"{type(exc).__name__}: {exc}"})
                existing_rows = []
        existing = {str(r.get("name", "")).lower(): r
                    for r in existing_rows if r.get("name")}
        result.planned = plan.classify(items, existing, on_conflict)

        for step in result.planned:
            source = step["item"]
            source_id = source.get("id")
            if step["action"] == "skip":
                if source_id and (step.get("existing") or {}).get("id"):
                    idmap_.record(source_id, step["existing"]["id"])
                if source_id:
                    result.skipped.append(source_id)
                continue

            raw_loc = source.get("_locationId")
            if not raw_loc:
                result.failed.append({
                    "id": source_id,
                    "detail": f"{name} {source.get('name')!r} has no location "
                              "in the archive, and every Calling create endpoint "
                              "is location-scoped"})
                continue
            loc_id = idmap_.get(raw_loc)
            if not loc_id:
                # The source tenant's raw id must NEVER be sent to the target -
                # that would create the object against the wrong tenant's
                # location and report a clean success.
                result.dangling.add(raw_loc)
                result.failed.append({
                    "id": source_id,
                    "detail": f"{name} {source.get('name')!r} has location "
                              f"{raw_loc!r}, but the target's matching "
                              "location was not imported, so it cannot be "
                              "created without leaking the source tenant's "
                              "location id"})
                continue

            payload = idmap_.substitute(idmap_mod.strip_identity(source))
            result.dangling |= idmap_.unmapped(payload)
            if not confirm:
                continue

            create_path = spec["item"].replace("{locationId}", loc_id)
            create_path = create_path.rsplit("/{id}", 1)[0]
            try:
                status, body = client.json("POST", create_path, payload)
            except Exception as exc:
                result.failed.append({"id": source_id,
                                      "detail": f"{type(exc).__name__}: {exc}"})
                continue
            if status >= 400:
                result.failed.append({"id": source_id,
                                      "detail": f"HTTP {status}: {_reason(body)}"})
                continue
            new_id = (body or {}).get("id") if isinstance(body, dict) else None
            result.created.append(new_id or source_id)
            if source_id and new_id:
                idmap_.record(source_id, new_id)

        out[name] = result
    return out
