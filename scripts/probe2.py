#!/usr/bin/env python3
"""Follow-up probe: resolve what probe.py proved wrong.

READ-ONLY. Never prints the token.

probe.py established:
  - GET organization/{orgId} on the WxCC host does NOT work (org name unavailable)
  - /{orgId}/project/{orgId}/flows 404s with an EMPTY body, which reads as a
    routing miss rather than a service-level "not found"
  - Calling responses use a per-object envelope key that client.list_all does
    not recognise

This script hunts for the right routes instead of guessing them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wxcc_export import auth, client, config  # noqa: E402


def show(label: str, status: int, body: object, limit: int = 220) -> None:
    if isinstance(body, dict):
        blob = f"keys={sorted(body)[:8]}"
        for k in ("message", "error", "errorMessage"):
            if body.get(k):
                blob += f" msg={str(body[k])[:120]!r}"
    elif isinstance(body, list):
        blob = f"array[{len(body)}]"
    elif body is None:
        blob = "<no body>"
    else:
        blob = str(body)[:limit]
    mark = "  <-- WORKS" if status == 200 else ""
    print(f"  {status:>3}  {label}{mark}")
    print(f"       {blob}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None)
    args = ap.parse_args()

    cfg = config.load_config(args.profile)
    token, _src = auth.valid_access_token(cfg)
    org = cfg["org_id"] or auth.extract_org_id(token)
    cc = client.ApiClient(cfg["api_base"], token, org_id=org)
    wx = client.ApiClient(cfg["webex_base"], token, org_id=org)

    print(f"org: {org}")
    print(f"cc base:    {cfg['api_base']}")
    print(f"webex base: {cfg['webex_base']}")

    # ------------------------------------------------------- org name
    print("\n=== A. Where does the tenant NAME live? ===")
    for label, cl, path in [
        ("WEBEX  /organizations/{org}", wx, f"organizations/{org}"),
        ("WEBEX  /organizations", wx, "organizations"),
        ("CC     organization/{org}", cc, f"organization/{org}"),
        ("CC     v2/organization/{org}", cc, f"v2/organization/{org}"),
        ("WEBEX  /identity/organizations/{org}", wx, f"identity/organizations/{org}"),
    ]:
        st, bd = cl.json("GET", path)
        show(label, st, bd)
        if st == 200 and isinstance(bd, dict):
            name = bd.get("displayName") or bd.get("name")
            if name:
                print(f"       >>> NAME = {name!r}")
        if st == 200 and isinstance(bd, dict) and isinstance(bd.get("items"), list):
            for it in bd["items"][:3]:
                if it.get("id") == org:
                    print(f"       >>> NAME = {it.get('displayName')!r}")

    # ------------------------------------------------------- flows
    print("\n=== B. Where do FLOWS live? (empty-body 404 = routing miss) ===")
    candidates = [
        f"{org}/project/{org}/flows",
        f"flow-store/{org}/project/{org}/flows",
        f"v1/{org}/project/{org}/flows",
        f"v1/flow-store/{org}/project/{org}/flows",
        f"flow-service/{org}/project/{org}/flows",
        f"designer/{org}/project/{org}/flows",
        f"organization/{org}/flow",
        f"organization/{org}/v2/flow",
        f"v1/{org}/flows",
        f"{org}/flows",
        f"{org}/project/{org}/v2/flows",
    ]
    for path in candidates:
        st, bd = cc.json("GET", f"{path}?includePagination=true&size=5")
        show(f"CC  /{path}", st, bd)

    # Is there a project list to discover projectId from?
    print("\n  -- looking for a project list --")
    for path in [f"{org}/projects", f"{org}/project", f"v1/{org}/projects",
                 f"flow-store/{org}/projects", f"organization/{org}/project"]:
        st, bd = cc.json("GET", path)
        show(f"CC  /{path}", st, bd)

    # ------------------------------------------------------- calling envelopes
    print("\n=== C. Calling envelope keys (list_all must handle these) ===")
    for name, path in [
        ("locations", "locations"),
        ("autoAttendants", "telephony/config/autoAttendants"),
        ("huntGroups", "telephony/config/huntGroups"),
        ("callParkExtensions", "telephony/config/callParkExtensions"),
        ("paging", "telephony/config/paging"),
        ("announcements", "telephony/config/announcements"),
        ("virtualExtensions", "telephony/config/virtualExtensions"),
        ("operatingModes", "telephony/config/operatingModes"),
    ]:
        st, bd = wx.json("GET", path)
        keys = sorted(bd) if isinstance(bd, dict) else type(bd).__name__
        listkeys = ([k for k, v in bd.items() if isinstance(v, list)]
                    if isinstance(bd, dict) else [])
        print(f"  {st:>3}  {name:22s} keys={keys} list-valued={listkeys}")

    # Does list_all survive these shapes?
    print("\n  -- does client.list_all handle them today? --")
    for name, path in [("autoAttendants", "telephony/config/autoAttendants"),
                       ("huntGroups", "telephony/config/huntGroups"),
                       ("announcements", "telephony/config/announcements")]:
        try:
            rows = wx.list_all(path)
            print(f"  OK    {name}: {len(rows)} rows")
        except Exception as exc:
            print(f"  FAIL  {name}: {type(exc).__name__}: {str(exc)[:150]}")

    # ------------------------------------------------------- call queues
    print("\n=== D. call-queues: find the real route ===")
    st, bd = wx.json("GET", "locations")
    locs = (bd or {}).get("items", []) if isinstance(bd, dict) else []
    lid = locs[0].get("id") if locs else None
    print(f"  using location: {str(lid)[:40]}...")
    if lid:
        for path in [f"telephony/config/locations/{lid}/queues",
                     "telephony/config/queues",
                     f"telephony/config/locations/{lid}/callQueues",
                     "telephony/config/callQueues"]:
            st, bd = wx.json("GET", path)
            show(f"WEBEX /{path[:70]}", st, bd)

    print("\nDone. Nothing was written to the tenant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
