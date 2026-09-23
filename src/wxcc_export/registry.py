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
    """The entity name is not in the registry at all."""


class NoChildCollection(Exception):
    """The entity is known, but has no child collection (address-book and
    outdial-ani are the only two that do)."""


class NotWritable(Exception):
    """The entity has no create endpoint in this API."""


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
        # VERIFIED 2026-09-23: the field is "skillType" (values seen:
        # PROFICIENCY), not "type".
        "create": ["name", "serviceLevelThreshold", "skillType", "active"],
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
        # VERIFIED 2026-09-23: the field is "dialledNumber", not "number".
        # DEPENDENCY WAS INVERTED: a dial-number carries entryPointId, and
        # GET entry-point/{id}/incoming-references reports ['dial-number'],
        # so the ENTRY POINT must exist first. The registry previously had
        # entry-point depending on dial-number, which would have created every
        # dial-number before its target existed and dangled the reference.
        "create": ["dialledNumber"], "deps": ["entry-point"], "writable": True,
    },
    # Added 2026-09-23 after a live probe found these carried real data that
    # the exporter was silently missing. contact-number held one user-created
    # row; dial-plan held two (both systemDefault). Confirmed against
    # davidwolgast-8xgo before its sandbox expired.
    "contact-number": {
        "list": "v2/contact-number", "item": "contact-number/{id}",
        "create": ["number"], "deps": [], "writable": True,
        # This entity has NO `name` field - identity is the phone number - so
        # collision detection has to key off `number` or every row looks
        # nameless and gets skipped.
        "name_field": "number",
        "note": "Observed record: {id, number, links, createdTime, "
                "lastUpdatedTime}. No name, no systemDefault.",
    },
    "dial-plan": {
        "list": "v2/dial-plan", "item": "dial-plan/{id}",
        "create": ["name", "regularExpression", "active"], "deps": [],
        "writable": True,
        "note": "Both rows on the probed tenant were systemDefault:true "
                "(US, Any Format), so an import will normally skip them.",
    },
    "agent-personal-greeting": {
        "list": "v3/agent-personal-greeting",
        "item": "agent-personal-greeting/{id}",
        "create": ["name"], "deps": [], "writable": True, "binary": True,
        "note": "EMPTY on the probed tenant, so its record shape and its "
                "binary download route are BOTH UNVERIFIED. It carries audio "
                "like audio-file does; if a tenant has greetings, expect the "
                "blob fetch to need the same treatment and probe it first.",
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
        # VERIFIED 2026-09-23: dial-number/{id}/incoming-references reports
        # ['outdial-ani'], so dial numbers must exist first.
        "create": ["name"], "deps": ["dial-number"], "writable": True,
        "child": {"list": "v2/outdial-ani/{parentId}/entry",
                  "create": "outdial-ani/{parentId}/entry"},
    },
    "user-profile": {
        "list": "v3/user-profile", "item": "user-profile/{id}",
        # VERIFIED 2026-09-23: resource-collection/{id}/incoming-references
        # reports ['user-profile'], so the collection must exist first.
        "create": ["name", "profileType"], "deps": ["resource-collection"],
        "writable": True,
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
        # VERIFIED 2026-09-23: real records carry only id/name/description/
        # links/timestamps. There is no `active` field - it was invented.
        "create": ["name"], "deps": ["skill"], "writable": True,
    },
    "business-hours": {
        "list": "v2/business-hours", "item": "business-hours/{id}",
        # VERIFIED 2026-09-23: the field is "timezone" (lowercase z), not
        # "timeZone". The old spelling would have 400d on every create.
        "create": ["name", "timezone"], "deps": ["holiday-list", "overrides"],
        "writable": True,
    },
    "entry-point": {
        "list": "v2/entry-point", "item": "entry-point/{id}",
        # CHANNELS LIVE HERE. A "Channel" in Control Hub is an entry point with
        # a non-TELEPHONY channelType - there is no separate Channels API.
        # Confirmed 2026-09-23: EntryPointDTO carries channelType,
        # socialChannelType, assetId, subscriptionId, imiOrgType.
        #
        # The UNFILTERED listing hides systemInternal rows: on the probed
        # tenant it returned 10 while ?channelTypes=TELEPHONY returned 11, the
        # extra being Record_Agent_Greeting (systemInternal: true). Sweeping
        # each channelType explicitly and unioning by id is the only listing
        # shape observed to return everything.
        "list_sweep": {
            "param": "channelTypes",
            "values": ["TELEPHONY", "EMAIL", "CHAT", "SOCIAL_CHANNEL", "VIDEO",
                       "FAX", "OTHERS", "CUSTOM_MESSAGING", "WORK_ITEM"],
        },
        "create": ["name", "entryPointType", "channelType",
                   "serviceLevelThreshold", "active", "maximumActiveContacts"],
        # Was ["dial-number"] - inverted, see the dial-number entry.
        "deps": [], "writable": True,
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

# NOTE: every path below is relative to the WEBEX host
# (https://webexapis.com/v1), NOT the WxCC regional host that CC_ENTITIES
# paths use. Handing one of these to the Contact Center client will 404.
CALLING_OBJECTS: dict[str, dict] = {
    "locations": {"list": "locations", "item": "locations/{id}",
                  "scope": "org", "writable": True},
    # Probe-confirmed 2026-08-26 (docs/api-notes.md, U5 Defect 1): 200 OK.
    "schedules": {"list": "telephony/config/locations/{locationId}/schedules",
                  "item": "telephony/config/locations/{locationId}/schedules/{id}",
                  "scope": "location", "writable": True},
    "auto-attendants": {"list": "telephony/config/autoAttendants",
                        "item": "telephony/config/locations/{locationId}/autoAttendants/{id}",
                        "scope": "org", "writable": True},
    "hunt-groups": {"list": "telephony/config/huntGroups",
                    "item": "telephony/config/locations/{locationId}/huntGroups/{id}",
                    "scope": "org", "writable": True},
    # Probe-confirmed 2026-08-26 (docs/api-notes.md, U5 Defect 1): call queues
    # are listed org-wide, not per location.
    #   GET telephony/config/locations/{locationId}/queues -> 404
    #   GET telephony/config/queues                         -> 200 {"queues": []}
    "call-queues": {"list": "telephony/config/queues",
                    "item": "telephony/config/locations/{locationId}/queues/{id}",
                    "scope": "org", "writable": True},
    # UNCONFIRMED (U5): the location-scoped item route below is inferred.
    # The published location path for Call Park is .../callParks, which is a
    # DIFFERENT object (see "call-parks"). Probe before trusting.
    "call-park-extensions": {"list": "telephony/config/callParkExtensions",
                             "item": "telephony/config/locations/{locationId}/callParkExtensions/{id}",
                             "scope": "org", "writable": True},
    # Probe-confirmed 2026-08-26 (docs/api-notes.md, U5 Defect 1): 200 OK.
    "call-parks": {"list": "telephony/config/locations/{locationId}/callParks",
                   "item": "telephony/config/locations/{locationId}/callParks/{id}",
                   "scope": "location", "writable": True},
    # Probe-confirmed 2026-08-26 (docs/api-notes.md, U5 Defect 1): 200 OK.
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
    # A Channel is an entry point with a non-TELEPHONY channelType.
    "Channels": "entry-point",
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

# CORRECTION 2026-09-23: "Channels" was previously listed here as having no
# API. That was WRONG - it came from searching for paths and tags named
# "channel", which found nothing because channels are not a separate resource.
# A Channel is an ENTRY POINT whose channelType is not TELEPHONY, and the
# exporter has always captured them via the entry-point entity.
UNSUPPORTED: dict[str, str] = {
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


def name_field(entity: str) -> str:
    """The field that carries an object's human identity.

    Almost always "name". contact-number is the exception - it has no name,
    only a phone number - and collision detection keys off this, so getting it
    wrong makes every row look nameless and get skipped.
    """
    return _spec(entity).get("name_field", "name")


def list_path(entity: str) -> str:
    return f"organization/{{orgId}}/{_spec(entity)['list']}"


def item_path(entity: str, item_id: str) -> str:
    tail = _spec(entity)["item"].replace("{id}", item_id)
    return f"organization/{{orgId}}/{tail}"


def create_path(entity: str) -> str:
    spec = _spec(entity)
    if not spec.get("writable", False):
        # Deriving a create path from the item path is a guess that LOOKS
        # right. `user` publishes GET only on its collection, so returning
        # organization/{orgId}/user here would hand a caller a POST target
        # the API does not implement.
        raise NotWritable(
            f"{entity} has no create endpoint. {spec.get('note', '')}".strip())
    tail = spec["item"].replace("/{id}", "")
    return f"organization/{{orgId}}/{tail}"


def child_list_path(entity: str, parent_id: str) -> str:
    child = _spec(entity).get("child")
    if not child:
        raise NoChildCollection(f"{entity} has no child collection")
    return f"organization/{{orgId}}/{child['list'].replace('{parentId}', parent_id)}"


def child_create_path(entity: str, parent_id: str) -> str:
    child = _spec(entity).get("child")
    if not child:
        raise NoChildCollection(f"{entity} has no child collection")
    return f"organization/{{orgId}}/{child['create'].replace('{parentId}', parent_id)}"
