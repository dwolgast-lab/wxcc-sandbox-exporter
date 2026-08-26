# wxcc-sandbox-exporter

Export a Webex Contact Center sandbox tenant's configuration to a single zip
archive, and selectively import that archive into a different sandbox
tenant. It exists because WxCC sandbox tenants expire and get replaced, and
rebuilding queues, teams, sites, skill profiles, flows, and a Calling
configuration by hand in Control Hub every time does not scale. It talks to
**one tenant at a time** — export from the old one, then import into the
new one — never both at once, on purpose.

## Before you rely on this: what it cannot do

Read this before you export anything you'd be upset to lose:

- **Channels and Surveys have no API at all.** Not "not implemented yet" —
  zero operations across all 328 Contact Center paths and all 61 tags in
  Cisco's own OpenAPI document. Nothing can export or import them. Recreate
  both by hand in Control Hub before the old tenant disappears.
- **Contact Center Users are export-only.** `/organization/{orgId}/user`
  publishes `GET` only — there is no create endpoint anywhere in the API.
  You get a `users.csv`/`users.json` reference manifest with every id
  already resolved to a name; you still invite, license, and assign each
  person by hand in the new tenant's Control Hub.
- **Flows, Subflows, Functions, and two Calling objects depend on
  tenant-specific facts that are not published in Cisco's OpenAPI
  documents.** They're resolved once against a real tenant and recorded in
  `docs/api-notes.md`. Until that file exists in your checkout, treat those
  parts as provisional — full detail in the
  [user guide, §1](docs/user-guide.md#1-what-this-does-and-does-not-do).
- **Authenticating a second tenant in a browser that still holds the first
  tenant's session can silently mint a token for the wrong tenant** — and it
  looks like success. Always a private window; always run `auth status`
  and check the org id. Full explanation in the
  [user guide, §4](docs/user-guide.md#4-the-browser-session-trap).

## Scope

The full picture, copied from `src/wxcc_export/registry.py` (the single
source of truth this tool's export/import walk is driven by) — not
paraphrased. See the [user guide](docs/user-guide.md#1-what-this-does-and-does-not-do)
for notes on each row.

**Contact Center — 22 entities, 21 import-capable, 1 export-only**

| Group | Entities |
|---|---|
| Customer Experience | `contact-service-queue`, `business-hours`, `holiday-list`, `overrides`, `audio-file`, `cad-variable`, `entry-point`, `dial-number` |
| User Management | `site`, `skill`, `skill-profile`, `team`, `user-profile`, `resource-collection`, `user` (**export-only — no create endpoint**) |
| Desktop Experience | `multimedia-profile`, `outdial-ani`, `desktop-layout`, `address-book`, `agent-profile`, `auxiliary-code`, `work-type` |

**Flows** — Flows, Subflows, Functions (export + import, subflows before flows)

**Webex Calling — 12 objects** (export + import, location-scoped, needs
Calling OAuth scopes not requested by the default `.env.example`)

`locations`, `schedules`, `auto-attendants`, `hunt-groups`, `call-queues`,
`call-park-extensions`, `call-parks`, `call-pickups`, `paging-groups`,
`announcements`, `virtual-extensions`, `operating-modes`

**No API exists for:** Channels, Surveys — see the callout above.

## Quick start

```bash
git clone https://github.com/dwolgast-lab/wxcc-sandbox-exporter
cd wxcc-sandbox-exporter
pip install -e .                    # required: the package lives under src/,
                                     # so `python -m wxcc_export` needs this first
cp .env.example .env                # add your Integration's client id/secret
python -m wxcc_export auth login    # opens a browser; use a PRIVATE window
python -m wxcc_export auth status   # CONFIRM the org id is the tenant you meant
python -m wxcc_export export
```

Every command also works as `wxcc-export ...` (the console script that
`pip install -e .` registers) instead of `python -m wxcc_export ...`.

Full detail on every command, every flag, and every failure mode: the
**[user guide](docs/user-guide.md)**. Tenant-specific facts that aren't in
Cisco's published API docs (Flows project id, the Subflow `flowType`, the
Calling scopes your sandbox actually has): **`docs/api-notes.md`**, once your
own probe run has produced it.

## Safety

- **Every import is dry-run by default.** Nothing is written to the target
  tenant until you pass `--confirm`; the dry-run plan and the real run
  compute the identical set of actions, so what you read is what would
  happen.
- **The tool refuses to import an archive into the org it came from.** This
  check runs before anything else, comparing the target profile's org id
  against the archive's recorded source org id — forgetting `--profile` on
  the new tenant can't silently re-import into the old one.
- **No hosted service ever holds your token.** This is a local CLI plus an
  optional `127.0.0.1`-only web UI; there is no server component and never
  will be one. OAuth2 tokens live in a gitignored `.wxcc/` directory on your
  own machine, one file per tenant profile.

## License

MIT — see [LICENSE](LICENSE).
