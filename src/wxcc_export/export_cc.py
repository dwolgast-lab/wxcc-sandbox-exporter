"""Registry-driven export of Contact Center configuration.

One walk serves every entity: the registry already names the list path, so a
second hand-written mapping would only be a place for the two to drift.
"""

from __future__ import annotations

from . import registry
from .client import ApiError

# Server-generated bookkeeping. Sending these back on create is at best ignored
# and at worst a 400, so they are dropped - except createdTime, which the
# non-default heuristic needs and which the importer strips separately.
VOLATILE_FIELDS = frozenset({
    "version", "lastUpdatedTime", "lastUpdatedBy", "createdBy",
    "eTag", "etag", "links", "meta",
})

DEFAULT_WINDOW_SECONDS = 1800


def strip_volatile(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in VOLATILE_FIELDS}


SYSTEM_DEFAULT_FIELD = "systemDefault"


def tag_likely_defaults(items: list[dict], org_created_ms: int | float | None = None,
                        window_seconds: int = DEFAULT_WINDOW_SECONDS) -> list[dict]:
    """Mark which objects were provisioned with the tenant.

    TWO signals, in strict order of authority:

    1. `systemDefault` - a REAL field the API returns on 14 of 22 entities
       (agent-profile, audio-file, auxiliary-code, cad-variable,
       contact-service-queue, desktop-layout, entry-point, multimedia-profile,
       site, skill, team, user, user-profile, work-type). An earlier revision of
       this project asserted no such flag existed. That was wrong - it was an
       inference from an OpenAPI search, and the live API returns it.

    2. The createdTime heuristic, anchored on the ORG's own creation time -
       used ONLY for the 8 entities that carry no systemDefault at all
       (address-book, business-hours, dial-number, holiday-list, outdial-ani,
       overrides, resource-collection, skill-profile).

    Why the order matters, measured on a live tenant (docs/api-notes.md U4):
    the heuristic agreed with `systemDefault` on 11 entities and OVER-reported
    on 3 - team (+1), audio-file (+1), user (+3). Every disagreement was a FALSE
    POSITIVE: calling something a provisioning default that the API says is not.
    On `team` it wrongly flagged 'Sandbox Team AgentType - sukt', created 515 s
    after the org. False positives are exactly what makes --only-non-default
    discard real configuration.

    Each item records `default_basis` so a reader of the archive can tell a fact
    from an inference. Without either signal nothing is tagged - no anchor means
    no defensible claim.

    Whether the ENTITY supports the flag is decided per collection: if any
    record carries the key, absence on a sibling means "not a default". If no
    record carries it, the entity does not publish it and the heuristic applies.
    """
    if not items:
        return items

    entity_has_flag = any(SYSTEM_DEFAULT_FIELD in i for i in items)

    if entity_has_flag:
        return [{**i,
                 "likely_default": i.get(SYSTEM_DEFAULT_FIELD) is True,
                 "default_basis": "systemDefault"}
                for i in items]

    if org_created_ms is None:
        return items
    stamps = [i.get("createdTime") for i in items]
    if any(not isinstance(s, (int, float)) for s in stamps):
        return items
    window_ms = window_seconds * 1000          # createdTime is epoch milliseconds
    return [{**i,
             "likely_default": (i["createdTime"] - org_created_ms) <= window_ms,
             "default_basis": "createdTime-heuristic"}
            for i in items]


def export_entity(client, entity: str, org_created_ms: int | float | None = None) -> dict:
    """Export one entity. Never raises: a failure is recorded and returned."""
    result: dict = {"entity": entity, "count": 0, "items": [], "error": None}
    try:
        raw = client.list_all(registry.list_path(entity))
    except ApiError as exc:
        result["error"] = f"HTTP {exc.status}: {str(exc)[:200]}"
        return result
    except Exception as exc:                    # never let a failure read as empty
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    items = tag_likely_defaults([strip_volatile(i) for i in raw], org_created_ms)
    result["items"] = items
    result["count"] = len(items)
    return result


def export_all(client, entities: list[str], on_progress=None,
               org_created_ms: int | float | None = None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for entity in entities:
        result = export_entity(client, entity, org_created_ms)
        out[entity] = result
        if on_progress:
            on_progress(entity, result)
    return out


# --- child collections (address-book entries, outdial-ani entries) ---

def export_children(client, entity: str, parent_ids: list[str]) -> dict[str, dict]:
    """Export the child rows of every parent. An entity without children is {}."""
    if not registry.CC_ENTITIES.get(entity, {}).get("child"):
        return {}
    out: dict[str, dict] = {}
    for parent_id in parent_ids:
        record: dict = {"parent_id": parent_id, "count": 0,
                        "items": [], "error": None}
        try:
            rows = client.list_all(registry.child_list_path(entity, parent_id))
            record["items"] = [strip_volatile(r) for r in rows]
            record["count"] = len(record["items"])
        except ApiError as exc:
            record["error"] = f"HTTP {exc.status}: {str(exc)[:200]}"
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        out[parent_id] = record
    return out


# --- audio file bytes ---

# A real audio-file record carries NONE of these. Kept only as a fallback for a
# record that happens to expose a direct link; blobId is the primary route.
AUDIO_URL_FIELDS = ("url", "fileUrl", "audioFileUrl", "downloadUrl")

# Confirmed live 2026-08-26 (docs/api-notes.md U7). Ten candidate routes were
# probed; this is the only one that returned bytes:
#   GET organization/{orgId}/blob/{blobId}  ->  200, 160674 bytes, RIFF....WAVE
# The first live export fetched 0 of 11 files because the code looked for URL
# fields that do not exist on the record.
AUDIO_BLOB_PATH = "organization/{orgId}/blob/{blobId}"

# The blob response carries NO Content-Type, so the extension has to come from
# the record. `name` normally already has one; this maps the contentType enum
# for the cases where it does not.
CONTENT_TYPE_EXTENSIONS = {
    "AUDIO_X_WAV": ".wav",
    "AUDIO_WAV": ".wav",
    "AUDIO_MPEG": ".mp3",
    "AUDIO_MP3": ".mp3",
    "AUDIO_OGG": ".ogg",
}


def audio_filename(item: dict) -> str:
    """A filename for an audio record, with an extension that reflects reality."""
    name = str(item.get("name") or item.get("id") or "audio")
    if "." in name.rsplit("/", 1)[-1]:
        return name
    ext = CONTENT_TYPE_EXTENSIONS.get(str(item.get("contentType", "")).upper(), "")
    return name + ext


def export_audio_binaries(client, audio_items: list[dict]
                          ) -> tuple[dict[str, bytes], list[str]]:
    """Fetch the bytes behind each audio-file record.

    An audio file the tool could not fetch must be VISIBLE in the archive's
    error list, never merely absent - a silently missing prompt is how an
    imported flow plays nothing. That diagnostic is what exposed the original
    bug: it named the fields the record ACTUALLY had, which is how blobId was
    found.
    """
    blobs: dict[str, bytes] = {}
    errors: list[str] = []
    for item in audio_items:
        item_id = item.get("id")
        blob_id = item.get("blobId")
        if blob_id:
            path = AUDIO_BLOB_PATH.replace("{blobId}", str(blob_id))
        else:
            path = next((item[f] for f in AUDIO_URL_FIELDS if item.get(f)), None)
        if not path:
            errors.append(
                f"audio-file {item_id} ({item.get('name')}): no blobId and no "
                f"download url - fields present: {sorted(item)[:12]}")
            continue
        try:
            status, data, _ctype = client.get_bytes(path)
        except Exception as exc:
            errors.append(f"audio-file {item_id}: {type(exc).__name__}: {exc}")
            continue
        if status != 200:
            errors.append(f"audio-file {item_id} ({item.get('name')}): "
                          f"download returned HTTP {status}")
            continue
        if not data:
            # A 200 with an empty body is a failure, not an empty prompt.
            errors.append(f"audio-file {item_id} ({item.get('name')}): "
                          "download returned HTTP 200 but zero bytes")
            continue
        blobs[item_id] = data
    return blobs, errors


# --- users reference manifest ---

USER_COLUMNS = ["email", "firstName", "lastName", "site", "teams",
                "skillProfile", "userProfile", "desktopProfile",
                "multimediaProfile", "id"]


def build_users_manifest(users: list[dict], lookup: dict[str, dict]
                         ) -> tuple[list[dict], str]:
    """Flatten users into a human-readable mapping, ids resolved to names.

    Users have NO write path (the collection publishes GET only), so this is a
    re-entry aid for a person working in Control Hub, not import input. An
    unresolvable id is kept verbatim rather than blanked: a UUID a human can
    search for beats an empty cell.
    """
    def name_of(entity: str, value: str | None) -> str:
        if not value:
            return ""
        return lookup.get(entity, {}).get(value, value)

    rows: list[dict] = []
    for u in users:
        team_ids = u.get("teamIds") or []
        rows.append({
            "email": u.get("email", ""),
            "firstName": u.get("firstName", ""),
            "lastName": u.get("lastName", ""),
            "site": name_of("site", u.get("siteId")),
            "teams": "; ".join(name_of("team", t) for t in team_ids),
            "skillProfile": name_of("skill-profile", u.get("skillProfileId")),
            "userProfile": name_of("user-profile", u.get("userProfileId")),
            "desktopProfile": name_of("agent-profile", u.get("agentProfileId")),
            "multimediaProfile": name_of("multimedia-profile",
                                         u.get("multimediaProfileId")),
            "id": u.get("id", ""),
        })

    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    writer = _csv.DictWriter(buf, fieldnames=USER_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return rows, buf.getvalue()


def build_name_lookup(exported: dict[str, dict]) -> dict[str, dict]:
    """{entity: {id: name}} from an export_all result, for manifest resolution."""
    return {
        entity: {i["id"]: i.get("name", "") for i in result["items"] if i.get("id")}
        for entity, result in exported.items()
    }
