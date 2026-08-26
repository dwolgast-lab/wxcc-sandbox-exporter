import pytest
from wxcc_export import tenant
from wxcc_export.client import ApiClient

BASE = "https://api.wxcc-us1.cisco.com"


def make(transport):
    return ApiClient(BASE, "TOKEN", org_id="ORG1", transport=transport)


def test_org_info_reads_name_and_subscription(transport):
    transport.add("GET /organization/ORG1",
                  body={"name": "davidwolgast-8xgo", "subscriptionType": "TRIAL"})
    info = tenant.org_info(make(transport))
    assert info["name"] == "davidwolgast-8xgo"
    assert info["production"] is False


def test_subscription_type_marks_a_paying_org_as_production(transport):
    transport.add("GET /organization/ORG1",
                  body={"name": "Acme", "subscriptionType": "SUBSCRIPTION"})
    assert tenant.org_info(make(transport))["production"] is True


def test_org_info_reports_unavailable_rather_than_guessing(transport):
    transport.add("GET /organization/ORG1", status=403, body={"message": "nope"})
    info = tenant.org_info(make(transport))
    assert info["name"] == "(org name unavailable)"
    assert info["production"] is None


def test_org_info_without_an_org_id_does_not_call_the_api(transport):
    c = ApiClient(BASE, "TOKEN", org_id=None, transport=transport)
    info = tenant.org_info(c)
    assert info["org_id"] is None
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
    info = {"name": "davidwolgast-8xgo", "org_id": "ORG1"}
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
