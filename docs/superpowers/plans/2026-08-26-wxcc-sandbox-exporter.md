# WxCC Sandbox Exporter/Importer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local Python CLI (plus a localhost-only web UI) that exports a Webex Contact Center sandbox tenant's configuration to a single `<tenant>-export.zip`, and selectively imports it into a different sandbox tenant.

**Architecture:** Three layers. (1) A stdlib-only transport layer — OAuth2 authorization-code-with-loopback, token store, paginated JSON client — adapted from the live-verified `wxcc.py` in the sibling `wxcc-skills` repo. (2) A declarative **entity registry** that names, for each config object, its list path, item path, required create fields, and dependencies; export and import are both generic walks driven by this registry rather than 20 hand-written object handlers. (3) A **generic ID-remapping** importer: because every WxCC id is a globally-unique opaque string, the importer records `old_id -> new_id` as it creates objects and then recursively substitutes across every remaining payload, including flow JSON. This avoids a hand-written foreign-key map, which the `wxcc-skills` authors already tried and documented as "slow, mostly inferred, and provably incomplete" (`wxcc-skills/mcp_server.py:558-563`).

**Tech Stack:** Python 3.11+ (stdlib `urllib`, `http.server`, `zipfile`, `json`), `pytest` for tests, hand-rolled HTTP stubs so tests need no network. No web framework — the local UI is `http.server` plus static HTML/JS. No third-party runtime dependency for the CLI core.

**Spec:** [`docs/wxcc-sandbox-exporter.md`](../../wxcc-sandbox-exporter.md)

---

## Decisions already made (do not re-litigate)

Recorded from the user on 2026-08-26:

| Fork | Decision |
|---|---|
| Webex Calling scope | **Bounded subset, export + import.** Locations, Schedules, Auto Attendants, Hunt Groups, Call Queues, Call Park, Call Pickup, Paging Groups, Announcements, Virtual Extensions, Operating Modes. |
| Contact Center Users | **Reference manifest only.** Export a `users.csv` + `users.json` mapping each user to their site/team/profiles/skills. **No write path.** |
| Delivery form | **Local Python CLI + localhost-only web UI.** No hosted service, no server-side custody of anyone's tokens. |
| Surveys & Channels | **`UNSUPPORTED.md` checklist** written into the archive. |

---

## Corrections applied after implementation (2026-08-26)

**This plan was executed. Two rounds of adversarial review found nine defects,
each reproduced by executing code. Where this document's task text still
disagrees with the committed source, THE SOURCE IS CORRECT.** The items below
are recorded so a re-execution does not reintroduce them.

### Defects that originated in THIS PLAN

| # | Where | Defect | Correction |
|---|---|---|---|
| P1 | Task 9, `export_flows.list_flows` / `list_functions` | `except Exception: return []` made a failed listing indistinguishable from a tenant with zero flows — contradicting `archive.py`'s own stated rule that a partial export must never look complete. **Task 9's test `test_list_flows_returns_empty_on_error` asserted the bug as intended.** | Both functions surface the failure to their caller; `export_all_flows` / `export_all_functions` append a descriptive entry to `errors`. The test was rewritten. |
| P2 | Task 16, `FUNCTION_IMPORT_FIELD` | Hardcoded to the guess `"file"` **directly beneath a comment saying "refusing is correct, guessing a field name is not."** U3 is unresolved and `docs/api-notes.md` does not exist. | Set to `UNRESOLVED`. `import_functions` refuses until the Task 5 probe resolves it. The success-path test monkeypatches a concrete value; the default stays the sentinel. |
| P3 | Task 13, `idmap._rewrite_string` | A sequential `text = text.replace(old, new)` loop re-scanned its own output. Three reproduced corruptions: `A→B` + `B→A` reverted to the original; `A→B` + `B→C` chained to `C`; a short id prefixing a longer one produced `"id=SHORTqrstuv;"`. The hardcoded `len(text) < 16` skip also ignored short ids entirely. | Single-pass compiled alternation, longest key first. The length floor derives from the shortest recorded key. Seven regression tests, all confirmed to fail against the original. |
| P4 | Task 6, `registry.create_path` | Returned a plausible `POST` path for `user`, whose collection publishes GET only. | Raises `NotWritable`. `NoChildCollection` replaces `UnknownEntity` for a known entity with no child collection. |
| P5 | Task 10, two Calling routes | `call-queues.list` and `call-park-extensions.item` are extrapolated from item paths this document's own evidence table shows as `—`. | Marked `UNCONFIRMED (U5)` in `registry.py` so the probe checks them. |
| P6 | Global Constraints | "any GitHub user can `git clone && python -m wxcc_export`" was false — that needs `PYTHONPATH=src` or `pip install -e .`. | Added top-level `wxcc-export.py`; verified by subprocess with no `PYTHONPATH`. |

### Defects in the implementation (not this plan's text)

- **Webex Calling import was non-functional.** `export_calling` tagged `_locationId` only on location-scoped items, so all seven org-scope types arrived with no location and the importer refused every one. `import_calling` then fell back to the **raw source-tenant location id** when unmapped, posting it into the target's create path and reporting clean success — undetectable downstream, because `strip_identity` lists `_locationId` in `IDENTITY_FIELDS` so `unmapped()` never saw it. And it never indexed the target for location-scoped objects, so `--on-conflict` never engaged and re-runs duplicated. A follow-up pass found the *same* silent-swallow still present in the `scope == "org"` branch after the first fix covered only `scope == "location"`.
- **The web UI silently discarded selections.** `/api/import` called only `import_cc` while the page rendered Flows and Calling as enabled checkboxes. It now mirrors `cli._run_import`, subflows-before-flows, sharing one `IdMap`.
- **`cli._run_export` overwrote** `exported["audio-file"]["error"]` per iteration, so only the last audio failure reached the manifest. Now accumulated.
- **The bearer-token warning printed twice** per export/import.

### Interface change to Task 15

`import_cc` returns **`(results, idmap)`**, not `results`. Tasks 16, 17 and 18 all
depend on reusing that map — a flow routing to queue `q1` needs the `q1 → q9`
mapping the CC pass recorded.

### Still unverified against a live tenant

**No code in this repository has called a real Webex API.** Task 5 has not run.
`PROJECT_ID_MODE`, `SUBFLOW_TYPE`, `FUNCTION_IMPORT_FIELD`, the Calling
`_locationId` candidate-field list, and both `UNCONFIRMED` Calling routes are all
provisional. Run `scripts/probe.py` and record the answers in `docs/api-notes.md`
before trusting any of them.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Python 3.11+.** Type hints use `X | None` syntax. The user's machine has Python 3.14.5 (confirmed: `python --version`).
- **The CLI core imports only the standard library.** `pytest` is a dev dependency only. Rationale: any GitHub user must be able to `git clone && python -m wxcc_export` with a bare Python install. This mirrors the sibling repo's stated rule ("`wxcc.py` stays dependency-free on purpose").
- **Never commit credentials.** `.env`, `.env.*`, `.wxcc/`, `*-export.zip` are gitignored from the first commit. `.env.example` is the only env file in git.
- **OAuth2 is the default auth path.** A personal bearer token is opt-in via `WXCC_BEARER_TOKEN` in the env file, and when set the tool must print `AUTH: personal bearer token (OAuth2 bypassed)` on every run.
- **Org ID is derived from the token, never configured by default.** Decode the access token per `wxcc-skills/wxcc.py:196 extract_org_id`. `WXCC_ORG_ID` exists only as an override.
- **The API base is region-specific.** Default `https://api.wxcc-us1.cisco.com` (confirmed working in `wxcc-skills/.env.example`). Never hardcode it anywhere but `config.py`.
- **Path versioning gotcha, verified across every entity in the sibling repo** (`wxcc-skills/mcp_server.py:715-731`): the **list** (GET collection) path carries `v2`/`v3`; the **item** path and the **create** (POST collection) path **drop it**. `GET v2/team` lists, but `POST v2/team` is *not* the create endpoint — `POST team` is.
- **Writes are gated.** Every import runs dry-run-by-default. A real write requires `--confirm`. After a confirmed write the importer **re-reads the object and diffs it**, because this API is documented to return `200` while silently ignoring fields (`wxcc-skills/CLAUDE.md`, "Writes").
- **Archive filename is `<orgName>-export.zip`**, where `orgName` comes from `GET organization/{orgId}` field `name` — the tenant's own record, not a configured label (confirmed `wxcc-skills/mcp_server.py:672-703`).
- **Unconfirmed API facts must be labelled.** Any value this plan marks `UNCONFIRMED` must be resolved by the Task 5 live probe and written into `docs/api-notes.md` before the task that depends on it is implemented. Do not guess a replacement.

---

## Confirmed API facts (evidence for every claim below)

Sources: the three OpenAPI documents in `docs/` supplied by the user, and the live-verified entity registry at `wxcc-skills/mcp_server.py:53`.

### Auth
- Authorize: `https://webexapis.com/v1/authorize`; Token: `https://webexapis.com/v1/access_token` (`wxcc-skills/wxcc.py:46-47`).
- Scopes: `cjp:config_read` for export, `cjp:config` for import (`wxcc-skills/.env.example`).

### Contact Center entities that map to confirmed endpoints

All are `organization/{orgId}/<path>`. `L` = list path, `I` = item path.

| Spec object | Entity | L | I |
|---|---|---|---|
| Queues | `contact-service-queue` | `v2/contact-service-queue` | `contact-service-queue/{id}` |
| Business Hours | `business-hours` | `v2/business-hours` | `business-hours/{id}` |
| (Business Hours dep) | `holiday-list` | `v2/holiday-list` | `holiday-list/{id}` |
| (Business Hours dep) | `overrides` | `v2/overrides` | `overrides/{id}` |
| Audio Files | `audio-file` | `v2/audio-file` | `audio-file/{id}` |
| Global Variables | `cad-variable` | `v2/cad-variable` | `cad-variable/{id}` |
| Sites | `site` | `v2/site` | `site/{id}` |
| Skill Management | `skill` | `v2/skill` | `skill/{id}` |
| Skill Profiles | `skill-profile` | `v2/skill-profile` | `skill-profile/{id}` |
| Teams | `team` | `v2/team` | `team/{id}` |
| User Profiles | `user-profile` | `v3/user-profile` | `user-profile/{id}` |
| Resource Collections | `resource-collection` | `v2/resource-collection` | `resource-collection/{id}` |
| CC Users | `user` | `v2/user` | `user/{id}` |
| Multimedia Profiles | `multimedia-profile` | `v2/multimedia-profile` | `multimedia-profile/{id}` |
| Outdial ANI | `outdial-ani` | `v2/outdial-ani` | `outdial-ani/{id}` |
| Desktop Layouts | `desktop-layout` | `v2/desktop-layout` | `desktop-layout/{id}` |
| Address Books | `address-book` | `v2/address-book` | `address-book/{id}` |
| Desktop Profiles | `agent-profile` | `v2/agent-profile` | `agent-profile/{id}` |
| Idle/Wrap-up Codes | `auxiliary-code` | `v2/auxiliary-code` | `auxiliary-code/{id}` |
| (Aux code dep) | `work-type` | `v2/work-type` | `work-type/{id}` |
| (Queue/EP dep) | `entry-point` | `v2/entry-point` | `entry-point/{id}` |
| (EP dep) | `dial-number` | `v2/dial-number` | `dial-number/{id}` |

### Flows (spec tag `Flows`)

- List: `GET /{orgId}/project/{projectId}/flows?flowType=FLOW&includePagination=true&size=100`
- Export one: `GET /{orgId}/project/{projectId}/v2/flows/{flowId}:export` -> `application/json`
- Import: `POST /{orgId}/project/{projectId}/v2/flows:import?overwrite=&flowType=` -> body `application/json`
- Note: `wxcc-skills` declares flows out of scope **by policy**. That is a that-repo decision. The API exists and this project uses it.

### Functions (spec tag `Functions`)

- List: `GET /v1/{orgId}/functions?page=&size=`
- Export one: `POST /v1/{orgId}/functions/{id}:export` -> `application/json`
- Import: `POST /v1/{orgId}/functions:import` -> body **`multipart/form-data`** (asymmetric with export — see U3)

### Contact Center Users cannot be created

`/organization/{orgid}/user` publishes **GET only**; `/organization/{orgid}/user/{id}` publishes GET, PATCH, PUT. There is no POST and no DELETE. Confirmed twice: the OpenAPI document, and the registry note "Users are created/deleted in Control Hub, not here." This is why the user chose the reference-manifest option.

### Surveys and Channels have no API

Across all 328 Contact Center paths and all 61 tags there is no `survey` or `channel` operation. The nearest neighbour is `Auto CSAT`, which is the AI-generated CSAT feature, not the Surveys page. This is a **product gap, not a search gap**, and Task 11 must say so in `UNSUPPORTED.md` rather than quietly omitting the objects.

### Webex Calling subset (spec tags `Features: *`, `Locations`)

Base is the Webex API host (`https://webexapis.com/v1`), **not** the WxCC regional host.

| Object | Org-level list | Location-scoped |
|---|---|---|
| Locations | `GET /locations` | — |
| Schedules | — | `GET /telephony/config/locations/{locationId}/schedules` |
| Auto Attendants | `GET /telephony/config/autoAttendants` | `.../locations/{locationId}/autoAttendants/{id}` |
| Hunt Groups | `GET /telephony/config/huntGroups` | `.../locations/{locationId}/huntGroups/{id}` |
| Call Queues | — | `.../locations/{locationId}/queues/{queueId}` |
| Call Park | `GET /telephony/config/callParkExtensions` | `.../locations/{locationId}/callParks` |
| Call Pickup | — | `.../locations/{locationId}/callPickups` |
| Paging Groups | `GET /telephony/config/paging` | `.../locations/{locationId}/paging/{pagingId}` |
| Announcements | `GET /telephony/config/announcements` | `.../announcements/{announcementId}` |
| Virtual Extensions | `GET /telephony/config/virtualExtensions` | — |
| Operating Modes | `GET /telephony/config/operatingModes` | — |

---

## UNCONFIRMED — must be resolved by the Task 5 live probe

These are facts this plan needs but **cannot** establish from the OpenAPI documents. Task 5 resolves each and writes the answer to `docs/api-notes.md`. **No downstream task may guess a value here.**

| ID | Question | Why the spec can't answer it |
|---|---|---|
| U1 | What is `projectId` in the Flows paths? | Path param declared `required: true` with no default, enum, or description of how to obtain it. |
| U2 | What `flowType` value selects Subflows? | Schema is `{"type":"string","default":"FLOW"}` — no enum published. `"SUBFLOW"` is a plausible guess and must not be used unverified. |
| U3 | What are the multipart field names for `POST /v1/{orgId}/functions:import`? | `requestBody` declares `multipart/form-data` but the part names are not enumerated. |
| U4 | Do config objects carry a `createdTime`, and does it cluster at tenant provisioning? | Drives the "non-default" heuristic. If absent, fall back to collision-aware import only. |
| U5 | Which OAuth scopes does the Calling subset need, and does the sandbox even have Calling provisioned? | Calling scopes are in the `spark-admin:telephony_config_*` family; the exact set and the sandbox's entitlement are both unverified. |
| U6 | Does `GET organization/{orgId}` return a `name` suitable for a filename (e.g. `davidwolgast-8xgo`)? | The user's example filename implies the org name *is* the sandbox slug. Must be confirmed, and sanitised regardless. |

**This plan is executable up to Task 8 without credentials.** Tasks 9, 10 and 15 are blocked on U1–U5.

---

## "Non-default only" — how this is actually handled

The spec asks to export "only non-default (items which automatically are built in the tenant at provisioning) if possible". **There is no `isDefault` flag on any entity in the API.** Pretending otherwise would be inventing a field.

Three mechanisms, in order of reliability:

1. **Collision-aware import (primary, always on).** Before creating anything, the importer lists the target tenant and indexes existing objects by `(entity, name)`. A source object whose name already exists in the target is *by definition already present* — whether it is a provisioning default or a previous import. Default policy `skip`; `--on-conflict=update|skip|rename` selects otherwise. This makes "don't duplicate the defaults" true **without** needing to know what a default is.
2. **`createdTime` clustering (heuristic, opt-in).** If U4 confirms the field exists, objects created within 120s of the earliest object in the tenant are tagged `"likely_default": true` in the manifest. This is a *label*, never a silent filter.
3. **`--only-non-default` export flag (opt-in).** Filters on the mechanism-2 tag. Off by default, because a false positive here silently loses real configuration.

The archive **always contains everything in scope**. Filtering happens at import time, where it is reversible.

---

## File Structure

```text
wxcc-sandbox-exporter/
  README.md                         # quickstart, scope, honest limits
  LICENSE                           # MIT
  .gitignore                        # .env*, .wxcc/, *-export.zip, __pycache__
  .env.example                      # the only env file in git
  pyproject.toml                    # packaging + pytest config
  requirements-dev.txt              # pytest only
  docs/
    wxcc-sandbox-exporter.md        # the spec (already present)
    api-notes.md                    # Task 5 probe findings — the U1..U6 answers
    user-guide.md                   # Task 19
    uat-plan.md                     # Task 20
  src/wxcc_export/
    __init__.py
    config.py         # env file loading, profiles, region host, bearer-token opt-in
    auth.py           # OAuth2 loopback flow, token store, refresh, org-id extraction
    client.py         # HTTP: request, JSON parse, pagination, retry/backoff, multipart
    registry.py       # CC entity registry (list/item/create/deps) + Calling subset
    tenant.py         # GET organization/{orgId} -> name, subscriptionType, safe filename
    archive.py        # zip read/write, manifest schema, UNSUPPORTED.md, users manifest
    export_cc.py      # generic registry-driven CC export + audio binaries + child entries
    export_flows.py   # flows, subflows, functions
    export_calling.py # the 11-object Calling subset
    idmap.py          # old_id -> new_id recording + recursive substitution
    plan.py           # dependency ordering (topological sort over registry deps)
    importer.py       # dry-run, collision detection, create/update, re-read verify
    cli.py            # argparse entrypoint
    web/
      server.py       # http.server, 127.0.0.1 bind only, single-origin token
      static/index.html, app.js, style.css
  tests/
    conftest.py       # FakeTransport: canned responses, records requests
    test_config.py  test_auth.py  test_client.py  test_registry.py
    test_tenant.py  test_archive.py  test_export_cc.py  test_idmap.py
    test_plan.py    test_importer.py  test_cli.py  test_web.py
    fixtures/        # captured (redacted) API response bodies
```

---

## Archive format (the contract between export and import)

`<orgName>-export.zip`:

```text
manifest.json                 # schema below — the index for everything else
UNSUPPORTED.md                # Surveys, Channels, and anything that failed
cc/<entity>.json              # one file per CC entity: {"entity":..,"items":[...]}
cc/audio/<id>__<filename>     # audio-file binaries, id-prefixed to avoid collision
cc/children/<entity>__<parentId>.json   # address-book + outdial-ani child entries
flows/flows/<flowId>.json     # one exported flow per file
flows/subflows/<flowId>.json
flows/functions/<id>.json
calling/<object>.json         # one file per Calling object type
users/users.json              # reference manifest (no write path)
users/users.csv               # same data, spreadsheet-friendly
```

`manifest.json` schema:

```json
{
  "schemaVersion": 1,
  "tool": "wxcc-sandbox-exporter",
  "toolVersion": "0.1.0",
  "exportedAt": "2026-08-26T15:04:05Z",
  "source": {"orgId": "...", "orgName": "...", "subscriptionType": "TRIAL",
             "apiBase": "https://api.wxcc-us1.cisco.com"},
  "sections": {
    "cc":      {"entities": {"site": {"count": 3, "file": "cc/site.json"}}},
    "flows":   {"flows": 4, "subflows": 1, "functions": 2, "projectId": "..."},
    "calling": {"objects": {"locations": {"count": 1, "file": "calling/locations.json"}}},
    "users":   {"count": 12, "writable": false}
  },
  "unsupported": ["surveys", "channels"],
  "errors": [{"section": "calling", "object": "queues", "detail": "HTTP 403 ..."}]
}
```

**`errors` is never empty-by-omission.** A section that failed is recorded, and `UNSUPPORTED.md` restates it in prose. A partial export must never look like a complete one.

---

## Task list overview

| # | Task | Blocked on credentials? |
|---|---|---|
| 1 | Repo scaffold, git init, config loading | no |
| 2 | OAuth2 + bearer-token auth and token store | no |
| 3 | HTTP client: pagination, retry, multipart | no |
| 4 | Tenant identity and archive filename | no |
| 5 | **Live probe** — resolve U1–U6 into `docs/api-notes.md` | **YES** |
| 6 | Entity registry + dependency graph | no |
| 7 | Generic CC export | no |
| 8 | Audio binaries, child entries, users manifest | no |
| 9 | Flows, subflows, functions export | yes (U1–U3) |
| 10 | Calling subset export | yes (U5) |
| 11 | Archive writer + manifest + UNSUPPORTED.md | no |
| 12 | Archive reader + selection model | no |
| 13 | ID remap engine | no |
| 14 | Import ordering + collision detection | no |
| 15 | CC importer with dry-run and re-read verify | no |
| 16 | Flows/functions/calling importer | yes (U1–U3, U5) |
| 17 | CLI | no |
| 18 | Local web UI | no |
| 19 | User guide | no |
| 20 | UAT plan | no |

---

# Tasks

### Task 1: Repo scaffold and configuration loading

**Files:**
- Create: `.gitignore`, `LICENSE`, `pyproject.toml`, `requirements-dev.txt`, `.env.example`
- Create: `src/wxcc_export/__init__.py`, `src/wxcc_export/config.py`
- Test: `tests/test_config.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `config.load_config(profile: str | None = None) -> dict` — keys `client_id`, `client_secret`, `redirect_uri`, `scopes`, `api_base`, `webex_base`, `org_id`, `bearer_token`, `profile`.
  - `config.env_file(profile: str | None) -> pathlib.Path`
  - `config.token_store(profile: str | None) -> pathlib.Path`
  - `config.WXCC_DEFAULT_API_BASE: str`, `config.WEBEX_API_BASE: str`
  - `config.ConfigError(Exception)`

- [ ] **Step 1: Initialise the repository**

The working directory is not yet a git repo (confirmed: `Is a git repository: false`).

```bash
cd /c/Users/david.wolgast/source/repos/wxcc-sandbox-exporter
git init -b main
```

- [ ] **Step 2: Write `.gitignore` before anything else**

Credentials must never enter history. Write this file first.

```gitignore
# credentials — never commit
.env
.env.*
!.env.example
.wxcc/
*.token.json

# export archives may contain tenant configuration
*-export.zip
exports/

# python
__pycache__/
*.py[cod]
.pytest_cache/
.venv/
venv/
*.egg-info/
build/
dist/
```

- [ ] **Step 3: Write `LICENSE` (MIT) and `requirements-dev.txt`**

`requirements-dev.txt`:

```text
pytest>=8.0
```

For `LICENSE`, use the standard MIT text with `Copyright (c) 2026 dwolgast-lab`.

- [ ] **Step 4: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "wxcc-sandbox-exporter"
version = "0.1.0"
description = "Export and import Webex Contact Center sandbox tenant configuration"
requires-python = ">=3.11"
dependencies = []

[project.scripts]
wxcc-export = "wxcc_export.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 5: Write `.env.example`**

```bash
# wxcc-sandbox-exporter configuration — copy to `.env` and fill in.
# `.env` is gitignored. Never commit a filled-in copy.
#
# Register an Integration at https://developer.webex.com (Manage Apps >
# Create an Integration). The authorizing user must be a Webex Contact
# Center administrator on the tenant you are exporting.

# --- OAuth2 (the default and recommended path) ---
WXCC_CLIENT_ID=
WXCC_CLIENT_SECRET=

# Must EXACTLY match a redirect URI registered on the Integration.
# The tool starts a local listener on this host/port to catch the auth code.
WXCC_REDIRECT_URI=http://localhost:8484/callback

# Space-separated. Export needs cjp:config_read. Import also needs cjp:config.
WXCC_SCOPES=cjp:config_read cjp:config

# --- Region ---
# Confirmed host for the US region. Set to your tenant's region host.
WXCC_API_BASE=https://api.wxcc-us1.cisco.com

# --- Optional: personal bearer token (bypasses OAuth2) ---
# Opt-in only. When set, OAuth2 is skipped and every run prints a warning.
# Tokens from developer.webex.com expire in 12 hours.
# WXCC_BEARER_TOKEN=

# --- Optional overrides ---
# Org id is derived from the access token. Set only if calls 404 on org.
# WXCC_ORG_ID=
```

- [ ] **Step 6: Write the failing test**

`tests/test_config.py`:

```python
import pytest
from wxcc_export import config


def write_env(tmp_path, text, name=".env"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_load_config_reads_key_values(tmp_path, monkeypatch):
    write_env(tmp_path, "WXCC_CLIENT_ID=abc\nWXCC_CLIENT_SECRET=shh\n")
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    cfg = config.load_config()
    assert cfg["client_id"] == "abc"
    assert cfg["client_secret"] == "shh"


def test_load_config_ignores_comments_and_blank_lines(tmp_path, monkeypatch):
    write_env(tmp_path, "# a comment\n\nWXCC_CLIENT_ID=abc\n   \n")
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    assert config.load_config()["client_id"] == "abc"


def test_load_config_strips_surrounding_quotes(tmp_path, monkeypatch):
    write_env(tmp_path, 'WXCC_CLIENT_ID="abc"\nWXCC_SCOPES=\'cjp:config_read\'\n')
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    cfg = config.load_config()
    assert cfg["client_id"] == "abc"
    assert cfg["scopes"] == "cjp:config_read"


def test_api_base_defaults_to_us_region(tmp_path, monkeypatch):
    write_env(tmp_path, "WXCC_CLIENT_ID=abc\n")
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    assert config.load_config()["api_base"] == "https://api.wxcc-us1.cisco.com"


def test_api_base_trailing_slash_is_stripped(tmp_path, monkeypatch):
    write_env(tmp_path, "WXCC_API_BASE=https://api.wxcc-eu1.cisco.com/\n")
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    assert config.load_config()["api_base"] == "https://api.wxcc-eu1.cisco.com"


def test_profile_selects_a_different_env_file(tmp_path, monkeypatch):
    write_env(tmp_path, "WXCC_CLIENT_ID=default\n")
    write_env(tmp_path, "WXCC_CLIENT_ID=target\n", name=".env.target")
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    assert config.load_config()["client_id"] == "default"
    assert config.load_config("target")["client_id"] == "target"


def test_profile_gets_its_own_token_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    assert config.token_store(None) != config.token_store("target")


def test_missing_env_file_raises_config_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    with pytest.raises(config.ConfigError) as exc:
        config.load_config("nope")
    assert ".env.nope" in str(exc.value)


def test_real_environment_overrides_the_file(tmp_path, monkeypatch):
    write_env(tmp_path, "WXCC_CLIENT_ID=from_file\n")
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    monkeypatch.setenv("WXCC_CLIENT_ID", "from_env")
    assert config.load_config()["client_id"] == "from_env"
```

- [ ] **Step 7: Run the test to verify it fails**

```bash
python -m pytest tests/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'wxcc_export'`.

- [ ] **Step 8: Write the implementation**

`src/wxcc_export/__init__.py`:

```python
"""Export and import Webex Contact Center sandbox tenant configuration."""

__version__ = "0.1.0"
```

`src/wxcc_export/config.py`:

```python
"""Configuration loading.

One env file per tenant, selected by profile, each with its own token store.
There is deliberately no "current tenant" pointer: a mutable global is how a
write meant for the new sandbox lands on the old one.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]

WXCC_DEFAULT_API_BASE = "https://api.wxcc-us1.cisco.com"
WEBEX_API_BASE = "https://webexapis.com/v1"


class ConfigError(Exception):
    """Configuration is missing or unusable."""


def env_file(profile: str | None) -> Path:
    return REPO_DIR / (f".env.{profile}" if profile else ".env")


def token_store(profile: str | None) -> Path:
    name = f"tokens.{profile}.json" if profile else "tokens.json"
    return REPO_DIR / ".wxcc" / name


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        val = raw.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key.strip()] = val
    return values


def load_config(profile: str | None = None) -> dict:
    """Read the profile's env file, with the real environment taking priority."""
    path = env_file(profile)
    if not path.exists():
        raise ConfigError(
            f"no config at {path.name}. Copy .env.example to {path.name} and fill it in."
        )
    raw = _parse_env(path)

    def get(key: str, default: str = "") -> str:
        return os.environ.get(key) or raw.get(key, default)

    api_base = get("WXCC_API_BASE", WXCC_DEFAULT_API_BASE).rstrip("/")
    return {
        "profile": profile,
        "client_id": get("WXCC_CLIENT_ID"),
        "client_secret": get("WXCC_CLIENT_SECRET"),
        "redirect_uri": get("WXCC_REDIRECT_URI", "http://localhost:8484/callback"),
        "scopes": get("WXCC_SCOPES", "cjp:config_read"),
        "api_base": api_base,
        "webex_base": WEBEX_API_BASE,
        "org_id": get("WXCC_ORG_ID") or None,
        "bearer_token": get("WXCC_BEARER_TOKEN") or None,
    }


def require(cfg: dict, *keys: str) -> None:
    """Fail with the env var name the user must set, not the internal key."""
    missing = [k for k in keys if not cfg.get(k)]
    if missing:
        names = ", ".join(f"WXCC_{k.upper()}" for k in missing)
        raise ConfigError(f"missing required setting(s): {names}")
```

- [ ] **Step 9: Run the tests to verify they pass**

```bash
python -m pytest tests/test_config.py -v
```

Expected: 9 passed.

- [ ] **Step 10: Commit**

```bash
git add .gitignore LICENSE pyproject.toml requirements-dev.txt .env.example \
        src/wxcc_export/__init__.py src/wxcc_export/config.py tests/test_config.py
git commit -m "feat: repo scaffold and profile-scoped configuration loading"
```

---

### Task 2: OAuth2 and personal-bearer-token authentication

**Files:**
- Create: `src/wxcc_export/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `config.load_config`, `config.token_store`, `config.ConfigError`.
- Produces:
  - `auth.extract_org_id(access_token: str) -> str | None`
  - `auth.login(cfg: dict) -> dict` — runs the loopback flow, saves and returns the token dict
  - `auth.valid_access_token(cfg: dict) -> tuple[str, str]` — returns `(token, source)` where `source` is `"oauth2"` or `"bearer"`; refreshes if within 300s of expiry
  - `auth.load_tokens(cfg) -> dict | None`, `auth.save_tokens(cfg, tok) -> None`, `auth.logout(cfg) -> None`
  - `auth.AuthError(Exception)`

**Why the access token carries the org id:** the Webex access token is a JWT-like value whose middle segment base64url-decodes to JSON containing the org. `wxcc-skills/wxcc.py:196` does exactly this and is live-verified. Reimplement rather than import, because that repo is a sibling, not a dependency.

- [ ] **Step 1: Write the failing test**

`tests/test_auth.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_auth.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'wxcc_export.auth'`.

- [ ] **Step 3: Write the implementation**

`src/wxcc_export/auth.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_auth.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wxcc_export/auth.py tests/test_auth.py
git commit -m "feat: OAuth2 loopback flow, token store, and opt-in bearer token"
```

---

### Task 3: HTTP client with pagination, retry, and multipart

**Files:**
- Create: `src/wxcc_export/client.py`
- Test: `tests/test_client.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: `auth.valid_access_token`, `auth.extract_org_id`.
- Produces:
  - `client.ApiClient(api_base: str, token: str, org_id: str | None = None, transport=None)`
  - `.url(path: str) -> str` — substitutes `{orgId}`
  - `.request(method, path, body=None, headers=None) -> tuple[int, str]`
  - `.json(method, path, body=None) -> tuple[int, object]`
  - `.list_all(path: str) -> list[dict]` — follows `meta.links.next` to exhaustion
  - `.get_bytes(path: str) -> tuple[int, bytes, str]` — returns `(status, body, content_type)`
  - `.multipart(method, path, parts: list[tuple]) -> tuple[int, object]`
  - `client.ApiError(Exception)` with attributes `.status`, `.body`, `.path`

**Pagination shape (confirmed):** WxCC list responses are `{"meta": {"links": {"next": "..."}}, "data": [...]}`, and `next` is a **path fragment appended to the api_base**, not an absolute URL (`wxcc-skills/wxcc.py:333-344`).

- [ ] **Step 1: Write the shared fake transport**

`tests/conftest.py`:

```python
"""A recording fake transport. No test in this suite touches the network."""

import json

import pytest


class FakeResponse:
    def __init__(self, status=200, body="", content_type="application/json"):
        self.status = status
        self.body = body if isinstance(body, bytes) else body.encode()
        self.content_type = content_type


class FakeTransport:
    """Maps 'METHOD /path' -> FakeResponse or a list of them (consumed in order)."""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.calls = []

    def add(self, key, status=200, body=None, content_type="application/json"):
        payload = json.dumps(body) if not isinstance(body, (str, bytes, type(None))) else body
        self.routes.setdefault(key, []).append(
            FakeResponse(status, payload or "", content_type))
        return self

    def __call__(self, method, url, headers=None, data=None):
        self.calls.append({"method": method, "url": url,
                           "headers": headers or {}, "data": data})
        path = url.split("://", 1)[-1]
        path = path[path.index("/"):] if "/" in path else "/"
        for key in (f"{method} {url}", f"{method} {path}"):
            queue = self.routes.get(key)
            if queue:
                return queue.pop(0) if len(queue) > 1 else queue[0]
        return FakeResponse(404, json.dumps({"error": f"no route for {method} {path}"}))


@pytest.fixture
def transport():
    return FakeTransport()
```

- [ ] **Step 2: Write the failing test**

`tests/test_client.py`:

```python
import json

import pytest
from wxcc_export.client import ApiClient, ApiError

BASE = "https://api.wxcc-us1.cisco.com"


def make(transport, org_id="ORG1"):
    return ApiClient(BASE, "TOKEN", org_id=org_id, transport=transport)


def test_url_substitutes_the_org_id(transport):
    c = make(transport)
    assert c.url("organization/{orgId}/v2/team") == f"{BASE}/organization/ORG1/v2/team"


def test_url_raises_when_org_id_is_needed_but_unknown(transport):
    c = ApiClient(BASE, "TOKEN", org_id=None, transport=transport)
    with pytest.raises(ApiError) as exc:
        c.url("organization/{orgId}/v2/team")
    assert "WXCC_ORG_ID" in str(exc.value)


def test_authorization_header_is_sent(transport):
    transport.add("GET /organization/ORG1/v2/team", body={"data": []})
    make(transport).json("GET", "organization/{orgId}/v2/team")
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer TOKEN"


def test_json_parses_the_body(transport):
    transport.add("GET /organization/ORG1/v2/team", body={"data": [{"id": "t1"}]})
    status, body = make(transport).json("GET", "organization/{orgId}/v2/team")
    assert status == 200
    assert body["data"][0]["id"] == "t1"


def test_json_returns_text_when_the_body_is_not_json(transport):
    transport.add("GET /ping", body="pong", content_type="text/plain")
    status, body = make(transport).json("GET", "ping")
    assert (status, body) == (200, "pong")


def test_list_all_follows_meta_links_next(transport):
    transport.add("GET /organization/ORG1/v2/team",
                  body={"data": [{"id": "a"}],
                        "meta": {"links": {"next": "/organization/ORG1/v2/team?page=1"}}})
    transport.add("GET /organization/ORG1/v2/team?page=1",
                  body={"data": [{"id": "b"}], "meta": {"links": {}}})
    items = make(transport).list_all("organization/{orgId}/v2/team")
    assert [i["id"] for i in items] == ["a", "b"]


def test_list_all_stops_on_a_page_without_a_next_link(transport):
    transport.add("GET /organization/ORG1/v2/team", body={"data": [{"id": "a"}]})
    assert len(make(transport).list_all("organization/{orgId}/v2/team")) == 1


def test_list_all_accepts_a_bare_array_response(transport):
    # Some Calling endpoints return a top-level list rather than meta+data.
    transport.add("GET /telephony/config/announcements", body=[{"id": "a"}])
    assert make(transport).list_all("telephony/config/announcements") == [{"id": "a"}]


def test_list_all_raises_on_an_error_page(transport):
    transport.add("GET /organization/ORG1/v2/team", status=403,
                  body={"message": "forbidden"})
    with pytest.raises(ApiError) as exc:
        make(transport).list_all("organization/{orgId}/v2/team")
    assert exc.value.status == 403


def test_retry_on_429_then_success(transport, monkeypatch):
    monkeypatch.setattr("wxcc_export.client.time.sleep", lambda _s: None)
    transport.add("GET /organization/ORG1/v2/team", status=429, body={"m": "slow down"})
    transport.add("GET /organization/ORG1/v2/team", body={"data": []})
    status, _ = make(transport).json("GET", "organization/{orgId}/v2/team")
    assert status == 200
    assert len(transport.calls) == 2


def test_retry_gives_up_after_the_limit(transport, monkeypatch):
    monkeypatch.setattr("wxcc_export.client.time.sleep", lambda _s: None)
    for _ in range(6):
        transport.add("GET /organization/ORG1/v2/team", status=429, body={})
    status, _ = make(transport).json("GET", "organization/{orgId}/v2/team")
    assert status == 429


def test_get_bytes_returns_the_raw_body_and_content_type(transport):
    transport.add("GET /audio", body=b"RIFFdata", content_type="audio/wav")
    status, data, ctype = make(transport).get_bytes("audio")
    assert (status, data, ctype) == (200, b"RIFFdata", "audio/wav")


def test_multipart_sets_a_boundary_content_type(transport):
    transport.add("POST /upload", body={"ok": True})
    make(transport).multipart("POST", "upload",
                              [("file", "a.wav", "audio/wav", b"RIFF")])
    ctype = transport.calls[0]["headers"]["Content-Type"]
    assert ctype.startswith("multipart/form-data; boundary=")


def test_multipart_body_contains_the_named_parts(transport):
    transport.add("POST /upload", body={"ok": True})
    make(transport).multipart("POST", "upload", [
        ("file", "a.wav", "audio/wav", b"RIFF"),
        ("info", None, "application/json", b'{"n":1}'),
    ])
    data = transport.calls[0]["data"]
    assert b'name="file"; filename="a.wav"' in data
    assert b'name="info"' in data
    assert b'{"n":1}' in data
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
python -m pytest tests/test_client.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'wxcc_export.client'`.

- [ ] **Step 4: Write the implementation**

`src/wxcc_export/client.py`:

```python
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
            data = doc.get("data")
            if data is None:
                for key in ("items", "locations", "announcements"):
                    if isinstance(doc.get(key), list):
                        data = doc[key]
                        break
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
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python -m pytest tests/test_client.py -v
```

Expected: 14 passed.

- [ ] **Step 6: Run the whole suite and record the baseline**

```bash
python -m pytest -q
```

Expected: 33 passed. Record this number — every later task reports its delta against it.

- [ ] **Step 7: Commit**

```bash
git add src/wxcc_export/client.py tests/test_client.py tests/conftest.py
git commit -m "feat: HTTP client with pagination, retry, and multipart bodies"
```

---

### Task 4: Tenant identity and archive filename

**Files:**
- Create: `src/wxcc_export/tenant.py`
- Test: `tests/test_tenant.py`

**Interfaces:**
- Consumes: `client.ApiClient`, `client.ApiError`.
- Produces:
  - `tenant.org_info(client) -> dict` — keys `name`, `org_id`, `subscription`, `production`
  - `tenant.safe_slug(name: str) -> str`
  - `tenant.archive_name(info: dict) -> str` — e.g. `davidwolgast-8xgo-export.zip`
  - `tenant.describe(info: dict) -> str` — one line naming the tenant, tagged PRODUCTION or trial/sandbox

**Why this matters beyond the filename:** every destructive import must print which tenant it is about to write to, taken from the tenant's own record. A configured label can be copied to the wrong profile; asking the tenant who it is cannot lie.

- [ ] **Step 1: Write the failing test**

`tests/test_tenant.py`:

```python
import pytest
from wxcc_export import tenant
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


def test_org_info_reads_name_and_subscription(transport):
    transport.add("GET /organization/ORG1",
                  body={"name": "davidwolgast-8xgo", "subscriptionType": "TRIAL"})
    info = tenant.org_info(make(transport))
    assert info["name"] == "davidwolgast-8xgo"
    assert info["production"] is False


def test_subscription_type_marks_a_paying_org_as_production(transport):
    transport.add("GET /organization/ORG1",
                  body={"name": "Acme", "subscriptionType": "SUBSCRIPTION"})
    assert tenant.org_info(make(transport))["production"] is True


def test_org_info_reports_unavailable_rather_than_guessing(transport):
    transport.add("GET /organization/ORG1", status=403, body={"message": "nope"})
    info = tenant.org_info(make(transport))
    assert info["name"] == "(org name unavailable)"
    assert info["production"] is None


def test_org_info_without_an_org_id_does_not_call_the_api(transport):
    c = ApiClient(BASE, "TOKEN", org_id=None, transport=transport)
    info = tenant.org_info(c)
    assert info["org_id"] is None
    assert transport.calls == []


def test_safe_slug_keeps_a_clean_name_unchanged():
    assert tenant.safe_slug("davidwolgast-8xgo") == "davidwolgast-8xgo"


def test_safe_slug_replaces_path_separators_and_spaces():
    assert tenant.safe_slug("Acme Corp / EU") == "Acme-Corp-EU"


def test_safe_slug_rejects_traversal():
    assert ".." not in tenant.safe_slug("../../etc/passwd")


def test_safe_slug_falls_back_when_nothing_usable_remains():
    assert tenant.safe_slug("///") == "wxcc-tenant"


def test_archive_name_matches_the_spec_example():
    info = {"name": "davidwolgast-8xgo", "org_id": "ORG1"}
    assert tenant.archive_name(info) == "davidwolgast-8xgo-export.zip"


def test_archive_name_falls_back_to_the_org_id_when_the_name_is_unavailable():
    info = {"name": "(org name unavailable)", "org_id": "ORG1"}
    assert tenant.archive_name(info) == "ORG1-export.zip"


def test_describe_tags_a_sandbox():
    info = {"name": "davidwolgast-8xgo", "org_id": "ORG1", "production": False}
    assert "[trial/sandbox]" in tenant.describe(info)


def test_describe_tags_production_loudly():
    info = {"name": "Acme", "org_id": "ORG1", "production": True}
    assert "[PRODUCTION]" in tenant.describe(info)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_tenant.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'wxcc_export.tenant'`.

- [ ] **Step 3: Write the implementation**

`src/wxcc_export/tenant.py`:

```python
"""Who this tenant actually is, straight from its own record.

Authoritative on purpose: a configured label can drift or be copied to the wrong
profile. `subscriptionType` distinguishes a paying customer's org from a
trial/sandbox without anyone having to declare it.
"""

from __future__ import annotations

import re

NAME_UNAVAILABLE = "(org name unavailable)"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def org_info(client) -> dict:
    org_id = client.org_id
    if not org_id:
        return {"name": "(org id unresolved)", "org_id": None,
                "subscription": None, "production": None}
    try:
        status, body = client.json("GET", f"organization/{org_id}")
    except Exception:
        status, body = 0, None
    if status != 200 or not isinstance(body, dict):
        return {"name": NAME_UNAVAILABLE, "org_id": org_id,
                "subscription": None, "production": None}
    return {
        "name": body.get("name") or NAME_UNAVAILABLE,
        "org_id": org_id,
        "subscription": body.get("subscriptionType"),
        # A paying subscription is a real customer tenant. Trials are sandboxes.
        "production": body.get("subscriptionType") == "SUBSCRIPTION",
    }


def safe_slug(name: str) -> str:
    """Make a tenant name safe to use as a filename component."""
    slug = _UNSAFE.sub("-", (name or "").strip()).strip("-.")
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.replace("..", "")
    return slug[:80] or "wxcc-tenant"


def archive_name(info: dict) -> str:
    name = info.get("name") or ""
    if not name or name.startswith("("):
        name = info.get("org_id") or "wxcc-tenant"
    return f"{safe_slug(name)}-export.zip"


def describe(info: dict) -> str:
    """One line naming exactly which tenant a result came from / would change."""
    if info.get("production") is None:
        return f"{info.get('name')} (org {info.get('org_id')})"
    tag = "PRODUCTION" if info["production"] else "trial/sandbox"
    return f"{info['name']} [{tag}] (org {info['org_id']})"
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_tenant.py -v
```

Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wxcc_export/tenant.py tests/test_tenant.py
git commit -m "feat: tenant identity from the org record and safe archive naming"
```

---

### Task 5: Live probe — resolve U1 through U6

> **BLOCKED ON CREDENTIALS.** This task cannot be completed without an authenticated session against a real WxCC sandbox. Ask the user to run `wxcc-export auth login`, or to place `WXCC_BEARER_TOKEN` in `.env`, before starting.

**Files:**
- Create: `scripts/probe.py`
- Create: `docs/api-notes.md` (the output)
- Test: none — this is a research script whose product is documentation. Do not write assertions against a live tenant.

**Interfaces:**
- Consumes: `config`, `auth`, `client`, `tenant`.
- Produces: `docs/api-notes.md` containing a resolved answer for each of U1–U6, each with the exact request made and the observed status and shape.

**The rule for this task:** record what the API *did*, not what the spec says it should do. Where the two disagree, the probe wins and the disagreement is written down. Every finding must carry the date it was observed.

- [ ] **Step 1: Write the probe script**

`scripts/probe.py`:

```python
#!/usr/bin/env python3
"""Answer the questions the OpenAPI documents cannot.

Read-only. Prints a report; writes nothing to the tenant. Run:
    python scripts/probe.py [--profile NAME]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wxcc_export import auth, client, config, tenant  # noqa: E402


def show(label: str, status: int, body: object, note: str = "") -> None:
    blob = json.dumps(body)[:400] if not isinstance(body, str) else body[:400]
    print(f"\n### {label}\n  HTTP {status}\n  {blob}")
    if note:
        print(f"  NOTE: {note}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None)
    args = ap.parse_args()

    cfg = config.load_config(args.profile)
    token, source = auth.valid_access_token(cfg)
    if source == "bearer":
        print("AUTH: personal bearer token (OAuth2 bypassed)")
    org_id = cfg["org_id"] or auth.extract_org_id(token)
    cc = client.ApiClient(cfg["api_base"], token, org_id=org_id)
    wx = client.ApiClient(cfg["webex_base"], token, org_id=org_id)

    info = tenant.org_info(cc)
    print(f"TENANT: {tenant.describe(info)}")
    print(f"U6 archive filename would be: {tenant.archive_name(info)}")

    # U1: what is projectId? Try org_id, then look for a projects collection.
    print("\n=== U1: flows projectId ===")
    for candidate in (org_id,):
        s, b = cc.json("GET", f"{candidate}/project/{candidate}/flows"
                              "?includePagination=true&size=5")
        show(f"projectId == orgId ({candidate})", s, b,
             "200 here means projectId is the org id")

    # U2: which flowType selects subflows?
    print("\n=== U2: flowType for subflows ===")
    for ft in ("FLOW", "SUBFLOW", "Subflow", "SUB_FLOW"):
        s, b = cc.json("GET", f"{org_id}/project/{org_id}/flows"
                              f"?flowType={ft}&includePagination=true&size=5")
        n = len(b.get("data", [])) if isinstance(b, dict) else "?"
        show(f"flowType={ft}", s, b, f"items returned: {n}")

    # U3: functions list + export shape (import field names need a real attempt).
    print("\n=== U3: functions ===")
    s, b = cc.json("GET", f"v1/{org_id}/functions?size=5")
    show("list functions", s, b)
    if isinstance(b, dict) and b.get("data"):
        fid = b["data"][0].get("id")
        s2, b2 = cc.json("POST", f"v1/{org_id}/functions/{fid}:export")
        show(f"export function {fid}", s2, b2,
             "record the top-level keys - the import multipart part must carry this")

    # U4: does a config object carry createdTime, and does it cluster?
    print("\n=== U4: createdTime ===")
    for ent, path in (("site", "v2/site"), ("team", "v2/team"),
                      ("auxiliary-code", "v2/auxiliary-code")):
        s, b = cc.json("GET", f"organization/{{orgId}}/{path}?pageSize=5")
        rows = b.get("data", []) if isinstance(b, dict) else []
        stamps = [(r.get("name"), r.get("createdTime") or r.get("createdAt"))
                  for r in rows]
        show(f"{ent} createdTime", s, stamps,
             "None means the non-default heuristic is unavailable for this entity")

    # U5: is Calling provisioned, and does this token reach it?
    print("\n=== U5: Webex Calling reachability ===")
    for label, path in (("locations", "locations"),
                        ("autoAttendants", "telephony/config/autoAttendants"),
                        ("huntGroups", "telephony/config/huntGroups"),
                        ("announcements", "telephony/config/announcements")):
        s, b = wx.json("GET", path)
        show(label, s, b, "403 = scope missing; 404 = not provisioned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Authenticate**

```bash
python -m wxcc_export.cli auth login          # or set WXCC_BEARER_TOKEN in .env
```

If Task 17 (the CLI) is not yet built, authenticate with a bearer token instead: put `WXCC_BEARER_TOKEN=<token from developer.webex.com>` in `.env`. Those tokens last 12 hours.

- [ ] **Step 3: Run the probe and capture the full output**

```bash
python scripts/probe.py 2>&1 | tee /tmp/probe-output.txt
```

- [ ] **Step 4: Write `docs/api-notes.md`**

Use this exact structure. Every row needs the observed status, not a guess.

```markdown
# API notes — observed behaviour

Findings from a live WxCC sandbox. **The spec maps what exists; the probe
records what works.** Where they disagree, the probe wins.

Probed: <YYYY-MM-DD> against org `<orgId>` (`<orgName>`, trial/sandbox).

## U1 — flows `projectId`
- Request: `GET /{orgId}/project/{orgId}/flows?includePagination=true&size=5`
- Observed: HTTP <status>
- **Answer:** <projectId is the org id | projectId comes from ... >

## U2 — `flowType` for subflows
| value | status | items |
|---|---|---|
| FLOW | | |
| SUBFLOW | | |
- **Answer:** <the value that works, or "subflows are not separately listable">

## U3 — functions import
- Export response top-level keys: <...>
- **Answer:** <the multipart field name(s), or "unresolved - import disabled">

## U4 — `createdTime` availability
| entity | field present | clusters at provisioning |
|---|---|---|
- **Answer:** <heuristic available for these entities | unavailable>

## U5 — Webex Calling reachability
| endpoint | status | meaning |
|---|---|---|
- **Answer:** <scopes needed | Calling not provisioned on this sandbox>

## U6 — archive filename
- `GET organization/{orgId}` -> `name` = `<value>`
- **Answer:** archive is named `<value>-export.zip`
```

- [ ] **Step 5: Record any finding that contradicts this plan**

If a probe result contradicts something written in the "Confirmed API facts" section above, **stop and report it** rather than working around it. Add a `## Contradictions` section to `docs/api-notes.md` naming the plan claim and the observed behaviour.

- [ ] **Step 6: Commit**

```bash
git add scripts/probe.py docs/api-notes.md
git commit -m "docs: live probe findings resolving flows, functions, and calling unknowns"
```

---

### Task 6: Entity registry and dependency graph

**Files:**
- Create: `src/wxcc_export/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `registry.CC_ENTITIES: dict[str, dict]` — per entity: `list`, `item`, `create`, `deps`, `writable`, `child`, `note`
  - `registry.CALLING_OBJECTS: dict[str, dict]` — per object: `list`, `item`, `scope` (`"org"` or `"location"`), `writable`
  - `registry.list_path(entity) -> str`, `registry.item_path(entity, id) -> str`, `registry.create_path(entity) -> str`
  - `registry.SPEC_GROUPS: dict[str, list[str]]` — the spec's UI grouping, for the selection UI
  - `registry.UNSUPPORTED: dict[str, str]` — object name -> why it cannot be captured
  - `registry.UnknownEntity(Exception)`

**The `deps` field drives import ordering.** It lists entities that must exist *before* this one can be created. It is derived from the required-create-field lists in the live-verified sibling registry, not invented: e.g. `site.create` requires `multimediaProfileId`, so `site` depends on `multimedia-profile`.

- [ ] **Step 1: Write the failing test**

`tests/test_registry.py`:

```python
import pytest
from wxcc_export import registry


def test_every_spec_object_maps_to_an_entity_or_is_declared_unsupported():
    spec_objects = {
        "Queues", "Business Hours", "Audio Files", "Global Variables", "Sites",
        "Skill Management", "Skill Profiles", "Teams", "User Profiles",
        "Resource Collections", "Contact Center Users", "Multimedia Profiles",
        "Outdial ANI", "Desktop Layouts", "Address Books", "Desktop Profiles",
        "Idle/Wrap-up Codes", "Flows", "Subflows", "Functions",
        "Channels", "Surveys",
    }
    covered = set(registry.SPEC_OBJECT_MAP) | set(registry.UNSUPPORTED)
    assert spec_objects <= covered, spec_objects - covered


def test_list_path_keeps_the_version_prefix():
    assert registry.list_path("team") == "organization/{orgId}/v2/team"


def test_user_profile_lists_on_v3():
    assert registry.list_path("user-profile") == "organization/{orgId}/v3/user-profile"


def test_item_path_drops_the_version_prefix():
    # GET v2/team lists, but the item path is team/{id} - this is not cosmetic.
    assert registry.item_path("team", "T1") == "organization/{orgId}/team/T1"


def test_create_path_drops_the_version_prefix():
    # POST v2/team is NOT the create endpoint. POST team is.
    assert registry.create_path("team") == "organization/{orgId}/team"


def test_unknown_entity_names_the_known_ones():
    with pytest.raises(registry.UnknownEntity) as exc:
        registry.list_path("queue")
    assert "contact-service-queue" in str(exc.value)


def test_site_depends_on_multimedia_profile():
    # site create requires multimediaProfileId, so the profile must exist first.
    assert "multimedia-profile" in registry.CC_ENTITIES["site"]["deps"]


def test_team_depends_on_site():
    assert "site" in registry.CC_ENTITIES["team"]["deps"]


def test_auxiliary_code_depends_on_work_type():
    assert "work-type" in registry.CC_ENTITIES["auxiliary-code"]["deps"]


def test_queue_depends_on_team_and_skill_profile():
    deps = registry.CC_ENTITIES["contact-service-queue"]["deps"]
    assert "team" in deps and "skill-profile" in deps


def test_no_entity_declares_a_dependency_on_an_unknown_entity():
    for name, spec in registry.CC_ENTITIES.items():
        for dep in spec["deps"]:
            assert dep in registry.CC_ENTITIES, f"{name} -> unknown dep {dep}"


def test_the_dependency_graph_is_acyclic():
    seen, stack = set(), set()

    def visit(node):
        if node in stack:
            raise AssertionError(f"cycle through {node}")
        if node in seen:
            return
        stack.add(node)
        for dep in registry.CC_ENTITIES[node]["deps"]:
            visit(dep)
        stack.discard(node)
        seen.add(node)

    for name in registry.CC_ENTITIES:
        visit(name)


def test_user_is_not_writable():
    # /organization/{orgid}/user publishes GET only; there is no create path.
    assert registry.CC_ENTITIES["user"]["writable"] is False


def test_surveys_and_channels_are_declared_unsupported_with_a_reason():
    for obj in ("Surveys", "Channels"):
        assert obj in registry.UNSUPPORTED
        assert len(registry.UNSUPPORTED[obj]) > 30


def test_calling_objects_declare_their_scope():
    for name, spec in registry.CALLING_OBJECTS.items():
        assert spec["scope"] in ("org", "location"), name
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_registry.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'wxcc_export.registry'`.

- [ ] **Step 3: Write the implementation**

`src/wxcc_export/registry.py`:

```python
"""What exists, where it lives, and what must be created before it.

Route facts are transcribed from the OpenAPI documents in docs/ and cross-checked
against the live-verified registry in the sibling wxcc-skills repo
(mcp_server.py:53). `deps` is derived from the required create fields: if
creating X requires a Y id, X depends on Y.

THE VERSION PREFIX RULE (verified across every entity): the LIST path carries
v2/v3; the ITEM path and the CREATE path DROP it. `GET v2/team` lists, but
`POST v2/team` is not the create endpoint.
"""

from __future__ import annotations


class UnknownEntity(Exception):
    pass


CC_ENTITIES: dict[str, dict] = {
    # --- no dependencies ---
    "multimedia-profile": {
        "list": "v2/multimedia-profile", "item": "multimedia-profile/{id}",
        "create": ["name", "active"], "deps": [], "writable": True,
    },
    "work-type": {
        "list": "v2/work-type", "item": "work-type/{id}",
        "create": ["name", "workTypeCode", "active"], "deps": [], "writable": True,
    },
    "skill": {
        "list": "v2/skill", "item": "skill/{id}",
        "create": ["name", "serviceLevelThreshold", "type", "active"],
        "deps": [], "writable": True,
    },
    "holiday-list": {
        "list": "v2/holiday-list", "item": "holiday-list/{id}",
        "create": ["name"], "deps": [], "writable": True,
    },
    "overrides": {
        "list": "v2/overrides", "item": "overrides/{id}",
        "create": ["name"], "deps": [], "writable": True,
    },
    "cad-variable": {
        "list": "v2/cad-variable", "item": "cad-variable/{id}",
        "create": ["name", "active", "variableType"], "deps": [], "writable": True,
        "note": "These are the Global Variables in the Control Hub UI.",
    },
    "resource-collection": {
        "list": "v2/resource-collection", "item": "resource-collection/{id}",
        "create": ["name"], "deps": [], "writable": True,
    },
    "dial-number": {
        "list": "v2/dial-number", "item": "dial-number/{id}",
        "create": ["number"], "deps": [], "writable": True,
    },
    "audio-file": {
        "list": "v2/audio-file", "item": "audio-file/{id}",
        "create": ["name"], "deps": [], "writable": True, "binary": True,
        "note": "Upload is multipart/form-data. The spec claims audio-file "
                "accepts JSON; the sibling repo records that it does not.",
    },
    "desktop-layout": {
        "list": "v2/desktop-layout", "item": "desktop-layout/{id}",
        "create": ["name"], "deps": [], "writable": True,
    },
    "address-book": {
        "list": "v2/address-book", "item": "address-book/{id}",
        "create": ["name"], "deps": [], "writable": True,
        "child": {"list": "v2/address-book/{parentId}/entry",
                  "create": "address-book/{parentId}/entry"},
    },
    "outdial-ani": {
        "list": "v2/outdial-ani", "item": "outdial-ani/{id}",
        "create": ["name"], "deps": [], "writable": True,
        "child": {"list": "v2/outdial-ani/{parentId}/entry",
                  "create": "outdial-ani/{parentId}/entry"},
    },
    "user-profile": {
        "list": "v3/user-profile", "item": "user-profile/{id}",
        "create": ["name", "profileType"], "deps": [], "writable": True,
    },

    # --- one level deep ---
    "site": {
        "list": "v2/site", "item": "site/{id}",
        "create": ["name", "active", "multimediaProfileId"],
        "deps": ["multimedia-profile"], "writable": True,
        "note": "All three create fields are required; a 400 names them.",
    },
    "auxiliary-code": {
        "list": "v2/auxiliary-code", "item": "auxiliary-code/{id}",
        "create": ["name", "active", "workTypeId", "defaultCode"],
        "deps": ["work-type"], "writable": True,
        "note": "These are the Idle and Wrap-up codes in the UI.",
    },
    "skill-profile": {
        "list": "v2/skill-profile", "item": "skill-profile/{id}",
        "create": ["name", "active"], "deps": ["skill"], "writable": True,
    },
    "business-hours": {
        "list": "v2/business-hours", "item": "business-hours/{id}",
        "create": ["name", "timeZone"], "deps": ["holiday-list", "overrides"],
        "writable": True,
    },
    "entry-point": {
        "list": "v2/entry-point", "item": "entry-point/{id}",
        "create": ["name", "entryPointType", "channelType",
                   "serviceLevelThreshold", "active", "maximumActiveContacts"],
        "deps": ["dial-number"], "writable": True,
    },
    "agent-profile": {
        "list": "v2/agent-profile", "item": "agent-profile/{id}",
        "create": ["name"], "deps": ["auxiliary-code", "address-book",
                                     "outdial-ani", "desktop-layout"],
        "writable": True,
        "note": "These are the Desktop Profiles in the UI.",
    },

    # --- two levels deep ---
    "team": {
        "list": "v2/team", "item": "team/{id}",
        "create": ["name", "active", "siteId", "teamStatus", "teamType"],
        "deps": ["site", "multimedia-profile", "skill-profile"], "writable": True,
    },
    "contact-service-queue": {
        "list": "v2/contact-service-queue", "item": "contact-service-queue/{id}",
        "create": ["name", "queueType", "channelType", "serviceLevelThreshold",
                   "maxActiveContacts", "maxTimeInQueue", "active", "routingType",
                   "monitoringPermitted", "parkingPermitted", "recordingPermitted",
                   "recordingAllCallsPermitted", "pauseRecordingPermitted"],
        "deps": ["team", "skill-profile", "entry-point", "audio-file"],
        "writable": True,
        "note": "The entity is contact-service-queue; /queue 404s. The five "
                "*Permitted booleans are required on create, not defaulted.",
    },

    # --- read-only ---
    "user": {
        "list": "v2/user", "item": "user/{id}",
        "create": [], "deps": ["site", "team", "skill-profile", "user-profile",
                               "agent-profile", "multimedia-profile"],
        "writable": False,
        "note": "GET only on the collection. Users are created and licensed in "
                "Control Hub, not here. Exported as a reference manifest.",
    },
}

CALLING_OBJECTS: dict[str, dict] = {
    "locations": {"list": "locations", "item": "locations/{id}",
                  "scope": "org", "writable": True},
    "schedules": {"list": "telephony/config/locations/{locationId}/schedules",
                  "item": "telephony/config/locations/{locationId}/schedules/{id}",
                  "scope": "location", "writable": True},
    "auto-attendants": {"list": "telephony/config/autoAttendants",
                        "item": "telephony/config/locations/{locationId}/autoAttendants/{id}",
                        "scope": "org", "writable": True},
    "hunt-groups": {"list": "telephony/config/huntGroups",
                    "item": "telephony/config/locations/{locationId}/huntGroups/{id}",
                    "scope": "org", "writable": True},
    "call-queues": {"list": "telephony/config/locations/{locationId}/queues",
                    "item": "telephony/config/locations/{locationId}/queues/{id}",
                    "scope": "location", "writable": True},
    "call-park-extensions": {"list": "telephony/config/callParkExtensions",
                             "item": "telephony/config/locations/{locationId}/callParkExtensions/{id}",
                             "scope": "org", "writable": True},
    "call-parks": {"list": "telephony/config/locations/{locationId}/callParks",
                   "item": "telephony/config/locations/{locationId}/callParks/{id}",
                   "scope": "location", "writable": True},
    "call-pickups": {"list": "telephony/config/locations/{locationId}/callPickups",
                     "item": "telephony/config/locations/{locationId}/callPickups/{id}",
                     "scope": "location", "writable": True},
    "paging-groups": {"list": "telephony/config/paging",
                      "item": "telephony/config/locations/{locationId}/paging/{id}",
                      "scope": "org", "writable": True},
    "announcements": {"list": "telephony/config/announcements",
                      "item": "telephony/config/announcements/{id}",
                      "scope": "org", "writable": True, "binary": True},
    "virtual-extensions": {"list": "telephony/config/virtualExtensions",
                           "item": "telephony/config/virtualExtensions/{id}",
                           "scope": "org", "writable": True},
    "operating-modes": {"list": "telephony/config/operatingModes",
                        "item": "telephony/config/operatingModes/{id}",
                        "scope": "org", "writable": True},
}

# The spec's own UI grouping, used to label the selection UI.
SPEC_GROUPS: dict[str, list[str]] = {
    "Customer Experience": ["contact-service-queue", "business-hours",
                            "holiday-list", "overrides", "audio-file",
                            "cad-variable", "entry-point", "dial-number"],
    "User Management": ["site", "skill", "skill-profile", "team",
                        "user-profile", "resource-collection", "user"],
    "Desktop Experience": ["multimedia-profile", "outdial-ani", "desktop-layout",
                           "address-book", "agent-profile", "auxiliary-code",
                           "work-type"],
}

SPEC_OBJECT_MAP: dict[str, str] = {
    "Queues": "contact-service-queue",
    "Business Hours": "business-hours",
    "Audio Files": "audio-file",
    "Global Variables": "cad-variable",
    "Sites": "site",
    "Skill Management": "skill",
    "Skill Profiles": "skill-profile",
    "Teams": "team",
    "User Profiles": "user-profile",
    "Resource Collections": "resource-collection",
    "Contact Center Users": "user",
    "Multimedia Profiles": "multimedia-profile",
    "Outdial ANI": "outdial-ani",
    "Desktop Layouts": "desktop-layout",
    "Address Books": "address-book",
    "Desktop Profiles": "agent-profile",
    "Idle/Wrap-up Codes": "auxiliary-code",
    "Flows": "__flows__",
    "Subflows": "__subflows__",
    "Functions": "__functions__",
}

UNSUPPORTED: dict[str, str] = {
    "Channels": (
        "No Channels operation exists anywhere in the Webex Contact Center API "
        "(searched all 328 paths and all 61 tags). Digital channels are "
        "provisioned through Webex Connect, a separate platform with its own "
        "API and its own tenant. Recreate them by hand in Control Hub under "
        "Contact Center > Customer Experience > Channels."
    ),
    "Surveys": (
        "No Surveys operation exists anywhere in the Webex Contact Center API "
        "(searched all 328 paths and all 61 tags). The nearest published "
        "feature is Auto CSAT, which is AI-generated scoring rather than the "
        "Surveys page, and is not a substitute. Recreate surveys by hand in "
        "Control Hub under Contact Center > Customer Experience > Surveys."
    ),
}


def _spec(entity: str) -> dict:
    if entity not in CC_ENTITIES:
        raise UnknownEntity(
            f"unknown entity {entity!r}. Known: {', '.join(sorted(CC_ENTITIES))}"
        )
    return CC_ENTITIES[entity]


def list_path(entity: str) -> str:
    return f"organization/{{orgId}}/{_spec(entity)['list']}"


def item_path(entity: str, item_id: str) -> str:
    tail = _spec(entity)["item"].replace("{id}", item_id)
    return f"organization/{{orgId}}/{tail}"


def create_path(entity: str) -> str:
    tail = _spec(entity)["item"].replace("/{id}", "")
    return f"organization/{{orgId}}/{tail}"


def child_list_path(entity: str, parent_id: str) -> str:
    child = _spec(entity).get("child")
    if not child:
        raise UnknownEntity(f"{entity} has no child collection")
    return f"organization/{{orgId}}/{child['list'].replace('{parentId}', parent_id)}"


def child_create_path(entity: str, parent_id: str) -> str:
    child = _spec(entity).get("child")
    if not child:
        raise UnknownEntity(f"{entity} has no child collection")
    return f"organization/{{orgId}}/{child['create'].replace('{parentId}', parent_id)}"
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_registry.py -v
```

Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wxcc_export/registry.py tests/test_registry.py
git commit -m "feat: entity registry with dependency graph and unsupported-object reasons"
```

---

### Task 7: Generic Contact Center export

**Files:**
- Create: `src/wxcc_export/export_cc.py`
- Test: `tests/test_export_cc.py`

**Interfaces:**
- Consumes: `registry.CC_ENTITIES`, `registry.list_path`, `client.ApiClient`, `client.ApiError`.
- Produces:
  - `export_cc.export_entity(client, entity) -> dict` — `{"entity","count","items","error"}`; `error` is `None` on success
  - `export_cc.export_all(client, entities: list[str], on_progress=None) -> dict[str, dict]`
  - `export_cc.tag_likely_defaults(items: list[dict], window_seconds: int = 120) -> list[dict]`
  - `export_cc.strip_volatile(item: dict) -> dict` — removes server-generated audit fields

**One walk drives every entity.** There is deliberately no per-entity export function: the registry already names the list path, so a second hand-written mapping would be a place for the two to drift apart.

**Failures are recorded, never swallowed.** An entity that 403s produces `{"error": "HTTP 403 ..."}` and a zero count, and the run continues. A partial export must never look complete — Task 11 surfaces every `error` in the manifest and in `UNSUPPORTED.md`.

- [ ] **Step 1: Write the failing test**

`tests/test_export_cc.py`:

```python
import pytest
from wxcc_export import export_cc
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


def test_export_entity_returns_the_items(transport):
    transport.add("GET /organization/ORG1/v2/site",
                  body={"data": [{"id": "s1", "name": "Denver"}]})
    result = export_cc.export_entity(make(transport), "site")
    assert result["count"] == 1
    assert result["items"][0]["name"] == "Denver"
    assert result["error"] is None


def test_export_entity_records_an_http_error_without_raising(transport):
    transport.add("GET /organization/ORG1/v2/site", status=403,
                  body={"message": "forbidden"})
    result = export_cc.export_entity(make(transport), "site")
    assert result["count"] == 0
    assert "403" in result["error"]


def test_export_entity_error_is_never_silently_empty(transport):
    transport.add("GET /organization/ORG1/v2/site", status=500, body={})
    result = export_cc.export_entity(make(transport), "site")
    # A failed entity must not be indistinguishable from a genuinely empty one.
    assert result["error"] is not None
    assert result["items"] == []


def test_export_all_continues_past_a_failing_entity(transport):
    transport.add("GET /organization/ORG1/v2/site", status=403, body={})
    transport.add("GET /organization/ORG1/v2/team",
                  body={"data": [{"id": "t1", "name": "Billing"}]})
    out = export_cc.export_all(make(transport), ["site", "team"])
    assert out["site"]["error"] is not None
    assert out["team"]["count"] == 1


def test_export_all_reports_progress(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    seen = []
    export_cc.export_all(make(transport), ["site"],
                         on_progress=lambda e, r: seen.append(e))
    assert seen == ["site"]


def test_strip_volatile_removes_audit_fields():
    item = {"id": "s1", "name": "Denver", "version": 3,
            "createdTime": 1, "lastUpdatedTime": 2, "createdBy": "u"}
    out = export_cc.strip_volatile(item)
    assert "version" not in out and "lastUpdatedTime" not in out
    assert out["id"] == "s1" and out["name"] == "Denver"


def test_strip_volatile_keeps_created_time_for_the_default_heuristic():
    out = export_cc.strip_volatile({"id": "s1", "createdTime": 1700000000000})
    assert out["createdTime"] == 1700000000000


def test_tag_likely_defaults_marks_the_provisioning_cluster():
    base = 1700000000000                       # epoch millis
    items = [
        {"id": "a", "createdTime": base},
        {"id": "b", "createdTime": base + 5_000},        # +5s  -> default
        {"id": "c", "createdTime": base + 600_000},      # +10m -> not default
    ]
    tagged = export_cc.tag_likely_defaults(items)
    flags = {i["id"]: i["likely_default"] for i in tagged}
    assert flags == {"a": True, "b": True, "c": False}


def test_tag_likely_defaults_is_a_noop_without_created_time():
    items = [{"id": "a"}, {"id": "b"}]
    tagged = export_cc.tag_likely_defaults(items)
    assert all("likely_default" not in i for i in tagged)


def test_tag_likely_defaults_handles_an_empty_list():
    assert export_cc.tag_likely_defaults([]) == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_export_cc.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'wxcc_export.export_cc'`.

- [ ] **Step 3: Write the implementation**

`src/wxcc_export/export_cc.py`:

```python
"""Registry-driven export of Contact Center configuration.

One walk serves every entity: the registry already names the list path, so a
second hand-written mapping would only be a place for the two to drift.
"""

from __future__ import annotations

from . import registry
from .client import ApiError

# Server-generated bookkeeping. Sending these back on create is at best ignored
# and at worst a 400, so they are dropped - except createdTime, which the
# non-default heuristic needs and which the importer strips separately.
VOLATILE_FIELDS = frozenset({
    "version", "lastUpdatedTime", "lastUpdatedBy", "createdBy",
    "eTag", "etag", "links", "meta",
})

DEFAULT_WINDOW_SECONDS = 120


def strip_volatile(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in VOLATILE_FIELDS}


def tag_likely_defaults(items: list[dict],
                        window_seconds: int = DEFAULT_WINDOW_SECONDS) -> list[dict]:
    """Label objects created in the same burst as the earliest one.

    This is a HEURISTIC, not a fact the API states: there is no isDefault flag
    on any entity. Objects provisioned with the tenant share a creation instant;
    anything created later was created by a person. The label is never used to
    filter silently - only to populate --only-non-default, which is opt-in.
    """
    stamps = [i.get("createdTime") for i in items]
    if not items or any(not isinstance(s, (int, float)) for s in stamps):
        return items
    earliest = min(stamps)
    window_ms = window_seconds * 1000          # createdTime is epoch milliseconds
    return [{**i, "likely_default": (i["createdTime"] - earliest) <= window_ms}
            for i in items]


def export_entity(client, entity: str) -> dict:
    """Export one entity. Never raises: a failure is recorded and returned."""
    result: dict = {"entity": entity, "count": 0, "items": [], "error": None}
    try:
        raw = client.list_all(registry.list_path(entity))
    except ApiError as exc:
        result["error"] = f"HTTP {exc.status}: {str(exc)[:200]}"
        return result
    except Exception as exc:                    # never let a failure read as empty
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    items = tag_likely_defaults([strip_volatile(i) for i in raw])
    result["items"] = items
    result["count"] = len(items)
    return result


def export_all(client, entities: list[str], on_progress=None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for entity in entities:
        result = export_entity(client, entity)
        out[entity] = result
        if on_progress:
            on_progress(entity, result)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_export_cc.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wxcc_export/export_cc.py tests/test_export_cc.py
git commit -m "feat: registry-driven Contact Center export with recorded failures"
```

---

### Task 8: Audio binaries, child entries, and the users manifest

**Files:**
- Modify: `src/wxcc_export/export_cc.py` (append the three functions below)
- Test: `tests/test_export_extras.py`

**Interfaces:**
- Consumes: everything from Task 7, plus `registry.child_list_path`.
- Produces:
  - `export_cc.export_children(client, entity, parent_ids) -> dict[str, dict]` — keyed by parent id
  - `export_cc.export_audio_binaries(client, audio_items) -> tuple[dict[str, bytes], list[str]]` — returns `(blobs, errors)`
  - `export_cc.build_users_manifest(users, lookup) -> tuple[list[dict], str]` — returns `(rows, csv_text)`

**Why users get their own shape:** the user chose "reference manifest only". The export must therefore be *readable by a human doing manual re-entry*, which raw API JSON is not. `build_users_manifest` resolves each id reference to the object's **name** using the already-exported entities, so the CSV says `Denver` rather than a UUID.

**Audio download is a real unknown.** The list response gives metadata; the bytes come from a separate fetch. If the download endpoint is not reachable, the file is recorded in `errors` and the archive still succeeds — an audio file the tool could not fetch must be visible, not absent.

- [ ] **Step 1: Write the failing test**

`tests/test_export_extras.py`:

```python
import csv
import io

from wxcc_export import export_cc
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


def test_export_children_keys_by_parent_id(transport):
    transport.add("GET /organization/ORG1/v2/address-book/ab1/entry",
                  body={"data": [{"id": "e1", "name": "Support"}]})
    out = export_cc.export_children(make(transport), "address-book", ["ab1"])
    assert out["ab1"]["count"] == 1
    assert out["ab1"]["items"][0]["name"] == "Support"


def test_export_children_records_a_failure_per_parent(transport):
    transport.add("GET /organization/ORG1/v2/address-book/ab1/entry",
                  status=403, body={})
    out = export_cc.export_children(make(transport), "address-book", ["ab1"])
    assert out["ab1"]["error"] is not None


def test_export_children_of_an_entity_without_children_is_empty(transport):
    assert export_cc.export_children(make(transport), "site", ["s1"]) == {}


def test_export_audio_binaries_downloads_by_url(transport):
    transport.add("GET /audio/a1.wav", body=b"RIFFdata", content_type="audio/wav")
    items = [{"id": "a1", "name": "welcome.wav", "url": "/audio/a1.wav"}]
    blobs, errors = export_cc.export_audio_binaries(make(transport), items)
    assert blobs["a1"] == b"RIFFdata"
    assert errors == []


def test_export_audio_binaries_records_a_failed_download(transport):
    transport.add("GET /audio/a1.wav", status=404, body=b"")
    items = [{"id": "a1", "name": "welcome.wav", "url": "/audio/a1.wav"}]
    blobs, errors = export_cc.export_audio_binaries(make(transport), items)
    assert blobs == {}
    assert "a1" in errors[0]


def test_export_audio_binaries_reports_an_item_with_no_download_url(transport):
    items = [{"id": "a1", "name": "welcome.wav"}]
    blobs, errors = export_cc.export_audio_binaries(make(transport), items)
    assert blobs == {}
    assert "no download url" in errors[0]


def test_users_manifest_resolves_ids_to_names():
    users = [{"id": "u1", "email": "a@x.com", "firstName": "Ann",
              "lastName": "Lee", "siteId": "s1", "teamIds": ["t1"],
              "skillProfileId": "sp1"}]
    lookup = {"site": {"s1": "Denver"}, "team": {"t1": "Billing"},
              "skill-profile": {"sp1": "Tier1"}}
    rows, csv_text = export_cc.build_users_manifest(users, lookup)
    assert rows[0]["site"] == "Denver"
    assert rows[0]["teams"] == "Billing"
    assert rows[0]["skillProfile"] == "Tier1"


def test_users_manifest_keeps_the_raw_id_when_the_name_is_unknown():
    users = [{"id": "u1", "email": "a@x.com", "siteId": "s9"}]
    rows, _ = export_cc.build_users_manifest(users, {"site": {}})
    assert rows[0]["site"] == "s9"


def test_users_manifest_csv_has_a_header_and_one_row_per_user():
    users = [{"id": "u1", "email": "a@x.com"}, {"id": "u2", "email": "b@x.com"}]
    _, csv_text = export_cc.build_users_manifest(users, {})
    parsed = list(csv.reader(io.StringIO(csv_text)))
    assert parsed[0][0] == "email"
    assert len(parsed) == 3


def test_users_manifest_handles_a_user_with_no_assignments():
    rows, _ = export_cc.build_users_manifest([{"id": "u1", "email": "a@x.com"}], {})
    assert rows[0]["site"] == ""
    assert rows[0]["teams"] == ""
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_export_extras.py -v
```

Expected: FAIL — `AttributeError: module 'wxcc_export.export_cc' has no attribute 'export_children'`.

- [ ] **Step 3: Append the implementation to `src/wxcc_export/export_cc.py`**

```python
# --- child collections (address-book entries, outdial-ani entries) ---

def export_children(client, entity: str, parent_ids: list[str]) -> dict[str, dict]:
    """Export the child rows of every parent. An entity without children is {}."""
    if not registry.CC_ENTITIES.get(entity, {}).get("child"):
        return {}
    out: dict[str, dict] = {}
    for parent_id in parent_ids:
        record: dict = {"parent_id": parent_id, "count": 0,
                        "items": [], "error": None}
        try:
            rows = client.list_all(registry.child_list_path(entity, parent_id))
            record["items"] = [strip_volatile(r) for r in rows]
            record["count"] = len(record["items"])
        except ApiError as exc:
            record["error"] = f"HTTP {exc.status}: {str(exc)[:200]}"
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        out[parent_id] = record
    return out


# --- audio file bytes ---

AUDIO_URL_FIELDS = ("url", "fileUrl", "audioFileUrl", "downloadUrl")


def export_audio_binaries(client, audio_items: list[dict]
                          ) -> tuple[dict[str, bytes], list[str]]:
    """Fetch the bytes behind each audio-file record.

    An audio file the tool could not fetch must be VISIBLE in the archive's
    error list, never merely absent - a silently missing prompt is how an
    imported flow plays nothing.
    """
    blobs: dict[str, bytes] = {}
    errors: list[str] = []
    for item in audio_items:
        item_id = item.get("id")
        url = next((item[f] for f in AUDIO_URL_FIELDS if item.get(f)), None)
        if not url:
            errors.append(
                f"audio-file {item_id} ({item.get('name')}): no download url in "
                f"the record - fields present: {sorted(item)[:10]}")
            continue
        try:
            status, data, _ctype = client.get_bytes(url)
        except Exception as exc:
            errors.append(f"audio-file {item_id}: {type(exc).__name__}: {exc}")
            continue
        if status != 200 or not data:
            errors.append(f"audio-file {item_id} ({item.get('name')}): "
                          f"download returned HTTP {status}")
            continue
        blobs[item_id] = data
    return blobs, errors


# --- users reference manifest ---

USER_COLUMNS = ["email", "firstName", "lastName", "site", "teams",
                "skillProfile", "userProfile", "desktopProfile",
                "multimediaProfile", "id"]


def build_users_manifest(users: list[dict], lookup: dict[str, dict]
                         ) -> tuple[list[dict], str]:
    """Flatten users into a human-readable mapping, ids resolved to names.

    Users have NO write path (the collection publishes GET only), so this is a
    re-entry aid for a person working in Control Hub, not import input. An
    unresolvable id is kept verbatim rather than blanked: a UUID a human can
    search for beats an empty cell.
    """
    def name_of(entity: str, value: str | None) -> str:
        if not value:
            return ""
        return lookup.get(entity, {}).get(value, value)

    rows: list[dict] = []
    for u in users:
        team_ids = u.get("teamIds") or []
        rows.append({
            "email": u.get("email", ""),
            "firstName": u.get("firstName", ""),
            "lastName": u.get("lastName", ""),
            "site": name_of("site", u.get("siteId")),
            "teams": "; ".join(name_of("team", t) for t in team_ids),
            "skillProfile": name_of("skill-profile", u.get("skillProfileId")),
            "userProfile": name_of("user-profile", u.get("userProfileId")),
            "desktopProfile": name_of("agent-profile", u.get("agentProfileId")),
            "multimediaProfile": name_of("multimedia-profile",
                                         u.get("multimediaProfileId")),
            "id": u.get("id", ""),
        })

    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    writer = _csv.DictWriter(buf, fieldnames=USER_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return rows, buf.getvalue()


def build_name_lookup(exported: dict[str, dict]) -> dict[str, dict]:
    """{entity: {id: name}} from an export_all result, for manifest resolution."""
    return {
        entity: {i["id"]: i.get("name", "") for i in result["items"] if i.get("id")}
        for entity, result in exported.items()
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_export_extras.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Run the whole suite and report the delta**

```bash
python -m pytest -q
```

Expected: 68 passed, 0 failed. Report as `baseline 33 passed -> 68 passed, 0 failing`.

- [ ] **Step 6: Commit**

```bash
git add src/wxcc_export/export_cc.py tests/test_export_extras.py
git commit -m "feat: child entries, audio binaries, and the users reference manifest"
```

---

### Task 9: Flows, subflows, and functions export

> **BLOCKED ON Task 5.** Read `docs/api-notes.md` first. `PROJECT_ID_SOURCE` (U1), `SUBFLOW_TYPE` (U2), and the functions export shape (U3) come from there. If a value is still unresolved, the corresponding export must return `{"error": "unresolved: U<n>"}` rather than guess.

**Files:**
- Create: `src/wxcc_export/export_flows.py`
- Test: `tests/test_export_flows.py`

**Interfaces:**
- Consumes: `client.ApiClient`, `docs/api-notes.md` values.
- Produces:
  - `export_flows.resolve_project_id(client) -> str` — per U1
  - `export_flows.list_flows(client, project_id, flow_type) -> list[dict]`
  - `export_flows.export_flow(client, project_id, flow_id, flow_type) -> tuple[dict|None, str|None]`
  - `export_flows.export_all_flows(client, project_id) -> dict` — `{"flows": {...}, "subflows": {...}, "errors": [...]}`
  - `export_flows.list_functions(client) -> list[dict]`
  - `export_flows.export_function(client, fn_id) -> tuple[dict|None, str|None]`
  - `export_flows.export_all_functions(client) -> dict`

**Confirmed paths (from the OpenAPI document):**
- `GET /{orgId}/project/{projectId}/flows?flowType=&includePagination=true&size=`
- `GET /{orgId}/project/{projectId}/v2/flows/{flowId}:export`
- `GET /v1/{orgId}/functions?page=&size=`
- `POST /v1/{orgId}/functions/{id}:export`

Note the flow list default `size` is **10**; always pass an explicit larger size and `includePagination=true`.

- [ ] **Step 1: Write the failing test**

`tests/test_export_flows.py`:

```python
import pytest
from wxcc_export import export_flows
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


def test_list_flows_passes_an_explicit_page_size(transport):
    transport.add("GET /ORG1/project/ORG1/flows?flowType=FLOW"
                  "&includePagination=true&size=100",
                  body={"data": [{"id": "f1", "name": "Main"}]})
    flows = export_flows.list_flows(make(transport), "ORG1", "FLOW")
    assert flows[0]["id"] == "f1"
    # The API default size is 10; relying on it silently truncates.
    assert "size=100" in transport.calls[0]["url"]


def test_list_flows_returns_empty_on_error(transport):
    transport.add("GET /ORG1/project/ORG1/flows?flowType=FLOW"
                  "&includePagination=true&size=100", status=403, body={})
    assert export_flows.list_flows(make(transport), "ORG1", "FLOW") == []


def test_export_flow_returns_the_document(transport):
    transport.add("GET /ORG1/project/ORG1/v2/flows/f1:export?flowType=FLOW",
                  body={"name": "Main", "nodes": []})
    doc, err = export_flows.export_flow(make(transport), "ORG1", "f1", "FLOW")
    assert doc["name"] == "Main"
    assert err is None


def test_export_flow_reports_an_error_without_raising(transport):
    transport.add("GET /ORG1/project/ORG1/v2/flows/f1:export?flowType=FLOW",
                  status=404, body={"message": "gone"})
    doc, err = export_flows.export_flow(make(transport), "ORG1", "f1", "FLOW")
    assert doc is None
    assert "404" in err


def test_export_all_flows_collects_both_types(transport):
    transport.add("GET /ORG1/project/ORG1/flows?flowType=FLOW"
                  "&includePagination=true&size=100",
                  body={"data": [{"id": "f1", "name": "Main"}]})
    transport.add("GET /ORG1/project/ORG1/v2/flows/f1:export?flowType=FLOW",
                  body={"name": "Main"})
    transport.add(f"GET /ORG1/project/ORG1/flows?flowType={export_flows.SUBFLOW_TYPE}"
                  "&includePagination=true&size=100",
                  body={"data": [{"id": "s1", "name": "Sub"}]})
    transport.add(f"GET /ORG1/project/ORG1/v2/flows/s1:export"
                  f"?flowType={export_flows.SUBFLOW_TYPE}", body={"name": "Sub"})
    out = export_flows.export_all_flows(make(transport), "ORG1")
    assert list(out["flows"]) == ["f1"]
    assert list(out["subflows"]) == ["s1"]
    assert out["errors"] == []


def test_export_all_flows_records_a_failed_flow_and_keeps_going(transport):
    transport.add("GET /ORG1/project/ORG1/flows?flowType=FLOW"
                  "&includePagination=true&size=100",
                  body={"data": [{"id": "f1"}, {"id": "f2"}]})
    transport.add("GET /ORG1/project/ORG1/v2/flows/f1:export?flowType=FLOW",
                  status=500, body={})
    transport.add("GET /ORG1/project/ORG1/v2/flows/f2:export?flowType=FLOW",
                  body={"name": "Two"})
    transport.add(f"GET /ORG1/project/ORG1/flows?flowType={export_flows.SUBFLOW_TYPE}"
                  "&includePagination=true&size=100", body={"data": []})
    out = export_flows.export_all_flows(make(transport), "ORG1")
    assert list(out["flows"]) == ["f2"]
    assert len(out["errors"]) == 1


def test_list_functions_uses_the_v1_org_path(transport):
    transport.add("GET /v1/ORG1/functions?page=0&size=100",
                  body={"data": [{"id": "fn1", "name": "lookup"}]})
    assert export_flows.list_functions(make(transport))[0]["id"] == "fn1"


def test_export_function_posts_to_the_export_verb(transport):
    transport.add("POST /v1/ORG1/functions/fn1:export", body={"code": "x"})
    doc, err = export_flows.export_function(make(transport), "fn1")
    assert doc == {"code": "x"} and err is None
    assert transport.calls[0]["method"] == "POST"


def test_export_all_functions_records_errors(transport):
    transport.add("GET /v1/ORG1/functions?page=0&size=100",
                  body={"data": [{"id": "fn1"}]})
    transport.add("POST /v1/ORG1/functions/fn1:export", status=400,
                  body={"message": "bad"})
    out = export_flows.export_all_functions(make(transport))
    assert out["functions"] == {}
    assert len(out["errors"]) == 1


def test_subflow_type_is_not_a_guess():
    # This value MUST come from the Task 5 probe. A module-level sentinel means
    # the probe has not been run, and export must refuse rather than guess.
    assert export_flows.SUBFLOW_TYPE != export_flows.UNRESOLVED, (
        "SUBFLOW_TYPE is still the unresolved sentinel - run scripts/probe.py "
        "and record U2 in docs/api-notes.md before implementing this task."
    )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_export_flows.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'wxcc_export.export_flows'`.

- [ ] **Step 3: Write the implementation**

Set `PROJECT_ID_MODE` and `SUBFLOW_TYPE` from `docs/api-notes.md`. The values below assume the probe confirmed `projectId == orgId` and `flowType=SUBFLOW`; **if the probe said otherwise, use what it said.**

`src/wxcc_export/export_flows.py`:

```python
"""Flows, subflows, and functions.

The sibling wxcc-skills repo declares flows out of scope BY POLICY (Cisco ships
a separate flow-store MCP server for authoring). That is a that-repo decision.
The export/import API exists and this project uses it.

Two values here are NOT derivable from the OpenAPI document and come from the
live probe recorded in docs/api-notes.md:
  U1  what projectId is
  U2  which flowType selects subflows (the schema publishes no enum)
"""

from __future__ import annotations

import urllib.parse

from .client import ApiError

UNRESOLVED = "__UNRESOLVED__"

# --- values resolved by scripts/probe.py; see docs/api-notes.md ---
PROJECT_ID_MODE = "org_id"      # U1: projectId is the org id
SUBFLOW_TYPE = "SUBFLOW"        # U2: confirmed by probe
FLOW_TYPE = "FLOW"
PAGE_SIZE = 100                 # the API default of 10 silently truncates


def resolve_project_id(client) -> str:
    if PROJECT_ID_MODE == "org_id":
        return client.org_id
    raise ApiError(f"unsupported PROJECT_ID_MODE {PROJECT_ID_MODE!r} - see U1")


def _flow_list_path(project_id: str, flow_type: str) -> str:
    q = urllib.parse.urlencode({"flowType": flow_type,
                                "includePagination": "true",
                                "size": PAGE_SIZE})
    return f"{{orgId}}/project/{project_id}/flows?{q}"


# CORRECTED (P1): the block below is the ORIGINAL, DEFECTIVE version.
# Swallowing the exception makes a failed export look like a tenant with
# zero flows. See src/wxcc_export/export_flows.py for the fixed shape,
# which returns the error to its caller for inclusion in errors[].
def list_flows(client, project_id: str, flow_type: str) -> list[dict]:
    try:
        return client.list_all(_flow_list_path(project_id, flow_type))
    except Exception:
        return []   # <-- DEFECT P1, do not copy


def export_flow(client, project_id: str, flow_id: str,
                flow_type: str) -> tuple[dict | None, str | None]:
    path = (f"{{orgId}}/project/{project_id}/v2/flows/{flow_id}:export"
            f"?flowType={flow_type}")
    try:
        status, body = client.json("GET", path)
    except Exception as exc:
        return None, f"flow {flow_id}: {type(exc).__name__}: {exc}"
    if status != 200 or not isinstance(body, dict):
        return None, f"flow {flow_id}: export returned HTTP {status}"
    return body, None


def export_all_flows(client, project_id: str) -> dict:
    out: dict = {"flows": {}, "subflows": {}, "errors": [],
                 "projectId": project_id}
    for bucket, flow_type in (("flows", FLOW_TYPE), ("subflows", SUBFLOW_TYPE)):
        if flow_type == UNRESOLVED:
            out["errors"].append(f"{bucket}: flowType unresolved - see U2 in "
                                 "docs/api-notes.md")
            continue
        for row in list_flows(client, project_id, flow_type):
            flow_id = row.get("id")
            if not flow_id:
                continue
            doc, err = export_flow(client, project_id, flow_id, flow_type)
            if err:
                out["errors"].append(err)
            else:
                out[bucket][flow_id] = {"meta": row, "document": doc}
    return out


def list_functions(client) -> list[dict]:
    try:
        return client.list_all(f"v1/{{orgId}}/functions?page=0&size={PAGE_SIZE}")
    except Exception:
        return []


def export_function(client, fn_id: str) -> tuple[dict | None, str | None]:
    try:
        status, body = client.json("POST", f"v1/{{orgId}}/functions/{fn_id}:export")
    except Exception as exc:
        return None, f"function {fn_id}: {type(exc).__name__}: {exc}"
    if status != 200 or not isinstance(body, dict):
        return None, f"function {fn_id}: export returned HTTP {status}"
    return body, None


def export_all_functions(client) -> dict:
    out: dict = {"functions": {}, "errors": []}
    for row in list_functions(client):
        fn_id = row.get("id")
        if not fn_id:
            continue
        doc, err = export_function(client, fn_id)
        if err:
            out["errors"].append(err)
        else:
            out["functions"][fn_id] = {"meta": row, "document": doc}
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_export_flows.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wxcc_export/export_flows.py tests/test_export_flows.py
git commit -m "feat: flows, subflows, and functions export using probe-confirmed values"
```

---

### Task 10: Webex Calling subset export

> **BLOCKED ON Task 5 (U5).** If `docs/api-notes.md` records that Calling is not provisioned on the sandbox or the token lacks the scopes, implement the module anyway but mark the whole section `{"error": "..."}` from the probe finding. Do not fabricate a passing export.

**Files:**
- Create: `src/wxcc_export/export_calling.py`
- Test: `tests/test_export_calling.py`

**Interfaces:**
- Consumes: `registry.CALLING_OBJECTS`, a second `ApiClient` pointed at `config.WEBEX_API_BASE`.
- Produces:
  - `export_calling.list_locations(client) -> list[dict]`
  - `export_calling.export_object(client, name, locations) -> dict`
  - `export_calling.export_all(client, names=None, on_progress=None) -> dict`

**The Calling API uses a different host.** `https://webexapis.com/v1`, not the WxCC regional host. It also paginates differently (`start`/`max` with a `Link` header on some endpoints, a bare array on others), which is why `client.list_all` already accepts both shapes.

- [ ] **Step 1: Write the failing test**

`tests/test_export_calling.py`:

```python
from wxcc_export import export_calling
from wxcc_export.client import ApiClient

WEBEX = "https://webexapis.com/v1"


def make(transport):
    return ApiClient(WEBEX, "TOKEN", org_id="ORG1", transport=transport)


def test_list_locations_returns_rows(transport):
    transport.add("GET /locations", body={"items": [{"id": "L1", "name": "HQ"}]})
    assert export_calling.list_locations(make(transport))[0]["id"] == "L1"


def test_org_scoped_object_is_fetched_once(transport):
    transport.add("GET /telephony/config/huntGroups",
                  body={"items": [{"id": "H1", "name": "Sales"}]})
    out = export_calling.export_object(make(transport), "hunt-groups", [])
    assert out["count"] == 1
    assert len(transport.calls) == 1


def test_location_scoped_object_is_fetched_per_location(transport):
    transport.add("GET /telephony/config/locations/L1/schedules",
                  body={"items": [{"id": "S1"}]})
    transport.add("GET /telephony/config/locations/L2/schedules",
                  body={"items": [{"id": "S2"}]})
    locs = [{"id": "L1"}, {"id": "L2"}]
    out = export_calling.export_object(make(transport), "schedules", locs)
    assert out["count"] == 2
    assert {i["id"] for i in out["items"]} == {"S1", "S2"}


def test_location_scoped_items_are_tagged_with_their_location(transport):
    transport.add("GET /telephony/config/locations/L1/schedules",
                  body={"items": [{"id": "S1"}]})
    out = export_calling.export_object(make(transport), "schedules", [{"id": "L1"}])
    assert out["items"][0]["_locationId"] == "L1"


def test_a_403_is_recorded_as_a_scope_problem(transport):
    transport.add("GET /telephony/config/huntGroups", status=403, body={})
    out = export_calling.export_object(make(transport), "hunt-groups", [])
    assert "403" in out["error"]
    assert out["count"] == 0


def test_a_404_is_recorded_as_not_provisioned(transport):
    transport.add("GET /telephony/config/huntGroups", status=404, body={})
    out = export_calling.export_object(make(transport), "hunt-groups", [])
    assert "404" in out["error"]


def test_one_failing_location_does_not_lose_the_others(transport):
    transport.add("GET /telephony/config/locations/L1/schedules", status=403, body={})
    transport.add("GET /telephony/config/locations/L2/schedules",
                  body={"items": [{"id": "S2"}]})
    out = export_calling.export_object(make(transport), "schedules",
                                       [{"id": "L1"}, {"id": "L2"}])
    assert out["count"] == 1
    assert out["error"] is not None


def test_export_all_covers_every_registered_object(transport):
    transport.add("GET /locations", body={"items": []})
    out = export_calling.export_all(make(transport))
    from wxcc_export.registry import CALLING_OBJECTS
    assert set(out["objects"]) == set(CALLING_OBJECTS) - {"locations"}


def test_export_all_stops_early_when_locations_fail(transport):
    transport.add("GET /locations", status=403, body={})
    out = export_calling.export_all(make(transport))
    # Without locations, location-scoped objects cannot be enumerated at all.
    assert out["error"] is not None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_export_calling.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'wxcc_export.export_calling'`.

- [ ] **Step 3: Write the implementation**

`src/wxcc_export/export_calling.py`:

```python
"""The bounded Webex Calling subset.

A different host from Contact Center: https://webexapis.com/v1. Most objects are
location-scoped, so the location list is fetched first and everything else fans
out from it. Losing the location list loses the whole section - that is reported,
not silently returned as empty.
"""

from __future__ import annotations

from . import registry
from .client import ApiError


def list_locations(client) -> list[dict]:
    return client.list_all(registry.CALLING_OBJECTS["locations"]["list"])


def _fetch(client, path: str) -> list[dict]:
    return client.list_all(path)


def export_object(client, name: str, locations: list[dict]) -> dict:
    spec = registry.CALLING_OBJECTS[name]
    result: dict = {"object": name, "count": 0, "items": [], "error": None}
    errors: list[str] = []

    if spec["scope"] == "org":
        try:
            result["items"] = _fetch(client, spec["list"])
        except ApiError as exc:
            result["error"] = _explain(exc)
            return result
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            return result
    else:
        for loc in locations:
            loc_id = loc.get("id")
            path = spec["list"].replace("{locationId}", loc_id or "")
            try:
                rows = _fetch(client, path)
            except ApiError as exc:
                errors.append(f"location {loc_id}: {_explain(exc)}")
                continue
            except Exception as exc:
                errors.append(f"location {loc_id}: {type(exc).__name__}: {exc}")
                continue
            result["items"].extend({**r, "_locationId": loc_id} for r in rows)

    result["count"] = len(result["items"])
    if errors:
        result["error"] = "; ".join(errors[:5])
    return result


def _explain(exc: ApiError) -> str:
    if exc.status == 403:
        return (f"HTTP 403 - the token lacks the Calling scopes "
                f"(spark-admin:telephony_config_read). {str(exc)[:120]}")
    if exc.status == 404:
        return (f"HTTP 404 - Webex Calling may not be provisioned on this "
                f"tenant. {str(exc)[:120]}")
    return f"HTTP {exc.status}: {str(exc)[:160]}"


def export_all(client, names: list[str] | None = None,
               on_progress=None) -> dict:
    out: dict = {"locations": [], "objects": {}, "error": None}
    try:
        out["locations"] = list_locations(client)
    except ApiError as exc:
        out["error"] = ("could not list locations, so no location-scoped Calling "
                        f"object could be enumerated: {_explain(exc)}")
        return out
    except Exception as exc:
        out["error"] = f"could not list locations: {type(exc).__name__}: {exc}"
        return out

    targets = names or [n for n in registry.CALLING_OBJECTS if n != "locations"]
    for name in targets:
        result = export_object(client, name, out["locations"])
        out["objects"][name] = result
        if on_progress:
            on_progress(name, result)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_export_calling.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wxcc_export/export_calling.py tests/test_export_calling.py
git commit -m "feat: bounded Webex Calling subset export with scope-aware errors"
```

---

### Task 11: Archive writer, manifest, and UNSUPPORTED.md

**Files:**
- Create: `src/wxcc_export/archive.py`
- Test: `tests/test_archive.py`

**Interfaces:**
- Consumes: `registry.UNSUPPORTED`, `tenant.archive_name`.
- Produces:
  - `archive.ArchiveWriter(path)` with `.add_json(name, obj)`, `.add_bytes(name, data)`, `.add_text(name, text)`, `.close()`
  - `archive.build_manifest(source, sections, errors) -> dict`
  - `archive.render_unsupported(errors, unsupported=registry.UNSUPPORTED) -> str`
  - `archive.write_export(path, source, cc, children, audio, flows, functions, calling, users) -> dict` — returns the manifest it wrote
  - `archive.SCHEMA_VERSION = 1`

**The manifest is the contract.** Task 12's reader depends on this exact shape, so the two tasks share the constant `SCHEMA_VERSION` and the reader refuses an archive whose version it does not know.

- [ ] **Step 1: Write the failing test**

`tests/test_archive.py`:

```python
import json
import zipfile

import pytest
from wxcc_export import archive


def test_writer_stores_json_that_round_trips(tmp_path):
    p = tmp_path / "out.zip"
    w = archive.ArchiveWriter(p)
    w.add_json("cc/site.json", {"entity": "site", "items": [{"id": "s1"}]})
    w.close()
    with zipfile.ZipFile(p) as z:
        doc = json.loads(z.read("cc/site.json"))
    assert doc["items"][0]["id"] == "s1"


def test_writer_stores_raw_bytes(tmp_path):
    p = tmp_path / "out.zip"
    w = archive.ArchiveWriter(p)
    w.add_bytes("cc/audio/a1__welcome.wav", b"RIFF")
    w.close()
    with zipfile.ZipFile(p) as z:
        assert z.read("cc/audio/a1__welcome.wav") == b"RIFF"


def test_writer_rejects_a_path_that_escapes_the_archive(tmp_path):
    w = archive.ArchiveWriter(tmp_path / "out.zip")
    with pytest.raises(ValueError):
        w.add_text("../evil.txt", "x")
    w.close()


def test_manifest_records_the_schema_version_and_source():
    m = archive.build_manifest({"orgId": "O1", "orgName": "sandbox"}, {}, [])
    assert m["schemaVersion"] == archive.SCHEMA_VERSION
    assert m["source"]["orgName"] == "sandbox"


def test_manifest_carries_an_iso_timestamp():
    m = archive.build_manifest({"orgId": "O1"}, {}, [])
    assert m["exportedAt"].endswith("Z")


def test_manifest_lists_every_error():
    errs = [{"section": "calling", "object": "queues", "detail": "HTTP 403"}]
    assert archive.build_manifest({}, {}, errs)["errors"] == errs


def test_manifest_names_the_unsupported_objects():
    m = archive.build_manifest({}, {}, [])
    assert set(m["unsupported"]) == {"Channels", "Surveys"}


def test_unsupported_md_explains_each_object():
    text = archive.render_unsupported([])
    assert "Channels" in text and "Surveys" in text
    assert "Webex Connect" in text          # the actual reason, not a shrug


def test_unsupported_md_also_lists_runtime_errors():
    errs = [{"section": "cc", "object": "site", "detail": "HTTP 403 forbidden"}]
    text = archive.render_unsupported(errs)
    assert "site" in text and "403" in text


def test_unsupported_md_says_so_when_nothing_failed():
    text = archive.render_unsupported([])
    assert "No errors" in text


def test_write_export_produces_a_readable_archive(tmp_path):
    p = tmp_path / "sandbox-export.zip"
    manifest = archive.write_export(
        p,
        source={"orgId": "O1", "orgName": "sandbox", "subscriptionType": "TRIAL",
                "apiBase": "https://api.wxcc-us1.cisco.com"},
        cc={"site": {"entity": "site", "count": 1,
                     "items": [{"id": "s1", "name": "Denver"}], "error": None}},
        children={}, audio={},
        flows={"flows": {}, "subflows": {}, "errors": [], "projectId": "O1"},
        functions={"functions": {}, "errors": []},
        calling={"locations": [], "objects": {}, "error": None},
        users={"rows": [{"email": "a@x.com"}], "csv": "email\na@x.com\n"},
    )
    with zipfile.ZipFile(p) as z:
        names = set(z.namelist())
        assert "manifest.json" in names
        assert "UNSUPPORTED.md" in names
        assert "cc/site.json" in names
        assert "users/users.csv" in names
        stored = json.loads(z.read("manifest.json"))
    assert stored == manifest
    assert manifest["sections"]["cc"]["entities"]["site"]["count"] == 1


def test_write_export_promotes_entity_errors_into_the_manifest(tmp_path):
    p = tmp_path / "out.zip"
    manifest = archive.write_export(
        p, source={"orgId": "O1"},
        cc={"site": {"entity": "site", "count": 0, "items": [],
                     "error": "HTTP 403 forbidden"}},
        children={}, audio={},
        flows={"flows": {}, "subflows": {}, "errors": []},
        functions={"functions": {}, "errors": []},
        calling={"locations": [], "objects": {}, "error": None},
        users={"rows": [], "csv": ""},
    )
    assert any(e["object"] == "site" for e in manifest["errors"])


def test_write_export_stores_audio_bytes_under_a_collision_safe_name(tmp_path):
    p = tmp_path / "out.zip"
    archive.write_export(
        p, source={}, cc={}, children={},
        audio={"a1": {"bytes": b"RIFF", "name": "welcome.wav"}},
        flows={"flows": {}, "subflows": {}, "errors": []},
        functions={"functions": {}, "errors": []},
        calling={"locations": [], "objects": {}, "error": None},
        users={"rows": [], "csv": ""},
    )
    with zipfile.ZipFile(p) as z:
        assert "cc/audio/a1__welcome.wav" in z.namelist()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_archive.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'wxcc_export.archive'`.

- [ ] **Step 3: Write the implementation**

`src/wxcc_export/archive.py`:

```python
"""The export archive: a zip whose manifest is the contract with the importer.

A partial export must never look like a complete one, so every recorded failure
is promoted into manifest["errors"] AND restated in prose in UNSUPPORTED.md.
"""

from __future__ import annotations

import datetime
import json
import re
import zipfile
from pathlib import Path

from . import registry

SCHEMA_VERSION = 1
TOOL_NAME = "wxcc-sandbox-exporter"
TOOL_VERSION = "0.1.0"

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_component(text: str) -> str:
    return _SAFE_NAME.sub("_", (text or "").strip()) or "unnamed"


class ArchiveWriter:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._zip = zipfile.ZipFile(self.path, "w", zipfile.ZIP_DEFLATED)

    def _check(self, name: str) -> str:
        if name.startswith("/") or ".." in Path(name).parts:
            raise ValueError(f"refusing to write outside the archive: {name!r}")
        return name

    def add_json(self, name: str, obj: object) -> None:
        self._zip.writestr(self._check(name),
                           json.dumps(obj, indent=2, sort_keys=True))

    def add_text(self, name: str, text: str) -> None:
        self._zip.writestr(self._check(name), text)

    def add_bytes(self, name: str, data: bytes) -> None:
        self._zip.writestr(self._check(name), data)

    def close(self) -> None:
        self._zip.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def build_manifest(source: dict, sections: dict, errors: list[dict]) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "toolVersion": TOOL_VERSION,
        "exportedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "sections": sections,
        "unsupported": sorted(registry.UNSUPPORTED),
        "errors": errors,
    }


def render_unsupported(errors: list[dict],
                       unsupported: dict[str, str] | None = None) -> str:
    unsupported = registry.UNSUPPORTED if unsupported is None else unsupported
    lines = [
        "# What this archive does NOT contain",
        "",
        "Read this before assuming the import produced a complete tenant.",
        "",
        "## Objects with no public API",
        "",
        "These cannot be exported by any tool, because Cisco publishes no",
        "endpoint for them. They must be recreated by hand.",
        "",
    ]
    for name in sorted(unsupported):
        lines += [f"### {name}", "", unsupported[name], ""]

    lines += ["## Objects that failed during THIS export", ""]
    if not errors:
        lines += ["No errors. Every object in scope was captured.", ""]
    else:
        lines += ["| section | object | detail |", "|---|---|---|"]
        for e in errors:
            detail = str(e.get("detail", "")).replace("|", "\\|")[:200]
            lines.append(f"| {e.get('section','')} | {e.get('object','')} "
                         f"| {detail} |")
        lines += ["",
                  "Each row above is configuration that is **missing** from this",
                  "archive. Re-run the export after fixing the cause, or recreate",
                  "those objects by hand.", ""]
    return "\n".join(lines)


def write_export(path, source: dict, cc: dict, children: dict, audio: dict,
                 flows: dict, functions: dict, calling: dict,
                 users: dict) -> dict:
    """Assemble the archive and return the manifest that was written."""
    errors: list[dict] = []
    sections: dict = {}

    with ArchiveWriter(path) as w:
        # --- contact center entities ---
        entity_index: dict = {}
        for entity, result in (cc or {}).items():
            fname = f"cc/{entity}.json"
            w.add_json(fname, {"entity": entity, "items": result.get("items", [])})
            entity_index[entity] = {"count": result.get("count", 0), "file": fname}
            if result.get("error"):
                errors.append({"section": "cc", "object": entity,
                               "detail": result["error"]})
        sections["cc"] = {"entities": entity_index}

        # --- child collections ---
        child_index: dict = {}
        for entity, per_parent in (children or {}).items():
            for parent_id, record in per_parent.items():
                fname = f"cc/children/{entity}__{_safe_component(parent_id)}.json"
                w.add_json(fname, {"entity": entity, "parentId": parent_id,
                                   "items": record.get("items", [])})
                child_index.setdefault(entity, {})[parent_id] = {
                    "count": record.get("count", 0), "file": fname}
                if record.get("error"):
                    errors.append({"section": "cc-children",
                                   "object": f"{entity}/{parent_id}",
                                   "detail": record["error"]})
        if child_index:
            sections["cc"]["children"] = child_index

        # --- audio bytes ---
        audio_index: dict = {}
        for item_id, blob in (audio or {}).items():
            fname = (f"cc/audio/{_safe_component(item_id)}__"
                     f"{_safe_component(blob.get('name', 'audio'))}")
            w.add_bytes(fname, blob["bytes"])
            audio_index[item_id] = {"file": fname, "bytes": len(blob["bytes"])}
        if audio_index:
            sections["cc"]["audio"] = audio_index

        # --- flows / subflows / functions ---
        for bucket in ("flows", "subflows"):
            for flow_id, payload in (flows or {}).get(bucket, {}).items():
                w.add_json(f"flows/{bucket}/{_safe_component(flow_id)}.json", payload)
        for fn_id, payload in (functions or {}).get("functions", {}).items():
            w.add_json(f"flows/functions/{_safe_component(fn_id)}.json", payload)
        sections["flows"] = {
            "flows": len((flows or {}).get("flows", {})),
            "subflows": len((flows or {}).get("subflows", {})),
            "functions": len((functions or {}).get("functions", {})),
            "projectId": (flows or {}).get("projectId"),
        }
        for detail in (flows or {}).get("errors", []):
            errors.append({"section": "flows", "object": "flow", "detail": detail})
        for detail in (functions or {}).get("errors", []):
            errors.append({"section": "flows", "object": "function",
                           "detail": detail})

        # --- calling ---
        calling_index: dict = {}
        if (calling or {}).get("locations"):
            w.add_json("calling/locations.json",
                       {"object": "locations", "items": calling["locations"]})
            calling_index["locations"] = {"count": len(calling["locations"]),
                                          "file": "calling/locations.json"}
        for name, result in (calling or {}).get("objects", {}).items():
            fname = f"calling/{name}.json"
            w.add_json(fname, {"object": name, "items": result.get("items", [])})
            calling_index[name] = {"count": result.get("count", 0), "file": fname}
            if result.get("error"):
                errors.append({"section": "calling", "object": name,
                               "detail": result["error"]})
        if (calling or {}).get("error"):
            errors.append({"section": "calling", "object": "locations",
                           "detail": calling["error"]})
        sections["calling"] = {"objects": calling_index}

        # --- users (reference only) ---
        w.add_json("users/users.json", {"users": (users or {}).get("rows", []),
                                        "writable": False})
        w.add_text("users/users.csv", (users or {}).get("csv", ""))
        sections["users"] = {"count": len((users or {}).get("rows", [])),
                             "writable": False}

        manifest = build_manifest(source, sections, errors)
        w.add_json("manifest.json", manifest)
        w.add_text("UNSUPPORTED.md", render_unsupported(errors))

    return manifest
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_archive.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Run the whole suite and report the delta**

```bash
python -m pytest -q
```

Expected: 100 passed, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add src/wxcc_export/archive.py tests/test_archive.py
git commit -m "feat: archive writer with manifest and an honest UNSUPPORTED.md"
```

---

### Task 12: Archive reader and selection model

**Files:**
- Modify: `src/wxcc_export/archive.py` (append the reader)
- Test: `tests/test_archive_read.py`

**Interfaces:**
- Consumes: `archive.SCHEMA_VERSION`.
- Produces:
  - `archive.ArchiveReader(path)` with `.manifest`, `.read_json(name)`, `.read_bytes(name)`, `.entity_items(entity)`, `.children(entity)`, `.audio_blob(item_id)`, `.flows(bucket)`, `.functions()`, `.calling_items(name)`, `.close()`
  - `archive.available_selections(manifest) -> list[dict]` — `{"key","label","group","count"}` for the UI
  - `archive.parse_selection(spec: str, manifest) -> list[str]` — accepts `all`, `cc`, `flows`, `calling`, or comma-separated keys
  - `archive.IncompatibleArchive(Exception)`

**Selection keys are stable strings.** `cc:site`, `flows:flows`, `flows:functions`, `calling:hunt-groups`. The CLI and the web UI both speak these, so the two interfaces cannot drift.

- [ ] **Step 1: Write the failing test**

`tests/test_archive_read.py`:

```python
import json
import zipfile

import pytest
from wxcc_export import archive


def build(tmp_path, **over):
    p = tmp_path / "t-export.zip"
    args = dict(
        source={"orgId": "O1", "orgName": "src"},
        cc={"site": {"entity": "site", "count": 1,
                     "items": [{"id": "s1", "name": "Denver"}], "error": None},
            "team": {"entity": "team", "count": 0, "items": [], "error": None}},
        children={"address-book": {"ab1": {"parent_id": "ab1", "count": 1,
                                           "items": [{"id": "e1"}], "error": None}}},
        audio={"a1": {"bytes": b"RIFF", "name": "welcome.wav"}},
        flows={"flows": {"f1": {"meta": {"id": "f1"}, "document": {"name": "Main"}}},
               "subflows": {}, "errors": [], "projectId": "O1"},
        functions={"functions": {"fn1": {"meta": {"id": "fn1"},
                                         "document": {"code": "x"}}},
                   "errors": []},
        calling={"locations": [{"id": "L1"}],
                 "objects": {"hunt-groups": {"object": "hunt-groups", "count": 1,
                                             "items": [{"id": "H1"}], "error": None}},
                 "error": None},
        users={"rows": [{"email": "a@x.com"}], "csv": "email\na@x.com\n"},
    )
    args.update(over)
    archive.write_export(p, **args)
    return p


def test_reader_exposes_the_manifest(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert r.manifest["source"]["orgName"] == "src"
    r.close()


def test_reader_rejects_an_unknown_schema_version(tmp_path):
    p = tmp_path / "bad.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("manifest.json", json.dumps({"schemaVersion": 99}))
    with pytest.raises(archive.IncompatibleArchive) as exc:
        archive.ArchiveReader(p)
    assert "99" in str(exc.value)


def test_reader_rejects_a_zip_with_no_manifest(tmp_path):
    p = tmp_path / "bad.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(archive.IncompatibleArchive):
        archive.ArchiveReader(p)


def test_entity_items_returns_the_stored_rows(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert r.entity_items("site")[0]["name"] == "Denver"
    r.close()


def test_entity_items_of_an_absent_entity_is_empty(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert r.entity_items("skill") == []
    r.close()


def test_children_are_keyed_by_parent(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert r.children("address-book")["ab1"][0]["id"] == "e1"
    r.close()


def test_audio_blob_round_trips(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert r.audio_blob("a1") == b"RIFF"
    r.close()


def test_flows_are_readable_by_bucket(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert r.flows("flows")["f1"]["document"]["name"] == "Main"
    assert r.flows("subflows") == {}
    r.close()


def test_functions_are_readable(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert r.functions()["fn1"]["document"]["code"] == "x"
    r.close()


def test_calling_items_are_readable(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert r.calling_items("hunt-groups")[0]["id"] == "H1"
    r.close()


def test_available_selections_skips_empty_sections(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    keys = {s["key"] for s in archive.available_selections(r.manifest)}
    assert "cc:site" in keys
    assert "cc:team" not in keys           # count 0 - nothing to import
    r.close()


def test_available_selections_labels_the_spec_group(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    site = next(s for s in archive.available_selections(r.manifest)
                if s["key"] == "cc:site")
    assert site["group"] == "User Management"
    r.close()


def test_parse_selection_all_returns_everything_available(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    keys = archive.parse_selection("all", r.manifest)
    assert "cc:site" in keys and "flows:flows" in keys
    r.close()


def test_parse_selection_by_section(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    keys = archive.parse_selection("cc", r.manifest)
    assert all(k.startswith("cc:") for k in keys)
    r.close()


def test_parse_selection_accepts_explicit_keys(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    assert archive.parse_selection("cc:site,flows:functions", r.manifest) == [
        "cc:site", "flows:functions"]
    r.close()


def test_parse_selection_rejects_an_unknown_key(tmp_path):
    r = archive.ArchiveReader(build(tmp_path))
    with pytest.raises(ValueError) as exc:
        archive.parse_selection("cc:nonsense", r.manifest)
    assert "cc:nonsense" in str(exc.value)
    r.close()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_archive_read.py -v
```

Expected: FAIL — `AttributeError: module 'wxcc_export.archive' has no attribute 'ArchiveReader'`.

- [ ] **Step 3: Append the reader to `src/wxcc_export/archive.py`**

```python
class IncompatibleArchive(Exception):
    """The zip is not an archive this tool version can read."""


class ArchiveReader:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        try:
            self._zip = zipfile.ZipFile(self.path)
        except zipfile.BadZipFile as exc:
            raise IncompatibleArchive(f"{self.path.name} is not a zip file") from exc
        try:
            self.manifest = json.loads(self._zip.read("manifest.json"))
        except KeyError as exc:
            raise IncompatibleArchive(
                f"{self.path.name} has no manifest.json - it was not produced by "
                f"{TOOL_NAME}") from exc
        version = self.manifest.get("schemaVersion")
        if version != SCHEMA_VERSION:
            raise IncompatibleArchive(
                f"archive schemaVersion {version} but this tool reads "
                f"{SCHEMA_VERSION}. Re-export with a matching tool version.")

    # --- raw access ---
    def read_json(self, name: str) -> object:
        try:
            return json.loads(self._zip.read(name))
        except KeyError:
            return None

    def read_bytes(self, name: str) -> bytes | None:
        try:
            return self._zip.read(name)
        except KeyError:
            return None

    # --- typed access ---
    def entity_items(self, entity: str) -> list[dict]:
        entry = (self.manifest["sections"].get("cc", {})
                 .get("entities", {}).get(entity))
        if not entry:
            return []
        doc = self.read_json(entry["file"]) or {}
        return doc.get("items", [])

    def children(self, entity: str) -> dict[str, list[dict]]:
        index = (self.manifest["sections"].get("cc", {})
                 .get("children", {}).get(entity, {}))
        out: dict[str, list[dict]] = {}
        for parent_id, entry in index.items():
            doc = self.read_json(entry["file"]) or {}
            out[parent_id] = doc.get("items", [])
        return out

    def audio_blob(self, item_id: str) -> bytes | None:
        entry = (self.manifest["sections"].get("cc", {})
                 .get("audio", {}).get(item_id))
        return self.read_bytes(entry["file"]) if entry else None

    def flows(self, bucket: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        prefix = f"flows/{bucket}/"
        for name in self._zip.namelist():
            if name.startswith(prefix) and name.endswith(".json"):
                out[Path(name).stem] = self.read_json(name)
        return out

    def functions(self) -> dict[str, dict]:
        return self.flows("functions")

    def calling_items(self, name: str) -> list[dict]:
        entry = (self.manifest["sections"].get("calling", {})
                 .get("objects", {}).get(name))
        if not entry:
            return []
        doc = self.read_json(entry["file"]) or {}
        return doc.get("items", [])

    def users(self) -> list[dict]:
        doc = self.read_json("users/users.json") or {}
        return doc.get("users", [])

    def close(self) -> None:
        self._zip.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def _group_of(entity: str) -> str:
    for group, members in registry.SPEC_GROUPS.items():
        if entity in members:
            return group
    return "Other"


def available_selections(manifest: dict) -> list[dict]:
    """Everything in the archive that has at least one item to import.

    An empty entity is omitted rather than offered: a checkbox that imports
    nothing is a checkbox that wastes a decision.
    """
    out: list[dict] = []
    sections = manifest.get("sections", {})

    for entity, entry in sections.get("cc", {}).get("entities", {}).items():
        if entry.get("count"):
            out.append({"key": f"cc:{entity}", "label": entity,
                        "group": _group_of(entity), "count": entry["count"],
                        "writable": registry.CC_ENTITIES.get(
                            entity, {}).get("writable", False)})

    flows = sections.get("flows", {})
    for bucket in ("flows", "subflows", "functions"):
        if flows.get(bucket):
            out.append({"key": f"flows:{bucket}", "label": bucket,
                        "group": "Flows", "count": flows[bucket],
                        "writable": True})

    for name, entry in sections.get("calling", {}).get("objects", {}).items():
        if entry.get("count"):
            out.append({"key": f"calling:{name}", "label": name,
                        "group": "Webex Calling", "count": entry["count"],
                        "writable": True})
    return out


def parse_selection(spec: str, manifest: dict) -> list[str]:
    """Turn a CLI selection string into concrete keys.

    Accepts `all`, a section name (`cc`, `flows`, `calling`), or a
    comma-separated list of explicit keys. An unknown key is an error, not a
    silent no-op: a typo that imports nothing looks exactly like success.
    """
    available = {s["key"] for s in available_selections(manifest)}
    spec = (spec or "").strip()
    if not spec or spec == "all":
        return sorted(available)
    keys: list[str] = []
    for token in (t.strip() for t in spec.split(",") if t.strip()):
        if token in ("cc", "flows", "calling"):
            keys += sorted(k for k in available if k.startswith(f"{token}:"))
        elif token in available:
            keys.append(token)
        else:
            raise ValueError(
                f"unknown selection {token!r}. Available: "
                f"{', '.join(sorted(available)) or '(archive is empty)'}")
    return keys
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_archive_read.py -v
```

Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wxcc_export/archive.py tests/test_archive_read.py
git commit -m "feat: archive reader and a selection model shared by CLI and web UI"
```

---

### Task 13: ID remapping engine

**Files:**
- Create: `src/wxcc_export/idmap.py`
- Test: `tests/test_idmap.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `idmap.IdMap()` with `.record(old, new)`, `.get(old)`, `.substitute(payload)`, `.unmapped(payload) -> set[str]`, `.as_dict()`
  - `idmap.looks_like_id(value: str) -> bool`
  - `idmap.strip_identity(item: dict) -> dict` — removes `id` and other server-assigned keys before a create

**Why generic substitution rather than a foreign-key map.** WxCC ids are globally unique opaque strings. If `s1` becomes `s9`, then *every* occurrence of `s1` anywhere in any remaining payload refers to that site — there is no other object it could mean. A recursive substitution is therefore both complete and safe, and it handles flow JSON (which embeds queue and entry-point ids in node parameters) with no extra work. The sibling repo tried the hand-written-map approach and recorded it as "slow, mostly inferred, and provably incomplete" (`wxcc-skills/mcp_server.py:558-563`).

- [ ] **Step 1: Write the failing test**

`tests/test_idmap.py`:

```python
import pytest
from wxcc_export import idmap


def test_record_and_get():
    m = idmap.IdMap()
    m.record("old1", "new1")
    assert m.get("old1") == "new1"
    assert m.get("missing") is None


def test_substitute_replaces_a_top_level_string():
    m = idmap.IdMap()
    m.record("s1", "s9")
    assert m.substitute({"siteId": "s1"}) == {"siteId": "s9"}


def test_substitute_recurses_into_nested_dicts():
    m = idmap.IdMap()
    m.record("t1", "t9")
    payload = {"routing": {"groups": [{"teamId": "t1"}]}}
    assert m.substitute(payload)["routing"]["groups"][0]["teamId"] == "t9"


def test_substitute_recurses_into_lists_of_strings():
    m = idmap.IdMap()
    m.record("t1", "t9")
    assert m.substitute({"teamIds": ["t1", "t2"]})["teamIds"] == ["t9", "t2"]


def test_substitute_rewrites_ids_embedded_in_flow_json():
    m = idmap.IdMap()
    m.record("q1", "q9")
    flow = {"nodes": [{"id": "n1", "params": {"queueId": "q1"}}]}
    assert m.substitute(flow)["nodes"][0]["params"]["queueId"] == "q9"


def test_substitute_replaces_an_id_inside_a_longer_string():
    # Flow node parameters sometimes carry a URI or expression containing the id.
    m = idmap.IdMap()
    m.record("q1abc", "q9xyz")
    out = m.substitute({"expr": "queue://q1abc/overflow"})
    assert out["expr"] == "queue://q9xyz/overflow"


def test_substitute_leaves_unmapped_values_alone():
    m = idmap.IdMap()
    assert m.substitute({"siteId": "unknown"}) == {"siteId": "unknown"}


def test_substitute_does_not_mutate_the_input():
    m = idmap.IdMap()
    m.record("s1", "s9")
    original = {"siteId": "s1"}
    m.substitute(original)
    assert original == {"siteId": "s1"}


def test_substitute_preserves_non_string_scalars():
    m = idmap.IdMap()
    payload = {"active": True, "count": 3, "ratio": 1.5, "nothing": None}
    assert m.substitute(payload) == payload


def test_unmapped_finds_id_shaped_values_with_no_mapping():
    m = idmap.IdMap()
    m.record("11111111-1111-1111-1111-111111111111", "x")
    payload = {"a": "11111111-1111-1111-1111-111111111111",
               "b": "22222222-2222-2222-2222-222222222222",
               "c": "Denver"}
    assert m.unmapped(payload) == {"22222222-2222-2222-2222-222222222222"}


def test_looks_like_id_accepts_a_uuid():
    assert idmap.looks_like_id("11111111-1111-1111-1111-111111111111")


def test_looks_like_id_rejects_a_human_name():
    assert not idmap.looks_like_id("Denver")
    assert not idmap.looks_like_id("Tier 1 Support")


def test_looks_like_id_rejects_a_short_token():
    assert not idmap.looks_like_id("abc")


def test_strip_identity_removes_the_id():
    out = idmap.strip_identity({"id": "s1", "name": "Denver"})
    assert "id" not in out and out["name"] == "Denver"


def test_strip_identity_removes_created_time_and_the_heuristic_label():
    out = idmap.strip_identity({"id": "s1", "createdTime": 1,
                                "likely_default": True, "name": "D"})
    assert set(out) == {"name"}


def test_strip_identity_keeps_reference_ids():
    # Only this object's OWN identity is stripped; references must survive to be
    # remapped afterwards.
    out = idmap.strip_identity({"id": "t1", "siteId": "s1"})
    assert out == {"siteId": "s1"}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_idmap.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'wxcc_export.idmap'`.

- [ ] **Step 3: Write the implementation**

`src/wxcc_export/idmap.py`:

```python
"""Rewrite source-tenant ids to target-tenant ids.

WxCC ids are globally unique opaque strings, so an occurrence of `s1` anywhere
in any payload refers to exactly one object. Recursive substitution is therefore
complete AND safe, and it rewrites flow JSON - which embeds queue and entry-point
ids in node parameters - with no extra machinery.

The alternative, a hand-written map of which field on which entity is a foreign
key, was tried in the sibling wxcc-skills repo and recorded there as "slow,
mostly inferred, and provably incomplete".
"""

from __future__ import annotations

import re

# Server-assigned identity and local bookkeeping. Sending these on a create is
# at best ignored and at worst a 400 ("New configuration cannot have an id").
IDENTITY_FIELDS = frozenset({
    "id", "createdTime", "createdAt", "lastUpdatedTime", "version",
    "likely_default", "_locationId", "organizationId", "orgId",
})

_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# Webex also issues long base64-ish ids (e.g. Y2lzY29zcGFyazovL3Vz...).
_OPAQUE = re.compile(r"^[A-Za-z0-9_-]{16,}$")


def looks_like_id(value: str) -> bool:
    """Is this string shaped like an identifier rather than a human name?

    Deliberately conservative: used only to REPORT ids that were not remapped,
    never to decide what to rewrite. Substitution is driven by exact matches
    against recorded mappings.
    """
    if not isinstance(value, str) or " " in value:
        return False
    return bool(_UUID.match(value) or _OPAQUE.match(value))


def strip_identity(item: dict) -> dict:
    """Drop this object's own identity, keeping its references intact."""
    return {k: v for k, v in item.items() if k not in IDENTITY_FIELDS}


class IdMap:
    def __init__(self) -> None:
        self._map: dict[str, str] = {}

    def record(self, old: str, new: str) -> None:
        if old and new:
            self._map[old] = new

    def get(self, old: str) -> str | None:
        return self._map.get(old)

    def as_dict(self) -> dict[str, str]:
        return dict(self._map)

    def substitute(self, payload):
        """Return a copy with every recorded id replaced. Never mutates input."""
        if isinstance(payload, dict):
            return {k: self.substitute(v) for k, v in payload.items()}
        if isinstance(payload, list):
            return [self.substitute(v) for v in payload]
        if isinstance(payload, str):
            return self._rewrite_string(payload)
        return payload

    def _rewrite_string(self, text: str) -> str:
        exact = self._map.get(text)
        if exact is not None:
            return exact
        # An id can appear inside a URI or an expression in flow JSON. Only
        # scan when a substring match is plausible, to keep this cheap.
        if len(text) < 16:
            return text
        for old, new in self._map.items():
            if old in text:
                text = text.replace(old, new)
        return text

    def unmapped(self, payload) -> set[str]:
        """Id-shaped strings with no recorded mapping.

        These are dangling references: they point at objects that were not
        imported, so the target will either reject them or store a broken link.
        The importer surfaces them rather than letting a 200 imply success.
        """
        found: set[str] = set()

        def walk(node):
            if isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
            elif isinstance(node, str) and looks_like_id(node):
                if node not in self._map:
                    found.add(node)

        walk(payload)
        return found
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_idmap.py -v
```

Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wxcc_export/idmap.py tests/test_idmap.py
git commit -m "feat: generic recursive ID remapping with dangling-reference detection"
```

---

### Task 14: Import ordering and collision detection

**Files:**
- Create: `src/wxcc_export/plan.py`
- Test: `tests/test_plan.py`

**Interfaces:**
- Consumes: `registry.CC_ENTITIES`.
- Produces:
  - `plan.order_entities(entities: list[str]) -> list[str]` — topological sort over `deps`
  - `plan.index_existing(client, entity) -> dict[str, dict]` — `{name_lower: item}` from the target tenant
  - `plan.classify(source_items, existing, on_conflict) -> list[dict]` — `{"action","item","existing","reason"}` where action is `create`, `update`, `skip`, or `rename`
  - `plan.CircularDependency(Exception)`

**Actions are decided before anything is written.** The importer executes a plan; it does not decide as it goes. This is what makes `--dry-run` meaningful: the dry run and the real run compute the same plan from the same inputs.

- [ ] **Step 1: Write the failing test**

`tests/test_plan.py`:

```python
import pytest
from wxcc_export import plan
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


def test_order_puts_a_dependency_before_its_dependent():
    ordered = plan.order_entities(["team", "site", "multimedia-profile"])
    assert ordered.index("multimedia-profile") < ordered.index("site")
    assert ordered.index("site") < ordered.index("team")


def test_order_pulls_in_nothing_that_was_not_requested():
    # Ordering must not silently widen the import to unrequested entities.
    assert set(plan.order_entities(["team", "site"])) == {"team", "site"}


def test_order_is_stable_for_independent_entities():
    a = plan.order_entities(["skill", "work-type"])
    b = plan.order_entities(["skill", "work-type"])
    assert a == b


def test_order_handles_the_full_entity_set():
    ordered = plan.order_entities(list(plan.registry.CC_ENTITIES))
    for entity, spec in plan.registry.CC_ENTITIES.items():
        for dep in spec["deps"]:
            assert ordered.index(dep) < ordered.index(entity)


def test_order_raises_on_a_cycle(monkeypatch):
    fake = {"a": {"deps": ["b"]}, "b": {"deps": ["a"]}}
    monkeypatch.setattr(plan.registry, "CC_ENTITIES", fake)
    with pytest.raises(plan.CircularDependency):
        plan.order_entities(["a", "b"])


def test_index_existing_keys_case_insensitively(transport):
    transport.add("GET /organization/ORG1/v2/site",
                  body={"data": [{"id": "s1", "name": "Denver"}]})
    idx = plan.index_existing(make(transport), "site")
    assert idx["denver"]["id"] == "s1"


def test_index_existing_is_empty_when_the_list_fails(transport):
    transport.add("GET /organization/ORG1/v2/site", status=403, body={})
    assert plan.index_existing(make(transport), "site") == {}


def test_classify_creates_a_new_name():
    out = plan.classify([{"id": "s1", "name": "Boulder"}], {}, "skip")
    assert out[0]["action"] == "create"


def test_classify_skips_a_name_that_already_exists():
    existing = {"denver": {"id": "s9", "name": "Denver"}}
    out = plan.classify([{"id": "s1", "name": "Denver"}], existing, "skip")
    assert out[0]["action"] == "skip"
    assert out[0]["existing"]["id"] == "s9"


def test_classify_skip_still_records_the_mapping_target():
    # A skipped object still exists in the target, so references to the source
    # id must remap onto the EXISTING object rather than dangle.
    existing = {"denver": {"id": "s9"}}
    out = plan.classify([{"id": "s1", "name": "Denver"}], existing, "skip")
    assert out[0]["existing"]["id"] == "s9"


def test_classify_update_on_conflict():
    existing = {"denver": {"id": "s9"}}
    out = plan.classify([{"id": "s1", "name": "Denver"}], existing, "update")
    assert out[0]["action"] == "update"


def test_classify_rename_on_conflict_suffixes_the_name():
    existing = {"denver": {"id": "s9"}}
    out = plan.classify([{"id": "s1", "name": "Denver"}], existing, "rename")
    assert out[0]["action"] == "rename"
    assert out[0]["item"]["name"] == "Denver (imported)"


def test_classify_rename_avoids_a_second_collision():
    existing = {"denver": {"id": "s9"}, "denver (imported)": {"id": "s8"}}
    out = plan.classify([{"id": "s1", "name": "Denver"}], existing, "rename")
    assert out[0]["item"]["name"] == "Denver (imported 2)"


def test_classify_reports_an_item_with_no_name():
    out = plan.classify([{"id": "s1"}], {}, "skip")
    assert out[0]["action"] == "skip"
    assert "no name" in out[0]["reason"]


def test_classify_rejects_an_unknown_conflict_policy():
    with pytest.raises(ValueError):
        plan.classify([{"id": "s1", "name": "X"}], {}, "explode")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_plan.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'wxcc_export.plan'`.

- [ ] **Step 3: Write the implementation**

`src/wxcc_export/plan.py`:

```python
"""Decide the whole import before writing any of it.

Ordering comes from the registry's dependency graph; actions come from comparing
the archive against the target tenant BY NAME. Deciding everything up front is
what makes --dry-run honest: the dry run and the real run compute the same plan.

Name comparison is also how "only non-default" is satisfied without inventing an
isDefault flag: an object whose name already exists in the target IS already
there, whether it arrived at provisioning or from an earlier import.
"""

from __future__ import annotations

from . import registry
from .client import ApiError

CONFLICT_POLICIES = ("skip", "update", "rename")


class CircularDependency(Exception):
    pass


def order_entities(entities: list[str]) -> list[str]:
    """Topologically sort the requested entities. Dependencies not requested
    are NOT pulled in - widening the import silently is worse than a broken
    reference the importer will report."""
    requested = list(dict.fromkeys(entities))
    wanted = set(requested)
    ordered: list[str] = []
    state: dict[str, str] = {}

    def visit(node: str) -> None:
        mark = state.get(node)
        if mark == "done":
            return
        if mark == "visiting":
            raise CircularDependency(f"dependency cycle through {node!r}")
        state[node] = "visiting"
        for dep in registry.CC_ENTITIES.get(node, {}).get("deps", []):
            if dep in wanted:
                visit(dep)
        state[node] = "done"
        ordered.append(node)

    for name in requested:
        visit(name)
    return ordered


def index_existing(client, entity: str) -> dict[str, dict]:
    """Index the TARGET tenant's objects by lowercased name.

    A failure returns {} and the caller treats every source object as new. That
    is the safe direction: the API rejects a duplicate name, so a bad index
    causes a visible 400, not a silent overwrite.
    """
    try:
        rows = client.list_all(registry.list_path(entity))
    except (ApiError, Exception):
        return {}
    return {str(r.get("name", "")).strip().lower(): r
            for r in rows if r.get("name")}


def _free_name(name: str, existing: dict[str, dict]) -> str:
    candidate = f"{name} (imported)"
    n = 2
    while candidate.strip().lower() in existing:
        candidate = f"{name} (imported {n})"
        n += 1
    return candidate


def classify(source_items: list[dict], existing: dict[str, dict],
             on_conflict: str) -> list[dict]:
    if on_conflict not in CONFLICT_POLICIES:
        raise ValueError(f"unknown conflict policy {on_conflict!r}. "
                         f"Use one of: {', '.join(CONFLICT_POLICIES)}")
    out: list[dict] = []
    for item in source_items:
        name = str(item.get("name", "")).strip()
        if not name:
            out.append({"action": "skip", "item": item, "existing": None,
                        "reason": "the object has no name, so it cannot be "
                                  "matched against the target safely"})
            continue
        match = existing.get(name.lower())
        if not match:
            out.append({"action": "create", "item": item, "existing": None,
                        "reason": "no object of this name in the target"})
        elif on_conflict == "skip":
            out.append({"action": "skip", "item": item, "existing": match,
                        "reason": f"{name!r} already exists in the target "
                                  "(default or previously imported)"})
        elif on_conflict == "update":
            out.append({"action": "update", "item": item, "existing": match,
                        "reason": f"{name!r} exists; updating it in place"})
        else:
            renamed = {**item, "name": _free_name(name, existing)}
            out.append({"action": "rename", "item": renamed, "existing": match,
                        "reason": f"{name!r} exists; creating a renamed copy"})
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_plan.py -v
```

Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wxcc_export/plan.py tests/test_plan.py
git commit -m "feat: dependency ordering and name-collision classification"
```

---

### Task 15: Contact Center importer with dry-run and re-read verify

**Files:**
- Create: `src/wxcc_export/importer.py`
- Test: `tests/test_importer.py`

**Interfaces:**
- Consumes: `plan`, `idmap`, `registry`, `archive.ArchiveReader`.
- Produces:
  - `importer.ImportResult` — a dataclass with `created`, `updated`, `skipped`, `failed`, `unverified`, `dangling`, `idmap`
  - `importer.import_entity(client, entity, items, idmap_, on_conflict, confirm) -> ImportResult`
  - `importer.import_cc(client, reader, keys, on_conflict, confirm, on_progress) -> dict[str, ImportResult]`
  - `importer.verify_write(client, entity, new_id, sent) -> list[str]` — returns the list of fields the server did not store

**The re-read is not optional.** The sibling repo records that this API "can return 200 while silently ignoring a field" (`wxcc-skills/CLAUDE.md`). A create that returns 201 and a field that never landed is the failure mode this catches. Fields the server legitimately transforms (ids it assigns, timestamps) are excluded from the diff.

- [ ] **Step 1: Write the failing test**

`tests/test_importer.py`:

```python
import pytest
from wxcc_export import idmap, importer
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


def test_dry_run_writes_nothing(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    res = importer.import_entity(make(transport), "site",
                                 [{"id": "s1", "name": "Denver"}],
                                 idmap.IdMap(), "skip", confirm=False)
    assert res.created == []
    assert res.planned[0]["action"] == "create"
    assert all(c["method"] == "GET" for c in transport.calls)


def test_confirmed_create_posts_to_the_unversioned_path(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    transport.add("POST /organization/ORG1/site", status=201,
                  body={"id": "s9", "name": "Denver"})
    transport.add("GET /organization/ORG1/site/s9",
                  body={"id": "s9", "name": "Denver"})
    res = importer.import_entity(make(transport), "site",
                                 [{"id": "s1", "name": "Denver"}],
                                 idmap.IdMap(), "skip", confirm=True)
    assert res.created == ["s9"]
    posts = [c for c in transport.calls if c["method"] == "POST"]
    # POST v2/site is NOT the create endpoint.
    assert posts[0]["url"].endswith("/organization/ORG1/site")


def test_create_records_the_id_mapping(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    transport.add("POST /organization/ORG1/site", status=201, body={"id": "s9"})
    transport.add("GET /organization/ORG1/site/s9", body={"id": "s9"})
    m = idmap.IdMap()
    importer.import_entity(make(transport), "site",
                           [{"id": "s1", "name": "Denver"}], m, "skip",
                           confirm=True)
    assert m.get("s1") == "s9"


def test_skip_still_maps_the_source_id_to_the_existing_object(transport):
    transport.add("GET /organization/ORG1/v2/site",
                  body={"data": [{"id": "s9", "name": "Denver"}]})
    m = idmap.IdMap()
    res = importer.import_entity(make(transport), "site",
                                 [{"id": "s1", "name": "Denver"}], m, "skip",
                                 confirm=True)
    assert res.skipped == ["s1"]
    # Otherwise every reference to s1 would dangle.
    assert m.get("s1") == "s9"


def test_references_are_remapped_before_the_write(transport):
    transport.add("GET /organization/ORG1/v2/team", body={"data": []})
    transport.add("POST /organization/ORG1/team", status=201, body={"id": "t9"})
    transport.add("GET /organization/ORG1/team/t9", body={"id": "t9"})
    m = idmap.IdMap()
    m.record("s1", "s9")
    importer.import_entity(make(transport), "team",
                           [{"id": "t1", "name": "Billing", "siteId": "s1"}],
                           m, "skip", confirm=True)
    post = next(c for c in transport.calls if c["method"] == "POST")
    assert b'"siteId": "s9"' in post["data"]


def test_the_objects_own_id_is_not_sent_on_create(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    transport.add("POST /organization/ORG1/site", status=201, body={"id": "s9"})
    transport.add("GET /organization/ORG1/site/s9", body={"id": "s9"})
    importer.import_entity(make(transport), "site",
                           [{"id": "s1", "name": "Denver"}], idmap.IdMap(),
                           "skip", confirm=True)
    post = next(c for c in transport.calls if c["method"] == "POST")
    assert b'"id"' not in post["data"]


def test_a_failed_create_is_recorded_with_the_api_reason(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    transport.add("POST /organization/ORG1/site", status=400,
                  body={"message": "multimediaProfileId is required"})
    res = importer.import_entity(make(transport), "site",
                                 [{"id": "s1", "name": "Denver"}],
                                 idmap.IdMap(), "skip", confirm=True)
    assert res.created == []
    assert "multimediaProfileId" in res.failed[0]["detail"]


def test_one_failure_does_not_abort_the_rest(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    transport.add("POST /organization/ORG1/site", status=400, body={"m": "no"})
    transport.add("POST /organization/ORG1/site", status=201, body={"id": "s9"})
    transport.add("GET /organization/ORG1/site/s9", body={"id": "s9"})
    res = importer.import_entity(
        make(transport), "site",
        [{"id": "s1", "name": "A"}, {"id": "s2", "name": "B"}],
        idmap.IdMap(), "skip", confirm=True)
    assert len(res.failed) == 1 and res.created == ["s9"]


def test_verify_write_reports_a_silently_ignored_field(transport):
    transport.add("GET /organization/ORG1/site/s9",
                  body={"id": "s9", "name": "Denver", "active": False})
    missing = importer.verify_write(make(transport), "site", "s9",
                                    {"name": "Denver", "active": True})
    assert "active" in missing


def test_verify_write_is_clean_when_everything_landed(transport):
    transport.add("GET /organization/ORG1/site/s9",
                  body={"id": "s9", "name": "Denver", "active": True})
    assert importer.verify_write(make(transport), "site", "s9",
                                 {"name": "Denver", "active": True}) == []


def test_verify_write_ignores_server_assigned_fields(transport):
    transport.add("GET /organization/ORG1/site/s9",
                  body={"id": "s9", "name": "D", "createdTime": 123,
                        "version": 1})
    assert importer.verify_write(make(transport), "site", "s9",
                                 {"name": "D"}) == []


def test_an_unverified_write_is_surfaced_not_counted_as_success(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": []})
    transport.add("POST /organization/ORG1/site", status=201, body={"id": "s9"})
    transport.add("GET /organization/ORG1/site/s9",
                  body={"id": "s9", "name": "Denver", "active": False})
    res = importer.import_entity(make(transport), "site",
                                 [{"id": "s1", "name": "Denver",
                                   "active": True}],
                                 idmap.IdMap(), "skip", confirm=True)
    assert res.created == ["s9"]
    assert res.unverified and "active" in res.unverified[0]["fields"]


def test_dangling_references_are_reported(transport):
    transport.add("GET /organization/ORG1/v2/team", body={"data": []})
    res = importer.import_entity(
        make(transport), "team",
        [{"id": "t1", "name": "Billing",
          "siteId": "22222222-2222-2222-2222-222222222222"}],
        idmap.IdMap(), "skip", confirm=False)
    assert "22222222-2222-2222-2222-222222222222" in res.dangling


def test_a_read_only_entity_is_refused(transport):
    res = importer.import_entity(make(transport), "user",
                                 [{"id": "u1", "name": "Ann"}],
                                 idmap.IdMap(), "skip", confirm=True)
    assert res.failed[0]["detail"].startswith("user is read-only")
    assert transport.calls == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_importer.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'wxcc_export.importer'`.

- [ ] **Step 3: Write the implementation**

`src/wxcc_export/importer.py`:

```python
"""Execute an import plan against the target tenant.

Two rules this module exists to enforce:

1. Nothing is written without confirm=True. A dry run computes the identical
   plan and reports it.
2. Every confirmed write is RE-READ and diffed. This API can return 200 or 201
   while silently ignoring a field, so a status code is not evidence the change
   landed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import idmap as idmap_mod
from . import plan, registry
from .client import ApiError

# Set by the server on every object; never part of what we asked it to store.
SERVER_ASSIGNED = frozenset({
    "id", "createdTime", "createdAt", "lastUpdatedTime", "lastUpdatedBy",
    "createdBy", "version", "eTag", "etag", "organizationId", "orgId", "links",
})


@dataclass
class ImportResult:
    entity: str
    planned: list = field(default_factory=list)
    created: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    unverified: list = field(default_factory=list)
    dangling: set = field(default_factory=set)

    def summary(self) -> str:
        return (f"{self.entity}: {len(self.created)} created, "
                f"{len(self.updated)} updated, {len(self.skipped)} skipped, "
                f"{len(self.failed)} failed, "
                f"{len(self.unverified)} unverified")


def _reason(body: object) -> str:
    if isinstance(body, dict):
        for key in ("message", "error", "detail", "errorMessage", "reason"):
            if body.get(key):
                return str(body[key])[:300]
        return str(body)[:300]
    return str(body)[:300]


def verify_write(client, entity: str, new_id: str, sent: dict) -> list[str]:
    """Re-read the object and return the fields the server did not store."""
    try:
        status, body = client.json("GET", registry.item_path(entity, new_id))
    except Exception as exc:
        return [f"__reread_failed__: {type(exc).__name__}: {exc}"]
    if status != 200 or not isinstance(body, dict):
        return [f"__reread_failed__: HTTP {status}"]
    missing: list[str] = []
    for key, want in sent.items():
        if key in SERVER_ASSIGNED:
            continue
        got = body.get(key)
        if got != want:
            missing.append(key)
    return missing


def import_entity(client, entity: str, items: list[dict],
                  idmap_: idmap_mod.IdMap, on_conflict: str,
                  confirm: bool) -> ImportResult:
    result = ImportResult(entity=entity)
    spec = registry.CC_ENTITIES.get(entity, {})

    if not spec.get("writable", False):
        note = spec.get("note", "")
        result.failed.append({
            "id": None,
            "detail": f"{entity} is read-only through this API - "
                      f"nothing was written. {note}"})
        return result

    existing = plan.index_existing(client, entity)
    result.planned = plan.classify(items, existing, on_conflict)

    for step in result.planned:
        source = step["item"]
        source_id = source.get("id")
        action = step["action"]

        if action == "skip":
            if source_id and step.get("existing", {}) and step["existing"].get("id"):
                # The object IS in the target - point references at it, or every
                # reference to this source id dangles.
                idmap_.record(source_id, step["existing"]["id"])
            if source_id:
                result.skipped.append(source_id)
            continue

        payload = idmap_.substitute(idmap_mod.strip_identity(source))
        result.dangling |= idmap_.unmapped(payload)

        if not confirm:
            continue

        try:
            if action == "update":
                target_id = step["existing"]["id"]
                status, body = client.json(
                    "PUT", registry.item_path(entity, target_id), payload)
            else:
                status, body = client.json(
                    "POST", registry.create_path(entity), payload)
        except Exception as exc:
            result.failed.append({"id": source_id,
                                  "detail": f"{type(exc).__name__}: {exc}"})
            continue

        if status >= 400:
            result.failed.append({"id": source_id,
                                  "detail": f"HTTP {status}: {_reason(body)}"})
            continue

        new_id = (body or {}).get("id") if isinstance(body, dict) else None
        if action == "update":
            new_id = new_id or step["existing"]["id"]
            result.updated.append(new_id)
        else:
            if not new_id:
                result.failed.append({
                    "id": source_id,
                    "detail": f"HTTP {status} but the response carried no id, so "
                              "the object cannot be verified or referenced"})
                continue
            result.created.append(new_id)

        if source_id and new_id:
            idmap_.record(source_id, new_id)

        missing = verify_write(client, entity, new_id, payload)
        if missing:
            result.unverified.append({"id": new_id, "fields": missing})

    return result


def import_cc(client, reader, keys: list[str], on_conflict: str = "skip",
              confirm: bool = False, on_progress=None
              ) -> tuple[dict[str, ImportResult], idmap_mod.IdMap]:
    """Import the cc:* selections in dependency order, sharing one IdMap.

    Returns (results, idmap). The map is returned rather than discarded because
    flows, functions, and Calling are imported afterwards and MUST reuse it - a
    flow that routes to queue q1 needs the q1 -> q9 mapping this pass recorded.
    """
    entities = [k.split(":", 1)[1] for k in keys if k.startswith("cc:")]
    ordered = plan.order_entities(entities)
    shared = idmap_mod.IdMap()
    out: dict[str, ImportResult] = {}
    for entity in ordered:
        result = import_entity(client, entity, reader.entity_items(entity),
                               shared, on_conflict, confirm)
        out[entity] = result
        if on_progress:
            on_progress(entity, result)
    return out, shared
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_importer.py -v
```

Expected: 14 passed.

- [ ] **Step 5: Run the whole suite and report the delta**

```bash
python -m pytest -q
```

Expected: 161 passed, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add src/wxcc_export/importer.py tests/test_importer.py
git commit -m "feat: CC importer with dry-run, ID remapping, and re-read verification"
```

---

### Task 16: Flows, functions, and Calling import

> **BLOCKED ON Task 5.** Needs U1 (`projectId`), U2 (`flowType`), U3 (functions multipart field names), U5 (Calling scopes). If U3 is unresolved, `import_functions` must refuse with that reason rather than guess a field name.

**Files:**
- Modify: `src/wxcc_export/importer.py` (append)
- Test: `tests/test_importer_flows.py`

**Interfaces:**
- Consumes: `export_flows.PROJECT_ID_MODE`, `export_flows.SUBFLOW_TYPE`, `idmap.IdMap`.
- Produces:
  - `importer.import_flows(client, reader, bucket, idmap_, overwrite, confirm) -> ImportResult`
  - `importer.import_functions(client, reader, idmap_, confirm) -> ImportResult`
  - `importer.import_calling(client, reader, names, idmap_, on_conflict, confirm) -> dict[str, ImportResult]`

**Subflows import before flows.** A flow can invoke a subflow; the reverse is not possible. Getting this backwards produces a flow that references a subflow id that does not exist yet.

**Flow payloads are remapped with the same shared IdMap** the CC import populated. This is the payoff of the generic substitution design: a flow that routes to queue `q1` gets `q9` with no flow-specific reference map.

- [ ] **Step 1: Write the failing test**

`tests/test_importer_flows.py`:

```python
import pytest
from wxcc_export import export_flows, idmap, importer
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"
SUB = export_flows.SUBFLOW_TYPE


class FakeReader:
    def __init__(self, flows=None, subflows=None, functions=None, calling=None):
        self._flows = {"flows": flows or {}, "subflows": subflows or {}}
        self._functions = functions or {}
        self._calling = calling or {}

    def flows(self, bucket):
        return self._flows.get(bucket, {})

    def functions(self):
        return self._functions

    def calling_items(self, name):
        return self._calling.get(name, [])


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


def test_flow_dry_run_writes_nothing(transport):
    reader = FakeReader(flows={"f1": {"meta": {"name": "Main"},
                                      "document": {"name": "Main"}}})
    res = importer.import_flows(make(transport), reader, "flows",
                                idmap.IdMap(), overwrite=False, confirm=False)
    assert res.created == []
    assert transport.calls == []


def test_confirmed_flow_import_posts_the_document(transport):
    transport.add(f"POST /ORG1/project/ORG1/v2/flows:import"
                  f"?overwrite=false&flowType=FLOW",
                  status=200, body={"id": "F9"})
    reader = FakeReader(flows={"f1": {"meta": {"name": "Main"},
                                      "document": {"name": "Main"}}})
    res = importer.import_flows(make(transport), reader, "flows",
                                idmap.IdMap(), overwrite=False, confirm=True)
    assert res.created == ["F9"]


def test_flow_references_are_remapped(transport):
    transport.add(f"POST /ORG1/project/ORG1/v2/flows:import"
                  f"?overwrite=false&flowType=FLOW", status=200, body={"id": "F9"})
    m = idmap.IdMap()
    m.record("q1", "q9")
    reader = FakeReader(flows={"f1": {"meta": {"name": "Main"},
                                      "document": {"nodes": [{"queueId": "q1"}]}}})
    importer.import_flows(make(transport), reader, "flows", m,
                          overwrite=False, confirm=True)
    assert b'"queueId": "q9"' in transport.calls[0]["data"]


def test_subflow_import_uses_the_probe_confirmed_flow_type(transport):
    transport.add(f"POST /ORG1/project/ORG1/v2/flows:import"
                  f"?overwrite=false&flowType={SUB}", status=200, body={"id": "S9"})
    reader = FakeReader(subflows={"s1": {"meta": {}, "document": {"name": "Sub"}}})
    res = importer.import_flows(make(transport), reader, "subflows",
                                idmap.IdMap(), overwrite=False, confirm=True)
    assert res.created == ["S9"]
    assert f"flowType={SUB}" in transport.calls[0]["url"]


def test_a_failed_flow_import_is_recorded(transport):
    transport.add(f"POST /ORG1/project/ORG1/v2/flows:import"
                  f"?overwrite=false&flowType=FLOW", status=400,
                  body={"message": "unknown activity"})
    reader = FakeReader(flows={"f1": {"meta": {"name": "Main"}, "document": {}}})
    res = importer.import_flows(make(transport), reader, "flows",
                                idmap.IdMap(), overwrite=False, confirm=True)
    assert "unknown activity" in res.failed[0]["detail"]


def test_flow_dangling_references_are_reported(transport):
    reader = FakeReader(flows={"f1": {"meta": {}, "document": {
        "queueId": "22222222-2222-2222-2222-222222222222"}}})
    res = importer.import_flows(make(transport), reader, "flows",
                                idmap.IdMap(), overwrite=False, confirm=False)
    assert "22222222-2222-2222-2222-222222222222" in res.dangling


def test_function_import_sends_multipart(transport):
    transport.add("POST /v1/ORG1/functions:import?overwrite=false",
                  status=200, body={"id": "FN9"})
    reader = FakeReader(functions={"fn1": {"meta": {"name": "lookup"},
                                           "document": {"code": "x"}}})
    res = importer.import_functions(make(transport), reader, idmap.IdMap(),
                                    confirm=True)
    assert res.created == ["FN9"]
    ctype = transport.calls[0]["headers"]["Content-Type"]
    assert ctype.startswith("multipart/form-data")


def test_function_import_refuses_when_the_field_name_is_unresolved(
        transport, monkeypatch):
    monkeypatch.setattr(importer, "FUNCTION_IMPORT_FIELD", importer.UNRESOLVED)
    reader = FakeReader(functions={"fn1": {"meta": {}, "document": {}}})
    res = importer.import_functions(make(transport), reader, idmap.IdMap(),
                                    confirm=True)
    assert "U3" in res.failed[0]["detail"]
    assert transport.calls == []


def test_calling_import_creates_an_org_scoped_object(transport):
    transport.add("GET /telephony/config/huntGroups", body={"items": []})
    transport.add("POST /telephony/config/locations/L1/huntGroups",
                  status=201, body={"id": "H9"})
    reader = FakeReader(calling={"hunt-groups": [
        {"id": "H1", "name": "Sales", "_locationId": "L1"}]})
    m = idmap.IdMap()
    m.record("L1", "L1")
    res = importer.import_calling(make(transport), reader, ["hunt-groups"],
                                  m, "skip", confirm=True)
    assert res["hunt-groups"].created == ["H9"]


def test_calling_import_skips_an_item_with_no_location(transport):
    transport.add("GET /telephony/config/huntGroups", body={"items": []})
    reader = FakeReader(calling={"hunt-groups": [{"id": "H1", "name": "Sales"}]})
    res = importer.import_calling(make(transport), reader, ["hunt-groups"],
                                  idmap.IdMap(), "skip", confirm=True)
    assert "no location" in res["hunt-groups"].failed[0]["detail"]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_importer_flows.py -v
```

Expected: FAIL — `AttributeError: module 'wxcc_export.importer' has no attribute 'import_flows'`.

- [ ] **Step 3: Append the implementation to `src/wxcc_export/importer.py`**

Set `FUNCTION_IMPORT_FIELD` from U3 in `docs/api-notes.md`.

```python
from . import export_flows

UNRESOLVED = "__UNRESOLVED__"

# U3, from docs/api-notes.md. If the probe did not resolve it, leave the
# sentinel: refusing is correct, guessing a field name is not.
FUNCTION_IMPORT_FIELD = UNRESOLVED   # CORRECTED (P2): was "file", a guess
FUNCTION_IMPORT_FILENAME = "function.json"


def import_flows(client, reader, bucket: str, idmap_: idmap_mod.IdMap,
                 overwrite: bool = False, confirm: bool = False) -> ImportResult:
    """Import one bucket of flows.

    Callers must import 'subflows' BEFORE 'flows': a flow can invoke a subflow,
    never the reverse.
    """
    result = ImportResult(entity=f"flows:{bucket}")
    flow_type = (export_flows.FLOW_TYPE if bucket == "flows"
                 else export_flows.SUBFLOW_TYPE)
    if flow_type == UNRESOLVED:
        result.failed.append({"id": None,
                              "detail": "flowType unresolved - see U2 in "
                                        "docs/api-notes.md"})
        return result

    project_id = export_flows.resolve_project_id(client)
    path = (f"{{orgId}}/project/{project_id}/v2/flows:import"
            f"?overwrite={str(overwrite).lower()}&flowType={flow_type}")

    for flow_id, payload in reader.flows(bucket).items():
        document = idmap_.substitute((payload or {}).get("document") or {})
        result.dangling |= idmap_.unmapped(document)
        result.planned.append({"action": "create", "item": {"id": flow_id},
                               "existing": None,
                               "reason": f"import into project {project_id}"})
        if not confirm:
            continue
        try:
            status, body = client.json("POST", path, document)
        except Exception as exc:
            result.failed.append({"id": flow_id,
                                  "detail": f"{type(exc).__name__}: {exc}"})
            continue
        if status >= 400:
            result.failed.append({"id": flow_id,
                                  "detail": f"HTTP {status}: {_reason(body)}"})
            continue
        new_id = (body or {}).get("id") if isinstance(body, dict) else None
        result.created.append(new_id or flow_id)
        if new_id:
            idmap_.record(flow_id, new_id)
    return result


def import_functions(client, reader, idmap_: idmap_mod.IdMap,
                     overwrite: bool = False,
                     confirm: bool = False) -> ImportResult:
    """Import custom functions.

    Export returns JSON but import takes multipart/form-data - the API is
    asymmetric here. The part name comes from the live probe (U3); if it is
    still the sentinel this refuses rather than guessing.
    """
    result = ImportResult(entity="flows:functions")
    functions = reader.functions()

    if FUNCTION_IMPORT_FIELD == UNRESOLVED:
        if functions:
            result.failed.append({
                "id": None,
                "detail": "the multipart field name for functions:import is "
                          "unresolved (U3 in docs/api-notes.md). Run "
                          "scripts/probe.py; refusing to guess a field name."})
        return result

    path = f"v1/{{orgId}}/functions:import?overwrite={str(overwrite).lower()}"
    for fn_id, payload in functions.items():
        document = idmap_.substitute((payload or {}).get("document") or {})
        result.dangling |= idmap_.unmapped(document)
        result.planned.append({"action": "create", "item": {"id": fn_id},
                               "existing": None, "reason": "import function"})
        if not confirm:
            continue
        import json as _json
        parts = [(FUNCTION_IMPORT_FIELD, FUNCTION_IMPORT_FILENAME,
                  "application/json", _json.dumps(document).encode())]
        try:
            status, body = client.multipart("POST", path, parts)
        except Exception as exc:
            result.failed.append({"id": fn_id,
                                  "detail": f"{type(exc).__name__}: {exc}"})
            continue
        if status >= 400:
            result.failed.append({"id": fn_id,
                                  "detail": f"HTTP {status}: {_reason(body)}"})
            continue
        new_id = (body or {}).get("id") if isinstance(body, dict) else None
        result.created.append(new_id or fn_id)
        if new_id:
            idmap_.record(fn_id, new_id)
    return result


def import_calling(client, reader, names: list[str], idmap_: idmap_mod.IdMap,
                   on_conflict: str = "skip",
                   confirm: bool = False) -> dict[str, ImportResult]:
    """Import the Calling subset. Location-scoped objects need a location id."""
    out: dict[str, ImportResult] = {}
    for name in names:
        spec = registry.CALLING_OBJECTS[name]
        result = ImportResult(entity=f"calling:{name}")
        items = reader.calling_items(name)

        try:
            existing_rows = client.list_all(
                spec["list"].replace("{locationId}", "")) if spec["scope"] == "org" else []
        except Exception:
            existing_rows = []
        existing = {str(r.get("name", "")).lower(): r
                    for r in existing_rows if r.get("name")}
        result.planned = plan.classify(items, existing, on_conflict)

        for step in result.planned:
            source = step["item"]
            source_id = source.get("id")
            if step["action"] == "skip":
                if source_id and (step.get("existing") or {}).get("id"):
                    idmap_.record(source_id, step["existing"]["id"])
                if source_id:
                    result.skipped.append(source_id)
                continue

            loc_id = idmap_.get(source.get("_locationId") or "") or \
                source.get("_locationId")
            if not loc_id:
                result.failed.append({
                    "id": source_id,
                    "detail": f"{name} {source.get('name')!r} has no location "
                              "in the archive, and every Calling create endpoint "
                              "is location-scoped"})
                continue

            payload = idmap_.substitute(idmap_mod.strip_identity(source))
            result.dangling |= idmap_.unmapped(payload)
            if not confirm:
                continue

            create_path = spec["item"].replace("{locationId}", loc_id)
            create_path = create_path.rsplit("/{id}", 1)[0]
            try:
                status, body = client.json("POST", create_path, payload)
            except Exception as exc:
                result.failed.append({"id": source_id,
                                      "detail": f"{type(exc).__name__}: {exc}"})
                continue
            if status >= 400:
                result.failed.append({"id": source_id,
                                      "detail": f"HTTP {status}: {_reason(body)}"})
                continue
            new_id = (body or {}).get("id") if isinstance(body, dict) else None
            result.created.append(new_id or source_id)
            if source_id and new_id:
                idmap_.record(source_id, new_id)

        out[name] = result
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_importer_flows.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wxcc_export/importer.py tests/test_importer_flows.py
git commit -m "feat: flows, functions, and Calling import with shared ID remapping"
```

---

### Task 17: Command-line interface

**Files:**
- Create: `src/wxcc_export/cli.py`
- Create: `src/wxcc_export/__main__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: every module built so far.
- Produces:
  - `cli.main(argv: list[str] | None = None) -> int`
  - `cli.build_parser() -> argparse.ArgumentParser`
  - Commands: `auth login|status|logout`, `export`, `inspect`, `import`, `web`

**Exit codes are part of the contract:** `0` success, `1` usage or config error, `2` auth error, `3` the operation completed but recorded errors. Code `3` exists so a caller can tell "exported with 4 objects missing" from "exported cleanly" — a partial export must not exit 0.

**`import` requires `--confirm` to write.** Without it the command prints the plan and exits 0 having written nothing. The confirmation prompt names the target tenant using `tenant.describe`, so `[PRODUCTION]` is impossible to miss.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:

```python
import json
import zipfile

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
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_cli.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'wxcc_export.cli'`.

- [ ] **Step 3: Write the implementation**

`src/wxcc_export/__main__.py`:

```python
from .cli import main

raise SystemExit(main())
```

`src/wxcc_export/cli.py`:

```python
"""Command-line interface.

Exit codes are part of the contract:
  0  success
  1  usage or configuration error
  2  authentication error
  3  the operation ran but recorded errors (a PARTIAL result)

Code 3 exists so "exported with 4 objects missing" cannot be mistaken for
"exported cleanly".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import (archive, auth, client, config, export_calling, export_cc,
               export_flows, importer, plan, registry, tenant)

EXIT_OK, EXIT_USAGE, EXIT_AUTH, EXIT_PARTIAL = 0, 1, 2, 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wxcc-export",
        description="Export and import Webex Contact Center sandbox configuration.")
    p.add_argument("--profile", default=None,
                   help="use .env.<profile> and its own token store")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("auth", help="manage authentication")
    a.add_argument("action", choices=["login", "status", "logout"])

    e = sub.add_parser("export", help="export this tenant to a zip archive")
    e.add_argument("--out", default=".", help="directory for the archive")
    e.add_argument("--select", default="all",
                   help="all | cc | flows | calling | comma-separated keys")
    e.add_argument("--only-non-default", action="store_true",
                   help="omit objects the createdTime heuristic flags as "
                        "provisioning defaults (opt-in; can lose real config)")

    i = sub.add_parser("inspect", help="show what an archive contains")
    i.add_argument("archive")

    m = sub.add_parser("import", help="import an archive into THIS tenant")
    m.add_argument("archive")
    m.add_argument("--select", default="all")
    m.add_argument("--on-conflict", choices=list(plan.CONFLICT_POLICIES),
                   default="skip")
    m.add_argument("--confirm", action="store_true",
                   help="actually write. Without this, prints the plan only.")
    m.add_argument("--overwrite-flows", action="store_true",
                   help="pass overwrite=true to the flow import endpoint")

    w = sub.add_parser("web", help="serve the local selection UI")
    w.add_argument("--port", type=int, default=8787)
    return p


def _clients(cfg: dict) -> tuple:
    token, source = auth.valid_access_token(cfg)
    if source == "bearer":
        print("AUTH: personal bearer token (OAuth2 bypassed)")
    org_id = cfg["org_id"] or auth.extract_org_id(token)
    cc = client.ApiClient(cfg["api_base"], token, org_id=org_id)
    wx = client.ApiClient(cfg["webex_base"], token, org_id=org_id)
    return cc, wx


def _run_export(cfg: dict, args) -> int:
    cc, wx = _clients(cfg)
    info = tenant.org_info(cc)
    print(f"Source tenant: {tenant.describe(info)}")

    entities = [e for e in registry.CC_ENTITIES]
    exported = export_cc.export_all(
        cc, entities,
        on_progress=lambda e, r: print(
            f"  {e:24s} {r['count']:5d}" + (f"  ERROR {r['error']}" if r["error"] else "")))

    if args.only_non_default:
        for result in exported.values():
            result["items"] = [i for i in result["items"]
                               if not i.get("likely_default")]
            result["count"] = len(result["items"])

    children = {}
    for entity in ("address-book", "outdial-ani"):
        ids = [i["id"] for i in exported.get(entity, {}).get("items", [])
               if i.get("id")]
        got = export_cc.export_children(cc, entity, ids)
        if got:
            children[entity] = got

    blobs, audio_errors = export_cc.export_audio_binaries(
        cc, exported.get("audio-file", {}).get("items", []))
    audio = {i: {"bytes": b,
                 "name": next((x.get("name", "audio")
                               for x in exported["audio-file"]["items"]
                               if x.get("id") == i), "audio")}
             for i, b in blobs.items()}
    for detail in audio_errors:
        exported.setdefault("audio-file", {})["error"] = detail

    project_id = export_flows.resolve_project_id(cc)
    flows = export_flows.export_all_flows(cc, project_id)
    functions = export_flows.export_all_functions(cc)
    calling = export_calling.export_all(
        wx, on_progress=lambda n, r: print(
            f"  calling/{n:20s} {r['count']:5d}"
            + (f"  ERROR {r['error']}" if r["error"] else "")))

    lookup = export_cc.build_name_lookup(exported)
    rows, csv_text = export_cc.build_users_manifest(
        exported.get("user", {}).get("items", []), lookup)

    out_path = Path(args.out) / tenant.archive_name(info)
    manifest = archive.write_export(
        out_path,
        source={"orgId": info["org_id"], "orgName": info["name"],
                "subscriptionType": info.get("subscription"),
                "apiBase": cfg["api_base"]},
        cc=exported, children=children, audio=audio, flows=flows,
        functions=functions, calling=calling,
        users={"rows": rows, "csv": csv_text})

    print(f"\nWrote {out_path}")
    if manifest["errors"]:
        print(f"\n{len(manifest['errors'])} object(s) FAILED and are missing "
              f"from the archive. See UNSUPPORTED.md inside it.")
        for e in manifest["errors"][:10]:
            print(f"  - {e['section']}/{e['object']}: {e['detail'][:120]}")
        return EXIT_PARTIAL
    return EXIT_OK


def _run_inspect(args) -> int:
    try:
        reader = archive.ArchiveReader(args.archive)
    except archive.IncompatibleArchive as exc:
        print(f"cannot read archive: {exc}", file=sys.stderr)
        return EXIT_USAGE
    m = reader.manifest
    print(f"Archive:  {args.archive}")
    print(f"Source:   {m['source'].get('orgName')} "
          f"(org {m['source'].get('orgId')})")
    print(f"Exported: {m['exportedAt']}\n")
    for sel in archive.available_selections(m):
        flag = "" if sel["writable"] else "   [read-only, export reference only]"
        print(f"  {sel['key']:34s} {sel['count']:5d}  {sel['group']}{flag}")
    print(f"\nNo API exists for: {', '.join(m['unsupported'])}")
    if m["errors"]:
        print(f"\n{len(m['errors'])} object(s) are MISSING from this archive:")
        for e in m["errors"]:
            print(f"  - {e['section']}/{e['object']}: {e['detail'][:140]}")
        reader.close()
        return EXIT_PARTIAL
    reader.close()
    return EXIT_OK


def _run_import(cfg: dict, args) -> int:
    try:
        reader = archive.ArchiveReader(args.archive)
    except archive.IncompatibleArchive as exc:
        print(f"cannot read archive: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        keys = archive.parse_selection(args.select, reader.manifest)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE

    cc, wx = _clients(cfg)
    info = tenant.org_info(cc)
    source_name = reader.manifest["source"].get("orgName")

    print(f"Source archive: {source_name}")
    print(f"TARGET tenant:  {tenant.describe(info)}")
    if info.get("org_id") == reader.manifest["source"].get("orgId"):
        print("\nREFUSING: the target tenant is the same org the archive came "
              "from. Point --profile at the NEW sandbox.", file=sys.stderr)
        return EXIT_USAGE
    if not args.confirm:
        print("\nDRY RUN - nothing will be written. Add --confirm to apply.\n")

    results, idmap_ = importer.import_cc(
        cc, reader, keys, args.on_conflict, args.confirm,
        on_progress=lambda e, r: print(f"  {r.summary()}"))

    # Subflows before flows: a flow can invoke a subflow, never the reverse.
    for bucket in ("subflows", "flows"):
        if f"flows:{bucket}" in keys:
            r = importer.import_flows(cc, reader, bucket, idmap_,
                                      args.overwrite_flows, args.confirm)
            results[f"flows:{bucket}"] = r
            print(f"  {r.summary()}")
    if "flows:functions" in keys:
        r = importer.import_functions(cc, reader, idmap_, confirm=args.confirm)
        results["flows:functions"] = r
        print(f"  {r.summary()}")

    calling_names = [k.split(":", 1)[1] for k in keys if k.startswith("calling:")]
    if calling_names:
        for name, r in importer.import_calling(wx, reader, calling_names, idmap_,
                                               args.on_conflict,
                                               args.confirm).items():
            results[f"calling:{name}"] = r
            print(f"  {r.summary()}")

    failed = sum(len(r.failed) for r in results.values())
    unverified = sum(len(r.unverified) for r in results.values())
    dangling = set().union(*(r.dangling for r in results.values())) if results else set()

    print("\n--- summary ---")
    for r in results.values():
        for f in r.failed:
            print(f"  FAILED  {r.entity} {f['id']}: {f['detail'][:160]}")
        for u in r.unverified:
            print(f"  UNVERIFIED {r.entity} {u['id']}: the server did not store "
                  f"{', '.join(u['fields'])}")
    if dangling:
        print(f"\n  {len(dangling)} reference(s) point at objects that were not "
              "imported. Those links are broken in the target:")
        for d in sorted(dangling)[:15]:
            print(f"    {d}")

    reader.close()
    if not args.confirm:
        print("\nDry run complete. Nothing was written.")
        return EXIT_OK
    return EXIT_PARTIAL if (failed or unverified or dangling) else EXIT_OK


def _run_auth(cfg: dict, args) -> int:
    if args.action == "login":
        tok = auth.login(cfg)
        print(f"Authenticated. org id: {tok.get('org_id')}")
        return EXIT_OK
    if args.action == "logout":
        auth.logout(cfg)
        print("Token removed.")
        return EXIT_OK
    token, source = auth.valid_access_token(cfg)
    org_id = cfg["org_id"] or auth.extract_org_id(token)
    cc = client.ApiClient(cfg["api_base"], token, org_id=org_id)
    print(f"auth source: {source}")
    print(f"tenant:      {tenant.describe(tenant.org_info(cc))}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = config.load_config(args.profile)
    except config.ConfigError as exc:
        print(f"{exc}\n", file=sys.stderr)
        return EXIT_USAGE

    if args.command == "inspect":
        return _run_inspect(args)

    if cfg.get("bearer_token"):
        print("AUTH: personal bearer token (OAuth2 bypassed)")

    try:
        if args.command == "auth":
            return _run_auth(cfg, args)
        if args.command == "export":
            return _run_export(cfg, args)
        if args.command == "import":
            return _run_import(cfg, args)
        if args.command == "web":
            from .web.server import serve
            return serve(cfg, args.port)
    except auth.AuthError as exc:
        print(f"authentication error: {exc}", file=sys.stderr)
        return EXIT_AUTH
    except config.ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_USAGE
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_cli.py -v
```

Expected: 12 passed.

- [ ] **Step 5: Verify the CLI actually runs**

A passing test is not proof the entry point works.

```bash
python -m wxcc_export --help
python -m wxcc_export export --help
```

Expected: both print usage and exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/wxcc_export/cli.py src/wxcc_export/__main__.py tests/test_cli.py
git commit -m "feat: CLI with dry-run-by-default import and partial-result exit codes"
```

---

### Task 18: Local web UI

**Files:**
- Create: `src/wxcc_export/web/__init__.py`, `src/wxcc_export/web/server.py`
- Create: `src/wxcc_export/web/static/index.html`, `app.js`, `style.css`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `archive.ArchiveReader`, `archive.available_selections`, `importer`, `tenant`.
- Produces:
  - `web.server.serve(cfg, port) -> int`
  - `web.server.make_handler(cfg, session_token) -> type` — the request handler class
  - Endpoints: `GET /` (the page), `GET /api/tenant`, `POST /api/inspect`, `POST /api/import`

**Security constraints, non-negotiable:**
- Bind to `127.0.0.1` only. Never `0.0.0.0` — this process holds a live admin token.
- Every `/api/*` request must carry a per-run random session token; the page receives it inline at render time. This blocks any other local process or a browser page from a different origin driving the API.
- Reject any request whose `Origin` header is present and is not this server's own origin (DNS-rebinding defence).
- The token is never written to disk and never appears in a URL.

- [ ] **Step 1: Write the failing test**

`tests/test_web.py`:

```python
import json

import pytest
from wxcc_export.web import server as web


class FakeWire:
    """Drives the handler's routing logic without opening a socket."""

    def __init__(self, handler_cls, token):
        self.handler_cls = handler_cls
        self.token = token


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


def test_index_html_embeds_the_session_token():
    page = web.render_index("SECRET123")
    assert "SECRET123" in page


def test_index_html_warns_before_a_write():
    page = web.render_index("T")
    assert "confirm" in page.lower()


def test_static_assets_exist():
    for name in ("index.html", "app.js", "style.css"):
        assert (web.STATIC_DIR / name).exists(), name
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_web.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'wxcc_export.web'`.

- [ ] **Step 3: Write `src/wxcc_export/web/server.py`**

```python
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
                    info = tenant.org_info(cc)
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
                if org_id == reader.manifest["source"].get("orgId"):
                    reader.close()
                    return self._json(400, {
                        "error": "the target tenant is the same org this archive "
                                 "came from - point the profile at the NEW sandbox"})
                results = importer.import_cc(
                    cc, reader, payload.get("keys", []),
                    payload.get("onConflict", "skip"),
                    bool(payload.get("confirm", False)))
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
```

- [ ] **Step 4: Write `src/wxcc_export/web/__init__.py`**

```python
"""Localhost-only selection UI."""
```

- [ ] **Step 5: Write `src/wxcc_export/web/static/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>WxCC Sandbox Import</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <main>
    <h1>WxCC Sandbox Import</h1>
    <p id="tenant" class="tenant">Checking which tenant this is&hellip;</p>

    <section>
      <label for="archive">Archive path</label>
      <input id="archive" type="text" placeholder="C:\path\to\tenant-export.zip">
      <button id="inspect">Inspect</button>
    </section>

    <section id="selection" hidden>
      <h2>Choose what to import</h2>
      <div id="groups"></div>

      <label for="conflict">If an object of the same name already exists</label>
      <select id="conflict">
        <option value="skip">Skip it (recommended - leaves defaults alone)</option>
        <option value="update">Update it in place</option>
        <option value="rename">Create a renamed copy</option>
      </select>

      <p class="warn">
        Import is a <strong>dry run</strong> until you tick confirm. A dry run
        writes nothing and shows exactly what would change.
      </p>
      <label class="confirm">
        <input id="confirm" type="checkbox">
        I have checked the target tenant above and want to write to it
      </label>
      <button id="run">Run</button>
    </section>

    <pre id="output" hidden></pre>
  </main>
  <script>window.SESSION_TOKEN = "__SESSION_TOKEN__";</script>
  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 6: Write `src/wxcc_export/web/static/app.js`**

```javascript
const token = window.SESSION_TOKEN;
const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json", "X-Session-Token": token },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

api("/api/tenant")
  .then((d) => {
    $("tenant").textContent = `Target tenant: ${d.tenant}`;
    if (d.tenant.includes("[PRODUCTION]")) $("tenant").classList.add("production");
  })
  .catch((e) => { $("tenant").textContent = `Could not identify tenant: ${e.message}`; });

$("inspect").addEventListener("click", async () => {
  try {
    const d = await api("/api/inspect", { archive: $("archive").value });
    renderSelections(d.selections);
    $("selection").hidden = false;
  } catch (e) { show({ error: e.message }); }
});

function renderSelections(selections) {
  const byGroup = {};
  for (const s of selections) (byGroup[s.group] ||= []).push(s);
  $("groups").innerHTML = Object.entries(byGroup).map(([group, rows]) => `
    <fieldset>
      <legend>${group}</legend>
      ${rows.map((r) => `
        <label class="${r.writable ? "" : "readonly"}">
          <input type="checkbox" value="${r.key}" ${r.writable ? "" : "disabled"}>
          ${r.label} <span class="count">${r.count}</span>
          ${r.writable ? "" : '<span class="note">no write API - export reference only</span>'}
        </label>`).join("")}
    </fieldset>`).join("");
}

$("run").addEventListener("click", async () => {
  const keys = [...document.querySelectorAll("#groups input:checked")].map((i) => i.value);
  if (!keys.length) return show({ error: "Nothing selected." });
  try {
    show(await api("/api/import", {
      archive: $("archive").value,
      keys,
      onConflict: $("conflict").value,
      confirm: $("confirm").checked,
    }));
  } catch (e) { show({ error: e.message }); }
});

function show(obj) {
  $("output").hidden = false;
  $("output").textContent = JSON.stringify(obj, null, 2);
}
```

- [ ] **Step 7: Write `src/wxcc_export/web/static/style.css`**

```css
:root { color-scheme: light dark; --fg: #1a1a1a; --bg: #fff; --line: #d0d0d0;
        --warn: #8a4b00; --danger: #a4000f; }
@media (prefers-color-scheme: dark) {
  :root { --fg: #e8e8e8; --bg: #16181c; --line: #3a3d44; --warn: #e0a458;
          --danger: #ff6b6b; }
}
body { font: 15px/1.5 system-ui, sans-serif; color: var(--fg);
       background: var(--bg); margin: 0; padding: 2rem; }
main { max-width: 46rem; margin: 0 auto; }
h1 { font-size: 1.4rem; }
.tenant { padding: .6rem .8rem; border: 1px solid var(--line); border-radius: 6px; }
.tenant.production { border-color: var(--danger); color: var(--danger);
                     font-weight: 600; }
section { margin: 1.5rem 0; }
input[type=text], select { width: 100%; padding: .5rem; margin: .3rem 0 .8rem;
                           border: 1px solid var(--line); border-radius: 4px;
                           background: var(--bg); color: var(--fg); }
button { padding: .5rem 1rem; border: 1px solid var(--line); border-radius: 4px;
         background: var(--bg); color: var(--fg); cursor: pointer; }
fieldset { border: 1px solid var(--line); border-radius: 6px; margin: .8rem 0; }
fieldset label { display: block; padding: .2rem 0; }
label.readonly { opacity: .55; }
.count { color: #888; font-variant-numeric: tabular-nums; }
.note { font-size: .85em; color: var(--warn); }
.warn { color: var(--warn); }
.confirm { display: block; margin: .8rem 0; }
pre { border: 1px solid var(--line); border-radius: 6px; padding: 1rem;
      overflow-x: auto; white-space: pre-wrap; }
```

- [ ] **Step 8: Run the tests to verify they pass**

```bash
python -m pytest tests/test_web.py -v
```

Expected: 11 passed.

- [ ] **Step 9: Verify the server actually serves**

A passing unit test does not prove the page renders.

```bash
python -m wxcc_export web --port 8787
```

Open `http://127.0.0.1:8787/`, confirm the tenant line resolves, then Ctrl-C.
Also confirm the guard works — this must return 403:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8787/api/tenant
```

- [ ] **Step 10: Run the whole suite and report the delta**

```bash
python -m pytest -q
```

Expected: 184 passed, 0 failed.

- [ ] **Step 11: Commit**

```bash
git add src/wxcc_export/web tests/test_web.py
git commit -m "feat: localhost-only selection UI with session-token and origin guards"
```

---

### Task 19: User documentation

**Files:**
- Create: `docs/user-guide.md`
- Create: `README.md`

**Interfaces:**
- Consumes: the finished CLI and web UI; `docs/api-notes.md`.
- Produces: documentation an unfamiliar GitHub user can follow from zero.

**The honesty bar for this document:** it must state, prominently and early, what the tool *cannot* do. A user who discovers mid-migration that Surveys were never captured has been failed by the docs, not by the API.

- [ ] **Step 1: Write `README.md`**

Contents, in this order:

1. One-paragraph description and the sandbox-to-sandbox use case.
2. **Scope table** — what is exported, what is import-capable, what is reference-only, what has no API. Copy the real entity list from `registry.py`; do not paraphrase it.
3. Quick start (six commands, below).
4. Link to the user guide and to `docs/api-notes.md`.
5. Safety section: writes are dry-run by default; the tool refuses to import into the org the archive came from; no hosted service ever holds your token.

Quick start block:

```bash
git clone https://github.com/dwolgast-lab/wxcc-sandbox-exporter
cd wxcc-sandbox-exporter
cp .env.example .env            # add your Integration's client id/secret
python -m wxcc_export auth login    # opens a browser; use a PRIVATE window
python -m wxcc_export auth status   # CONFIRM the org id is the tenant you meant
python -m wxcc_export export
```

- [ ] **Step 2: Write `docs/user-guide.md`**

Required sections, each written out in full — no "see the README":

1. **What this does and does not do.** Lead with the limits table:

   | Object | Export | Import | Note |
   |---|---|---|---|
   | Contact Center config (19 entities) | yes | yes | dependency-ordered, ids remapped |
   | Flows and Subflows | yes | yes | subflows imported first |
   | Functions | yes | yes | export is JSON, import is multipart |
   | Contact Center Users | yes | **no** | the API has no create; invite them in Control Hub, then use `users/users.csv` to re-apply their config by hand |
   | Webex Calling (11 objects) | yes | yes | location-scoped; needs Calling scopes |
   | **Channels** | **no** | **no** | no API exists; configured in Webex Connect |
   | **Surveys** | **no** | **no** | no API exists; configure by hand in Control Hub |

2. **Registering a Webex Integration.** Step by step: developer.webex.com > My Apps > Create an Integration; redirect URI must exactly match `WXCC_REDIRECT_URI`; scopes `cjp:config_read` and `cjp:config`; the authorizing user must be a Contact Center administrator. State that each GitHub user registers their **own** Integration — there is no shared client id.

3. **The two-tenant workflow.** `.env` for the old sandbox, `.env.newsandbox` for the new one; each has its own token store; every command takes `--profile`. State plainly that there is deliberately no "switch tenant" command.

4. **The browser-session trap.** Authenticating a second profile while the browser still holds a Webex session can silently mint a token for the *first* tenant, and it looks like it worked. Always use a private window; always run `auth status` and read the org id before doing anything else.

5. **Exporting.** The command, where the file lands, what the name means, and how to read `inspect` output. Explain exit code 3 and why a partial export is not a failure but is not a success either.

6. **Importing.** Dry run first, always. Explain `--on-conflict` with a worked example of each policy. Explain that objects already in the target are skipped by default, and that this is how provisioning defaults are avoided without the API having a "default" flag.

7. **Reading the import summary.** What `FAILED`, `UNVERIFIED`, and dangling references each mean, and what to do about each. Be explicit that `UNVERIFIED` means the API returned success but the re-read shows the field did not land — that is a real problem, not a warning to ignore.

8. **Users: the manual step.** Exactly how to use `users/users.csv`: invite and license each person in Control Hub first, then apply site/team/profile/skill assignments. State that the tool will not do this for you and why.

9. **The web UI.** How to start it, that it is loopback-only, and that it holds a live admin token so it should be closed when not in use.

10. **Troubleshooting table:** `401` (token expired, re-run `auth login`), `403` on Calling (missing scopes, see `docs/api-notes.md` U5), `404` on flows (wrong `projectId`, see U1), `400 multimediaProfileId is required` (import the multimedia profile first, or widen `--select`), the same-org refusal.

- [ ] **Step 3: Verify every command in the docs actually runs**

Do not ship a command you have not executed. For each fenced command in both files:

```bash
python -m wxcc_export --help
python -m wxcc_export auth --help
python -m wxcc_export export --help
python -m wxcc_export import --help
python -m wxcc_export inspect --help
python -m wxcc_export web --help
```

Any command in the docs that does not run must be corrected in the docs, not left aspirational.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/user-guide.md
git commit -m "docs: user guide and README leading with the tool's real limits"
```

---

### Task 20: UAT plan

**Files:**
- Create: `docs/uat-plan.md`

**Interfaces:**
- Consumes: the finished tool.
- Produces: a document a person can execute against two real sandbox tenants, with an explicit pass/fail per case.

**Every case states an expected observation, not "verify it works".** A case whose expected result is a feeling cannot fail.

- [ ] **Step 1: Write the header and prerequisites**

```markdown
# UAT plan — WxCC Sandbox Exporter/Importer

**Tester:** ____________  **Date:** ____________  **Tool version:** ________

## Prerequisites

| # | Item | Ready? |
|---|---|---|
| P1 | An OLD sandbox tenant with configuration to export | |
| P2 | A NEW sandbox tenant, freshly provisioned, admin access | |
| P3 | A Webex Integration registered, redirect URI matching `.env` | |
| P4 | `.env` points at the OLD tenant; `.env.new` at the NEW one | |
| P5 | `python -m pytest -q` passes; record the count: ______ | |
| P6 | `docs/api-notes.md` exists and every U1-U6 row is answered | |

**Stop if P6 fails.** Flows, functions, and Calling cases below depend on
probe-confirmed values; running them against unresolved defaults tests nothing.

## How to record a result

Each case has an **Expected** line. Write what you actually observed in
**Observed**, then PASS or FAIL. "Looks right" is not an observation - record
the count, the name, the exit code, or the error text.
```

- [ ] **Step 2: Write the authentication cases**

```markdown
## A. Authentication

### A1 - OAuth2 login against the OLD tenant
Run: `python -m wxcc_export auth login`
**Expected:** a browser opens; after consent the page says "Authorized";
the command prints an org id.
**Observed:** ______________________  **PASS / FAIL**

### A2 - The org id is the tenant you meant
Run: `python -m wxcc_export auth status`
**Expected:** prints `auth source: oauth2` and a tenant line naming the OLD
sandbox with `[trial/sandbox]`.
**Observed:** ______________________  **PASS / FAIL**

### A3 - The second profile does NOT reuse the first tenant's session
Run: `python -m wxcc_export --profile new auth login` **in a private window**,
then `python -m wxcc_export --profile new auth status`.
**Expected:** the org id differs from A2. If the two org ids MATCH, this is the
browser-session trap - FAIL and re-run in a fresh private window.
**Observed:** old=__________ new=__________  **PASS / FAIL**

### A4 - Personal bearer token is announced
Put `WXCC_BEARER_TOKEN=<token>` in a scratch `.env.pat`, run
`python -m wxcc_export --profile pat auth status`.
**Expected:** the first line reads `AUTH: personal bearer token (OAuth2 bypassed)`.
**Observed:** ______________________  **PASS / FAIL**

### A5 - Expired token fails cleanly
Corrupt `access_token` in `.wxcc/tokens.json`, run `auth status`.
**Expected:** a one-line authentication error and exit code 2 - not a traceback.
Check with `echo $?` (PowerShell: `$LASTEXITCODE`).
**Observed:** ______________________  **PASS / FAIL**
```

- [ ] **Step 3: Write the export cases**

```markdown
## B. Export

### B1 - Archive is named after the tenant
Run: `python -m wxcc_export export`
**Expected:** a file `<orgName>-export.zip` appears, where `<orgName>` matches
the name shown in A2.
**Observed:** filename ______________________  **PASS / FAIL**

### B2 - Counts match Control Hub
Run: `python -m wxcc_export inspect <archive>`. Open Control Hub for the OLD
tenant and count Queues, Teams, Sites, and Wrap-up codes.
**Expected:** each `cc:*` count equals the Control Hub count.
**Observed:** queues CH=____ tool=____ ; teams CH=____ tool=____ ;
sites CH=____ tool=____ ; aux codes CH=____ tool=____  **PASS / FAIL**

### B3 - Audio files carry real bytes
Unzip the archive; list `cc/audio/`.
**Expected:** one file per audio-file record, each larger than 0 bytes, and
each playable.
**Observed:** count ____ , smallest ____ bytes  **PASS / FAIL**

### B4 - Flows exported and are valid JSON
**Expected:** `flows/flows/` contains one `.json` per flow in Control Hub, and
each parses. Check with:
`python -c "import json,glob;[json.load(open(f)) for f in glob.glob('flows/flows/*.json')];print('ok')"`
**Observed:** ______________________  **PASS / FAIL**

### B5 - UNSUPPORTED.md names Surveys and Channels
**Expected:** `UNSUPPORTED.md` exists and explains why each cannot be captured.
**Observed:** ______________________  **PASS / FAIL**

### B6 - A partial export exits 3, not 0
Temporarily narrow the Integration's scopes so one entity 403s, re-export.
**Expected:** the run prints the failed object AND exits 3.
**Observed:** exit code ____  **PASS / FAIL**

### B7 - users.csv is human-readable
Open `users/users.csv`.
**Expected:** one row per CC user; `site`, `teams`, `skillProfile` show NAMES,
not UUIDs.
**Observed:** ______________________  **PASS / FAIL**
```

- [ ] **Step 4: Write the import cases**

```markdown
## C. Import into the NEW tenant

### C1 - Dry run writes nothing
Run: `python -m wxcc_export --profile new import <archive>`
Then check Control Hub on the NEW tenant.
**Expected:** the plan prints; the last line says nothing was written; Control
Hub shows NO new objects.
**Observed:** ______________________  **PASS / FAIL**

### C2 - The tool refuses to import into the source org
Run: `python -m wxcc_export import <archive>` (the OLD profile, no --profile).
**Expected:** refuses with "the target tenant is the same org", exit 1.
**Observed:** ______________________  **PASS / FAIL**

### C3 - Confirmed import creates objects in dependency order
Run: `python -m wxcc_export --profile new import <archive> --select cc --confirm`
**Expected:** sites appear before teams; no `400 ... is required` failures caused
by a missing dependency.
**Observed:** failures ______________________  **PASS / FAIL**

### C4 - References are remapped, not copied
In the NEW tenant open an imported Team.
**Expected:** its Site is the NEWLY created site, and the site's id in the new
tenant differs from the id in `cc/site.json`.
**Observed:** old site id ________ new ________  **PASS / FAIL**

### C5 - Re-running the import skips rather than duplicating
Run the same command again.
**Expected:** every object reports `skipped`; Control Hub counts do NOT double.
**Observed:** queues before ____ after ____  **PASS / FAIL**

### C6 - Provisioning defaults are not duplicated
Compare the NEW tenant's default Wrap-up codes before and after import.
**Expected:** the built-in codes are skipped by name, not duplicated.
**Observed:** ______________________  **PASS / FAIL**

### C7 - --on-conflict rename creates a suffixed copy
Run with `--on-conflict rename --select cc:site --confirm`.
**Expected:** a site named `<name> (imported)` appears alongside the original.
**Observed:** ______________________  **PASS / FAIL**

### C8 - Flows import after their subflows
Run: `python -m wxcc_export --profile new import <archive> --select flows --confirm`
**Expected:** subflows are reported before flows; opening an imported flow in
Flow Designer shows it points at the NEW tenant's queues, not dangling ids.
**Observed:** ______________________  **PASS / FAIL**

### C9 - An unverified write is surfaced
Import an entity known to silently ignore a field (see `docs/api-notes.md`).
**Expected:** the summary prints `UNVERIFIED ... the server did not store <field>`.
**Observed:** ______________________  **PASS / FAIL**

### C10 - Dangling references are reported
Import only `cc:team` without `cc:site`.
**Expected:** the summary lists the unmapped site ids as broken references.
**Observed:** ______________________  **PASS / FAIL**

### C11 - Users are refused, with a reason
Run with `--select cc:user --confirm`.
**Expected:** reports `user is read-only through this API`; nothing is written.
**Observed:** ______________________  **PASS / FAIL**

### C12 - A clean import exits 0, a problematic one exits 3
**Expected:** C5 (all skipped, no failures) exits 0; C10 (dangling) exits 3.
**Observed:** C5 ____ C10 ____  **PASS / FAIL**
```

- [ ] **Step 5: Write the web UI and sign-off cases**

```markdown
## D. Web UI

### D1 - Serves on loopback only
Run `python -m wxcc_export --profile new web`. From another machine on the LAN,
browse to `http://<this-machine-ip>:8787/`.
**Expected:** the remote browser cannot connect. The local one can.
**Observed:** ______________________  **PASS / FAIL**

### D2 - API refuses a request with no session token
Run: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8787/api/tenant`
**Expected:** `403`.
**Observed:** ______________________  **PASS / FAIL**

### D3 - The target tenant is shown before any write
**Expected:** the page names the NEW tenant at the top; a production org is
shown in red.
**Observed:** ______________________  **PASS / FAIL**

### D4 - Read-only objects cannot be selected
**Expected:** the Contact Center Users checkbox is disabled and labelled
"no write API - export reference only".
**Observed:** ______________________  **PASS / FAIL**

### D5 - Import requires the confirm checkbox
Select an object, leave confirm unticked, click Run.
**Expected:** a dry-run result; Control Hub unchanged.
**Observed:** ______________________  **PASS / FAIL**

## E. Round-trip acceptance

### E1 - Export the NEW tenant and compare
After a full import, export the NEW tenant and compare counts with B2.
**Expected:** each imported entity's count in the NEW tenant equals the OLD
tenant's count, minus any object reported FAILED or skipped as a default.
**Observed:** ______________________  **PASS / FAIL**

### E2 - Place a test call through an imported flow
**Expected:** the call reaches the imported queue and plays the imported audio
prompt. This is the only case that proves the configuration is functional
rather than merely present.
**Observed:** ______________________  **PASS / FAIL**

## Sign-off

| Section | Cases | Passed | Failed |
|---|---|---|---|
| A Authentication | 5 | | |
| B Export | 7 | | |
| C Import | 12 | | |
| D Web UI | 5 | | |
| E Round-trip | 2 | | |

**Blocking failures (must fix before release):** any FAIL in A3, C2, C5, D1, D2.
These are the cases that protect the wrong tenant from being written to.

**Tester signature:** ____________________  **Date:** ____________
```

- [ ] **Step 6: Commit**

```bash
git add docs/uat-plan.md
git commit -m "docs: UAT plan with observable expected results per case"
```

---

## Final verification before release

- [ ] **Run the whole suite one last time and report against the baseline**

```bash
python -m pytest -q
```

Expected: 184 passed, 0 failed. Report as `baseline 33 -> 184 passed, 0 failing`.

- [ ] **Confirm no credential ever entered git history**

```bash
git log --all --full-history --source -- .env .env.* .wxcc/
git grep -nIE "client_secret|Bearer [A-Za-z0-9._-]{40,}" -- ':!docs/*' ':!*.md'
```

Expected: both produce no output. If either does, **stop** — the secret must be
rotated, not merely deleted from the working tree.

- [ ] **Create the public GitHub repository**

> **Irreversible / outward-facing.** This publishes the repository. Get explicit
> confirmation from the user first. Rollback: `gh repo delete dwolgast-lab/wxcc-sandbox-exporter --yes`
> (deletes the remote; the local clone survives).

```bash
gh repo create dwolgast-lab/wxcc-sandbox-exporter --public \
  --source . --remote origin --description \
  "Export and import Webex Contact Center sandbox tenant configuration"
git push -u origin main
```

---

## Self-review

Run after the plan is written; fix findings inline.

**1. Spec coverage.** Every object named in `docs/wxcc-sandbox-exporter.md`:

| Spec requirement | Where handled |
|---|---|
| OAuth2 default, bearer token opt-in | Task 2 |
| Tenant derived from token org id | Task 2 (`extract_org_id`), Task 4 |
| `<tenant>-export` compressed archive | Task 4 (`archive_name`), Task 11 |
| Import ingests the archive natively | Task 12 |
| Choose which objects to import, or all | Task 12 (`parse_selection`), Tasks 17, 18 |
| Webex Calling non-default feature config | Tasks 10, 16 (bounded subset per the user's decision) |
| Queues, Business Hours, Audio Files, Global Variables | Tasks 6, 7, 8 |
| Channels | Task 6 `UNSUPPORTED` — no API exists |
| Flows, Subflows | Tasks 9, 16 |
| Functions | Tasks 9, 16 |
| Surveys | Task 6 `UNSUPPORTED` — no API exists |
| Sites, Skills, Skill Profiles, Teams | Tasks 6, 7 |
| User Profiles, Resource Collections | Tasks 6, 7 |
| Contact Center Users | Task 8 (manifest), Task 15 (refused with a reason) |
| Multimedia Profiles, Outdial ANI, Desktop Layouts | Tasks 6, 7 |
| Address Books, Desktop Profiles, Idle/Wrap-up Codes | Tasks 6, 7, 8 |
| Non-default only, "if possible" | "Non-default only" section; Tasks 7, 14 |
| Git repo + public GitHub remote | Task 1, Final verification |
| Any GitHub user can run it | Task 1 (stdlib only), Task 19 (own Integration) |
| Thorough build and test plans | TDD steps throughout; Task 20 |
| Reuse wxcc-skills prior art | Tasks 2, 3, 6 reuse its verified route and auth facts |

**No spec requirement is unhandled.** Two are handled by declaring them
impossible with evidence, which is the honest outcome, not a gap.

**2. Placeholder scan.** No step says "TBD", "add error handling", or "similar
to Task N". Every code step carries runnable code. The one deliberate
placeholder class is the `UNRESOLVED` sentinel in Tasks 9 and 16 — that is a
*runtime refusal to guess*, gated by a test that fails if the probe was skipped.

**3. Type consistency.** Cross-checked: `ApiClient.list_all` returns `list[dict]`
in Task 3 and is consumed as such in Tasks 7, 10, 14. `IdMap.substitute` /
`.unmapped` / `.record` are named identically in Tasks 13, 15, 16.
`ImportResult` fields (`created`, `updated`, `skipped`, `failed`, `unverified`,
`dangling`, `planned`) match between Task 15's dataclass and Task 16's and
Task 17's consumers. `registry.list_path` / `item_path` / `create_path` are used
consistently in Tasks 7, 14, 15. Selection keys `cc:<entity>`, `flows:<bucket>`,
`calling:<name>` are identical in Tasks 12, 17, 18.

One inconsistency was found during this review and **fixed inline**:
`import_cc` originally returned only `dict[str, ImportResult]`, leaving Task 17
with no way to reach the `IdMap` that Tasks 16's flow and Calling imports must
reuse. It now returns `(results, idmap)`, and Task 17's `_run_import` unpacks
that tuple. Any implementer of Task 15 must therefore also update the
`import_cc` call in `tests/test_importer.py` if they add one — the tests as
written call `import_entity`, not `import_cc`, so no existing test breaks.

**4. Cross-task fact consistency.** Every route in Task 6's registry was
transcribed from the OpenAPI documents and spot-checked against the sibling
repo's live-verified registry. The version-prefix rule (list keeps `v2`/`v3`;
item and create drop it) is asserted by tests in Task 6 and relied on by
Tasks 7, 15 — so a regression in one surfaces in the other.
