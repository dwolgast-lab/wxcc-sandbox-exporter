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
