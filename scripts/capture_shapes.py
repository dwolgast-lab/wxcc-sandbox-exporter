#!/usr/bin/env python3
"""Snapshot every entity's real record shape before a tenant disappears.

READ-ONLY. Never prints the token.

The archive holds the DATA. This holds the SCHEMA AS OBSERVED: for each entity,
the union of fields across all rows, each field's Python type and a sample
value, which fields are always/sometimes/never populated, and one full record.
Plus the reference graph from incoming-references.

That is what makes an import failure debuggable after the source tenant is gone
-- a 400 naming a field you can no longer inspect is otherwise a dead end.

    python scripts/capture_shapes.py [--profile NAME] [--out FILE]
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wxcc_export import auth, client, config, export_cc, registry  # noqa: E402


def describe(rows: list[dict]) -> dict:
    """Field inventory across every row of one entity."""
    counts: collections.Counter = collections.Counter()
    types: dict[str, set] = collections.defaultdict(set)
    samples: dict[str, object] = {}
    populated: collections.Counter = collections.Counter()

    for r in rows:
        for k, v in r.items():
            counts[k] += 1
            types[k].add(type(v).__name__)
            if v not in (None, "", [], {}):
                populated[k] += 1
                if k not in samples:
                    samples[k] = v if not isinstance(v, (list, dict)) \
                        else json.loads(json.dumps(v))[:3] if isinstance(v, list) else v
    n = len(rows)
    return {
        "rowCount": n,
        "fields": {
            k: {
                "presentIn": counts[k],
                "populatedIn": populated[k],
                "always": counts[k] == n,
                "types": sorted(types[k]),
                "sample": samples.get(k),
            }
            for k in sorted(counts)
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--refs", action="store_true",
                    help="also walk incoming-references (slower, many calls)")
    args = ap.parse_args()

    cfg = config.load_config(args.profile)
    token, _src = auth.valid_access_token(cfg)
    org = cfg["org_id"] or auth.extract_org_id(token)
    cc = client.ApiClient(cfg["api_base"], token, org_id=org)

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: dict = {"capturedAt": stamp, "orgId": org, "entities": {}, "errors": []}

    for entity in sorted(registry.CC_ENTITIES):
        try:
            # Use the exporter's own listing so a sweep (entry-point) applies.
            rows = export_cc._list_entity(cc, entity)
        except Exception as exc:
            out["errors"].append(f"{entity}: {type(exc).__name__}: {exc}")
            print(f"  {entity:26s} FAILED {type(exc).__name__}")
            continue

        info = describe(rows)
        info["listPath"] = registry.list_path(entity)
        info["nameField"] = registry.name_field(entity)
        info["declaredCreateFields"] = registry.CC_ENTITIES[entity].get("create", [])
        info["fullSample"] = rows[0] if rows else None

        # Which declared create fields are actually present on real rows?
        present = set(info["fields"])
        info["declaredCreateFieldsMissingFromRows"] = [
            f for f in info["declaredCreateFields"] if f not in present]

        out["entities"][entity] = info
        print(f"  {entity:26s} {info['rowCount']:>4d} rows, "
              f"{len(info['fields']):>3d} distinct fields")

        if args.refs and rows:
            rid = rows[0].get("id")
            try:
                st, bd = cc.json(
                    "GET", f"organization/{{orgId}}/{entity}/{rid}/incoming-references")
                info["incomingReferencesSample"] = {
                    "status": st,
                    "referencedEntities": (bd or {}).get("meta", {}).get(
                        "referencedEntities") if isinstance(bd, dict) else None,
                }
            except Exception as exc:
                info["incomingReferencesSample"] = {"error": str(exc)[:160]}

    dest = Path(args.out) if args.out else Path(
        f"tenant-shapes-{org}-{stamp.replace(':','').replace('-','')}.json")
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    total = sum(v["rowCount"] for v in out["entities"].values())
    print(f"\nWrote {dest}")
    print(f"  {len(out['entities'])} entities, {total} rows, "
          f"{len(out['errors'])} errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
