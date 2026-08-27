"""Who this tenant actually is, straight from its own record.

Authoritative on purpose: a configured label can drift or be copied to the wrong
profile. `subscriptionType` distinguishes a paying customer's org from a
trial/sandbox without anyone having to declare it.

`organization/{orgId}` on the WxCC host is NOT a reliable source (docs/api-notes.md,
U6): it is not part of the Contact Center API surface at all and returned HTTP 429
on every attempt in a live probe, surviving the client's full retry ladder. The
Webex host's `organizations/{orgId}` is the confirmed source for the display name
and creation time; `subscriptionType` has no other confirmed source, so it is only
opportunistically read from the CC host and never asserted when that call fails.
"""

from __future__ import annotations

import re
from datetime import datetime

NAME_UNAVAILABLE = "(org name unavailable)"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _iso_to_epoch_ms(value) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def org_info(client, webex_client=None) -> dict:
    org_id = client.org_id
    if not org_id:
        return {"name": "(org id unresolved)", "org_id": None,
                "subscription": None, "production": None, "created_ms": None}

    subscription = None
    try:
        status, body = client.json("GET", f"organization/{org_id}")
        if status == 200 and isinstance(body, dict):
            subscription = body.get("subscriptionType")
    except Exception:
        pass

    name = None
    created_ms = None
    if webex_client is not None:
        try:
            status, body = webex_client.json("GET", f"organizations/{org_id}")
            if status == 200 and isinstance(body, dict):
                name = body.get("displayName")
                created_ms = _iso_to_epoch_ms(body.get("created"))
        except Exception:
            pass

    return {
        "name": name or NAME_UNAVAILABLE,
        "org_id": org_id,
        "subscription": subscription,
        # A paying subscription is a real customer tenant. Trials are sandboxes.
        # None means unknown (the CC endpoint was unreachable) - never guess.
        "production": None if subscription is None else subscription == "SUBSCRIPTION",
        "created_ms": created_ms,
    }


def safe_slug(name: str) -> str:
    """Make a tenant name safe to use as a filename component."""
    slug = _UNSAFE.sub("-", (name or "").strip()).strip("-.")
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.replace("..", "")
    return slug[:80] or "wxcc-tenant"


def archive_name(info: dict) -> str:
    name = info.get("name") or ""
    if not name or name.startswith("("):
        name = info.get("org_id") or "wxcc-tenant"
    return f"{safe_slug(name)}-export.zip"


def describe(info: dict) -> str:
    """One line naming exactly which tenant a result came from / would change."""
    if info.get("production") is None:
        return f"{info.get('name')} [subscription type unknown] (org {info.get('org_id')})"
    tag = "PRODUCTION" if info["production"] else "trial/sandbox"
    return f"{info['name']} [{tag}] (org {info['org_id']})"
