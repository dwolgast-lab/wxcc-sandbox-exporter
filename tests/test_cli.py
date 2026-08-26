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
                        lambda cc: {"org_id": "O1", "name": "Sandbox",
                                    "subscription": None})

    audio_items = [{"id": "a1", "name": "one"},
                   {"id": "a2", "name": "two"},
                   {"id": "a3", "name": "three"}]
    exported_fixture = {"audio-file": {"entity": "audio-file", "count": 3,
                                       "items": audio_items, "error": None}}
    monkeypatch.setattr(cli.export_cc, "export_all",
                        lambda cc, entities, on_progress=None: exported_fixture)
    monkeypatch.setattr(
        cli.export_cc, "export_audio_binaries",
        lambda cc, items: ({}, [
            "audio-file a1: ApiError: HTTP 404",
            "audio-file a2: ApiError: HTTP 500",
            "audio-file a3: ApiError: timeout",
        ]))
    monkeypatch.setattr(cli.export_flows, "resolve_project_id", lambda cc: "")
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


def test_launcher_script_runs_with_no_pythonpath_from_a_fresh_clone():
    repo_root = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "wxcc-export.py", "--help"],
        cwd=repo_root, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "usage" in result.stdout.lower()
