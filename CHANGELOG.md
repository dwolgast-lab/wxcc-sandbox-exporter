# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-24

First public release.

### Added

- **Standalone executables** for Windows, macOS and Linux, built with
  PyInstaller. No Python install is needed to run them. The source code is
  still available for anyone who wants to run from Python.
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
- The executables are unsigned. Windows SmartScreen and macOS Gatekeeper will
  warn the first time you run them; see the user guide, §0.

[Unreleased]: https://github.com/dwolgast-lab/wxcc-sandbox-exporter/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/dwolgast-lab/wxcc-sandbox-exporter/releases/tag/v0.1.0
