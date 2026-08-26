from wxcc_export import export_calling
from wxcc_export.client import ApiClient

WEBEX = "https://webexapis.com/v1"


def make(transport):
    return ApiClient(WEBEX, "TOKEN", org_id="ORG1", transport=transport)


def test_list_locations_returns_rows(transport):
    transport.add("GET /v1/locations", body={"items": [{"id": "L1", "name": "HQ"}]})
    assert export_calling.list_locations(make(transport))[0]["id"] == "L1"


def test_org_scoped_object_is_fetched_once(transport):
    transport.add("GET /v1/telephony/config/huntGroups",
                  body={"items": [{"id": "H1", "name": "Sales"}]})
    out = export_calling.export_object(make(transport), "hunt-groups", [])
    assert out["count"] == 1
    assert len(transport.calls) == 1


def test_location_scoped_object_is_fetched_per_location(transport):
    transport.add("GET /v1/telephony/config/locations/L1/schedules",
                  body={"items": [{"id": "S1"}]})
    transport.add("GET /v1/telephony/config/locations/L2/schedules",
                  body={"items": [{"id": "S2"}]})
    locs = [{"id": "L1"}, {"id": "L2"}]
    out = export_calling.export_object(make(transport), "schedules", locs)
    assert out["count"] == 2
    assert {i["id"] for i in out["items"]} == {"S1", "S2"}


def test_location_scoped_items_are_tagged_with_their_location(transport):
    transport.add("GET /v1/telephony/config/locations/L1/schedules",
                  body={"items": [{"id": "S1"}]})
    out = export_calling.export_object(make(transport), "schedules", [{"id": "L1"}])
    assert out["items"][0]["_locationId"] == "L1"


def test_org_scoped_item_with_flat_locationid_is_tagged(transport):
    transport.add("GET /v1/telephony/config/huntGroups",
                  body={"items": [{"id": "H1", "locationId": "L1"}]})
    out = export_calling.export_object(make(transport), "hunt-groups", [])
    assert out["items"][0]["_locationId"] == "L1"


def test_org_scoped_item_with_nested_location_id_is_tagged(transport):
    transport.add("GET /v1/telephony/config/huntGroups",
                  body={"items": [{"id": "H1", "location": {"id": "L1"}}]})
    out = export_calling.export_object(make(transport), "hunt-groups", [])
    assert out["items"][0]["_locationId"] == "L1"


def test_org_scoped_item_with_no_location_gets_none_and_an_error(transport):
    transport.add("GET /v1/telephony/config/huntGroups",
                  body={"items": [{"id": "H1", "name": "Sales"}]})
    out = export_calling.export_object(make(transport), "hunt-groups", [])
    assert "_locationId" in out["items"][0]
    assert out["items"][0]["_locationId"] is None
    assert out["error"] is not None
    assert "H1" in out["error"]


def test_a_403_is_recorded_as_a_scope_problem(transport):
    transport.add("GET /v1/telephony/config/huntGroups", status=403, body={})
    out = export_calling.export_object(make(transport), "hunt-groups", [])
    assert "403" in out["error"]
    assert out["count"] == 0


def test_a_404_is_recorded_as_not_provisioned(transport):
    transport.add("GET /v1/telephony/config/huntGroups", status=404, body={})
    out = export_calling.export_object(make(transport), "hunt-groups", [])
    assert "404" in out["error"]


def test_one_failing_location_does_not_lose_the_others(transport):
    transport.add("GET /v1/telephony/config/locations/L1/schedules", status=403, body={})
    transport.add("GET /v1/telephony/config/locations/L2/schedules",
                  body={"items": [{"id": "S2"}]})
    out = export_calling.export_object(make(transport), "schedules",
                                       [{"id": "L1"}, {"id": "L2"}])
    assert out["count"] == 1
    assert out["error"] is not None


def test_export_all_covers_every_registered_object(transport):
    transport.add("GET /v1/locations", body={"items": []})
    out = export_calling.export_all(make(transport))
    from wxcc_export.registry import CALLING_OBJECTS
    assert set(out["objects"]) == set(CALLING_OBJECTS) - {"locations"}


def test_export_all_stops_early_when_locations_fail(transport):
    transport.add("GET /v1/locations", status=403, body={})
    out = export_calling.export_all(make(transport))
    # Without locations, location-scoped objects cannot be enumerated at all.
    assert out["error"] is not None
