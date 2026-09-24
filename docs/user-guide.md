# User guide — wxcc-sandbox-exporter

This guide covers every command in full. Nothing here is "see the README" —
if you only read one document before using this tool against a real tenant,
read this one.

---

## 0. Installing

Two ways to run it. Both behave identically.

### Option A: the standalone executable (no Python needed)

1. Open the repository's
   [Releases page](https://github.com/dwolgast-lab/wxcc-sandbox-exporter/releases)
   and download `wxcc-export-<version>-windows-x64.zip`. It runs on 64-bit
   Windows 10 and 11.

   **Only Windows builds are published at the moment.** On macOS or Linux,
   use Option B.

2. Unzip it into a folder of its own, such as `wxcc-export/`. The zip
   contains the executable, this guide, the README, the CHANGELOG, the
   license and `.env.example`.
3. **Put your `.env` in that same folder, next to the executable.** The
   executable always reads `.env` and stores its tokens in `.wxcc/` next to
   itself, whatever directory you run it from. Put it somewhere you can
   write to, not `C:\Program Files`.
4. The executable is not code-signed, so the first run shows a SmartScreen
   warning, "Windows protected your PC". Click **More info**, then
   **Run anyway**.
5. Check that it runs: `.\wxcc-export.exe --version`.

**Command names.** This guide writes commands as `python -m wxcc_export ...`.
With the executable, write `wxcc-export ...` (or `.\wxcc-export.exe ...` in
PowerShell) instead. The arguments are the same.

### Option B: from source (Python 3.11 or newer)

The tool has **no third-party runtime dependencies**, so there is nothing to
`pip install`:

```bash
git clone https://github.com/dwolgast-lab/wxcc-sandbox-exporter
cd wxcc-sandbox-exporter
python wxcc-export.py --version
```

`python wxcc-export.py ...` works straight after cloning. Put `.env` in the
checkout root. If you want the `wxcc-export` command on your PATH, or want
`python -m wxcc_export` to work, run `pip install -e .`; neither is required.
The source code for each release is also attached to its GitHub Release page
as a zip and a tar.gz.

### Fastest start: a personal bearer token

If you only need a quick export, you can skip the Integration registration
in [§2](#2-registering-a-webex-integration). Create a `.env` containing only:

```
WXCC_BEARER_TOKEN=<your personal access token from developer.webex.com>
```

The token must belong to a Contact Center administrator on the tenant, and it
expires 12 hours after you create it, so generate a fresh one just before you
run. Then run `wxcc-export auth status`, confirm that the org it prints is
the tenant you meant, and run `wxcc-export export`.

Two settings may need adding:
- `WXCC_API_BASE`: set it if your tenant is **not** in the US1 region. The
  default is `https://api.wxcc-us1.cisco.com`, the only region this tool has
  been tested against.
- `WXCC_ORG_ID`: set it if calls fail on the org id. The org id is normally
  read out of the token.

The tool prints a warning every time it uses a bearer token. OAuth2 (§2) is
the better choice for anything longer than one session.

---

## 1. What this does and does not do

Read this section before you export anything. The tool talks to the real
Webex Contact Center and Webex Calling APIs, and those APIs simply do not
expose every object Control Hub shows you. A migration that silently drops
Surveys is not a bug in this tool — it is the shape of the API surface — but
you are the one who has to know that *before* the old tenant is gone.

| Object | Export | Import | Note |
|---|---|---|---|
| Contact Center config (25 entities — see [§1a](#1a-the-25-contact-center-entities)) | yes | yes | dependency-ordered, ids remapped |
| Flows and Subflows | yes | yes | subflows are imported before flows; the project id and the flowType that selects a Subflow are tenant-specific facts recorded in `docs/api-notes.md` (see the callout below) |
| Functions | yes | yes | export returns JSON; import requires `multipart/form-data` — the two are asymmetric on Cisco's side, not a quirk of this tool. The multipart field name is also recorded in `docs/api-notes.md` |
| Audio Files | yes | **partial** | the audio bytes ARE captured in the archive under `cc/audio/`, but re-uploading them on import is not implemented as multipart — see [§10](#10-troubleshooting) |
| Contact Center Users | yes | **no** | `/organization/{orgId}/user` publishes `GET` only — there is no `POST`. Invite and license each person in Control Hub, then use `users/users.csv` to reapply their site/team/profile/skill assignments by hand ([§8](#8-users-the-manual-step)) |
| Webex Calling (12 objects — see [§1b](#1b-the-12-webex-calling-objects)) | yes | yes | location-scoped; needs Calling OAuth scopes that the shipped `.env.example` does not request by default |
| **Channels** | yes | yes | **captured as entry points.** A Channel is not a separate resource — it is an entry point whose `channelType` is not `TELEPHONY` (`EMAIL`, `CHAT`, `SOCIAL_CHANNEL`, `VIDEO`, `FAX`, `CUSTOM_MESSAGING`, `WORK_ITEM`, `OTHERS`). `EntryPointDTO` carries `channelType`, `socialChannelType`, `assetId`, `subscriptionId`. The exporter sweeps every channel type, because the unfiltered listing hides `systemInternal` rows — on a live tenant it returned 10 entry points while `?channelTypes=TELEPHONY` returned 11. An earlier version of this guide said Channels had no API; that was wrong |
| **Surveys** | **no** | **no** | same search, same result — no `survey` operation exists. The nearest published feature is Auto CSAT, which is AI-generated scoring, not the Surveys page, and is not a substitute. Recreate by hand in Control Hub under Contact Center > Customer Experience > Surveys |

> **Before you trust Flows, Functions, or two of the Calling objects with a
> real migration:** three facts this tool needs are not published in Cisco's
> OpenAPI documents at all — the Flows `projectId`, the `flowType` value that
> selects a Subflow, and the multipart field name for Functions import. They
> have to be established once, against a real tenant, and written to
> `docs/api-notes.md`. If that file does not exist in your checkout, the
> values baked into the code (`export_flows.py`'s `PROJECT_ID_MODE` and
> `SUBFLOW_TYPE`, `importer.py`'s `FUNCTION_IMPORT_FIELD`) are labelled
> **provisional / unverified** in their own comments — not confirmed facts.
> Two Webex Calling routes (`call-queues` list, `call-park-extensions` item —
> see `registry.py`) carry the same `UNCONFIRMED` label because the OpenAPI
> document does not publish them as lists. Run a small real export/import
> against a disposable sandbox first and read the summary output before you
> point this at a tenant you care about. A `404` on flows or a Calling object
> that never appears is the visible symptom — see [§10](#10-troubleshooting).

### 1a. The 25 Contact Center entities

This is the entity list from `src/wxcc_export/registry.py`, transcribed, not
paraphrased. All 25 export; 24 import (create + update); `user` is
export-only, because its collection publishes `GET` only.

**Customer Experience**

| Entity (API name) | Spec label | Writable |
|---|---|---|
| `contact-service-queue` | Queues | yes |
| `business-hours` | Business Hours | yes |
| `holiday-list` | (Business Hours dependency) | yes |
| `overrides` | (Business Hours dependency) | yes |
| `audio-file` | Audio Files | yes — see the partial-import note above |
| `cad-variable` | Global Variables | yes |
| `entry-point` | **Channels** + (Queue dependency) | yes — swept across every `channelType` |
| `dial-number` | (Entry Point dependency) | yes |
| `contact-number` | Contact Numbers | yes — identity is `number`, not `name` |
| `dial-plan` | Dial Plans | yes — both rows on a probed tenant were `systemDefault` |

**User Management**

| Entity (API name) | Spec label | Writable |
|---|---|---|
| `site` | Sites | yes |
| `skill` | Skill Management | yes |
| `skill-profile` | Skill Profiles | yes |
| `team` | Teams | yes |
| `user-profile` | User Profiles | yes |
| `resource-collection` | Resource Collections | yes |
| `user` | Contact Center Users | **no** — no create endpoint |

**Desktop Experience**

| Entity (API name) | Spec label | Writable |
|---|---|---|
| `multimedia-profile` | Multimedia Profiles | yes |
| `outdial-ani` | Outdial ANI | yes |
| `desktop-layout` | Desktop Layouts | yes |
| `address-book` | Address Books | yes |
| `agent-profile` | Desktop Profiles | yes |
| `auxiliary-code` | Idle/Wrap-up Codes | yes |
| `work-type` | (Aux Code dependency) | yes |
| `agent-personal-greeting` | Agent Personal Greetings | yes — **shape unverified**, the probed tenant had none |

Three of these — `contact-number`, `dial-plan`, `agent-personal-greeting` —
were added on 2026-09-23 after a live probe found the exporter was silently
missing them. Two held real data.

### 1b. The 12 Webex Calling objects

The original scope decision named 11 Calling objects, grouping "Call Park"
as one item. The API actually exposes it as **two** distinct objects — Call
Park Extensions (org-scoped) and Call Parks (location-scoped) — so the
registry, and this archive, carry 12:

`locations`, `schedules`, `auto-attendants`, `hunt-groups`, `call-queues`,
`call-park-extensions`, `call-parks`, `call-pickups`, `paging-groups`,
`announcements`, `virtual-extensions`, `operating-modes`.

These live on the Webex API host (`webexapis.com`), not the Contact Center
regional host, and most are scoped per-Location: the tool lists Locations
first, then fans out.

---

## 2. Registering a Webex Integration

Every GitHub user who runs this tool registers **their own** Integration —
there is no shared client id baked into the tool, and there should never be
one: a shared credential is a shared liability for every tenant anyone ever
points it at.

1. Go to <https://developer.webex.com>, sign in, and open **My Webex Apps**.
2. **Create a New App** > **Create an Integration**.
3. Set the **Redirect URI** to exactly match `WXCC_REDIRECT_URI` in your
   `.env` file (the shipped default is `http://localhost:8484/callback`).
   This has to match character-for-character, including the port — the tool
   catches the OAuth2 authorization code on a local listener bound to that
   exact host and port.
4. Grant the scopes: `cjp:config_read` (export) and `cjp:config` (import).
   If you plan to touch the Webex Calling subset, also add the
   `spark-admin:telephony_config_read` and `spark-admin:telephony_config_write`
   scopes — the shipped `.env.example` does not request these by default,
   because Calling is an optional part of the tool's scope (see
   [§10](#10-troubleshooting), the `403` row).
5. Save the Integration and copy its **Client ID** and **Client Secret**
   into your `.env` file.
6. The Webex account that runs `auth login` against a tenant must be a
   Contact Center administrator on that tenant. A non-admin token will
   authenticate fine and then fail on the first API call with `403`.

---

## 3. The two-tenant workflow

The tool is deliberately profile-scoped, one env file per tenant, each with
its own token store:

- `.env` — the default profile. Nothing forces this to mean "old" or "new";
  it is just whichever profile you don't pass `--profile` for.
- `.env.<name>` — an additional profile, selected with `--profile <name>` on
  *any* command (`wxcc-export --profile newsandbox export`, or
  `wxcc-export export --profile newsandbox` — both orders work).
- Each profile's tokens live at `.wxcc/tokens.json` or
  `.wxcc/tokens.<name>.json`, so authenticating one profile never touches
  another profile's stored token.

**There is deliberately no "switch tenant" or "current tenant" command or
pointer file.** A mutable "which tenant am I pointed at right now" global is
exactly the kind of state that lets a write meant for the new sandbox land on
the old one by accident — one stale terminal tab, one forgotten flag, and the
"current" tenant is not the one you think it is. Naming the tenant
explicitly on every command, via `--profile`, is slower to type and
considerably harder to get wrong.

A typical two-tenant setup:

```bash
cp .env.example .env              # the OLD sandbox
cp .env.example .env.new          # the NEW sandbox
# fill in each file's own client id/secret (or share one Integration —
# the credentials can be identical; the org id comes from who logs in)
python -m wxcc_export auth login              # OLD tenant
python -m wxcc_export --profile new auth login   # NEW tenant, PRIVATE window
```

---

## 4. The browser-session trap

This is the single easiest way to corrupt a migration, and it will not look
like a failure when it happens.

Webex's OAuth2 authorize endpoint, like most identity providers, remembers
which account your browser is already signed into. If you authenticate the
`new` profile in the *same* browser window that still holds a live Webex
session for the `old` tenant's admin account, the authorize page can skip
the login prompt entirely and silently mint a token **for the tenant you
were already signed into** — not the one you meant to switch to. The
command completes, prints an org id, and looks exactly like success.

This tool passes `prompt=login` on every authorization request specifically
to force a fresh credential prompt (see the comment in `auth.py`'s `login()`),
but that is a hint to the identity provider, not a guarantee — active SSO
sessions can still short-circuit it depending on your Webex org's identity
configuration.

**Two rules, every time you authenticate a second profile:**

1. **Always use a private/incognito browser window.** Never reuse a window
   that has any other Webex session open in it.
2. **Always run `auth status` immediately after and read the org id.**

```bash
python -m wxcc_export --profile new auth status
```

If the org id printed here matches the org id from your `old` profile's
`auth status`, stop. You authenticated the wrong tenant. Log out
(`auth logout`) and redo it in a genuinely fresh private window.

---

## 5. Exporting

```bash
python -m wxcc_export export
```

What happens, in order:

1. The tool resolves and prints the source tenant (name, org id, and
   whether it's tagged `PRODUCTION` or `trial/sandbox`, from the tenant's
   own `organization/{orgId}` record — never from a label you configured).
2. It walks all 25 Contact Center entities, the Flows/Subflows/Functions
   buckets, and the 12 Calling objects, printing a running count per object.
3. It writes `<orgName>-export.zip` into the current directory (override
   the destination directory with `--out DIR`; the filename itself is not
   configurable, on purpose — it always names the tenant it actually came
   from).
4. If anything failed, the run prints each failure and exits **3**, not 0 or
   1. Exit code 3 means "the export ran and produced a real archive, but it
   is missing something" — never mistake a `3` for a clean `0`. Anything
   that failed is also written into `UNSUPPORTED.md` inside the archive
   itself, so the record travels with the zip file even if you only saw the
   terminal output once.

Flags:

| Flag | Meaning |
|---|---|
| `--out DIR` | write the archive into `DIR` instead of the current directory |
| `--select all\|cc\|flows\|calling\|<comma-separated keys>` | export only part of the scope. Keys look like `cc:site`, `flows:functions`, `calling:locations` — see `inspect` output on an existing archive for the exact key spelling |
| `--only-non-default` | drop objects the `createdTime`-clustering heuristic flags as provisioning defaults. **Off by default, and you should think hard before turning it on**: there is no `isDefault` field on any WxCC object, so this is a heuristic (anything created within 120 seconds of the tenant's earliest object is guessed to be a default) — a false positive here silently drops real configuration from the archive |

### Reading `inspect`

```bash
python -m wxcc_export inspect <archive>
```

`inspect` needs no credentials and no `.env` file — it only reads the local
zip. It prints the source tenant, export timestamp, a count per object with
its selection key, and (if the export was partial) the same failure list
that's inside `UNSUPPORTED.md`. Objects tagged
`[read-only, export reference only]` are `cc:user` — they cannot be
imported, only referenced. `inspect` exits `3` on the same "partial export"
condition `export` does, `0` on a clean archive.

---

## 6. Importing

**Always run without `--confirm` first.** Every import is dry-run by
default — it computes and prints the exact same plan a real run would
execute, without writing anything, so you can read it before committing to
it:

```bash
python -m wxcc_export --profile new import <archive>.zip --select cc
```

Add `--confirm` only once the dry-run plan looks right:

```bash
python -m wxcc_export --profile new import <archive>.zip --select cc --confirm
```

Before touching anything, the importer refuses outright if the target
profile resolves to the **same org id** the archive came from — you cannot
accidentally re-import an export back into the tenant it was taken from by
forgetting `--profile`.

### `--on-conflict`

Every object is matched against the target tenant **by name**, because
there is no `isDefault` flag anywhere in the API to tell "provisioning
default" apart from "previously imported" — an object whose name already
exists in the target *is*, by definition, already there. This is also how
provisioning defaults are avoided without the tool ever having to know what
a default looks like.

| Policy | Behaviour when a name collides |
|---|---|
| `skip` (default) | Nothing is written for that object. Its target-side id is still recorded for reference remapping — anything that pointed at the source object now points at the existing target object instead |
| `update` | The existing target object is overwritten in place (`PUT`) with the source object's fields |
| `rename` | A new object is created alongside the existing one, named `<name> (imported)` (or `(imported 2)`, `(imported 3)`, … if that's also taken) |

Worked example — a `site` named `Main` already exists in the new tenant:

```bash
# default: Main is left alone, nothing created
python -m wxcc_export --profile new import archive.zip --select cc:site --confirm

# overwrite the existing Main with the source tenant's Main
python -m wxcc_export --profile new import archive.zip --select cc:site --on-conflict update --confirm

# keep both: creates "Main (imported)"
python -m wxcc_export --profile new import archive.zip --select cc:site --on-conflict rename --confirm
```

### Selecting what to import

`--select` takes the same vocabulary as export: `all` (default), a section
(`cc`, `flows`, `calling`), or a comma-separated list of explicit keys
(`cc:site,cc:team`). An unrecognized key is a hard error, not a silent
no-op — a typo that imports nothing should never look like a typo that
imported everything.

Flows import subflows before flows automatically (a flow can invoke a
subflow, never the reverse) — you do not need to sequence `--select` calls
yourself to get that ordering.

### A dry run's exit code is always 0

This is worth being explicit about: **without `--confirm`, the command
always exits 0**, even if the printed plan shows objects that would fail
(for example, selecting `cc:user`, which is always refused — see
[§7](#7-reading-the-import-summary)) or references that would dangle. A dry
run's job is to show you the plan; read the printed summary, not just the
exit code, before deciding to add `--confirm`. Only a **confirmed** run's
exit code reflects whether anything actually went wrong (`0` clean, `3` if
anything failed, was unverified, or left a dangling reference).

---

## 7. Reading the import summary

Every import — dry run or confirmed — ends with a per-object line like:

```
site: 3 created, 0 updated, 5 skipped, 0 failed, 0 unverified
```

and, when there's something to report, a detail section underneath:

- **`FAILED`** — the create or update call itself did not succeed (a
  non-2xx response, a network error, or a response that carried no `id` to
  record). The detail line names the entity, the source id, and the API's
  own error text. Nothing was written for that object. `cc:user` always
  reports `FAILED ... user is read-only through this API` for every row,
  by design — see [§8](#8-users-the-manual-step).

- **`UNVERIFIED`** — **this is a real problem, not a warning to skim past.**
  After every confirmed write, the importer re-reads the object from the API
  and compares it, field by field, against what it just sent. `UNVERIFIED`
  means the write call returned success (HTTP 200/201) but the re-read shows
  one or more fields did not actually land — the API accepted the request
  and then silently dropped part of it. This is a documented behaviour of
  the WxCC API, not a bug in the importer, and it's exactly why the re-read
  exists: a `200` status code is not evidence a field was stored. The line
  names which fields didn't stick (for example,
  `UNVERIFIED site abc123: the server did not store multimediaProfileId`).
  Treat every `UNVERIFIED` object as needing a manual check in Control Hub
  before you trust it.

- **Dangling references** — after the summary, a count of id-shaped strings
  found in the payloads sent that have **no** recorded old-id → new-id
  mapping. This means some part of an imported object still points at a
  source-tenant id that was never created in the target — most commonly
  because you selected a narrower `--select` than the object's dependencies
  needed (importing `cc:team` without `cc:site` leaves every team's site
  reference dangling), or because the object it should have pointed at
  failed to import. The target will either reject the dangling id outright
  or silently store a broken link, depending on the field; either way,
  widen `--select` to include the missing dependency and re-run.

A confirmed run exits **0** only when `failed`, `unverified`, and dangling
references are all empty across every selected object. Any of the three
present exits **3**.

---

## 8. Users: the manual step

Contact Center Users cannot be created or updated through this API — full
stop. `/organization/{orgId}/user` publishes `GET` only; there is no `POST`.
This is confirmed twice over: the OpenAPI document omits the operation, and
Cisco's own registry notes record "Users are created/deleted in Control Hub,
not here." Selecting `cc:user` on import always reports every user as
`FAILED ... read-only`, and nothing is written — the tool refuses rather
than silently skipping, so you always see the reason.

What the export gives you instead is `users/users.json` and
`users/users.csv` — a reference manifest, one row per Contact Center user,
with every id already resolved to a human-readable name: `site`, `teams`,
`skillProfile`, `userProfile`, `desktopProfile`, and `multimediaProfile`
columns show the assignment by NAME, not by UUID, specifically so you can
work from it without cross-referencing anything else.

To actually move users to the new tenant:

1. **Invite and license each person in Control Hub first**, on the new
   tenant. This is unavoidable — it's a Control Hub operation with no API
   path in or around this tool.
2. Open `users/users.csv` from the export (or `users/users.json` if you'd
   rather script against it) and, for each user, apply their `site`,
   `teams`, `skillProfile`, `userProfile`, `desktopProfile`, and
   `multimediaProfile` assignments by hand in the new tenant's Control Hub —
   using the names from the CSV, which by this point should already exist
   in the new tenant if you ran the `cc` import first.

The tool will not do this step for you, and there is no code path that
could: the API this tool talks to genuinely does not expose a way to create
or license a Contact Center user.

---

## 9. The web UI

```bash
python -m wxcc_export web
```

This starts a local HTTP server (default port `8787`, override with
`--port`) and opens it in your default browser. It offers the same
selection-and-import workflow as the CLI's `import` command, aimed at
someone who would rather tick checkboxes than type `--select` keys.

Three things worth knowing:

- **It binds to `127.0.0.1` only, never `0.0.0.0`.** Nothing on your network
  other than this machine can reach it, by design — there is no remote
  mode.
- **Every request carries a per-run random session token**, generated fresh
  each time you run `web` and handed to the page inline — never written to
  disk, never put in a URL. A request without it, or with a mismatched
  `Origin` header, is refused with `403`. This is the DNS-rebinding defence:
  a malicious page open in another tab cannot quietly call this server on
  your behalf.
- **The process holds a live admin access token for as long as it's
  running.** Close it (`Ctrl-C`) when you're done, the same way you would
  close any tool holding a live credential.
- **It currently drives Contact Center object import only.** Flows,
  Functions, and the Calling subset are CLI-only right now
  (`import --select flows`, `import --select calling`) — the web server's
  `/api/import` endpoint calls the same `import_cc` path the CLI's `--select
  cc` uses, and nothing else.

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `401` on any API call | The stored access token has expired | `python -m wxcc_export auth login` again for that profile |
| `403` on Calling objects only | The token's scopes don't include Calling. `.env.example`'s default `WXCC_SCOPES` only requests `cjp:config_read cjp:config`, not the `spark-admin:telephony_config_*` family | Add `spark-admin:telephony_config_read` (and `_write` for import) to `WXCC_SCOPES` in your `.env`, grant them on the Integration, and `auth login` again. See U5 in `docs/api-notes.md` for whether the sandbox even has Calling provisioned |
| `404` on flows | The `projectId` this tool derives (see `PROJECT_ID_MODE` in `export_flows.py`) doesn't match your tenant | Check U1 in `docs/api-notes.md`; if that file doesn't exist yet in your checkout, the value is provisional — see the callout in [§1](#1-what-this-does-and-does-not-do) |
| `400 ... multimediaProfileId is required` (or any other `<field> is required`) | You imported an object without its dependency already present in the target — for example a `site` without its `multimedia-profile` | Import the missing dependency first, or widen `--select` to include it. `--select cc` (no narrower filter) always brings in the full dependency-ordered set |
| Importing into the same tenant the archive came from | `import` refuses this outright, printing `REFUSING: the target tenant is the same org the archive came from` | Point `--profile` at the tenant you actually want to write to, not the one you exported from |
| Two profiles report the same org id after `auth login` | The browser-session trap — see [§4](#4-the-browser-session-trap) | `auth logout` the wrong profile, open a genuinely fresh private window, and log in again |
| `cc:audio-file` import shows `FAILED` (or `UNVERIFIED` naming an audio-related field) | Re-uploading audio bytes on import isn't implemented as a multipart upload yet — the create call currently sends JSON metadata only, and Cisco's `audio-file` endpoint is on record as not accepting a JSON body | Re-upload the audio file by hand in Control Hub, under the same name, then re-run the import (the name-match `skip` policy will pick it up as already present) |
| `cc:user` reports every row `FAILED ... read-only` | Expected — there is no create endpoint for users | See [§8](#8-users-the-manual-step) |
