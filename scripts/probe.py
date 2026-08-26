#!/usr/bin/env python3
"""Answer the questions the OpenAPI documents cannot.

READ-ONLY. This script issues GET requests plus the two POST *export* verbs
(functions :export, which is a read despite the verb). It writes NOTHING to the
tenant and never prints your token.

    python scripts/probe.py [--profile NAME] [--out docs/api-notes.md]

Every finding is recorded as what the API DID, not what the spec says it should
do. Where the two disagree, the probe wins.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wxcc_export import auth, client, config, registry, tenant  # noqa: E402

LINE = "-" * 74
report: list[str] = []


def out(text: str = "") -> None:
    print(text)
    report.append(text)


def probe(label: str, fn) -> tuple[int, object]:
    """Run one request, print a compact result, never raise."""
    try:
        status, body = fn()
    except Exception as exc:
        out(f"  {label}\n      EXCEPTION {type(exc).__name__}: {exc}")
        return 0, None
    if isinstance(body, dict):
        keys = sorted(body)[:10]
        n = len(body.get("data") or body.get("items") or [])
        blob = f"keys={keys} items={n}"
    elif isinstance(body, list):
        blob = f"bare array, {len(body)} items"
    else:
        blob = str(body)[:160]
    out(f"  {label}\n      HTTP {status}  {blob}")
    return status, body


def rows_of(body: object) -> list:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("data", "items"):
            if isinstance(body.get(key), list):
                return body[key]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None)
    ap.add_argument("--out", default="docs/api-notes.md")
    args = ap.parse_args()

    try:
        cfg = config.load_config(args.profile)
    except config.ConfigError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    try:
        token, source = auth.valid_access_token(cfg)
    except auth.AuthError as exc:
        print(f"authentication error: {exc}", file=sys.stderr)
        return 2

    if source == "bearer":
        out("AUTH: personal bearer token (OAuth2 bypassed)")
    org_id = cfg["org_id"] or auth.extract_org_id(token)
    if not org_id:
        print("could not derive an org id from the token. Set WXCC_ORG_ID.",
              file=sys.stderr)
        return 2

    cc = client.ApiClient(cfg["api_base"], token, org_id=org_id)
    wx = client.ApiClient(cfg["webex_base"], token, org_id=org_id)

    info = tenant.org_info(cc)
    out(f"TENANT: {tenant.describe(info)}")
    out(f"API BASE: {cfg['api_base']}")
    out(LINE)

    findings: dict[str, str] = {}

    # ---------------------------------------------------------------- U6
    out("\n=== U6: org name -> archive filename ===")
    out(f"  GET organization/{{orgId}} -> name = {info.get('name')!r}")
    out(f"  subscriptionType = {info.get('subscription')!r}")
    out(f"  archive would be named: {tenant.archive_name(info)}")
    findings["U6"] = (f"org name {info.get('name')!r}; archive "
                      f"`{tenant.archive_name(info)}`")

    # ---------------------------------------------------------------- U1
    out("\n=== U1: what is the flows projectId? ===")
    status, body = probe(
        f"GET /{{orgId}}/project/{org_id}/flows  (projectId == orgId)",
        lambda: cc.json("GET", f"{{orgId}}/project/{org_id}/flows"
                               "?includePagination=true&size=5"))
    if status == 200:
        findings["U1"] = "CONFIRMED: projectId is the org id (HTTP 200)."
    else:
        findings["U1"] = (f"NOT confirmed: projectId==orgId returned HTTP "
                          f"{status}. projectId comes from somewhere else - "
                          "do NOT guess; flows export must stay disabled.")

    # ---------------------------------------------------------------- U2
    out("\n=== U2: which flowType selects Subflows? ===")
    seen: dict[str, tuple[int, int]] = {}
    for ft in ("FLOW", "SUBFLOW", "Subflow", "SUB_FLOW", "subflow"):
        st, bd = probe(f"flowType={ft}",
                       lambda ft=ft: cc.json(
                           "GET", f"{{orgId}}/project/{org_id}/flows"
                                  f"?flowType={ft}&includePagination=true&size=5"))
        seen[ft] = (st, len(rows_of(bd)))
    ok = [f"{k} -> HTTP {v[0]}, {v[1]} items" for k, v in seen.items()]
    out("  summary: " + "; ".join(ok))
    good = [k for k, v in seen.items() if v[0] == 200 and k != "FLOW"]
    findings["U2"] = ("candidates accepted: " + (", ".join(good) or "NONE") +
                      f". Raw: {seen}. NOTE a 200 with 0 items does not prove "
                      "the value is right - it may just be ignored. Compare "
                      "against the Subflows actually visible in Control Hub.")

    # ---------------------------------------------------------------- U3
    out("\n=== U3: functions export shape / import field ===")
    st, bd = probe("GET /v1/{orgId}/functions",
                   lambda: cc.json("GET", f"v1/{{orgId}}/functions?size=5"))
    fn_rows = rows_of(bd)
    if fn_rows:
        fid = fn_rows[0].get("id")
        st2, bd2 = probe(f"POST /v1/{{orgId}}/functions/{fid}:export",
                         lambda: cc.json(
                             "POST", f"v1/{{orgId}}/functions/{fid}:export"))
        keys = sorted(bd2) if isinstance(bd2, dict) else type(bd2).__name__
        out(f"      export top-level keys: {keys}")
        findings["U3"] = (f"export returns {keys}. The multipart field name for "
                          ":import is STILL UNRESOLVED - it cannot be read off a "
                          "GET. Determine it from the Webex developer docs or a "
                          "deliberate trial import, then set "
                          "importer.FUNCTION_IMPORT_FIELD.")
    else:
        findings["U3"] = ("no functions exist in this tenant, so the export "
                          "shape could not be observed. Import field remains "
                          "UNRESOLVED; import_functions will refuse.")

    # ---------------------------------------------------------------- U4
    out("\n=== U4: does createdTime exist, and does it cluster? ===")
    stamps_seen: dict[str, list] = {}
    for ent in ("site", "team", "auxiliary-code", "contact-service-queue"):
        st, bd = probe(f"{ent}",
                       lambda ent=ent: cc.json("GET", registry.list_path(ent)))
        rows = rows_of(bd)[:8]
        pairs = [(r.get("name"), r.get("createdTime") or r.get("createdAt"))
                 for r in rows]
        stamps_seen[ent] = pairs
        for name, ts in pairs:
            out(f"      {str(name)[:34]:34s} createdTime={ts}")
    has = {e: any(ts is not None for _n, ts in v) for e, v in stamps_seen.items()}
    findings["U4"] = (f"createdTime present per entity: {has}. If all False the "
                      "likely_default heuristic is unavailable and "
                      "collision-aware import is the only mechanism.")

    # ---------------------------------------------------------------- U5
    out("\n=== U5: is Webex Calling reachable, and where does location live? ===")
    calling: dict[str, int] = {}
    loc_rows: list = []
    st, bd = probe("GET /locations", lambda: wx.json("GET", "locations"))
    calling["locations"] = st
    loc_rows = rows_of(bd)
    out(f"      locations found: {len(loc_rows)}")

    for name in ("auto-attendants", "hunt-groups", "announcements",
                 "virtual-extensions", "operating-modes", "paging-groups",
                 "call-park-extensions"):
        spec = registry.CALLING_OBJECTS[name]
        st, bd = probe(f"{name}  ({spec['list']})",
                       lambda spec=spec: wx.json("GET", spec["list"]))
        calling[name] = st
        # THE question the review made load-bearing: which field carries the
        # location on an ORG-scope item?
        for row in rows_of(bd)[:3]:
            cand = {k: row.get(k) for k in
                    ("locationId", "locationID", "location") if k in row}
            if cand:
                out(f"      location fields on a {name} row: {cand}")

    # The two routes registry.py marks UNCONFIRMED.
    if loc_rows:
        lid = loc_rows[0].get("id")
        out(f"\n  -- the two UNCONFIRMED routes, against location {lid} --")
        for name in ("call-queues", "call-parks", "call-pickups", "schedules"):
            spec = registry.CALLING_OBJECTS[name]
            path = spec["list"].replace("{locationId}", lid or "")
            st, _ = probe(f"{name}  ({path})",
                          lambda path=path: wx.json("GET", path))
            calling[name] = st

    reachable = {k: v for k, v in calling.items() if v == 200}
    findings["U5"] = (f"statuses: {calling}. Reachable: {sorted(reachable)}. "
                      "403 = the token lacks spark-admin:telephony_config_read; "
                      "404 = Calling is not provisioned on this tenant.")

    # ---------------------------------------------------------------- write
    out("\n" + LINE)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    doc = [f"# API notes - observed behaviour", "",
           "Findings from a live WxCC tenant. **The spec maps what exists; the",
           "probe records what works.** Where they disagree, the probe wins.", "",
           f"Probed: {stamp} against org `{org_id}` "
           f"(`{info.get('name')}`, {info.get('subscription')}).", ""]
    for key in ("U1", "U2", "U3", "U4", "U5", "U6"):
        doc += [f"## {key}", "", findings.get(key, "not probed"), ""]
    doc += ["## Raw transcript", "", "```", *report, "```", ""]

    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(doc), encoding="utf-8")
    print(f"\nWrote {dest}")
    print("Review it, then update the PROVISIONAL constants in "
          "export_flows.py / importer.py / registry.py to match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
