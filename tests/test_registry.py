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


def test_only_surveys_is_declared_unsupported():
    """Channels was wrongly listed here.

    The original claim came from searching for paths and tags named "channel",
    which found nothing - because a Channel is not a separate resource. It is
    an ENTRY POINT whose channelType is not TELEPHONY, and the exporter has
    always captured them through the entry-point entity.
    """
    assert set(registry.UNSUPPORTED) == {"Surveys"}
    assert len(registry.UNSUPPORTED["Surveys"]) > 30


def test_channels_map_to_the_entry_point_entity():
    assert registry.SPEC_OBJECT_MAP["Channels"] == "entry-point"


def test_entry_point_sweeps_every_channel_type():
    """The unfiltered listing hides systemInternal rows.

    Observed live: the plain listing returned 10 entry points while
    ?channelTypes=TELEPHONY returned 11 - the extra being
    Record_Agent_Greeting (systemInternal: true).
    """
    sweep = registry.CC_ENTITIES["entry-point"]["list_sweep"]
    assert sweep["param"] == "channelTypes"
    # Every value the EntryPointDTO / queue enums publish.
    assert set(sweep["values"]) >= {
        "TELEPHONY", "EMAIL", "CHAT", "SOCIAL_CHANNEL", "VIDEO", "FAX",
        "OTHERS", "CUSTOM_MESSAGING", "WORK_ITEM"}


def test_no_other_entity_declares_a_sweep_it_cannot_use():
    for name, spec in registry.CC_ENTITIES.items():
        sweep = spec.get("list_sweep")
        if sweep:
            assert "param" in sweep and sweep.get("values"), name

def test_calling_objects_declare_their_scope():
    for name, spec in registry.CALLING_OBJECTS.items():
        assert spec["scope"] in ("org", "location"), name


# --- guards on the path builders --------------------------------------------
# child_list_path / child_create_path and the writable gate were untested.


def test_create_path_refuses_a_read_only_entity():
    # /organization/{orgid}/user publishes GET only. Deriving a POST path from
    # the item path yields something that LOOKS right and 404s (or worse).
    with pytest.raises(registry.NotWritable) as exc:
        registry.create_path("user")
    assert "Control Hub" in str(exc.value)


def test_create_path_still_works_for_a_writable_entity():
    assert registry.create_path("site") == "organization/{orgId}/site"


def test_child_list_path_builds_the_entry_collection():
    assert registry.child_list_path("address-book", "ab1") == (
        "organization/{orgId}/v2/address-book/ab1/entry")


def test_child_create_path_drops_the_version_prefix():
    assert registry.child_create_path("address-book", "ab1") == (
        "organization/{orgId}/address-book/ab1/entry")


def test_outdial_ani_also_has_a_child_collection():
    assert "outdial-ani/oa1/entry" in registry.child_list_path("outdial-ani", "oa1")


def test_child_path_on_an_entity_without_children_raises_its_own_error():
    # A known entity that simply has no children is NOT an unknown entity.
    with pytest.raises(registry.NoChildCollection):
        registry.child_list_path("site", "s1")
    assert not issubclass(registry.NoChildCollection, registry.UnknownEntity)


def test_child_path_on_a_genuinely_unknown_entity_still_raises_unknown_entity():
    with pytest.raises(registry.UnknownEntity):
        registry.child_list_path("nonsense", "x1")


def test_only_address_book_and_outdial_ani_declare_children():
    have = {n for n, s in registry.CC_ENTITIES.items() if s.get("child")}
    assert have == {"address-book", "outdial-ani"}


def test_binary_entities_are_flagged():
    # audio-file bytes are fetched separately; the flag is what tells the
    # exporter to go and get them.
    assert registry.CC_ENTITIES["audio-file"].get("binary") is True
    assert registry.CALLING_OBJECTS["announcements"].get("binary") is True


def test_spec_object_map_sentinels_are_not_entities():
    # __flows__ / __subflows__ / __functions__ are routed separately; feeding
    # them to list_path must fail loudly rather than build a bogus URL.
    for value in registry.SPEC_OBJECT_MAP.values():
        if value.startswith("__"):
            with pytest.raises(registry.UnknownEntity):
                registry.list_path(value)
        else:
            assert value in registry.CC_ENTITIES


def test_every_calling_object_with_a_location_scoped_item_declares_the_placeholder():
    for name, spec in registry.CALLING_OBJECTS.items():
        if "{locationId}" in spec["item"]:
            # Task 10 must resolve locationId even for scope == "org" objects,
            # by reading it out of the org-level list payload.
            assert spec["scope"] in ("org", "location"), name


def test_call_queues_list_is_org_scoped_not_location_scoped():
    # Probe-confirmed 2026-08-26 (docs/api-notes.md, U5 Defect 1):
    # GET telephony/config/locations/{locationId}/queues -> 404
    # GET telephony/config/queues                        -> 200 {"queues": []}
    spec = registry.CALLING_OBJECTS["call-queues"]
    assert "{locationId}" not in spec["list"]
    assert spec["list"] == "telephony/config/queues"
    assert spec["scope"] == "org"


# --- create fields and dependencies, verified against a live tenant ---------
# Captured 2026-09-23 from org davidwolgast-8xgo before its sandbox expired,
# via scripts/capture_shapes.py. Every assertion below corrects a registry
# error that real records exposed.

def test_business_hours_timezone_is_lowercase():
    # Was "timeZone". Real records carry "timezone"; the old spelling would
    # have 400d on every create.
    assert "timezone" in registry.CC_ENTITIES["business-hours"]["create"]
    assert "timeZone" not in registry.CC_ENTITIES["business-hours"]["create"]


def test_skill_uses_skill_type_not_type():
    # Real value seen: skillType == "PROFICIENCY".
    assert "skillType" in registry.CC_ENTITIES["skill"]["create"]
    assert "type" not in registry.CC_ENTITIES["skill"]["create"]


def test_skill_profile_has_no_active_field():
    # Real records are id/name/description/links/timestamps only.
    assert registry.CC_ENTITIES["skill-profile"]["create"] == ["name"]


def test_dial_number_uses_dialled_number():
    c = registry.CC_ENTITIES["dial-number"]["create"]
    assert "dialledNumber" in c and "number" not in c
    # entryPointId being a create field is itself the proof that a dial number
    # points AT an entry point, not the other way round.
    assert "entryPointId" in c


def test_create_lists_match_the_live_verified_sibling_registry():
    """These are documentation, not payload builders - nothing in src/ reads
    them - but wrong documentation is how the dependency inversion survived.

    Spot-checks against wxcc-skills/mcp_server.py, which was built with real
    writes against a live tenant.
    """
    expect = {
        "business-hours": {"name", "timezone", "workingHours"},
        "skill": {"name", "serviceLevelThreshold", "skillType", "active"},
        "skill-profile": {"name"},
        "user-profile": {"name", "profileType", "permissionAccessLevel",
                         "resourceAccessLevel", "active"},
        "overrides": {"name", "timezone", "overrides"},
        "holiday-list": {"name", "holidays"},
    }
    for ent, fields in expect.items():
        assert set(registry.CC_ENTITIES[ent]["create"]) == fields, ent


# --- the dependency graph the API's own incoming-references reports ---------

def test_dial_number_depends_on_entry_point_not_the_reverse():
    """The registry had this INVERTED.

    A dial-number record carries entryPointId, and
    GET entry-point/{id}/incoming-references reports ['dial-number'].
    The old graph created every dial number before its entry point existed.
    """
    assert "entry-point" in registry.CC_ENTITIES["dial-number"]["deps"]
    assert "dial-number" not in registry.CC_ENTITIES["entry-point"]["deps"]


def test_user_profile_depends_on_resource_collection():
    # resource-collection/{id}/incoming-references -> ['user-profile']
    assert "resource-collection" in registry.CC_ENTITIES["user-profile"]["deps"]


def test_outdial_ani_depends_on_dial_number():
    # dial-number/{id}/incoming-references -> ['flow', 'outdial-ani']
    assert "dial-number" in registry.CC_ENTITIES["outdial-ani"]["deps"]


def test_observed_reference_graph_is_respected_by_the_ordering():
    """Each pair is (must_exist_first, depends_on_it), read straight off the
    live incoming-references responses."""
    from wxcc_export import plan
    order = plan.order_entities(list(registry.CC_ENTITIES))
    pairs = [
        ("entry-point", "dial-number"),
        ("dial-number", "outdial-ani"),
        ("resource-collection", "user-profile"),
        ("work-type", "auxiliary-code"),
        ("site", "team"),
        ("skill", "skill-profile"),
        ("holiday-list", "business-hours"),
        ("overrides", "business-hours"),
        ("outdial-ani", "agent-profile"),
        ("multimedia-profile", "site"),
    ]
    for first, second in pairs:
        assert order.index(first) < order.index(second), f"{first} must precede {second}"
