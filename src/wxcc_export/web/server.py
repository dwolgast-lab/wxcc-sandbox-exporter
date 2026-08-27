"""A localhost-only selection UI.

This process holds a live Contact Center admin token, so:
  - it binds to 127.0.0.1 ONLY, never 0.0.0.0;
  - every /api/* call must carry a per-run random session token, handed to the
    page inline at render time and never written to disk or put in a URL;
  - a request carrying a foreign Origin is refused (DNS-rebinding defence).

There is no hosted equivalent of this UI by design: a server that held other
people's tenant admin tokens would be a liability, not a feature.
"""

from __future__ import annotations

import json
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .. import archive, auth, client, importer, plan, tenant

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY_BYTES = 2 * 1024 * 1024


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def authorized(headers, token: str, own_origin: str | None) -> bool:
    supplied = None
    for key in ("X-Session-Token", "x-session-token"):
        if hasattr(headers, "get"):
            supplied = headers.get(key) or supplied
    if not supplied or not secrets.compare_digest(str(supplied), token):
        return False
    origin = headers.get("Origin") if hasattr(headers, "get") else None
    if origin and own_origin and origin != own_origin:
        return False
    return True


def render_index(token: str) -> str:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return html.replace("__SESSION_TOKEN__", token)


def make_handler(cfg: dict, token: str, own_origin: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, obj) -> None:
            self._send(status, json.dumps(obj).encode(), "application/json")

        def _guard(self) -> bool:
            if authorized(self.headers, token, own_origin):
                return True
            self._json(403, {"error": "unauthorized"})
            return False

        def do_GET(self):                                     # noqa: N802
            if self.path == "/":
                return self._send(200, render_index(token).encode(),
                                  "text/html; charset=utf-8")
            for name, ctype in (("/app.js", "application/javascript"),
                                ("/style.css", "text/css")):
                if self.path == name:
                    data = (STATIC_DIR / name.lstrip("/")).read_bytes()
                    return self._send(200, data, ctype)
            if self.path == "/api/tenant":
                if not self._guard():
                    return
                try:
                    tok, source = auth.valid_access_token(cfg)
                    org_id = cfg["org_id"] or auth.extract_org_id(tok)
                    cc = client.ApiClient(cfg["api_base"], tok, org_id=org_id)
                    wx = client.ApiClient(cfg["webex_base"], tok, org_id=org_id)
                    info = tenant.org_info(cc, wx)
                    return self._json(200, {"tenant": tenant.describe(info),
                                            "orgId": info["org_id"],
                                            "authSource": source})
                except Exception as exc:
                    return self._json(500, {"error": str(exc)})
            return self._json(404, {"error": "not found"})

        def do_POST(self):                                    # noqa: N802
            if not self._guard():
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                return self._json(413, {"error": "body too large"})
            payload = json.loads(self.rfile.read(length) or b"{}")

            if self.path == "/api/inspect":
                try:
                    reader = archive.ArchiveReader(payload["archive"])
                except (archive.IncompatibleArchive, KeyError, OSError) as exc:
                    return self._json(400, {"error": str(exc)})
                out = {"manifest": reader.manifest,
                       "selections": archive.available_selections(reader.manifest)}
                reader.close()
                return self._json(200, out)

            if self.path == "/api/import":
                try:
                    reader = archive.ArchiveReader(payload["archive"])
                except (archive.IncompatibleArchive, KeyError, OSError) as exc:
                    return self._json(400, {"error": str(exc)})
                tok, _ = auth.valid_access_token(cfg)
                org_id = cfg["org_id"] or auth.extract_org_id(tok)
                cc = client.ApiClient(cfg["api_base"], tok, org_id=org_id)
                wx = client.ApiClient(cfg["webex_base"], tok, org_id=org_id)
                if org_id == reader.manifest["source"].get("orgId"):
                    reader.close()
                    return self._json(400, {
                        "error": "the target tenant is the same org this archive "
                                 "came from - point the profile at the NEW sandbox"})

                keys = payload.get("keys", [])
                on_conflict = payload.get("onConflict", "skip")
                confirm = bool(payload.get("confirm", False))

                results, idmap_ = importer.import_cc(
                    cc, reader, keys, on_conflict, confirm)

                # Subflows before flows: a flow can invoke a subflow, never the
                # reverse. Mirrors cli._run_import's sequencing.
                for bucket in ("subflows", "flows"):
                    if f"flows:{bucket}" in keys:
                        results[f"flows:{bucket}"] = importer.import_flows(
                            cc, reader, bucket, idmap_, confirm=confirm)
                if "flows:functions" in keys:
                    results["flows:functions"] = importer.import_functions(
                        cc, reader, idmap_, confirm=confirm)

                calling_names = [k.split(":", 1)[1] for k in keys
                                 if k.startswith("calling:")]
                if calling_names:
                    for name, r in importer.import_calling(
                            wx, reader, calling_names, idmap_, on_conflict,
                            confirm).items():
                        results[f"calling:{name}"] = r

                reader.close()
                return self._json(200, {"results": {
                    k: {"summary": r.summary(), "failed": r.failed,
                        "unverified": r.unverified,
                        "dangling": sorted(r.dangling)}
                    for k, r in results.items()}})

            return self._json(404, {"error": "not found"})

        def log_message(self, *_args):
            return

    return Handler


def serve(cfg: dict, port: int = 8787) -> int:
    token = new_session_token()
    own_origin = f"http://127.0.0.1:{port}"
    handler = make_handler(cfg, token, own_origin)
    httpd = HTTPServer(("127.0.0.1", port), handler)
    url = f"{own_origin}/"
    print(f"Serving the selection UI at {url}")
    print("Bound to loopback only. Press Ctrl-C to stop.")
    webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0
