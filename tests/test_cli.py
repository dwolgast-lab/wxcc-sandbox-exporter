import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from wxcc_export import cli


def test_parser_requires_a_command():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


def test_export_defaults_to_all_sections():
    args = cli.build_parser().parse_args(["export"])
    assert args.select == "all"


def test_import_requires_an_archive_path():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["import"])


def test_import_defaults_to_dry_run():
    args = cli.build_parser().parse_args(["import", "a.zip"])
    assert args.confirm is False


def test_import_conflict_policy_is_validated():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["import", "a.zip", "--on-conflict", "explode"])


def test_import_conflict_default_is_skip():
    args = cli.build_parser().parse_args(["import", "a.zip"])
    assert args.on_conflict == "skip"


def test_profile_flag_is_accepted_on_every_command():
    for argv in (["export"], ["import", "a.zip"], ["auth", "status"]):
        args = cli.build_parser().parse_args(argv + ["--profile", "target"])
        assert args.profile == "target"


def test_inspect_prints_the_manifest_summary(tmp_path, capsys):
    from wxcc_export import archive
    p = tmp_path / "t-export.zip"
    archive.write_export(
        p, source={"orgId": "O1", "orgName": "src"},
        cc={"site": {"entity": "site", "count": 2,
                     "items": [{"id": "s1", "name": "A"},
                               {"id": "s2", "name": "B"}], "error": None}},
        children={}, audio={},
        flows={"flows": {}, "subflows": {}, "errors": []},
        functions={"functions": {}, "errors": []},
        calling={"locations": [], "objects": {}, "error": None},
        users={"rows": [], "csv": ""})
    assert cli.main(["inspect", str(p)]) == 0
    out = capsys.readouterr().out
    assert "cc:site" in out and "2" in out


def test_inspect_reports_errors_recorded_in_the_archive(tmp_path, capsys):
    from wxcc_export import archive
    p = tmp_path / "t-export.zip"
    archive.write_export(
        p, source={"orgId": "O1"},
        cc={"site": {"entity": "site", "count": 0, "items": [],
                     "error": "HTTP 403 forbidden"}},
        children={}, audio={},
        flows={"flows": {}, "subflows": {}, "errors": []},
        functions={"functions": {}, "errors": []},
        calling={"locations": [], "objects": {}, "error": None},
        users={"rows": [], "csv": ""})
    rc = cli.main(["inspect", str(p)])
    out = capsys.readouterr().out
    assert "403" in out
    # A partial archive must not report itself as clean.
    assert rc == 3


def test_inspect_rejects_a_foreign_zip(tmp_path, capsys):
    p = tmp_path / "other.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("a.txt", "hi")
    assert cli.main(["inspect", str(p)]) == 1
    assert "manifest" in capsys.readouterr().err


def test_missing_config_exits_one_not_a_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.config, "REPO_DIR", tmp_path)
    assert cli.main(["export"]) == 1
    assert "\n" in capsys.readouterr().err


def test_bearer_token_use_is_announced(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env").write_text("WXCC_BEARER_TOKEN=PAT\n", encoding="utf-8")
    monkeypatch.setattr(cli.config, "REPO_DIR", tmp_path)
    monkeypatch.setattr(cli, "_run_export", lambda *a, **k: 0)
    cli.main(["export"])
    assert "personal bearer token" in capsys.readouterr().out


def test_bearer_token_warning_prints_only_once(tmp_path, monkeypatch, capsys):
    # main() prints the bearer-token warning, then _run_export -> _clients()
    # prints it again. Every export/import currently shows the line twice.
    (tmp_path / ".env").write_text("WXCC_BEARER_TOKEN=PAT\n", encoding="utf-8")
    monkeypatch.setattr(cli.config, "REPO_DIR", tmp_path)
    monkeypatch.setattr(cli.auth, "valid_access_token",
                        lambda cfg: ("PAT", "bearer"))
    monkeypatch.setattr(cli.auth, "extract_org_id", lambda token: "org1")
    monkeypatch.setattr(cli.client, "ApiClient", lambda *a, **k: object())

    def fake_run_export(cfg, args):
        cli._clients(cfg)  # exercises the real (buggy) _clients()
        return 0

    monkeypatch.setattr(cli, "_run_export", fake_run_export)
    cli.main(["export"])
    out = capsys.readouterr().out
    assert out.count("personal bearer token") == 1, out


def test_audio_download_errors_are_all_preserved(tmp_path, monkeypatch, capsys):
    # Three audio files each fail to download for a distinct reason. All three
    # must be individually identifiable in the manifest/UNSUPPORTED.md, not
    # just the last one written by the loop.
    monkeypatch.setattr(cli, "_clients", lambda cfg: (object(), object()))
    monkeypatch.setattr(cli.tenant, "org_info",
                        lambda cc, wx=None: {"org_id": "O1", "name": "Sandbox",
                                             "subscription": None, "created_ms": None})

    audio_items = [{"id": "a1", "name": "one"},
                   {"id": "a2", "name": "two"},
                   {"id": "a3", "name": "three"}]
    exported_fixture = {"audio-file": {"entity": "audio-file", "count": 3,
                                       "items": audio_items, "error": None}}
    monkeypatch.setattr(
        cli.export_cc, "export_all",
        lambda cc, entities, on_progress=None, org_created_ms=None: exported_fixture)
    monkeypatch.setattr(
        cli.export_cc, "export_audio_binaries",
        lambda cc, items: ({}, [
            "audio-file a1: ApiError: HTTP 404",
            "audio-file a2: ApiError: HTTP 500",
            "audio-file a3: ApiError: timeout",
        ]))
    monkeypatch.setattr(cli.export_flows, "export_all_flows",
                        lambda cc, pid: {"flows": {}, "subflows": {}, "errors": []})
    monkeypatch.setattr(cli.export_flows, "export_all_functions",
                        lambda cc: {"functions": {}, "errors": []})
    monkeypatch.setattr(cli.export_calling, "export_all",
                        lambda wx, on_progress=None:
                            {"locations": [], "objects": {}, "error": None})

    class Args:
        out = str(tmp_path)
        only_non_default = False

    cfg = {"api_base": "https://api.example.com"}
    cli._run_export(cfg, Args())

    p = next(tmp_path.glob("*.zip"))
    from wxcc_export import archive
    reader = archive.ArchiveReader(p)
    audio_errors = [e for e in reader.manifest["errors"]
                    if e["section"] == "cc" and e["object"] == "audio-file"]
    reader.close()
    assert len(audio_errors) == 1
    detail = audio_errors[0]["detail"]
    for expected in ("a1", "a2", "a3"):
        assert expected in detail, detail


def test_run_export_passes_the_webex_client_to_org_info(tmp_path, monkeypatch):
    # Without the webex client, tenant.org_info can't reach
    # organizations/{orgId} and the tenant name silently falls back to the
    # org id (tenant.py, U6).
    captured = {}
    cc_obj, wx_obj = object(), object()
    monkeypatch.setattr(cli, "_clients", lambda cfg: (cc_obj, wx_obj))

    def fake_org_info(cc, wx=None):
        captured["cc"], captured["wx"] = cc, wx
        return {"org_id": "O1", "name": "Sandbox", "subscription": None,
                "created_ms": 1000}

    monkeypatch.setattr(cli.tenant, "org_info", fake_org_info)
    monkeypatch.setattr(
        cli.export_cc, "export_all",
        lambda cc, entities, on_progress=None, org_created_ms=None: {})
    monkeypatch.setattr(cli.export_cc, "export_audio_binaries",
                        lambda cc, items: ({}, []))
    monkeypatch.setattr(cli.export_flows, "export_all_functions",
                        lambda cc: {"functions": {}, "errors": []})
    monkeypatch.setattr(
        cli.export_calling, "export_all",
        lambda wx, on_progress=None: {"locations": [], "objects": {}, "error": None})

    class Args:
        out = str(tmp_path)
        only_non_default = False

    cli._run_export({"api_base": "https://api.example.com"}, Args())
    assert captured["cc"] is cc_obj
    assert captured["wx"] is wx_obj


def test_run_export_threads_org_created_ms_into_export_all(tmp_path, monkeypatch):
    # --only-non-default has no anchor without this - the heuristic (by
    # design) tags nothing if org_created_ms never arrives.
    captured = {}
    monkeypatch.setattr(cli, "_clients", lambda cfg: (object(), object()))
    monkeypatch.setattr(
        cli.tenant, "org_info",
        lambda cc, wx=None: {"org_id": "O1", "name": "Sandbox",
                             "subscription": None, "created_ms": 1774641184199})

    def fake_export_all(cc, entities, on_progress=None, org_created_ms=None):
        captured["org_created_ms"] = org_created_ms
        return {}

    monkeypatch.setattr(cli.export_cc, "export_all", fake_export_all)
    monkeypatch.setattr(cli.export_cc, "export_audio_binaries",
                        lambda cc, items: ({}, []))
    monkeypatch.setattr(cli.export_flows, "export_all_functions",
                        lambda cc: {"functions": {}, "errors": []})
    monkeypatch.setattr(
        cli.export_calling, "export_all",
        lambda wx, on_progress=None: {"locations": [], "objects": {}, "error": None})

    class Args:
        out = str(tmp_path)
        only_non_default = False

    cli._run_export({"api_base": "https://api.example.com"}, Args())
    assert captured["org_created_ms"] == 1774641184199


def test_export_reports_partial_exit_code_when_a_section_fails(tmp_path, monkeypatch):
    """A partial export must NEVER exit 0.

    Flows are no longer disabled - the projectId turned out to be a fixed
    constant (5e5c9ad6d61f870d6d778c1b), not the org id, and the API works.
    So this now stubs a genuine flow-listing FAILURE to prove the partial-exit
    contract still holds for whatever does go wrong.
    """
    monkeypatch.setattr(cli, "_clients", lambda cfg: (object(), object()))
    monkeypatch.setattr(
        cli.tenant, "org_info",
        lambda cc, wx=None: {"org_id": "O1", "name": "Sandbox",
                             "subscription": None, "created_ms": None})
    monkeypatch.setattr(
        cli.export_cc, "export_all",
        lambda cc, entities, on_progress=None, org_created_ms=None: {
            "user": {"entity": "user", "count": 0, "items": [], "error": None}})
    monkeypatch.setattr(cli.export_cc, "export_audio_binaries",
                        lambda cc, items: ({}, []))
    monkeypatch.setattr(
        cli.export_flows, "export_all_flows",
        lambda cc, project_id=None: {
            "flows": {}, "subflows": {}, "projectId": "5e5c9ad6d61f870d6d778c1b",
            "errors": ["listing flows (flowType=FLOW): HTTP 403: forbidden"]})
    monkeypatch.setattr(cli.export_flows, "export_all_functions",
                        lambda cc: {"functions": {}, "errors": []})
    monkeypatch.setattr(
        cli.export_calling, "export_all",
        lambda wx, on_progress=None: {"locations": [], "objects": {}, "error": None})

    class Args:
        out = str(tmp_path)
        only_non_default = False

    rc = cli._run_export({"api_base": "https://api.example.com"}, Args())

    assert rc == 3, "a failed section is genuinely missing - must not report success"
    p = next(tmp_path.glob("*.zip"))
    from wxcc_export import archive
    reader = archive.ArchiveReader(p)
    flow_errors = [e for e in reader.manifest["errors"] if e["section"] == "flows"]
    reader.close()
    assert flow_errors, "the flow failure must reach the manifest"
    assert "403" in flow_errors[0]["detail"]


def test_export_exits_zero_when_everything_succeeds(tmp_path, monkeypatch):
    # The counterpart: a clean export must exit 0, or exit code 3 means nothing.
    monkeypatch.setattr(cli, "_clients", lambda cfg: (object(), object()))
    monkeypatch.setattr(
        cli.tenant, "org_info",
        lambda cc, wx=None: {"org_id": "O1", "name": "Sandbox",
                             "subscription": None, "created_ms": None})
    monkeypatch.setattr(
        cli.export_cc, "export_all",
        lambda cc, entities, on_progress=None, org_created_ms=None: {
            "site": {"entity": "site", "count": 1,
                     "items": [{"id": "s1", "name": "A"}], "error": None}})
    monkeypatch.setattr(cli.export_cc, "export_audio_binaries",
                        lambda cc, items: ({}, []))
    monkeypatch.setattr(
        cli.export_flows, "export_all_flows",
        lambda cc, project_id=None: {"flows": {}, "subflows": {}, "errors": [],
                                     "projectId": "5e5c9ad6d61f870d6d778c1b"})
    monkeypatch.setattr(cli.export_flows, "export_all_functions",
                        lambda cc: {"functions": {}, "errors": []})
    monkeypatch.setattr(
        cli.export_calling, "export_all",
        lambda wx, on_progress=None: {"locations": [], "objects": {}, "error": None})

    class Args:
        out = str(tmp_path)
        only_non_default = False

    assert cli._run_export({"api_base": "https://api.example.com"}, Args()) == 0


def test_run_import_passes_the_webex_client_to_org_info(tmp_path, monkeypatch):
    from wxcc_export import archive
    p = tmp_path / "src-export.zip"
    archive.write_export(
        p, source={"orgId": "SAME-ORG", "orgName": "src"},
        cc={}, children={}, audio={},
        flows={"flows": {}, "subflows": {}, "errors": []},
        functions={"functions": {}, "errors": []},
        calling={"locations": [], "objects": {}, "error": None},
        users={"rows": [], "csv": ""})

    captured = {}
    cc_obj, wx_obj = object(), object()
    monkeypatch.setattr(cli, "_clients", lambda cfg: (cc_obj, wx_obj))

    def fake_org_info(cc, wx=None):
        captured["cc"], captured["wx"] = cc, wx
        return {"org_id": "SAME-ORG", "name": "Target", "subscription": None,
                "created_ms": None}

    monkeypatch.setattr(cli.tenant, "org_info", fake_org_info)

    class Args:
        archive = str(p)
        select = "all"
        on_conflict = "skip"
        confirm = False
        overwrite_flows = False

    rc = cli._run_import({"api_base": "x", "webex_base": "y"}, Args())
    assert rc == cli.EXIT_USAGE  # same-org refusal, reached AFTER org_info runs
    assert captured["cc"] is cc_obj
    assert captured["wx"] is wx_obj


def test_run_auth_status_passes_the_webex_client_to_org_info(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli.auth, "valid_access_token",
                        lambda cfg: ("TOK", "bearer"))
    monkeypatch.setattr(cli.auth, "extract_org_id", lambda token: "O1")
    monkeypatch.setattr(cli.client, "ApiClient",
                        lambda base, token, org_id=None: object())

    def fake_org_info(cc, wx=None):
        captured["cc"], captured["wx"] = cc, wx
        return {"org_id": "O1", "name": "Sandbox", "subscription": None,
                "created_ms": None}

    monkeypatch.setattr(cli.tenant, "org_info", fake_org_info)

    class Args:
        action = "status"

    cfg = {"api_base": "https://cc.example", "webex_base": "https://wx.example",
          "org_id": None}
    rc = cli._run_auth(cfg, Args())
    assert rc == 0
    assert "wx" in captured and captured["wx"] is not None
    assert captured["wx"] is not captured["cc"]


def test_launcher_script_runs_with_no_pythonpath_from_a_fresh_clone():
    repo_root = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "wxcc-export.py", "--help"],
        cwd=repo_root, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "usage" in result.stdout.lower()
