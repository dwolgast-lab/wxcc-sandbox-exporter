#!/usr/bin/env python3
"""Third probe: audio-file binaries, and whether any entity has a real
system-default flag.

READ-ONLY. Never prints the token.

probe/probe2 left two things open that the first live export then exposed:
  - ALL 11 audio-file records failed to download. They carry `blobId`, and none
    of the URL fields export_cc.AUDIO_URL_FIELDS looks for.
  - The audio-file record carries `systemDefault`, which would be a REAL default
    flag - contradicting the claim in docs/api-notes.md that no entity has one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wxcc_export import auth, client, config, registry  # noqa: E402


def show(label: str, status: int, body: object) -> None:
    if isinstance(body, dict):
        blob = f"keys={sorted(body)[:12]}"
        for k in ("message", "error"):
            if body.get(k):
                blob += f"  msg={str(body[k])[:110]!r}"
    elif isinstance(body, (bytes, bytearray)):
        blob = f"{len(body)} bytes, starts {bytes(body[:12])!r}"
    elif body is None:
        blob = "<no body>"
    else:
        blob = str(body)[:150]
    mark = "   <-- WORKS" if status == 200 else ""
    print(f"  {status:>3}  {label}{mark}\n       {blob}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None)
    args = ap.parse_args()

    cfg = config.load_config(args.profile)
    token, _ = auth.valid_access_token(cfg)
    org = cfg["org_id"] or auth.extract_org_id(token)
    cc = client.ApiClient(cfg["api_base"], token, org_id=org)

    # ---------------------------------------------------- A. the record
    print("=== A. What an audio-file record actually contains ===")
    rows = cc.list_all(registry.list_path("audio-file"))
    print(f"  {len(rows)} audio files")
    if not rows:
        print("  none to inspect"); return 0
    sample = rows[0]
    print("  full record (first):")
    print("   ", json.dumps(sample, indent=2)[:900].replace("\n", "\n    "))
    aid = sample.get("id")
    blob_id = sample.get("blobId")
    print(f"\n  id      = {aid}")
    print(f"  blobId  = {blob_id}")

    # ---------------------------------------------------- B. item GET
    print("\n=== B. Does the ITEM GET carry more than the list row? ===")
    st, bd = cc.json("GET", registry.item_path("audio-file", aid))
    if isinstance(bd, dict):
        extra = sorted(set(bd) - set(sample))
        print(f"  HTTP {st}  keys={sorted(bd)}")
        print(f"  fields the item GET adds over the list row: {extra or 'NONE'}")
        for k in extra:
            print(f"    {k} = {str(bd[k])[:120]!r}")
    else:
        show("item GET", st, bd)

    # ---------------------------------------------------- C. download routes
    print("\n=== C. Hunting the download route ===")
    candidates = [
        f"organization/{{orgId}}/audio-file/{aid}/download",
        f"organization/{{orgId}}/audio-file/{aid}/content",
        f"organization/{{orgId}}/audio-file/{aid}/file",
        f"organization/{{orgId}}/audio-file/{aid}/blob",
        f"organization/{{orgId}}/v2/audio-file/{aid}/download",
    ]
    if blob_id:
        candidates += [
            f"organization/{{orgId}}/blob/{blob_id}",
            f"organization/{{orgId}}/audio-file/blob/{blob_id}",
            f"organization/{{orgId}}/audio-file/{aid}/blob/{blob_id}",
            f"organization/{{orgId}}/file/{blob_id}",
            f"organization/{{orgId}}/v2/blob/{blob_id}",
        ]
    for path in candidates:
        try:
            st, data, ctype = cc.get_bytes(path)
        except Exception as exc:
            print(f"  ERR  {path}\n       {type(exc).__name__}: {exc}")
            continue
        head = bytes(data[:12]) if data else b""
        looks_audio = head[:4] in (b"RIFF", b"OggS", b"ID3\x03") or head[:2] == b"\xff\xfb"
        print(f"  {st:>3}  /{path.replace('{orgId}', org)[:78]}")
        print(f"       {len(data)} bytes  ctype={ctype!r}  audio-magic={looks_audio}"
              f"  head={head!r}")

    # ---------------------------------------------------- D. systemDefault
    print("\n=== D. Which entities carry a REAL default flag? ===")
    flags = ("systemDefault", "isDefault", "defaultCode", "default")
    for ent in sorted(registry.CC_ENTITIES):
        try:
            rr = cc.list_all(registry.list_path(ent))
        except Exception as exc:
            print(f"  {ent:24s} list failed: {type(exc).__name__}")
            continue
        if not rr:
            print(f"  {ent:24s} (empty)")
            continue
        present = sorted({f for r in rr for f in flags if f in r})
        if present:
            vals = {f: sorted({str(r.get(f)) for r in rr}) for f in present}
            n_true = {f: sum(1 for r in rr if r.get(f) is True) for f in present}
            print(f"  {ent:24s} {present}  values={vals}  true-count={n_true} "
                  f"of {len(rr)}")
        else:
            print(f"  {ent:24s} -")

    print("\nDone. Nothing was written to the tenant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
