# API notes — observed behaviour

Findings from a **live WxCC sandbox**, via `scripts/probe.py` and
`scripts/probe2.py`. **The OpenAPI documents map what exists; the probe records
what works. Where they disagree, the probe wins.**

Probed: **2026-08-26** against org `174bc2cb-6f00-48c5-b5ce-f4a93ffec5df`
(`davidwolgast-8xgo`), region host `https://api.wxcc-us1.cisco.com`,
authenticated with a personal bearer token.

---

## Summary

| ID | Question | Verdict |
|---|---|---|
| U1 | flows `projectId` | **RESOLVED — a fixed constant, `5e5c9ad6d61f870d6d778c1b`, identical on every tenant.** Flows work. |
| U2 | `flowType` for Subflows | **RESOLVED — `SUBFLOW`.** Returns 3 subflows vs 23 flows on the live tenant. |
| U3 | functions import multipart field | **RESOLVED — part named `file`, `.json` filename, typed `application/octet-stream`.** |
| U4 | default detection | **A REAL FLAG EXISTS.** `systemDefault` is present on 14 of 22 entities. The earlier claim that no entity has one was wrong. |
| U7 | audio-file binaries | **ROUTE FOUND** — `GET organization/{orgId}/blob/{blobId}`. The first live export fetched 0 of 11. |
| U5 | Calling reachability | **CONFIRMED reachable**, but two route/envelope defects found. |
| U6 | tenant name for the filename | **CONFIRMED** — but from a different host than assumed. |

---

## U6 — tenant name (and the archive filename)

**`GET organization/{orgId}` on the WxCC host is not usable.** It is not published
in the Contact Center OpenAPI document (a search for a bare-orgid path returns
nothing), and live it returns **HTTP 429 persistently**, surviving the client's
full 5-attempt exponential backoff. It is not a reliable source.

**Use the Webex host instead:**

```
GET https://webexapis.com/v1/organizations/{orgId}
200 {"id": "Y2lzY29zcGFyazovL3VzL09SR0FOSVpBVElPTi8xNzRiYzJjYi0...",
     "displayName": "davidwolgast-8xgo",
     "created": "2026-03-27T19:53:04.199Z"}
```

The field is **`displayName`**, not `name`. It yields `davidwolgast-8xgo` —
exactly the value the spec asked the archive to be named after.

`GET /identity/organizations/{orgId}` also returns `displayName` and works.

**Consequence:** archive filename is `davidwolgast-8xgo-export.zip`.

**`subscriptionType` — revised.** An earlier revision of this file said the tag
had "no confirmed source." That over-stated it. The first live export **did**
read `subscriptionType: "TRIAL"` from `GET organization/{orgId}` on the WxCC
host and correctly printed `[trial/sandbox]`.

So the 429s above were **transient rate-limiting caused by the probe's own
request volume**, not a dead endpoint. The correct reading: the CC endpoint works
but throttles aggressively and cannot be relied on for the *name* when the tool
is making many calls. The Webex host is the dependable source for `displayName`;
the CC endpoint remains a best-effort source for `subscriptionType`, and its
failure must degrade to "unknown" rather than to a false `[trial/sandbox]`.

---

## U4 — default detection: `systemDefault` is REAL

**CORRECTION.** An earlier revision of this file asserted "there is no
`isDefault` field on any entity." **That was wrong**, and it was an inferred
claim stated as fact. Probing the live tenant found **`systemDefault` on 14 of
22 entities.** It never appeared in the OpenAPI schemas I searched, but the API
returns it.

Entities that DO carry `systemDefault`:

`agent-profile`, `audio-file`, `auxiliary-code`, `cad-variable`,
`contact-service-queue`, `desktop-layout`, `entry-point`, `multimedia-profile`,
`site`, `skill`, `team`, `user`, `user-profile`, `work-type`

Entities that do NOT (8):

`address-book`, `business-hours`, `dial-number`, `holiday-list`, `outdial-ani`,
`overrides`, `resource-collection`, `skill-profile`

The value is `true`, `false`, or absent. `auxiliary-code` additionally carries
`defaultCode`, which is a *different* thing — it marks the code selected by
default, not a system-provisioned object.

### The createdTime heuristic is measurably worse — keep it only as a fallback

The heuristic (objects created within 1800 s of the org's `created`) was checked
against the real flag on all 14 flag-bearing entities in a live export:

| result | entities |
|---|---|
| heuristic agrees with `systemDefault` | 11 |
| heuristic **over**-reports | 3 — `team` (+1), `audio-file` (+1), `user` (+3) |
| heuristic under-reports | 0 |

**Every disagreement is a false positive** — the heuristic calling something a
provisioning default that the API says is not. On `team` it wrongly flags
`Sandbox Team AgentType - sukt` (created 515 s after the org). That is precisely
the failure mode that makes `--only-non-default` lose real configuration.

**Therefore:** `systemDefault` is the primary signal wherever it exists. The
createdTime heuristic applies **only** to the 8 entities that lack the flag, and
must be labelled as inferred rather than reported as fact.

Reference measurements from org `davidwolgast-8xgo`
(created `2026-03-27T19:53:04.199Z` = `1774641184199` ms):

| entity | name | delta from org creation | `systemDefault` |
|---|---|---|---|
| site | Site-1 | 324 s | true |
| site | Architect Lounge | 124.7 days | absent |
| team | Team-1 | 324 s | true |
| team | Sandbox Team AgentType - sukt | 515 s | **absent — heuristic false positive** |
| auxiliary-code | RONA, Sale, Meeting, … | 325 s | true |
| auxiliary-code | testForClaude | 116.9 days | absent |
| contact-service-queue | Queue-1, Outdial Queue-1, … | 326 s | true |
| contact-service-queue | WhisperTest_Q | 33.1 days | absent |

`createdTime` is epoch **milliseconds** and is present on every entity probed.

---

## U7 — audio-file binaries: the download route

The first live export fetched **0 of 11** audio files. The record carries
**`blobId`**, and none of the URL fields the exporter looked for
(`url`, `fileUrl`, `audioFileUrl`, `downloadUrl`) exists on any record.

A real record, in full:

```json
{
  "id": "01938b9c-e218-42a1-a19c-1d58a96a53dd",
  "name": "SandboxUpload1.wav",
  "contentType": "AUDIO_X_WAV",
  "blobId": "audio-file_18a32fe9-0bcd-487d-b884-3a80a5802686",
  "links": [],
  "createdTime": 1774641703000,
  "lastUpdatedTime": 1774641703000
}
```

The item `GET` adds **nothing** over the list row — there is no richer
representation to fetch.

**The working route, found by probing ten candidates:**

```
GET organization/{orgId}/blob/{blobId}
200   160674 bytes   Content-Type: (empty)   first bytes: 52 49 46 46 ... 57 41 56 45  (RIFF ... WAVE)
```

Confirmed real audio by its `RIFF….WAVE` magic bytes. Note the response carries
**no `Content-Type`**, so the extension must come from the record's `name` or
its `contentType` enum (`AUDIO_X_WAV`), not from the response headers.

Every other candidate 404s, including
`audio-file/{id}/download`, `/content`, `/file`, `/blob`,
`v2/audio-file/{id}/download`, `audio-file/blob/{blobId}`, `file/{blobId}`, and
`v2/blob/{blobId}`.

---

## U1 / U2 — Flows: RESOLVED

**CORRECTION.** An earlier revision of this file concluded that "the Flows API
is not served on the WxCC regional host at all." **That was wrong**, and it was
a bad inference: eleven candidate base paths all returned empty-body 404s, and I
generalised from "this project id 404s" to "this whole API is absent."

The cause was the **id format**. The route only matches a 24-character hex
ObjectId. Every probe passed the org id — a 36-character UUID with dashes — so
the request never matched the route and the gateway 404'd with no body. The
"routing miss" reading was right; the conclusion drawn from it was not.

### `projectId` is a fixed constant, identical on every tenant

```
5e5c9ad6d61f870d6d778c1b
```

It is **not** the org id and it is **not** discoverable — there is no
project-list endpoint. Confirmed live 2026-08-26 against `davidwolgast-8xgo`:

```
GET /{orgId}/project/5e5c9ad6d61f870d6d778c1b/flows?flowType=FLOW
    200   23 flows    (Record_Agent_Greeting, BasicQueueFlow, StandardCallFlow, …)
GET /{orgId}/project/5e5c9ad6d61f870d6d778c1b/flows?flowType=SUBFLOW
    200    3 subflows (Queue_Record, QueueRecord, QueueRecord1)
GET /{orgId}/project/{proj}/v2/flows/{flowId}:export?flowType=FLOW
    200   26 KB of flow JSON
```

The export document's top-level keys:

```
associatedChannels, description, desktopVariableViewOrder, edges, eventFlows,
flowType, id, name, nodes, orgId, preferences, projectId, schemaVersion,
variables, version
```

**`flowType=SUBFLOW` (U2) is confirmed** — it returns a set distinct from `FLOW`.

### TRAP: a wrong project id returns 200, not an error

```
GET /{orgId}/project/deadbeefdeadbeefdeadbeef/flows   ->  200  []
```

A well-formed but wrong project id yields an **empty list with a success
status**. An empty flow list therefore does **not** prove the project id is
right. Only the constant above is known to return a tenant's real flows.

A live export with the correct constant produced 23 flows, 3 subflows and 2
functions, with zero errors.

---

## U3 — Functions: RESOLVED

**Export**, confirmed live:

```
GET  /v1/{orgId}/functions             200  {"data": [...], "pageInfo": {...}}
POST /v1/{orgId}/functions/{id}:export 200
     keys: description, inputs, language, name, outputs, runtime, sourceCode
```

**Import** — the shape came from a REAL successful import run against the live
tenant, not from the spec and not from a guess:

```
POST /v1/{orgId}/functions:import?overwrite=
Headers: Authorization: Bearer …,  Accept: application/json
multipart/form-data, ONE part:
    name     = "file"
    filename = "Copy_parse_call_data_6.json"      (a .json filename)
    type     = "application/octet-stream"
    content  = the exported function document, verbatim
```

Two things worth stating precisely, because the original implementation had
them wrong:

- The part is typed **`application/octet-stream`**, *not* `application/json`,
  which is what this project originally sent.
- `overwrite` is a **query parameter**, not a form field.

The field name `"file"` matches what the plan had guessed — but it was a guess
at the time, and the refusal path that blocked it was correct. The guard
remains: if `FUNCTION_IMPORT_FIELD` is ever reset to the sentinel,
`import_functions` refuses instead of inventing a name.

---

## U5 — Webex Calling

**Calling IS provisioned on this sandbox and every org-level endpoint returns
200.** Two locations exist. All object collections are currently empty, so
element-level shapes could not be observed.

### Defect 1 — the `call-queues` route in the registry was wrong

```
GET telephony/config/locations/{locationId}/queues   404  "No static resource ..."
GET telephony/config/queues                          200  {"queues": []}     <-- correct
GET telephony/config/callQueues                      404
```

Call queues are listed **org-wide**, not per-location. The registry's
`call-queues.list` was an extrapolation (flagged `UNCONFIRMED (U5)`); it is now
corrected to `telephony/config/queues` with `scope: "org"`.

The other three previously-unconfirmed location-scoped routes are **correct**:

```
telephony/config/locations/{loc}/callParks    200 {"callParks": []}
telephony/config/locations/{loc}/callPickups  200 {"callPickups": []}
telephony/config/locations/{loc}/schedules    200 {"schedules": []}
```

### Defect 2 — every Calling response uses its own envelope key

`client.list_all` recognised only `data`, `items`, `locations`, `announcements`,
so it **raised on every org-scope Calling object**:

```
FAIL  autoAttendants: expected a list response ..., got keys ['autoAttendants']
FAIL  huntGroups:     expected a list response ..., got keys ['huntGroups']
FAIL  announcements:  expected a list response ..., got keys []
```

Observed envelopes:

| endpoint | envelope key |
|---|---|
| `locations` | `items` |
| `telephony/config/autoAttendants` | `autoAttendants` |
| `telephony/config/huntGroups` | `huntGroups` |
| `telephony/config/callParkExtensions` | `callParkExtensions` |
| `telephony/config/paging` | **`locationPaging`** (not `paging`) |
| `telephony/config/queues` | `queues` |
| `telephony/config/locations/{loc}/callParks` | `callParks` |
| `telephony/config/locations/{loc}/callPickups` | `callPickups` |
| `telephony/config/locations/{loc}/schedules` | `schedules` |
| `telephony/config/announcements` | **`{}` — no key at all when empty** |
| `telephony/config/virtualExtensions` | **`{}` when empty** |
| `telephony/config/operatingModes` | **`{}` when empty** |

The key is not derivable from the path (`paging` → `locationPaging`), and an
empty collection may omit the key entirely. `list_all` now selects the single
list-valued key generically and treats a body with no list-valued key as an
empty collection.

### Still unknown

**Which field carries the location on an org-scope Calling item.** Every
collection was empty, so no row could be inspected. The
`LOCATION_ID_CANDIDATES` list in `export_calling.py`
(`locationId`, `location.id`, `locationID`) remains **unverified**. Create one
auto attendant or hunt group in the sandbox and re-run `scripts/probe.py` to
settle it.

---

## Rate limiting

`GET organization/{orgId}` on the WxCC host returned **429 on every attempt**,
including after the client's full retry ladder (5 attempts, exponential backoff
to 30 s). Other CC endpoints under the same token answered 200 in the same run,
so this is endpoint-specific rather than a global throttle.
