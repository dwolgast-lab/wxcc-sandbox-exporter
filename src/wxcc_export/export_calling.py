"""The bounded Webex Calling subset.

A different host from Contact Center: https://webexapis.com/v1. Most objects are
location-scoped, so the location list is fetched first and everything else fans
out from it. Losing the location list loses the whole section - that is reported,
not silently returned as empty.
"""

from __future__ import annotations

from . import registry
from .client import ApiError

# UNVERIFIED (U5 live probe has not run): the field an org-scoped Calling item
# uses to name its own location is not consistent across the API and is not
# confirmed against a live tenant. These are candidates, tried in order.
# docs/api-notes.md is where the probe records the truth once it runs.
ORG_ITEM_LOCATION_FIELDS = ("locationId", "location.id", "locationID")


def list_locations(client) -> list[dict]:
    return client.list_all(registry.CALLING_OBJECTS["locations"]["list"])


def _fetch(client, path: str) -> list[dict]:
    return client.list_all(path)


def _org_item_location_id(item: dict) -> str | None:
    for field in ORG_ITEM_LOCATION_FIELDS:
        if field == "location.id":
            location = item.get("location")
            value = location.get("id") if isinstance(location, dict) else None
        else:
            value = item.get(field)
        if value is not None:
            return value
    return None


def export_object(client, name: str, locations: list[dict]) -> dict:
    spec = registry.CALLING_OBJECTS[name]
    result: dict = {"object": name, "count": 0, "items": [], "error": None}
    errors: list[str] = []

    if spec["scope"] == "org":
        try:
            rows = _fetch(client, spec["list"])
        except ApiError as exc:
            result["error"] = _explain(exc)
            return result
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            return result
        tagged = []
        for r in rows:
            loc_id = _org_item_location_id(r)
            if loc_id is None:
                item_ref = r.get("id", "<no id>")
                errors.append(f"item {item_ref}: could not determine its location")
            tagged.append({**r, "_locationId": loc_id})
        result["items"] = tagged
    else:
        for loc in locations:
            loc_id = loc.get("id")
            path = spec["list"].replace("{locationId}", loc_id or "")
            try:
                rows = _fetch(client, path)
            except ApiError as exc:
                errors.append(f"location {loc_id}: {_explain(exc)}")
                continue
            except Exception as exc:
                errors.append(f"location {loc_id}: {type(exc).__name__}: {exc}")
                continue
            result["items"].extend({**r, "_locationId": loc_id} for r in rows)

    result["count"] = len(result["items"])
    if errors:
        result["error"] = "; ".join(errors[:5])
    return result


def _explain(exc: ApiError) -> str:
    if exc.status == 403:
        return (f"HTTP 403 - the token lacks the Calling scopes "
                f"(spark-admin:telephony_config_read). {str(exc)[:120]}")
    if exc.status == 404:
        return (f"HTTP 404 - Webex Calling may not be provisioned on this "
                f"tenant. {str(exc)[:120]}")
    return f"HTTP {exc.status}: {str(exc)[:160]}"


def export_all(client, names: list[str] | None = None,
               on_progress=None) -> dict:
    out: dict = {"locations": [], "objects": {}, "error": None}
    try:
        out["locations"] = list_locations(client)
    except ApiError as exc:
        out["error"] = ("could not list locations, so no location-scoped Calling "
                        f"object could be enumerated: {_explain(exc)}")
        return out
    except Exception as exc:
        out["error"] = f"could not list locations: {type(exc).__name__}: {exc}"
        return out

    targets = names or [n for n in registry.CALLING_OBJECTS if n != "locations"]
    for name in targets:
        result = export_object(client, name, out["locations"])
        out["objects"][name] = result
        if on_progress:
            on_progress(name, result)
    return out
