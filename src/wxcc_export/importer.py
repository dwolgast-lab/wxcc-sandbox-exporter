"""Execute an import plan against the target tenant.

Two rules this module exists to enforce:

1. Nothing is written without confirm=True. A dry run computes the identical
   plan and reports it.
2. Every confirmed write is RE-READ and diffed. This API can return 200 or 201
   while silently ignoring a field, so a status code is not evidence the change
   landed.
"""

from __future__ import annotations

import json as _json
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
    # Dry run: what a --confirm run would write. Without these a dry run could
    # only ever print "0 created", which reads as "nothing to do".
    dry_run: bool = False
    would_create: list = field(default_factory=list)
    would_update: list = field(default_factory=list)
    # Objects the API cannot write at all (users) - a manual step, not a failure.
    manual: list = field(default_factory=list)
    note: str = ""
    # Fields held back from the create and set after later imports (registry
    # "deferred"): [{"source_id", "target_id", "held": {field: source value}}].
    deferred: list = field(default_factory=list)

    def summary(self) -> str:
        if self.manual:
            present = sum(1 for m in self.manual if m.get("inTarget"))
            return (f"{self.entity}: read-only through the API - "
                    f"{present} of {len(self.manual)} already in the target "
                    f"(linked by {registry.name_field(self.entity)}), "
                    f"{len(self.manual) - present} to create by hand")
        if self.dry_run:
            head = (f"{len(self.would_create)} would be created, "
                    f"{len(self.would_update)} would be updated")
        else:
            head = f"{len(self.created)} created, {len(self.updated)} updated"
        return (f"{self.entity}: {head}, {len(self.skipped)} skipped, "
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
    result = ImportResult(entity=entity, dry_run=not confirm)
    spec = registry.CC_ENTITIES.get(entity, {})

    if not spec.get("writable", False):
        # Expected, not an error: a failure here made every clean run exit 3.
        # Nothing is written, but objects that already exist in the target
        # (users invited there by hand) are MAPPED by name/email, so a team's
        # userIds point at the target's users instead of the source's.
        field_ = registry.name_field(entity)
        existing = plan.index_existing(client, entity)          # GET only
        for i in items:
            match = existing.get(str(i.get(field_, "")).strip().lower())
            if match and i.get("id") and match.get("id"):
                idmap_.record(i["id"], match["id"])
            result.manual.append({"id": i.get("id"), "name": i.get(field_),
                                  "inTarget": bool(match)})
        result.note = spec.get("note", "")
        return result
    deferred_fields = spec.get("deferred", [])

    existing = plan.index_existing(client, entity)
    result.planned = plan.classify(items, existing, on_conflict,
                                   registry.name_field(entity))

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

        stripped = idmap_mod.strip_identity(source)
        held = {f: stripped.pop(f) for f in deferred_fields
                if stripped.get(f) not in (None, "")}
        payload = idmap_.substitute(stripped)
        result.dangling |= idmap_.unmapped(payload)

        if not confirm:
            # Stand-in mapping so later objects' references to this one are not
            # reported as dangling - the real run records the real new id here.
            if action == "update":
                result.would_update.append(source_id)
                target_id = step["existing"]["id"]
            else:
                result.would_create.append(source_id)
                target_id = source_id
            if source_id:
                idmap_.record(source_id, target_id)
            if held:
                result.deferred.append({"source_id": source_id,
                                        "target_id": target_id, "held": held})
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
        if held:
            result.deferred.append({"source_id": source_id,
                                    "target_id": new_id, "held": held})

        missing = verify_write(client, entity, new_id, payload)
        if missing:
            result.unverified.append({"id": new_id, "fields": missing})

    return result


def apply_deferred(client, entity: str, pending: list[dict],
                   idmap_: idmap_mod.IdMap, confirm: bool) -> ImportResult:
    """Set the fields held back at create time, now that their targets exist.

    Read-modify-write: GET the object as the target stores it, set the held
    fields to their remapped values, PUT it back, then verify.
    """
    result = ImportResult(entity=f"{entity}:links", dry_run=not confirm)
    for d in pending:
        held, target_id = d["held"], d["target_id"]
        missing_refs = [v for v in held.values()
                        if isinstance(v, str) and idmap_.get(v) is None]
        if missing_refs:
            result.failed.append({
                "id": target_id,
                "detail": f"{entity} {target_id} links to "
                          f"{', '.join(missing_refs)}, which was not imported - "
                          "that link was left unset. Import it too, or set it "
                          "in Control Hub."})
            continue
        wanted = {k: idmap_.substitute(v) for k, v in held.items()}
        if not confirm:
            result.would_update.append(d["source_id"])
            continue
        try:
            status, body = client.json("GET", registry.item_path(entity, target_id))
            if status != 200 or not isinstance(body, dict):
                raise ApiError(f"re-read returned HTTP {status}", status=status)
            status, body = client.json("PUT", registry.item_path(entity, target_id),
                                       {**body, **wanted})
        except Exception as exc:
            result.failed.append({"id": target_id,
                                  "detail": f"{type(exc).__name__}: {exc}"})
            continue
        if status >= 400:
            result.failed.append({"id": target_id,
                                  "detail": f"HTTP {status}: {_reason(body)}"})
            continue
        result.updated.append(target_id)
        missing = verify_write(client, entity, target_id, wanted)
        if missing:
            result.unverified.append({"id": target_id, "fields": missing})
    return result


def import_cc(client, reader, keys: list[str], on_conflict: str = "skip",
              confirm: bool = False, on_progress=None,
              idmap_: idmap_mod.IdMap | None = None
              ) -> tuple[dict[str, ImportResult], idmap_mod.IdMap]:
    """Import the cc:* selections in dependency order, sharing one IdMap.

    Returns (results, idmap). The map is returned rather than discarded because
    flows, functions, and Calling are imported afterwards and MUST reuse it - a
    flow that routes to queue q1 needs the q1 -> q9 mapping this pass recorded.
    """
    entities = [k.split(":", 1)[1] for k in keys if k.startswith("cc:")]
    ordered = plan.order_entities(entities)
    # Read-only entities write nothing, so dependency order does not bind them;
    # run them first so their by-name mappings exist before anything that
    # references them (team.userIds -> user) is created.
    ordered = ([e for e in ordered
                if not registry.CC_ENTITIES.get(e, {}).get("writable", False)]
               + [e for e in ordered
                  if registry.CC_ENTITIES.get(e, {}).get("writable", False)])
    shared = idmap_ if idmap_ is not None else idmap_mod.IdMap()
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

# U3 RESOLVED 2026-08-26 from a REAL successful import against the live tenant.
# The multipart part is named "file", carries a .json FILENAME, and is typed
# application/octet-stream - NOT application/json, which is what this file
# originally sent. The endpoint takes `overwrite` as a query parameter.
#   POST /v1/{orgId}/functions:import?overwrite=
#   files: {"file": ("Copy_parse_call_data_6.json", <json bytes>,
#                    "application/octet-stream")}
FUNCTION_IMPORT_FIELD = "file"
FUNCTION_IMPORT_PART_TYPE = "application/octet-stream"


def function_import_filename(document: dict, fn_id: str) -> str:
    """The uploaded part needs a .json filename; the API keys off it."""
    name = str((document or {}).get("name") or fn_id or "function").strip()
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)
    return (safe or "function") + ".json"


def import_flows(client, reader, bucket: str, idmap_: idmap_mod.IdMap,
                 overwrite: bool = False, confirm: bool = False) -> ImportResult:
    """Import one bucket of flows.

    Callers must import 'subflows' BEFORE 'flows': a flow can invoke a subflow,
    never the reverse.
    """
    result = ImportResult(entity=f"flows:{bucket}", dry_run=not confirm)
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
        # A flow document carries its own id; that is not a reference.
        result.dangling |= idmap_.unmapped(document) - {flow_id}
        result.planned.append({"action": "create", "item": {"id": flow_id},
                               "existing": None,
                               "reason": f"import into project {project_id}"})
        if not confirm:
            result.would_create.append(flow_id)
            idmap_.record(flow_id, flow_id)     # stand-in, as in import_entity
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
    if confirm:
        _map_flows_by_name(client, project_id, flow_type, reader.flows(bucket),
                           idmap_)
    return result


def _map_flows_by_name(client, project_id: str, flow_type: str,
                       source: dict, idmap_: idmap_mod.IdMap) -> None:
    """Map source flow ids to target ids by flow name, for any still unmapped.

    Entry points link to flows by id. The import response is not confirmed to
    carry the new id, and a flow that already existed in the target (import
    refused) is still the right link target - so match on name, which Flow
    Designer keeps unique per flow type.
    """
    pending = {fid: ((p or {}).get("meta") or {}).get("name")
               or ((p or {}).get("document") or {}).get("name")
               for fid, p in source.items() if idmap_.get(fid) is None}
    if not pending:
        return
    rows, _err = export_flows.list_flows(client, project_id, flow_type)
    by_name = {r.get("name"): r.get("id") for r in rows if r.get("name")}
    for fid, name in pending.items():
        if by_name.get(name):
            idmap_.record(fid, by_name[name])


def import_functions(client, reader, idmap_: idmap_mod.IdMap,
                     overwrite: bool = False,
                     confirm: bool = False) -> ImportResult:
    """Import custom functions.

    The API is asymmetric: export returns plain JSON, import takes
    multipart/form-data. The exact shape is not guessed - it was taken from a
    real successful import against the live tenant (U3, docs/api-notes.md):
    one part named "file", with a .json filename, typed
    application/octet-stream, carrying the exported document verbatim.
    """
    result = ImportResult(entity="flows:functions", dry_run=not confirm)
    functions = reader.functions()

    if FUNCTION_IMPORT_FIELD == UNRESOLVED:
        if functions:
            result.failed.append({
                "id": None,
                "detail": "the multipart field name for functions:import is "
                          "unresolved (U3 in docs/api-notes.md); refusing to "
                          "guess a field name."})
        return result

    path = f"v1/{{orgId}}/functions:import?overwrite={str(overwrite).lower()}"
    for fn_id, payload in functions.items():
        document = idmap_.substitute((payload or {}).get("document") or {})
        result.dangling |= idmap_.unmapped(document)
        filename = function_import_filename(document, fn_id)
        result.planned.append({"action": "create", "item": {"id": fn_id},
                               "existing": None,
                               "reason": f"import function as {filename}"})
        if not confirm:
            result.would_create.append(fn_id)
            idmap_.record(fn_id, fn_id)         # stand-in, as in import_entity
            continue
        parts = [(FUNCTION_IMPORT_FIELD, filename, FUNCTION_IMPORT_PART_TYPE,
                  _json.dumps(document).encode())]
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
        result = ImportResult(entity=f"calling:{name}", dry_run=not confirm)
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
            if name == "locations":
                # A location has no parent location; demanding one failed every
                # location create. ("scope" in the registry is the LISTING
                # scope - org-listed objects are still created per location.)
                raw_loc = None
            elif not raw_loc:
                result.failed.append({
                    "id": source_id,
                    "detail": f"{name} {source.get('name')!r} has no location "
                              "in the archive, and every Calling create endpoint "
                              "is location-scoped"})
                continue
            loc_id = idmap_.get(raw_loc) if raw_loc else None
            if raw_loc and not loc_id:
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
                result.would_create.append(source_id)
                if source_id:
                    idmap_.record(source_id, source_id)   # stand-in
                continue

            create_path = spec["item"].replace("{locationId}", loc_id or "")
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


def run_import(cc, wx, reader, keys: list[str], on_conflict: str, confirm: bool,
               target_org_id: str | None, overwrite_flows: bool = False,
               on_progress=None) -> dict[str, ImportResult]:
    """The whole import, in the one order that works. Used by the CLI AND the
    web UI - two hand-copied sequences had already drifted once.

      1. Contact Center entities, dependency-ordered (deferred fields held back)
      2. subflows, then flows (a flow can invoke a subflow, never the reverse)
      3. functions
      4. deferred fields - entry points get their flowId now the flows exist
      5. Webex Calling
    """
    seed = idmap_mod.IdMap()
    seed.known_source_ids = set(reader.source_ids())
    source_org = (reader.manifest.get("source") or {}).get("orgId")
    if source_org and target_org_id:
        # Flow documents embed the source org id; it must become the target org.
        seed.record(source_org, target_org_id)

    results, idmap_ = import_cc(cc, reader, keys, on_conflict, confirm,
                                on_progress=on_progress, idmap_=seed)

    def done(name: str, r: ImportResult) -> None:
        results[name] = r
        if on_progress:
            on_progress(name, r)

    for bucket in ("subflows", "flows"):
        if f"flows:{bucket}" in keys:
            done(f"flows:{bucket}", import_flows(cc, reader, bucket, idmap_,
                                                 overwrite_flows, confirm))
    if "flows:functions" in keys:
        done("flows:functions", import_functions(cc, reader, idmap_,
                                                 confirm=confirm))

    for entity in list(results):
        pending = getattr(results[entity], "deferred", None)
        if pending:
            r = apply_deferred(cc, entity, pending, idmap_, confirm)
            done(r.entity, r)

    calling_names = [k.split(":", 1)[1] for k in keys if k.startswith("calling:")]
    if calling_names:
        for name, r in import_calling(wx, reader, calling_names, idmap_,
                                      on_conflict, confirm).items():
            done(f"calling:{name}", r)
    return results
