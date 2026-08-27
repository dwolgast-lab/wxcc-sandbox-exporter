import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import HTTPServer

import pytest
from wxcc_export import importer as importer_mod
from wxcc_export.idmap import IdMap
from wxcc_export.web import server as web


class FakeWire:
    """Drives the handler's routing logic without opening a socket."""

    def __init__(self, handler_cls, token):
        self.handler_cls = handler_cls
        self.token = token


class FakeReader:
    """Stands in for archive.ArchiveReader - only .manifest and .close() are
    used directly by the server; the (monkeypatched) importer functions treat
    the reader as opaque."""

    def __init__(self, source_org_id="SOURCE-ORG"):
        self.manifest = {"source": {"orgId": source_org_id, "orgName": "Source Co"}}
        self.closed = False

    def close(self):
        self.closed = True


@contextmanager
def running_server(cfg, token="TOK", own_origin=None):
    """Boots the real handler on loopback so do_GET/do_POST routing - not just
    the helper functions - is exercised end to end."""
    origin = own_origin or "http://127.0.0.1:0"
    handler_cls = web.make_handler(cfg, token, origin)
    httpd = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        thread.join()
        httpd.server_close()


def _post(base_url, path, body, token=None):
    req = urllib.request.Request(
        base_url + path, method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 **({"X-Session-Token": token} if token else {})})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_serve_binds_only_to_loopback(monkeypatch):
    captured = {}

    class FakeHTTPServer:
        def __init__(self, addr, handler):
            captured["addr"] = addr

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    monkeypatch.setattr(web, "HTTPServer", FakeHTTPServer)
    monkeypatch.setattr(web.webbrowser, "open", lambda _u: None)
    web.serve({"api_base": "x", "webex_base": "y", "org_id": None,
               "bearer_token": "T", "profile": None}, 8787)
    assert captured["addr"][0] == "127.0.0.1"


def test_session_token_is_random_per_run():
    assert web.new_session_token() != web.new_session_token()


def test_session_token_is_long_enough_to_resist_guessing():
    assert len(web.new_session_token()) >= 32


def test_authorized_accepts_the_matching_token():
    assert web.authorized({"X-Session-Token": "abc"}, "abc", None)


def test_authorized_rejects_a_missing_token():
    assert not web.authorized({}, "abc", None)


def test_authorized_rejects_a_wrong_token():
    assert not web.authorized({"X-Session-Token": "nope"}, "abc", None)


def test_authorized_rejects_a_foreign_origin():
    headers = {"X-Session-Token": "abc", "Origin": "https://evil.example"}
    assert not web.authorized(headers, "abc", "http://127.0.0.1:8787")


def test_authorized_accepts_its_own_origin():
    headers = {"X-Session-Token": "abc", "Origin": "http://127.0.0.1:8787"}
    assert web.authorized(headers, "abc", "http://127.0.0.1:8787")


def test_authorized_compares_the_token_with_compare_digest(monkeypatch):
    calls = []
    real = web.secrets.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(web.secrets, "compare_digest", spy)
    web.authorized({"X-Session-Token": "abc"}, "abc", None)
    assert calls == [("abc", "abc")]


def test_index_html_embeds_the_session_token():
    page = web.render_index("SECRET123")
    assert "SECRET123" in page


def test_index_html_warns_before_a_write():
    page = web.render_index("T")
    assert "confirm" in page.lower()


def test_static_assets_exist():
    for name in ("index.html", "app.js", "style.css"):
        assert (web.STATIC_DIR / name).exists(), name


CFG = {"api_base": "https://cc.example", "webex_base": "https://webexapis.example",
      "org_id": "TARGET-ORG", "bearer_token": "T", "profile": None}


def test_import_dispatches_flows_functions_and_calling(monkeypatch):
    """The web import must mirror cli._run_import's sequencing: subflows then
    flows then functions then calling, all sharing the idmap import_cc
    returns - not just the cc:* selections."""
    calls = []
    shared_idmap = IdMap()

    def fake_import_cc(client, reader, keys, on_conflict, confirm, **kw):
        calls.append(("import_cc", client, keys, on_conflict, confirm))
        return {"cc:queue": importer_mod.ImportResult(entity="cc:queue")}, shared_idmap

    def fake_import_flows(client, reader, bucket, idmap_, *a, confirm=False, **kw):
        calls.append(("import_flows", client, bucket, idmap_, confirm))
        return importer_mod.ImportResult(entity=f"flows:{bucket}")

    def fake_import_functions(client, reader, idmap_, *a, confirm=False, **kw):
        calls.append(("import_functions", client, idmap_, confirm))
        return importer_mod.ImportResult(entity="flows:functions")

    def fake_import_calling(client, reader, names, idmap_, on_conflict, confirm):
        calls.append(("import_calling", client, names, idmap_, on_conflict, confirm))
        return {n: importer_mod.ImportResult(entity=f"calling:{n}") for n in names}

    monkeypatch.setattr(web.importer, "import_cc", fake_import_cc)
    monkeypatch.setattr(web.importer, "import_flows", fake_import_flows)
    monkeypatch.setattr(web.importer, "import_functions", fake_import_functions)
    monkeypatch.setattr(web.importer, "import_calling", fake_import_calling)
    monkeypatch.setattr(web.archive, "ArchiveReader", lambda path: FakeReader())

    with running_server(CFG) as base:
        status, body = _post(base, "/api/import", {
            "archive": "whatever.zip",
            "keys": ["cc:queue", "flows:subflows", "flows:flows",
                     "flows:functions", "calling:voicemail"],
            "onConflict": "skip", "confirm": True}, token="TOK")

    assert status == 200, body
    names_called = [c[0] for c in calls]
    assert names_called.count("import_flows") == 2, calls
    # subflows must be imported before flows (a flow can invoke a subflow).
    flow_calls = [c for c in calls if c[0] == "import_flows"]
    assert flow_calls[0][2] == "subflows"
    assert flow_calls[1][2] == "flows"
    assert "import_functions" in names_called, calls
    assert "import_calling" in names_called, calls

    calling_call = next(c for c in calls if c[0] == "import_calling")
    assert calling_call[2] == ["voicemail"]

    # every downstream call reused the exact IdMap import_cc produced.
    assert flow_calls[0][3] is shared_idmap
    assert flow_calls[1][3] is shared_idmap
    fn_call = next(c for c in calls if c[0] == "import_functions")
    assert fn_call[2] is shared_idmap
    assert calling_call[3] is shared_idmap

    # calling must be imported through the Webex client, not the CC client.
    cc_client = next(c[1] for c in calls if c[0] == "import_cc")
    assert calling_call[1] is not cc_client

    # the response must report every section, not just cc:*.
    assert set(body["results"]) == {
        "cc:queue", "flows:subflows", "flows:flows", "flows:functions",
        "calling:voicemail"}


def _get(base_url, path, token=None):
    req = urllib.request.Request(
        base_url + path,
        headers={**({"X-Session-Token": token} if token else {})})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_api_tenant_passes_the_webex_client_to_org_info(monkeypatch):
    # Without the webex client, tenant.org_info can't reach
    # organizations/{orgId} and the tenant name silently falls back to the
    # org id (tenant.py, U6).
    captured = {}
    monkeypatch.setattr(web.auth, "valid_access_token",
                        lambda cfg: ("TOK", "bearer"))
    monkeypatch.setattr(web.auth, "extract_org_id", lambda token: "O1")
    monkeypatch.setattr(web.client, "ApiClient",
                        lambda base, token, org_id=None: (base, "client"))

    def fake_org_info(cc, wx=None):
        captured["cc"], captured["wx"] = cc, wx
        return {"org_id": "O1", "name": "Sandbox", "subscription": None,
                "created_ms": None}

    monkeypatch.setattr(web.tenant, "org_info", fake_org_info)

    with running_server(CFG, token="TOK") as base:
        status, body = _get(base, "/api/tenant", token="TOK")

    assert status == 200, body
    assert captured["cc"] == (CFG["api_base"], "client")
    assert captured["wx"] == (CFG["webex_base"], "client")


def test_api_tenant_requires_the_session_token():
    with running_server(CFG, token="TOK") as base:
        status, body = _get(base, "/api/tenant", token=None)
    assert status == 403


def test_import_requires_the_session_token(monkeypatch):
    calls = []
    monkeypatch.setattr(web.importer, "import_cc",
                        lambda *a, **kw: calls.append("called") or (({}, IdMap())))
    monkeypatch.setattr(web.archive, "ArchiveReader", lambda path: FakeReader())

    with running_server(CFG) as base:
        status, body = _post(base, "/api/import",
                             {"archive": "x.zip", "keys": ["cc:queue"],
                              "confirm": True}, token=None)

    assert status == 403
    assert not calls
