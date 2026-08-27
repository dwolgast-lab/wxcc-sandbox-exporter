"""HTTP access to one org's Webex APIs.

The token is supplied, never looked up here, so the same client works for the
WxCC regional host and for webexapis.com. `transport` is injectable so the test
suite never opens a socket.
"""

from __future__ import annotations

import json
import secrets
import time
import urllib.error
import urllib.request

RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_ATTEMPTS = 5
MAX_PAGES = 500


class ApiError(Exception):
    def __init__(self, message: str, status: int = 0, body: object = None,
                 path: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body
        self.path = path


class _Response:
    def __init__(self, status: int, body: bytes, content_type: str):
        self.status = status
        self.body = body
        self.content_type = content_type


def _urllib_transport(method: str, url: str, headers: dict | None = None,
                      data: bytes | None = None) -> _Response:
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return _Response(r.status, r.read(),
                             r.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as e:
        return _Response(e.code, e.read(), e.headers.get("Content-Type", ""))
    except urllib.error.URLError as e:
        raise ApiError(f"network error calling {url}: {e.reason}") from e


def multipart_body(parts: list[tuple[str, str | None, str | None, bytes]],
                   boundary: str) -> bytes:
    """Build a multipart/form-data body.

    Each part is (field_name, filename_or_None, content_type_or_None, bytes).
    A part with a filename is sent as a file; one without is a plain field, and
    an explicit content type on it is preserved - WxCC's audio-file upload
    requires the metadata part to be typed application/json.
    """
    out = bytearray()
    for name, filename, ctype, payload in parts:
        out += f"--{boundary}\r\n".encode()
        disp = f'Content-Disposition: form-data; name="{name}"'
        if filename:
            disp += f'; filename="{filename}"'
        out += (disp + "\r\n").encode()
        if ctype:
            out += f"Content-Type: {ctype}\r\n".encode()
        out += b"\r\n" + payload + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out)


class ApiClient:
    def __init__(self, api_base: str, token: str, org_id: str | None = None,
                 transport=None):
        self.api_base = api_base.rstrip("/")
        self.token = token
        self.org_id = org_id
        self._transport = transport or _urllib_transport

    def url(self, path: str) -> str:
        if "{orgId}" in path:
            if not self.org_id:
                raise ApiError(
                    "path needs {orgId} but the org id could not be derived from "
                    "the token - set WXCC_ORG_ID to override.", path=path)
            path = path.replace("{orgId}", self.org_id)
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.api_base}/{path.lstrip('/')}"

    def _send(self, method: str, url: str, headers: dict,
              data: bytes | None) -> _Response:
        delay = 1.0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            resp = self._transport(method, url, headers=headers, data=data)
            if resp.status not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
                return resp
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
        return resp

    def request(self, method: str, path: str, body: object = None,
                headers: dict | None = None) -> tuple[int, str]:
        h = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        h.update(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        resp = self._send(method, self.url(path), h, data)
        return resp.status, resp.body.decode("utf-8", errors="replace")

    def json(self, method: str, path: str, body: object = None) -> tuple[int, object]:
        status, text = self.request(method, path, body)
        if not text:
            return status, None
        try:
            return status, json.loads(text)
        except json.JSONDecodeError:
            return status, text

    def get_bytes(self, path: str) -> tuple[int, bytes, str]:
        h = {"Authorization": f"Bearer {self.token}"}
        resp = self._send("GET", self.url(path), h, None)
        return resp.status, resp.body, resp.content_type

    def multipart(self, method: str, path: str,
                  parts: list[tuple[str, str | None, str | None, bytes]]
                  ) -> tuple[int, object]:
        boundary = "----wxccexport" + secrets.token_hex(16)
        data = multipart_body(parts, boundary)
        h = {"Authorization": f"Bearer {self.token}",
             "Accept": "application/json",
             "Content-Type": f"multipart/form-data; boundary={boundary}"}
        resp = self._send(method, self.url(path), h, data)
        text = resp.body.decode("utf-8", errors="replace")
        if not text:
            return resp.status, None
        try:
            return resp.status, json.loads(text)
        except json.JSONDecodeError:
            return resp.status, text

    def list_all(self, path: str) -> list[dict]:
        """Follow meta.links.next to exhaustion.

        `next` is a path fragment relative to api_base, not an absolute URL.
        Some Webex Calling endpoints return a bare array instead of meta+data;
        both shapes are accepted, anything else is an error rather than a
        silently-empty result.

        Every Webex Calling collection wraps its list in its OWN envelope key
        (autoAttendants, huntGroups, queues, ... - even a key not derivable
        from the path, like paging -> "locationPaging"), so the key is
        selected generically rather than from a hardcoded allowlist. "data"
        (the Contact Center paginated shape) is still preferred when present,
        so CC behaviour is unchanged. A dict with no list-valued key at all is
        a live-observed empty Calling collection (e.g. announcements returns
        a bare {} when empty), not an error, so it yields [].
        """
        records: list[dict] = []
        url = self.url(path)
        for page in range(MAX_PAGES):
            status, text = self._get_raw(url)
            if status >= 400:
                raise ApiError(f"list failed on page {page}: HTTP {status}",
                               status=status, body=text[:400], path=path)
            doc = json.loads(text) if text else {}
            if isinstance(doc, list):
                return records + doc
            if not isinstance(doc, dict):
                raise ApiError(
                    f"expected a list response from {path}, got "
                    f"{type(doc).__name__}", status=status, path=path)
            data = doc.get("data")
            if data is None:
                list_keys = [k for k, v in doc.items()
                             if k != "data" and isinstance(v, list)]
                if not list_keys:
                    data = []
                elif len(list_keys) == 1:
                    data = doc[list_keys[0]]
                elif "items" in list_keys:
                    # locations returns items + notFoundIds together - both are
                    # lists, but notFoundIds is a sibling list of ids a batch
                    # lookup couldn't find, not a second envelope of records.
                    # "items" is the well-established Webex collection key, so
                    # it wins over an unrecognised second list key.
                    data = doc["items"]
                else:
                    raise ApiError(
                        f"ambiguous list response from {path}, multiple "
                        f"list-valued keys {sorted(list_keys)}",
                        status=status, path=path)
            if not isinstance(data, list):
                raise ApiError(
                    f"expected a list response from {path}, got keys "
                    f"{sorted(doc)[:8]}", status=status, path=path)
            records.extend(data)
            nxt = (doc.get("meta") or {}).get("links", {}).get("next")
            if not nxt:
                return records
            url = nxt if nxt.startswith("http") else self.api_base + nxt
        raise ApiError(f"aborted after {MAX_PAGES} pages on {path}", path=path)

    def _get_raw(self, url: str) -> tuple[int, str]:
        h = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        resp = self._send("GET", url, h, None)
        return resp.status, resp.body.decode("utf-8", errors="replace")
