"""A rejected token must stop the run, not masquerade as an empty target.

Seen 2026-09-25: with an expired bearer token the dry run reported "0 skipped"
everywhere (every target lookup 401'd and was read as "nothing exists"), and
the confirmed run then sent 200+ writes that each came back 401.
"""

import pytest

from wxcc_export import archive, auth, cli, importer, plan
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"
REJECTED = {"key": 401, "message": [{"description":
                                     "Validation Unsuccessful: FAIL_VALIDATE_TOKEN"}]}


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


def _archive(tmp_path):
    p = tmp_path / "src-export.zip"
    archive.write_export(
        p, source={"orgId": "SRCORG", "orgName": "src"},
        cc={"site": {"entity": "site", "count": 2, "error": None,
                     "items": [{"id": "s1", "name": "A"}, {"id": "s2", "name": "B"}]}},
        children={}, audio={}, flows={"flows": {}, "subflows": {}, "errors": []},
        functions={"functions": {}, "errors": []}, calling={}, users={})
    return p


class Args:
    select = "cc"
    on_conflict = "skip"
    overwrite_flows = False

    def __init__(self, path, confirm):
        self.archive = str(path)
        self.confirm = confirm


def test_target_lookup_rejected_is_an_auth_error_not_an_empty_target(transport):
    transport.add("GET /organization/ORG1/v2/site", status=401, body=REJECTED)
    with pytest.raises(auth.AuthError):
        plan.index_existing(make(transport), "site")


def test_import_stops_before_planning_when_the_token_is_rejected(
        tmp_path, transport, monkeypatch, capsys):
    transport.add("GET /organization/ORG1", status=401, body=REJECTED)
    monkeypatch.setattr(cli, "_clients", lambda cfg: (make(transport), make(transport)))
    for confirm in (False, True):
        code = cli._run_import({}, Args(_archive(tmp_path), confirm))
        assert code == cli.EXIT_AUTH
    assert all(c["method"] == "GET" for c in transport.calls)
    err = capsys.readouterr().err
    assert "401" in err and "fresh" in err


def test_first_rejected_write_stops_the_run_and_reports_progress(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    transport.add("POST /organization/ORG1/site", status=401, body=REJECTED)

    class Reader:
        manifest = {"source": {"orgId": "SRCORG"}}

        def entity_items(self, entity):
            return [{"id": "s1", "name": "A"}, {"id": "s2", "name": "B"}]

        def source_ids(self):
            return {"s1", "s2", "SRCORG"}

    with pytest.raises(auth.AuthError) as exc:
        importer.run_import(make(transport), make(transport), Reader(),
                            ["cc:site"], "skip", True, "TGT")
    posts = [c for c in transport.calls if c["method"] == "POST"]
    assert len(posts) == 1, "no further writes after the token is rejected"
    assert exc.value.results["site"].failed
