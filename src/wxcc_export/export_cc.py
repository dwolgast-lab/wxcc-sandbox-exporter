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

DEFAULT_WINDOW_SECONDS = 120


def strip_volatile(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in VOLATILE_FIELDS}


def tag_likely_defaults(items: list[dict],
                        window_seconds: int = DEFAULT_WINDOW_SECONDS) -> list[dict]:
    """Label objects created in the same burst as the earliest one.

    This is a HEURISTIC, not a fact the API states: there is no isDefault flag
    on any entity. Objects provisioned with the tenant share a creation instant;
    anything created later was created by a person. The label is never used to
    filter silently - only to populate --only-non-default, which is opt-in.
    """
    stamps = [i.get("createdTime") for i in items]
    if not items or any(not isinstance(s, (int, float)) for s in stamps):
        return items
    earliest = min(stamps)
    window_ms = window_seconds * 1000          # createdTime is epoch milliseconds
    return [{**i, "likely_default": (i["createdTime"] - earliest) <= window_ms}
            for i in items]


def export_entity(client, entity: str) -> dict:
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
    items = tag_likely_defaults([strip_volatile(i) for i in raw])
    result["items"] = items
    result["count"] = len(items)
    return result


def export_all(client, entities: list[str], on_progress=None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for entity in entities:
        result = export_entity(client, entity)
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

AUDIO_URL_FIELDS = ("url", "fileUrl", "audioFileUrl", "downloadUrl")


def export_audio_binaries(client, audio_items: list[dict]
                          ) -> tuple[dict[str, bytes], list[str]]:
    """Fetch the bytes behind each audio-file record.

    An audio file the tool could not fetch must be VISIBLE in the archive's
    error list, never merely absent - a silently missing prompt is how an
    imported flow plays nothing.
    """
    blobs: dict[str, bytes] = {}
    errors: list[str] = []
    for item in audio_items:
        item_id = item.get("id")
        url = next((item[f] for f in AUDIO_URL_FIELDS if item.get(f)), None)
        if not url:
            errors.append(
                f"audio-file {item_id} ({item.get('name')}): no download url in "
                f"the record - fields present: {sorted(item)[:10]}")
            continue
        try:
            status, data, _ctype = client.get_bytes(url)
        except Exception as exc:
            errors.append(f"audio-file {item_id}: {type(exc).__name__}: {exc}")
            continue
        if status != 200 or not data:
            errors.append(f"audio-file {item_id} ({item.get('name')}): "
                          f"download returned HTTP {status}")
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
