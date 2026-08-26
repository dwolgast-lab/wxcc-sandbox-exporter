"""Who this tenant actually is, straight from its own record.

Authoritative on purpose: a configured label can drift or be copied to the wrong
profile. `subscriptionType` distinguishes a paying customer's org from a
trial/sandbox without anyone having to declare it.
"""

from __future__ import annotations

import re

NAME_UNAVAILABLE = "(org name unavailable)"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def org_info(client) -> dict:
    org_id = client.org_id
    if not org_id:
        return {"name": "(org id unresolved)", "org_id": None,
                "subscription": None, "production": None}
    try:
        status, body = client.json("GET", f"organization/{org_id}")
    except Exception:
        status, body = 0, None
    if status != 200 or not isinstance(body, dict):
        return {"name": NAME_UNAVAILABLE, "org_id": org_id,
                "subscription": None, "production": None}
    return {
        "name": body.get("name") or NAME_UNAVAILABLE,
        "org_id": org_id,
        "subscription": body.get("subscriptionType"),
        # A paying subscription is a real customer tenant. Trials are sandboxes.
        "production": body.get("subscriptionType") == "SUBSCRIPTION",
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
        return f"{info.get('name')} (org {info.get('org_id')})"
    tag = "PRODUCTION" if info["production"] else "trial/sandbox"
    return f"{info['name']} [{tag}] (org {info['org_id']})"
