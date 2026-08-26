import pytest
from wxcc_export import idmap


def test_record_and_get():
    m = idmap.IdMap()
    m.record("old1", "new1")
    assert m.get("old1") == "new1"
    assert m.get("missing") is None


def test_substitute_replaces_a_top_level_string():
    m = idmap.IdMap()
    m.record("s1", "s9")
    assert m.substitute({"siteId": "s1"}) == {"siteId": "s9"}


def test_substitute_recurses_into_nested_dicts():
    m = idmap.IdMap()
    m.record("t1", "t9")
    payload = {"routing": {"groups": [{"teamId": "t1"}]}}
    assert m.substitute(payload)["routing"]["groups"][0]["teamId"] == "t9"


def test_substitute_recurses_into_lists_of_strings():
    m = idmap.IdMap()
    m.record("t1", "t9")
    assert m.substitute({"teamIds": ["t1", "t2"]})["teamIds"] == ["t9", "t2"]


def test_substitute_rewrites_ids_embedded_in_flow_json():
    m = idmap.IdMap()
    m.record("q1", "q9")
    flow = {"nodes": [{"id": "n1", "params": {"queueId": "q1"}}]}
    assert m.substitute(flow)["nodes"][0]["params"]["queueId"] == "q9"


def test_substitute_replaces_an_id_inside_a_longer_string():
    # Flow node parameters sometimes carry a URI or expression containing the id.
    m = idmap.IdMap()
    m.record("q1abc", "q9xyz")
    out = m.substitute({"expr": "queue://q1abc/overflow"})
    assert out["expr"] == "queue://q9xyz/overflow"


def test_substitute_leaves_unmapped_values_alone():
    m = idmap.IdMap()
    assert m.substitute({"siteId": "unknown"}) == {"siteId": "unknown"}


def test_substitute_does_not_mutate_the_input():
    m = idmap.IdMap()
    m.record("s1", "s9")
    original = {"siteId": "s1"}
    m.substitute(original)
    assert original == {"siteId": "s1"}


def test_substitute_preserves_non_string_scalars():
    m = idmap.IdMap()
    payload = {"active": True, "count": 3, "ratio": 1.5, "nothing": None}
    assert m.substitute(payload) == payload


def test_unmapped_finds_id_shaped_values_with_no_mapping():
    m = idmap.IdMap()
    m.record("11111111-1111-1111-1111-111111111111", "x")
    payload = {"a": "11111111-1111-1111-1111-111111111111",
               "b": "22222222-2222-2222-2222-222222222222",
               "c": "Denver"}
    assert m.unmapped(payload) == {"22222222-2222-2222-2222-222222222222"}


def test_looks_like_id_accepts_a_uuid():
    assert idmap.looks_like_id("11111111-1111-1111-1111-111111111111")


def test_looks_like_id_rejects_a_human_name():
    assert not idmap.looks_like_id("Denver")
    assert not idmap.looks_like_id("Tier 1 Support")


def test_looks_like_id_rejects_a_short_token():
    assert not idmap.looks_like_id("abc")


def test_strip_identity_removes_the_id():
    out = idmap.strip_identity({"id": "s1", "name": "Denver"})
    assert "id" not in out and out["name"] == "Denver"


def test_strip_identity_removes_created_time_and_the_heuristic_label():
    out = idmap.strip_identity({"id": "s1", "createdTime": 1,
                                "likely_default": True, "name": "D"})
    assert set(out) == {"name"}


def test_strip_identity_keeps_reference_ids():
    # Only this object's OWN identity is stripped; references must survive to be
    # remapped afterwards.
    out = idmap.strip_identity({"id": "t1", "siteId": "s1"})
    assert out == {"siteId": "s1"}


# --- regression tests for the chained-replacement corruption -----------------
# The original _rewrite_string looped `text = text.replace(old, new)` over the
# map, so it re-scanned text it had just written. These reproduce the failures
# that loop produced; they must stay green.


def test_substitute_does_not_revert_a_two_cycle():
    # A -> B and B -> A. The sequential loop rewrote A->B, then matched the
    # fresh B and flipped it back to A, silently yielding the ORIGINAL value.
    m = idmap.IdMap()
    m.record("q1abcdefghijkl", "q9abcdefghijkl")
    m.record("q9abcdefghijkl", "q1abcdefghijkl")
    out = m.substitute({"expr": "queue://q1abcdefghijkl/overflow"})
    assert out["expr"] == "queue://q9abcdefghijkl/overflow"


def test_substitute_does_not_chain_through_an_intermediate_value():
    # A -> B, B -> C. A must land on B, never on C.
    m = idmap.IdMap()
    m.record("aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb")
    m.record("bbbbbbbbbbbbbbbb", "cccccccccccccccc")
    out = m.substitute({"expr": "x://aaaaaaaaaaaaaaaa/y"})
    assert out["expr"] == "x://bbbbbbbbbbbbbbbb/y"


def test_substitute_prefers_the_longest_matching_id():
    # A short id that is a prefix of a longer one must not shadow it.
    m = idmap.IdMap()
    m.record("abcdefghijklmnop", "SHORT")
    m.record("abcdefghijklmnopqrstuv", "LONG")
    out = m.substitute({"expr": "id=abcdefghijklmnopqrstuv;"})
    assert out["expr"] == "id=LONG;"


def test_substitute_rewrites_a_short_id_in_a_short_string():
    # The old hardcoded `len(text) < 16` early-return skipped this entirely.
    m = idmap.IdMap()
    m.record("q1", "q9")
    assert m.substitute({"ref": "s1/q1"})["ref"] == "s1/q9"


def test_substitute_with_an_empty_map_is_identity():
    m = idmap.IdMap()
    payload = {"a": "anything at all", "b": ["x", "y"]}
    assert m.substitute(payload) == payload


def test_recording_after_a_substitute_invalidates_the_cache():
    m = idmap.IdMap()
    m.record("aaaaaaaaaaaaaaaa", "AAAA")
    assert m.substitute({"v": "x/aaaaaaaaaaaaaaaa"})["v"] == "x/AAAA"
    m.record("bbbbbbbbbbbbbbbb", "BBBB")
    assert m.substitute({"v": "x/bbbbbbbbbbbbbbbb"})["v"] == "x/BBBB"


def test_regex_metacharacters_in_an_id_are_escaped():
    m = idmap.IdMap()
    m.record("a.b*c+d(e)fghijkl", "SAFE")
    assert m.substitute({"v": "z/a.b*c+d(e)fghijkl"})["v"] == "z/SAFE"
    # The pattern must not match a string that only fits the regex reading.
    assert m.substitute({"v": "z/axbxcxdxexfghijkl"})["v"] == "z/axbxcxdxexfghijkl"
