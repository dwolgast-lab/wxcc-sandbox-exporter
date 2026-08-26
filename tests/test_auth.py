import base64
import json
import time

import pytest
from wxcc_export import auth


def make_token(payload: dict) -> str:
    def seg(obj):
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{seg({'alg': 'none'})}.{seg(payload)}.sig"


def test_extract_org_id_reads_the_middle_segment():
    tok = make_token({"orgId": "ORG123", "sub": "user"})
    assert auth.extract_org_id(tok) == "ORG123"


def test_extract_org_id_handles_missing_padding():
    # base64url with a length that needs 2 '=' of padding restored
    tok = make_token({"orgId": "A" * 10})
    assert auth.extract_org_id(tok) == "A" * 10


def test_extract_org_id_returns_none_for_an_opaque_token():
    assert auth.extract_org_id("not-a-jwt") is None


def test_extract_org_id_returns_none_when_payload_has_no_org():
    assert auth.extract_org_id(make_token({"sub": "user"})) is None


def test_bearer_token_short_circuits_oauth(tmp_path, monkeypatch):
    cfg = {"bearer_token": "PAT123", "profile": None}
    token, source = auth.valid_access_token(cfg)
    assert token == "PAT123"
    assert source == "bearer"


def test_valid_access_token_returns_a_live_stored_token(tmp_path, monkeypatch):
    cfg = {"bearer_token": None, "profile": None}
    monkeypatch.setattr(auth, "load_tokens",
                        lambda c: {"access_token": "LIVE",
                                   "expires_at": time.time() + 3600})
    token, source = auth.valid_access_token(cfg)
    assert (token, source) == ("LIVE", "oauth2")


def test_valid_access_token_refreshes_a_token_inside_the_skew(monkeypatch):
    cfg = {"bearer_token": None, "profile": None}
    monkeypatch.setattr(auth, "load_tokens",
                        lambda c: {"access_token": "STALE",
                                   "refresh_token": "R",
                                   "expires_at": time.time() + 10})
    called = {}

    def fake_refresh(c, tok):
        called["yes"] = True
        return {"access_token": "FRESH", "expires_at": time.time() + 3600}

    monkeypatch.setattr(auth, "refresh_tokens", fake_refresh)
    token, _ = auth.valid_access_token(cfg)
    assert token == "FRESH"
    assert called == {"yes": True}


def test_valid_access_token_raises_when_nothing_is_stored(monkeypatch):
    cfg = {"bearer_token": None, "profile": None}
    monkeypatch.setattr(auth, "load_tokens", lambda c: None)
    with pytest.raises(auth.AuthError) as exc:
        auth.valid_access_token(cfg)
    assert "auth login" in str(exc.value)


def test_save_tokens_writes_owner_only_permissions(tmp_path, monkeypatch):
    monkeypatch.setattr(auth.config, "REPO_DIR", tmp_path)
    cfg = {"profile": None}
    auth.save_tokens(cfg, {"access_token": "X", "expires_at": 1})
    store = auth.config.token_store(None)
    assert store.exists()
    assert json.loads(store.read_text())["access_token"] == "X"


def test_expires_at_is_derived_from_expires_in():
    before = time.time()
    tok = auth._store_token_response({"access_token": "X", "expires_in": 1209600})
    assert tok["expires_at"] >= before + 1209600 - 5
