import pytest
from wxcc_export import tenant
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"
WEBEX_BASE = "https://webexapis.com/v1"

# Real values observed live against a WxCC sandbox (docs/api-notes.md, U6):
# GET https://webexapis.com/v1/organizations/{orgId} -> 200
#   {"displayName": "davidwolgast-8xgo", "created": "2026-03-27T19:53:04.199Z"}
REAL_DISPLAY_NAME = "davidwolgast-8xgo"
REAL_CREATED_ISO = "2026-03-27T19:53:04.199Z"
REAL_CREATED_MS = 1774641184199


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


def make_webex(transport):
    return ApiClient(WEBEX_BASE, "TOKEN", org_id="ORG1", transport=transport)


def test_org_info_reads_display_name_and_created_from_webex_host(transport):
    transport.add("GET /organization/ORG1", body={"subscriptionType": "TRIAL"})
    transport.add("GET /v1/organizations/ORG1",
                  body={"displayName": REAL_DISPLAY_NAME, "created": REAL_CREATED_ISO})
    info = tenant.org_info(make(transport), make_webex(transport))
    assert info["name"] == REAL_DISPLAY_NAME
    assert info["created_ms"] == REAL_CREATED_MS


def test_org_info_tolerates_a_429_from_the_unreachable_cc_org_endpoint(transport):
    """U6: organization/{orgId} on the WxCC host 429s on every attempt.

    The name still comes through via the Webex host; the subscription type,
    which has no other confirmed source, is reported unknown rather than the
    call raising or the archive silently getting an org-id filename.
    """
    transport.add("GET /organization/ORG1", status=429, body={"message": "too many requests"})
    transport.add("GET /v1/organizations/ORG1",
                  body={"displayName": REAL_DISPLAY_NAME, "created": REAL_CREATED_ISO})
    info = tenant.org_info(make(transport), make_webex(transport))
    assert info["name"] == REAL_DISPLAY_NAME
    assert info["subscription"] is None
    assert info["production"] is None


def test_subscription_type_marks_a_paying_org_as_production(transport):
    transport.add("GET /organization/ORG1", body={"subscriptionType": "SUBSCRIPTION"})
    transport.add("GET /v1/organizations/ORG1",
                  body={"displayName": "Acme", "created": REAL_CREATED_ISO})
    assert tenant.org_info(make(transport), make_webex(transport))["production"] is True


def test_org_info_tags_a_trial_subscription_as_not_production(transport):
    transport.add("GET /organization/ORG1", body={"subscriptionType": "TRIAL"})
    transport.add("GET /v1/organizations/ORG1",
                  body={"displayName": "Acme", "created": REAL_CREATED_ISO})
    assert tenant.org_info(make(transport), make_webex(transport))["production"] is False


def test_org_info_without_a_webex_client_reports_name_unavailable(transport):
    transport.add("GET /organization/ORG1", body={"subscriptionType": "TRIAL"})
    info = tenant.org_info(make(transport))
    assert info["name"] == "(org name unavailable)"
    assert info["created_ms"] is None


def test_org_info_without_an_org_id_does_not_call_the_api(transport):
    c = ApiClient(BASE, "TOKEN", org_id=None, transport=transport)
    info = tenant.org_info(c, make_webex(transport))
    assert info["org_id"] is None
    assert info["created_ms"] is None
    assert transport.calls == []


def test_safe_slug_keeps_a_clean_name_unchanged():
    assert tenant.safe_slug("davidwolgast-8xgo") == "davidwolgast-8xgo"


def test_safe_slug_replaces_path_separators_and_spaces():
    assert tenant.safe_slug("Acme Corp / EU") == "Acme-Corp-EU"


def test_safe_slug_rejects_traversal():
    assert ".." not in tenant.safe_slug("../../etc/passwd")


def test_safe_slug_falls_back_when_nothing_usable_remains():
    assert tenant.safe_slug("///") == "wxcc-tenant"


def test_archive_name_matches_the_spec_example():
    info = {"name": REAL_DISPLAY_NAME, "org_id": "ORG1"}
    assert tenant.archive_name(info) == "davidwolgast-8xgo-export.zip"


def test_archive_name_uses_the_real_observed_displayname_end_to_end(transport):
    """U6: the archive must be named from the Webex host's displayName, not the
    unreachable CC org endpoint."""
    transport.add("GET /organization/ORG1", status=429, body={"message": "too many requests"})
    transport.add("GET /v1/organizations/ORG1",
                  body={"displayName": REAL_DISPLAY_NAME, "created": REAL_CREATED_ISO})
    info = tenant.org_info(make(transport), make_webex(transport))
    assert tenant.archive_name(info) == "davidwolgast-8xgo-export.zip"


def test_archive_name_falls_back_to_the_org_id_when_the_name_is_unavailable():
    info = {"name": "(org name unavailable)", "org_id": "ORG1"}
    assert tenant.archive_name(info) == "ORG1-export.zip"


def test_describe_tags_a_sandbox():
    info = {"name": "davidwolgast-8xgo", "org_id": "ORG1", "production": False}
    assert "[trial/sandbox]" in tenant.describe(info)


def test_describe_tags_production_loudly():
    info = {"name": "Acme", "org_id": "ORG1", "production": True}
    assert "[PRODUCTION]" in tenant.describe(info)


def test_describe_reports_unknown_subscription_rather_than_guessing():
    """U6: subscriptionType has no confirmed source when the CC endpoint is
    unreachable. Asserting "sandbox" without evidence on a screen that
    precedes a destructive write is exactly the wrong failure."""
    info = {"name": "davidwolgast-8xgo", "org_id": "ORG1", "production": None}
    out = tenant.describe(info)
    assert "unknown" in out
    assert "sandbox" not in out
    assert "PRODUCTION" not in out
