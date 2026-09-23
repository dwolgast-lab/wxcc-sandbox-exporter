import pytest
from wxcc_export import export_cc
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"

# Real org `created` for davidwolgast-8xgo, from docs/api-notes.md U4
# (2026-03-27T19:53:04.199Z, probed 2026-08-26).
ORG_CREATED_MS = 1774641184199
DAY_MS = 86_400_000


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


def test_export_entity_threads_org_created_ms_into_tagging(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": [
        {"id": "s1", "name": "Site-1", "createdTime": ORG_CREATED_MS + 324_000},
        {"id": "s2", "name": "Architect Lounge",
         "createdTime": ORG_CREATED_MS + int(124.7 * DAY_MS)},
    ]})
    result = export_cc.export_entity(make(transport), "site",
                                     org_created_ms=ORG_CREATED_MS)
    flags = {i["id"]: i["likely_default"] for i in result["items"]}
    assert flags == {"s1": True, "s2": False}


def test_export_entity_without_org_created_ms_does_not_tag(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": [
        {"id": "s1", "name": "Site-1", "createdTime": ORG_CREATED_MS + 324_000},
    ]})
    result = export_cc.export_entity(make(transport), "site")
    assert "likely_default" not in result["items"][0]


def test_export_all_threads_org_created_ms_to_every_entity(transport):
    transport.add("GET /organization/ORG1/v2/site", body={"data": [
        {"id": "s1", "createdTime": ORG_CREATED_MS + 324_000}]})
    transport.add("GET /organization/ORG1/v2/team", body={"data": [
        {"id": "t1", "createdTime": ORG_CREATED_MS + int(33.1 * DAY_MS)}]})
    out = export_cc.export_all(make(transport), ["site", "team"],
                               org_created_ms=ORG_CREATED_MS)
    assert out["site"]["items"][0]["likely_default"] is True
    assert out["team"]["items"][0]["likely_default"] is False


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
    # Generic window-math check, anchored explicitly rather than on org creation.
    base = 1700000000000                       # epoch millis
    items = [
        {"id": "a", "createdTime": base},
        {"id": "b", "createdTime": base + 5_000},          # +5s    -> default
        {"id": "c", "createdTime": base + 2_000_000},      # +33.3m -> not default
    ]
    tagged = export_cc.tag_likely_defaults(items, org_created_ms=base)
    flags = {i["id"]: i["likely_default"] for i in tagged}
    assert flags == {"a": True, "b": True, "c": False}


def test_tag_likely_defaults_is_a_noop_without_created_time():
    items = [{"id": "a"}, {"id": "b"}]
    tagged = export_cc.tag_likely_defaults(items, org_created_ms=1700000000000)
    assert all("likely_default" not in i for i in tagged)


def test_tag_likely_defaults_handles_an_empty_list():
    assert export_cc.tag_likely_defaults([], org_created_ms=1700000000000) == []


def test_tag_likely_defaults_anchors_on_org_created_time():
    # Real deltas from docs/api-notes.md U4 (org davidwolgast-8xgo, probed
    # 2026-08-26): provisioning finishes within ~515s of org creation; the
    # earliest user-created object is 33.1 days later.
    items = [
        {"id": "site-1", "createdTime": ORG_CREATED_MS + 324_000},           # +324s
        {"id": "team-1", "createdTime": ORG_CREATED_MS + 324_000},           # +324s
        {"id": "sandbox-team", "createdTime": ORG_CREATED_MS + 515_000},     # +515s
        {"id": "whisper-test-q",
         "createdTime": ORG_CREATED_MS + int(33.1 * DAY_MS)},                # +33.1d
        {"id": "test-for-claude",
         "createdTime": ORG_CREATED_MS + int(116.9 * DAY_MS)},               # +116.9d
        {"id": "architect-lounge",
         "createdTime": ORG_CREATED_MS + int(124.7 * DAY_MS)},               # +124.7d
    ]
    tagged = export_cc.tag_likely_defaults(items, org_created_ms=ORG_CREATED_MS)
    flags = {i["id"]: i["likely_default"] for i in tagged}
    assert flags == {
        "site-1": True, "team-1": True, "sandbox-team": True,
        "whisper-test-q": False, "test-for-claude": False,
        "architect-lounge": False,
    }


def test_tag_likely_defaults_without_anchor_does_not_tag():
    # No org_created_ms means no defensible claim - decline to tag rather than
    # guess. Items come back byte-for-byte unchanged.
    items = [{"id": "a", "createdTime": ORG_CREATED_MS},
             {"id": "b", "createdTime": ORG_CREATED_MS + 324_000}]
    tagged = export_cc.tag_likely_defaults(items)
    assert tagged == items
    assert all("likely_default" not in i for i in tagged)


def test_tag_likely_defaults_entity_with_no_defaults_is_not_false_flagged():
    # Regression for the old bug: anchoring on "the earliest item of this
    # entity" tagged the oldest user-created item as a provisioning default
    # whenever an entity happened to have no real defaults at all. These are
    # the real WhisperTest_Q / Fruits / testForClaude deltas - all user-created,
    # none within the org-creation window.
    items = [
        {"id": "whisper-test-q",
         "createdTime": ORG_CREATED_MS + int(33.1 * DAY_MS)},
        {"id": "fruits", "createdTime": ORG_CREATED_MS + int(48.9 * DAY_MS)},
        {"id": "test-for-claude",
         "createdTime": ORG_CREATED_MS + int(116.9 * DAY_MS)},
    ]
    tagged = export_cc.tag_likely_defaults(items, org_created_ms=ORG_CREATED_MS)
    assert all(i["likely_default"] is False for i in tagged)


# --- systemDefault is authoritative; the heuristic is a fallback -------------
# Numbers below are REAL, from org davidwolgast-8xgo
# (created 2026-03-27T19:53:04.199Z = 1774641184199 ms). See docs/api-notes.md U4.

ORG_CREATED_MS = 1774641184199


def test_system_default_beats_the_heuristic():
    # 'Sandbox Team AgentType - sukt' was created 515s after the org, so the
    # heuristic called it a provisioning default. The API says it is not.
    # This exact item is why systemDefault is now primary.
    items = [
        {"id": "t1", "name": "Team-1",
         "createdTime": 1774641508000, "systemDefault": True},
        {"id": "t2", "name": "Sandbox Team AgentType - sukt",
         "createdTime": 1774641699000},          # key absent -> not a default
    ]
    out = export_cc.tag_likely_defaults(items, ORG_CREATED_MS)
    by_name = {i["name"]: i for i in out}
    assert by_name["Team-1"]["likely_default"] is True
    assert by_name["Sandbox Team AgentType - sukt"]["likely_default"] is False, (
        "the heuristic would have said True; systemDefault must win"
    )
    assert all(i["default_basis"] == "systemDefault" for i in out)


def test_system_default_false_is_respected_even_inside_the_window():
    # 3 users were created during provisioning but carry systemDefault False.
    items = [{"id": "u1", "createdTime": 1774641300000, "systemDefault": False}]
    out = export_cc.tag_likely_defaults(items, ORG_CREATED_MS)
    assert out[0]["likely_default"] is False
    assert out[0]["default_basis"] == "systemDefault"


def test_absent_flag_on_a_sibling_means_not_default_not_unknown():
    # If ANY record in the collection carries the key, the entity publishes it,
    # so absence on a sibling is a real "no".
    items = [{"id": "a", "systemDefault": True, "createdTime": 1},
             {"id": "b", "createdTime": 2}]
    out = export_cc.tag_likely_defaults(items, ORG_CREATED_MS)
    assert [i["likely_default"] for i in out] == [True, False]


def test_heuristic_applies_only_when_no_record_has_the_flag():
    # These 8 entities carry no systemDefault at all: address-book,
    # business-hours, dial-number, holiday-list, outdial-ani, overrides,
    # resource-collection, skill-profile.
    items = [
        {"id": "h1", "createdTime": 1774641508000},      # +324s  -> default
        {"id": "h2", "createdTime": 1785417712000},      # +125d  -> not
    ]
    out = export_cc.tag_likely_defaults(items, ORG_CREATED_MS)
    assert [i["likely_default"] for i in out] == [True, False]
    assert all(i["default_basis"] == "createdTime-heuristic" for i in out)


def test_the_basis_is_recorded_so_fact_and_inference_are_distinguishable():
    flagged = export_cc.tag_likely_defaults(
        [{"id": "a", "systemDefault": True}], ORG_CREATED_MS)
    inferred = export_cc.tag_likely_defaults(
        [{"id": "b", "createdTime": 1774641508000}], ORG_CREATED_MS)
    assert flagged[0]["default_basis"] == "systemDefault"
    assert inferred[0]["default_basis"] == "createdTime-heuristic"


def test_no_flag_and_no_anchor_means_no_tag_at_all():
    items = [{"id": "a", "createdTime": 1774641508000}]
    out = export_cc.tag_likely_defaults(items, None)
    assert "likely_default" not in out[0]
    assert "default_basis" not in out[0]


def test_default_code_is_not_confused_with_system_default():
    # auxiliary-code carries BOTH. defaultCode marks the code selected by
    # default; systemDefault marks a provisioning-created object.
    items = [{"id": "a", "name": "RONA", "defaultCode": False,
              "systemDefault": True, "createdTime": 1774641509000}]
    out = export_cc.tag_likely_defaults(items, ORG_CREATED_MS)
    assert out[0]["likely_default"] is True
    assert out[0]["defaultCode"] is False


# --- entry-point channel sweep ----------------------------------------------

def test_sweep_unions_rows_the_plain_listing_hides(transport):
    """Live: plain listing gave 10 entry points, channelTypes=TELEPHONY gave 11.

    The hidden row was systemInternal. The sweep must recover it.
    """
    base = "GET /organization/ORG1/v2/entry-point"
    transport.add(base, body={"data": [{"id": "ep1", "name": "Visible",
                                        "channelType": "TELEPHONY"}]})
    transport.add(f"{base}?channelTypes=TELEPHONY&pageSize=100",
                  body={"data": [{"id": "ep1", "name": "Visible",
                                  "channelType": "TELEPHONY"},
                                 {"id": "ep2", "name": "Record_Agent_Greeting",
                                  "channelType": "TELEPHONY",
                                  "systemInternal": True}]})
    for ct in ("EMAIL","CHAT","SOCIAL_CHANNEL","VIDEO","FAX","OTHERS",
               "CUSTOM_MESSAGING","WORK_ITEM"):
        transport.add(f"{base}?channelTypes={ct}&pageSize=100", body={"data": []})
    out = export_cc.export_entity(make(transport), "entry-point")
    assert out["count"] == 2
    assert {i["id"] for i in out["items"]} == {"ep1", "ep2"}


def test_sweep_picks_up_a_digital_channel_entry_point(transport):
    # A Channel IS an entry point with a non-TELEPHONY channelType.
    base = "GET /organization/ORG1/v2/entry-point"
    transport.add(base, body={"data": []})
    transport.add(f"{base}?channelTypes=TELEPHONY&pageSize=100", body={"data": []})
    transport.add(f"{base}?channelTypes=EMAIL&pageSize=100",
                  body={"data": [{"id": "ep9", "name": "Support Email",
                                  "channelType": "EMAIL"}]})
    for ct in ("CHAT","SOCIAL_CHANNEL","VIDEO","FAX","OTHERS",
               "CUSTOM_MESSAGING","WORK_ITEM"):
        transport.add(f"{base}?channelTypes={ct}&pageSize=100", body={"data": []})
    out = export_cc.export_entity(make(transport), "entry-point")
    assert [i["channelType"] for i in out["items"]] == ["EMAIL"]


def test_sweep_does_not_duplicate_a_row_seen_twice(transport):
    base = "GET /organization/ORG1/v2/entry-point"
    row = {"id": "ep1", "name": "Dup", "channelType": "TELEPHONY"}
    transport.add(base, body={"data": [row]})
    for ct in ("TELEPHONY","EMAIL","CHAT","SOCIAL_CHANNEL","VIDEO","FAX",
               "OTHERS","CUSTOM_MESSAGING","WORK_ITEM"):
        transport.add(f"{base}?channelTypes={ct}&pageSize=100", body={"data": [row]})
    out = export_cc.export_entity(make(transport), "entry-point")
    assert out["count"] == 1


def test_one_failing_filter_value_does_not_lose_the_others(transport):
    base = "GET /organization/ORG1/v2/entry-point"
    transport.add(base, body={"data": []})
    transport.add(f"{base}?channelTypes=TELEPHONY&pageSize=100", status=500, body={})
    transport.add(f"{base}?channelTypes=EMAIL&pageSize=100",
                  body={"data": [{"id": "ep9", "channelType": "EMAIL"}]})
    for ct in ("CHAT","SOCIAL_CHANNEL","VIDEO","FAX","OTHERS",
               "CUSTOM_MESSAGING","WORK_ITEM"):
        transport.add(f"{base}?channelTypes={ct}&pageSize=100", body={"data": []})
    out = export_cc.export_entity(make(transport), "entry-point")
    assert out["count"] == 1


def test_an_entity_without_a_sweep_makes_one_plain_call(transport):
    transport.add("GET /organization/ORG1/v2/site",
                  body={"data": [{"id": "s1", "name": "A"}]})
    export_cc.export_entity(make(transport), "site")
    assert len(transport.calls) == 1
