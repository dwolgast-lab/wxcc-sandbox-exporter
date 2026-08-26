"""OAuth2 authorization-code flow with a loopback redirect, plus an opt-in PAT.

OAuth2 is the default. A personal bearer token is a deliberate downgrade: it is
short-lived, cannot be refreshed, and is not scoped, so every code path that
uses one says so out loud.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import config

AUTHORIZE_URL = "https://webexapis.com/v1/authorize"
TOKEN_URL = "https://webexapis.com/v1/access_token"
EXPIRY_SKEW_SECONDS = 300


class AuthError(Exception):
    """Authentication is missing, expired, or refused."""


def extract_org_id(access_token: str) -> str | None:
    """Read the org id out of the access token's payload segment.

    Webex access tokens are JWT-shaped. The middle segment base64url-decodes to
    JSON carrying the org. Anything unexpected returns None rather than raising:
    an opaque token is a legitimate case, not an error.
    """
    parts = access_token.split(".")
    if len(parts) < 2:
        return None
    seg = parts[1]
    seg += "=" * (-len(seg) % 4)          # restore stripped base64 padding
    try:
        payload = json.loads(base64.urlsafe_b64decode(seg))
    except Exception:
        return None
    for key in ("orgId", "org_id", "organizationId"):
        if payload.get(key):
            return str(payload[key])
    return None


def load_tokens(cfg: dict) -> dict | None:
    store = config.token_store(cfg.get("profile"))
    if not store.exists():
        return None
    try:
        return json.loads(store.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def save_tokens(cfg: dict, tok: dict) -> None:
    store = config.token_store(cfg.get("profile"))
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(tok, indent=2), encoding="utf-8")
    try:
        store.chmod(0o600)                 # best effort; a no-op on some filesystems
    except OSError:
        pass


def logout(cfg: dict) -> None:
    store = config.token_store(cfg.get("profile"))
    if store.exists():
        store.unlink()


def _store_token_response(resp: dict) -> dict:
    tok = dict(resp)
    if "expires_in" in resp:
        tok["expires_at"] = time.time() + float(resp["expires_in"])
    tok["org_id"] = extract_org_id(resp.get("access_token", "")) or None
    return tok


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise AuthError(f"token endpoint returned {e.code}: "
                        f"{e.read().decode()[:300]}") from e


class _CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None
    state: str | None = None

    def do_GET(self):                                    # noqa: N802
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        _CallbackHandler.code = (params.get("code") or [None])[0]
        _CallbackHandler.state = (params.get("state") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = _CallbackHandler.code is not None
        msg = "Authorized. You can close this tab." if ok else "Authorization failed."
        self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode())

    def log_message(self, *_args):                       # silence the default logging
        return


def login(cfg: dict) -> dict:
    """Run the authorization-code flow against a local loopback listener."""
    config.require(cfg, "client_id", "client_secret", "redirect_uri")
    parsed = urllib.parse.urlparse(cfg["redirect_uri"])
    if parsed.hostname not in ("localhost", "127.0.0.1"):
        raise AuthError(
            f"redirect_uri host must be localhost or 127.0.0.1, got {parsed.hostname!r}. "
            "This tool catches the code on a local listener; a remote redirect "
            "would hand your tenant's token to someone else's server."
        )
    state = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "scope": cfg["scopes"],
        "state": state,
        # Force a fresh credential prompt. Without this, an existing browser
        # session silently re-mints a token for whichever tenant is already
        # signed in - and it looks like it worked.
        "prompt": "login",
    }
    url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    print("Open this URL in a PRIVATE browser window:\n")
    print(f"  {url}\n")
    webbrowser.open(url)

    _CallbackHandler.code = None
    _CallbackHandler.state = None
    server = HTTPServer((parsed.hostname, parsed.port or 80), _CallbackHandler)
    server.timeout = 300
    server.handle_request()
    server.server_close()

    if not _CallbackHandler.code:
        raise AuthError("no authorization code received (timed out or denied).")
    if _CallbackHandler.state != state:
        raise AuthError("state mismatch - discarding the response.")

    resp = _post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "code": _CallbackHandler.code,
        "redirect_uri": cfg["redirect_uri"],
    })
    tok = _store_token_response(resp)
    save_tokens(cfg, tok)
    return tok


def refresh_tokens(cfg: dict, tok: dict) -> dict:
    if not tok.get("refresh_token"):
        raise AuthError("stored token has no refresh_token - run `auth login` again.")
    resp = _post_form(TOKEN_URL, {
        "grant_type": "refresh_token",
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "refresh_token": tok["refresh_token"],
    })
    fresh = _store_token_response(resp)
    fresh.setdefault("refresh_token", tok["refresh_token"])
    save_tokens(cfg, fresh)
    return fresh


def valid_access_token(cfg: dict) -> tuple[str, str]:
    """Return (token, source). Refreshes an OAuth2 token that is near expiry."""
    if cfg.get("bearer_token"):
        return cfg["bearer_token"], "bearer"
    tok = load_tokens(cfg)
    if not tok or not tok.get("access_token"):
        raise AuthError("not authenticated - run `wxcc-export auth login` first.")
    if tok.get("expires_at", 0) - EXPIRY_SKEW_SECONDS <= time.time():
        tok = refresh_tokens(cfg, tok)
    return tok["access_token"], "oauth2"
