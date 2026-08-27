"""Command-line interface.

Exit codes are part of the contract:
  0  success
  1  usage or configuration error
  2  authentication error
  3  the operation ran but recorded errors (a PARTIAL result)

Code 3 exists so "exported with 4 objects missing" cannot be mistaken for
"exported cleanly".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import (archive, auth, client, config, export_calling, export_cc,
               export_flows, importer, plan, registry, tenant)

EXIT_OK, EXIT_USAGE, EXIT_AUTH, EXIT_PARTIAL = 0, 1, 2, 3


def build_parser() -> argparse.ArgumentParser:
    # A shared parent so --profile is accepted both before AND after the
    # subcommand (`wxcc-export --profile x export` and `wxcc-export export
    # --profile x`) - argparse does not propagate a top-level optional into a
    # chosen subparser on its own.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", default=None,
                        help="use .env.<profile> and its own token store")

    p = argparse.ArgumentParser(
        prog="wxcc-export",
        description="Export and import Webex Contact Center sandbox configuration.",
        parents=[common])
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("auth", help="manage authentication", parents=[common])
    a.add_argument("action", choices=["login", "status", "logout"])

    e = sub.add_parser("export", help="export this tenant to a zip archive",
                       parents=[common])
    e.add_argument("--out", default=".", help="directory for the archive")
    e.add_argument("--select", default="all",
                   help="all | cc | flows | calling | comma-separated keys")
    e.add_argument("--only-non-default", action="store_true",
                   help="omit objects the createdTime heuristic flags as "
                        "provisioning defaults (opt-in; can lose real config)")

    i = sub.add_parser("inspect", help="show what an archive contains",
                       parents=[common])
    i.add_argument("archive")

    m = sub.add_parser("import", help="import an archive into THIS tenant",
                       parents=[common])
    m.add_argument("archive")
    m.add_argument("--select", default="all")
    m.add_argument("--on-conflict", choices=list(plan.CONFLICT_POLICIES),
                   default="skip")
    m.add_argument("--confirm", action="store_true",
                   help="actually write. Without this, prints the plan only.")
    m.add_argument("--overwrite-flows", action="store_true",
                   help="pass overwrite=true to the flow import endpoint")

    w = sub.add_parser("web", help="serve the local selection UI",
                       parents=[common])
    w.add_argument("--port", type=int, default=8787)
    return p


def _clients(cfg: dict) -> tuple:
    # The bearer-token warning is printed once, in main(), for every command
    # that authenticates - not here, or export/import would show it twice.
    token, _ = auth.valid_access_token(cfg)
    org_id = cfg["org_id"] or auth.extract_org_id(token)
    cc = client.ApiClient(cfg["api_base"], token, org_id=org_id)
    wx = client.ApiClient(cfg["webex_base"], token, org_id=org_id)
    return cc, wx


def _run_export(cfg: dict, args) -> int:
    cc, wx = _clients(cfg)
    info = tenant.org_info(cc, wx)
    print(f"Source tenant: {tenant.describe(info)}")

    entities = [e for e in registry.CC_ENTITIES]
    exported = export_cc.export_all(
        cc, entities,
        on_progress=lambda e, r: print(
            f"  {e:24s} {r['count']:5d}" + (f"  ERROR {r['error']}" if r["error"] else "")),
        org_created_ms=info["created_ms"])

    if args.only_non_default:
        # The progress lines above printed PRE-filter counts, so report what
        # the filter actually removed. Otherwise the terminal disagrees with
        # the archive, and the operator trusts the wrong number.
        dropped_total = 0
        by_basis = {"systemDefault": 0, "createdTime-heuristic": 0}
        for result in exported.values():
            before = result["items"]
            kept = [i for i in before if not i.get("likely_default")]
            for i in before:
                if i.get("likely_default"):
                    basis = i.get("default_basis", "unknown")
                    by_basis[basis] = by_basis.get(basis, 0) + 1
            dropped = len(before) - len(kept)
            if dropped:
                print(f"  --only-non-default: {result['entity']} "
                      f"{len(before)} -> {len(kept)} ({dropped} dropped)")
            dropped_total += dropped
            result["items"] = kept
            result["count"] = len(kept)
        print(f"  --only-non-default removed {dropped_total} object(s): "
              f"{by_basis.get('systemDefault', 0)} by the API's systemDefault "
              f"flag, {by_basis.get('createdTime-heuristic', 0)} INFERRED from "
              "creation time (see docs/api-notes.md U4).")

    children = {}
    for entity in ("address-book", "outdial-ani"):
        ids = [i["id"] for i in exported.get(entity, {}).get("items", [])
               if i.get("id")]
        got = export_cc.export_children(cc, entity, ids)
        if got:
            children[entity] = got

    blobs, audio_errors = export_cc.export_audio_binaries(
        cc, exported.get("audio-file", {}).get("items", []))
    audio = {i: {"bytes": b,
                 "name": next((x.get("name", "audio")
                               for x in exported["audio-file"]["items"]
                               if x.get("id") == i), "audio")}
             for i, b in blobs.items()}
    if audio_errors:
        combined = "; ".join(audio_errors)
        record = exported.setdefault("audio-file", {})
        record["error"] = (f"{record['error']}; {combined}"
                           if record.get("error") else combined)

    # Flows are disabled by evidence (U1, docs/api-notes.md): the flows API
    # is not served on the WxCC regional host at all, so there is no project
    # id to resolve - resolve_project_id() would only raise. export_all_flows
    # records that finding as an error and makes no HTTP call.
    flows = export_flows.export_all_flows(cc, None)
    functions = export_flows.export_all_functions(cc)
    calling = export_calling.export_all(
        wx, on_progress=lambda n, r: print(
            f"  calling/{n:20s} {r['count']:5d}"
            + (f"  ERROR {r['error']}" if r["error"] else "")))

    lookup = export_cc.build_name_lookup(exported)
    rows, csv_text = export_cc.build_users_manifest(
        exported.get("user", {}).get("items", []), lookup)

    out_path = Path(args.out) / tenant.archive_name(info)
    manifest = archive.write_export(
        out_path,
        source={"orgId": info["org_id"], "orgName": info["name"],
                "subscriptionType": info.get("subscription"),
                "apiBase": cfg["api_base"]},
        cc=exported, children=children, audio=audio, flows=flows,
        functions=functions, calling=calling,
        users={"rows": rows, "csv": csv_text})

    print(f"\nWrote {out_path}")
    if manifest["errors"]:
        print(f"\n{len(manifest['errors'])} object(s) FAILED and are missing "
              f"from the archive. See UNSUPPORTED.md inside it.")
        for e in manifest["errors"][:10]:
            print(f"  - {e['section']}/{e['object']}: {e['detail'][:120]}")
        return EXIT_PARTIAL
    return EXIT_OK


def _run_inspect(args) -> int:
    try:
        reader = archive.ArchiveReader(args.archive)
    except archive.IncompatibleArchive as exc:
        print(f"cannot read archive: {exc}", file=sys.stderr)
        return EXIT_USAGE
    m = reader.manifest
    print(f"Archive:  {args.archive}")
    print(f"Source:   {m['source'].get('orgName')} "
          f"(org {m['source'].get('orgId')})")
    print(f"Exported: {m['exportedAt']}\n")
    for sel in archive.available_selections(m):
        flag = "" if sel["writable"] else "   [read-only, export reference only]"
        print(f"  {sel['key']:34s} {sel['count']:5d}  {sel['group']}{flag}")
    print(f"\nNo API exists for: {', '.join(m['unsupported'])}")
    if m["errors"]:
        print(f"\n{len(m['errors'])} object(s) are MISSING from this archive:")
        for e in m["errors"]:
            print(f"  - {e['section']}/{e['object']}: {e['detail'][:140]}")
        reader.close()
        return EXIT_PARTIAL
    reader.close()
    return EXIT_OK


def _run_import(cfg: dict, args) -> int:
    try:
        reader = archive.ArchiveReader(args.archive)
    except archive.IncompatibleArchive as exc:
        print(f"cannot read archive: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        keys = archive.parse_selection(args.select, reader.manifest)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE

    cc, wx = _clients(cfg)
    info = tenant.org_info(cc, wx)
    source_name = reader.manifest["source"].get("orgName")

    print(f"Source archive: {source_name}")
    print(f"TARGET tenant:  {tenant.describe(info)}")
    if info.get("org_id") == reader.manifest["source"].get("orgId"):
        print("\nREFUSING: the target tenant is the same org the archive came "
              "from. Point --profile at the NEW sandbox.", file=sys.stderr)
        return EXIT_USAGE
    if not args.confirm:
        print("\nDRY RUN - nothing will be written. Add --confirm to apply.\n")

    results, idmap_ = importer.import_cc(
        cc, reader, keys, args.on_conflict, args.confirm,
        on_progress=lambda e, r: print(f"  {r.summary()}"))

    # Subflows before flows: a flow can invoke a subflow, never the reverse.
    for bucket in ("subflows", "flows"):
        if f"flows:{bucket}" in keys:
            r = importer.import_flows(cc, reader, bucket, idmap_,
                                      args.overwrite_flows, args.confirm)
            results[f"flows:{bucket}"] = r
            print(f"  {r.summary()}")
    if "flows:functions" in keys:
        r = importer.import_functions(cc, reader, idmap_, confirm=args.confirm)
        results["flows:functions"] = r
        print(f"  {r.summary()}")

    calling_names = [k.split(":", 1)[1] for k in keys if k.startswith("calling:")]
    if calling_names:
        for name, r in importer.import_calling(wx, reader, calling_names, idmap_,
                                               args.on_conflict,
                                               args.confirm).items():
            results[f"calling:{name}"] = r
            print(f"  {r.summary()}")

    failed = sum(len(r.failed) for r in results.values())
    unverified = sum(len(r.unverified) for r in results.values())
    dangling = set().union(*(r.dangling for r in results.values())) if results else set()

    print("\n--- summary ---")
    for r in results.values():
        for f in r.failed:
            print(f"  FAILED  {r.entity} {f['id']}: {f['detail'][:160]}")
        for u in r.unverified:
            print(f"  UNVERIFIED {r.entity} {u['id']}: the server did not store "
                  f"{', '.join(u['fields'])}")
    if dangling:
        print(f"\n  {len(dangling)} reference(s) point at objects that were not "
              "imported. Those links are broken in the target:")
        for d in sorted(dangling)[:15]:
            print(f"    {d}")

    reader.close()
    if not args.confirm:
        print("\nDry run complete. Nothing was written.")
        return EXIT_OK
    return EXIT_PARTIAL if (failed or unverified or dangling) else EXIT_OK


def _run_auth(cfg: dict, args) -> int:
    if args.action == "login":
        tok = auth.login(cfg)
        print(f"Authenticated. org id: {tok.get('org_id')}")
        return EXIT_OK
    if args.action == "logout":
        auth.logout(cfg)
        print("Token removed.")
        return EXIT_OK
    token, source = auth.valid_access_token(cfg)
    org_id = cfg["org_id"] or auth.extract_org_id(token)
    cc = client.ApiClient(cfg["api_base"], token, org_id=org_id)
    wx = client.ApiClient(cfg["webex_base"], token, org_id=org_id)
    print(f"auth source: {source}")
    print(f"tenant:      {tenant.describe(tenant.org_info(cc, wx))}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # inspect only reads a local archive - it needs no credentials, so it must
    # not be gated on a config file that a fresh checkout does not have yet.
    if args.command == "inspect":
        return _run_inspect(args)

    try:
        cfg = config.load_config(args.profile)
    except config.ConfigError as exc:
        print(f"{exc}\n", file=sys.stderr)
        return EXIT_USAGE

    if cfg.get("bearer_token"):
        print("AUTH: personal bearer token (OAuth2 bypassed)")

    try:
        if args.command == "auth":
            return _run_auth(cfg, args)
        if args.command == "export":
            return _run_export(cfg, args)
        if args.command == "import":
            return _run_import(cfg, args)
        if args.command == "web":
            from .web.server import serve
            return serve(cfg, args.port)
    except auth.AuthError as exc:
        print(f"authentication error: {exc}", file=sys.stderr)
        return EXIT_AUTH
    except config.ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_USAGE
