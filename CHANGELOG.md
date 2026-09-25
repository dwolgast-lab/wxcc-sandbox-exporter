# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-09-25

Fixes found from the first real import attempt, a dry run into a new
sandbox. None of v0.1.0's import fixes had been run against a live tenant.

### Fixed

- **Flow files can be imported straight into Flow Designer.** Each flow,
  subflow and function is now saved as the plain Flow Designer document,
  named `<Flow_Name>.json` like Flow Designer's own export. v0.1.0 wrapped
  them in an envelope that Flow Designer rejected with "Flow name is empty".
  The archive format is now version 2. v0.1.1 still reads v0.1.0 archives;
  v0.1.0 cannot read new ones.
- **A dry run shows what it would do.** v0.1.0 printed "0 created" for every
  object in a dry run, whatever was planned. It now prints "N would be
  created, N would be updated".
- **Dangling-reference reports are accurate.** v0.1.0 counted flow node
  names, event names and Cisco catalog ids as broken links: 216 of 349 on
  one real archive. Only ids of objects in the archive are now reported.
  Objects a dry run would create are no longer reported either.
- **Entry points are linked to their flows.** Entry points reference flows,
  but were imported before them, so they would have been sent the old
  tenant's flow ids. The importer now creates entry points first and sets
  `flowId` and `outdialQueueId` once flows and queues exist. Desktop
  layouts' `teamIds` are handled the same way, because layouts and teams
  point at each other. Flows whose import response has no id are matched
  to the target by name.
- **Dial numbers are imported.** They have no `name` field, so v0.1.0
  skipped every one as "nameless". They are now matched by number.
- **Entry points are created after the audio files they play**
  (`musicOnHoldId`).
- **Internal bookkeeping (`default_basis`) is no longer sent to the API**
  on create.
- **The source org id inside flow documents is rewritten** to the target
  org.
- **Users are a manual step, not a failure.** Users that already exist in
  the target are matched by email, and team membership is linked to them.
  v0.1.0 reported users as FAILED.
- **Calling locations no longer fail with "no location".** A location has
  no parent location.
- The CLI and the web UI now run the same import sequence
  (`importer.run_import`); they were two hand-maintained copies.

### Known limitations

- **Still not run as a confirmed import against a real tenant.** Every
  change above is covered by tests against a simulated API and by dry runs
  of a real archive. Two API behaviours are assumed and unconfirmed: that
  an entry point can be created without `flowId`, and that a desktop layout
  can be created without `teamIds`. If either is rejected, the error is
  reported for that object.
- Address-book entries are not imported with their address book.
- Audio files are still not re-uploaded.

## [0.1.0] - 2026-09-24

First public release.

### Added

- **A standalone Windows executable** (64-bit), built with PyInstaller. No
  Python install is needed to run it. On macOS and Linux, run the tool from
  source; the source code is attached to every release.
- `--version` flag.
- **Export** of a Webex Contact Center tenant to `<tenant>-export.zip`:
  - 25 Contact Center entities. Entry points are swept across every
    `channelType`, so Channels (digital entry points) are captured.
  - Flows, subflows and functions.
  - 12 Webex Calling object types.
  - A `users.csv` reference manifest.
  - An `UNSUPPORTED.md` checklist listing everything that has no API.
- **Import** into a different tenant:
  - Imports are dependency-ordered and dry-run by default. Nothing is written
    until you pass `--confirm`.
  - A `--select` filter chooses which objects to import.
  - A `--on-conflict skip|update|rename` policy handles objects that already
    exist in the target.
  - IDs are remapped everywhere they appear, including inside flow JSON.
  - The tool refuses to import back into the org the archive came from.
- `inspect` shows an archive's contents without credentials.
- Authentication through OAuth2 authorization code with a loopback redirect,
  or an opt-in personal bearer token set in `.env`.
- One `.env.<profile>` file and one token store per tenant.
- A local web UI (`web`) bound to `127.0.0.1` only, protected by a per-run
  session token.

### Known limitations

- **Import has not yet been run against a real tenant.** It is covered by
  tests against a simulated API only. Run the dry run first and read the plan.
- Audio files are exported, but they are not re-uploaded on import.
- No API exists for Surveys. Recreate them by hand; `UNSUPPORTED.md` lists them.
- Contact Center users can only be exported, as a CSV reference. Invite and
  license users in Control Hub.
- The executable is unsigned, so Windows SmartScreen warns the first time you
  run it. The user guide, §0, explains how to continue.
- No macOS or Linux executables yet.

[Unreleased]: https://github.com/dwolgast-lab/wxcc-sandbox-exporter/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/dwolgast-lab/wxcc-sandbox-exporter/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/dwolgast-lab/wxcc-sandbox-exporter/releases/tag/v0.1.0
