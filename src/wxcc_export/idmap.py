"""Rewrite source-tenant ids to target-tenant ids.

WxCC ids are globally unique opaque strings, so an occurrence of `s1` anywhere
in any payload refers to exactly one object. Recursive substitution is therefore
complete AND safe, and it rewrites flow JSON - which embeds queue and entry-point
ids in node parameters - with no extra machinery.

The alternative, a hand-written map of which field on which entity is a foreign
key, was tried in the sibling wxcc-skills repo and recorded there as "slow,
mostly inferred, and provably incomplete".
"""

from __future__ import annotations

import re

# Server-assigned identity and local bookkeeping. Sending these on a create is
# at best ignored and at worst a 400 ("New configuration cannot have an id").
IDENTITY_FIELDS = frozenset({
    "id", "createdTime", "createdAt", "lastUpdatedTime", "version",
    "likely_default", "default_basis", "_locationId", "organizationId", "orgId",
})

_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# Webex also issues long base64-ish ids (e.g. Y2lzY29zcGFyazovL3Vz...).
_OPAQUE = re.compile(r"^[A-Za-z0-9_-]{16,}$")


def looks_like_id(value: str) -> bool:
    """Is this string shaped like an identifier rather than a human name?

    Deliberately conservative: used only to REPORT ids that were not remapped,
    never to decide what to rewrite. Substitution is driven by exact matches
    against recorded mappings.
    """
    if not isinstance(value, str) or " " in value:
        return False
    return bool(_UUID.match(value) or _OPAQUE.match(value))


def strip_identity(item: dict) -> dict:
    """Drop this object's own identity, keeping its references intact."""
    return {k: v for k, v in item.items() if k not in IDENTITY_FIELDS}


class IdMap:
    def __init__(self) -> None:
        self._map: dict[str, str] = {}
        self._pattern = None
        self._shortest = 0
        # Every id the SOURCE archive holds. When set, unmapped() reports only
        # these: a string is a dangling reference only if it is provably the id
        # of a source object. Guessing from shape reported flow node names,
        # event names and Cisco catalog ids as broken links (216 of 349 on a
        # real archive, 2026-09-25).
        self.known_source_ids: set[str] | None = None

    def record(self, old: str, new: str) -> None:
        if old and new:
            self._map[old] = new
            self._pattern = None            # invalidate the cached alternation

    def get(self, old: str) -> str | None:
        return self._map.get(old)

    def as_dict(self) -> dict[str, str]:
        return dict(self._map)

    def substitute(self, payload):
        """Return a copy with every recorded id replaced. Never mutates input."""
        if isinstance(payload, dict):
            return {k: self.substitute(v) for k, v in payload.items()}
        if isinstance(payload, list):
            return [self.substitute(v) for v in payload]
        if isinstance(payload, str):
            return self._rewrite_string(payload)
        return payload

    def _compiled(self):
        """Build (and cache) one alternation over every recorded old id.

        Longest key first, so a short id cannot shadow a longer one that
        contains it as a prefix.
        """
        if self._pattern is None and self._map:
            keys = sorted(self._map, key=len, reverse=True)
            self._pattern = re.compile("|".join(re.escape(k) for k in keys))
            self._shortest = min(len(k) for k in self._map)
        return self._pattern

    def _rewrite_string(self, text: str) -> str:
        exact = self._map.get(text)
        if exact is not None:
            return exact
        # An id can appear inside a URI or an expression in flow JSON.
        pattern = self._compiled()
        if pattern is None or len(text) < self._shortest:
            return text
        # ONE pass. A sequential old.replace(new) loop would re-scan text it had
        # just written, so a map containing both A->B and B->A silently reverted
        # the value to its original with no error. re.sub never re-examines its
        # own output, which removes that whole class of corruption structurally
        # rather than relying on ids never colliding.
        return pattern.sub(lambda m: self._map[m.group(0)], text)

    def unmapped(self, payload) -> set[str]:
        """Id-shaped strings with no recorded mapping.

        These are dangling references: they point at objects that were not
        imported, so the target will either reject them or store a broken link.
        The importer surfaces them rather than letting a 200 imply success.

        With known_source_ids set, only ids of objects in the source archive
        count. That cannot see references to object types the tool never
        exports (e.g. connectors) - a known, documented blind spot, preferred
        over hundreds of false alarms that bury the real ones.
        """
        found: set[str] = set()
        known = self.known_source_ids

        def walk(node):
            if isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
            elif isinstance(node, str) and node not in self._map:
                if (node in known) if known is not None else looks_like_id(node):
                    found.add(node)

        walk(payload)
        return found
