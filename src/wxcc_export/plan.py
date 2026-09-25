"""Decide the whole import before writing any of it.

Ordering comes from the registry's dependency graph; actions come from comparing
the archive against the target tenant BY NAME. Deciding everything up front is
what makes --dry-run honest: the dry run and the real run compute the same plan.

Name comparison is also how "only non-default" is satisfied without inventing an
isDefault flag: an object whose name already exists in the target IS already
there, whether it arrived at provisioning or from an earlier import.
"""

from __future__ import annotations

from . import auth, registry
from .client import ApiError

CONFLICT_POLICIES = ("skip", "update", "rename")


class CircularDependency(Exception):
    pass


def order_entities(entities: list[str]) -> list[str]:
    """Topologically sort the requested entities. Dependencies not requested
    are NOT pulled in - widening the import silently is worse than a broken
    reference the importer will report."""
    requested = list(dict.fromkeys(entities))
    wanted = set(requested)
    ordered: list[str] = []
    state: dict[str, str] = {}

    def visit(node: str) -> None:
        mark = state.get(node)
        if mark == "done":
            return
        if mark == "visiting":
            raise CircularDependency(f"dependency cycle through {node!r}")
        state[node] = "visiting"
        for dep in registry.CC_ENTITIES.get(node, {}).get("deps", []):
            if dep in wanted:
                visit(dep)
        state[node] = "done"
        ordered.append(node)

    for name in requested:
        visit(name)
    return ordered


def index_existing(client, entity: str) -> dict[str, dict]:
    """Index the TARGET tenant's objects by lowercased name.

    A failure returns {} and the caller treats every source object as new. That
    is the safe direction: the API rejects a duplicate name, so a bad index
    causes a visible 400, not a silent overwrite.

    EXCEPT a rejected token (401/403), which raises. Read as "the target is
    empty", an expired token made a dry run plan a create for everything and
    look clean (2026-09-25).
    """
    field = registry.name_field(entity)
    try:
        rows = client.list_all(registry.list_path(entity))
    except ApiError as exc:
        if exc.status in (401, 403):
            raise auth.AuthError(
                f"the target rejected the token while listing {entity} "
                f"(HTTP {exc.status})") from exc
        return {}
    except Exception:
        return {}
    return {str(r.get(field, "")).strip().lower(): r
            for r in rows if r.get(field)}


def _free_name(name: str, existing: dict[str, dict]) -> str:
    candidate = f"{name} (imported)"
    n = 2
    while candidate.strip().lower() in existing:
        candidate = f"{name} (imported {n})"
        n += 1
    return candidate


def classify(source_items: list[dict], existing: dict[str, dict],
             on_conflict: str, name_field: str = "name") -> list[dict]:
    """Decide create / update / skip / rename for every source object.

    `name_field` is the field carrying the object's human identity. It is
    "name" for every entity but contact-number, which has only a phone number -
    without the override every contact-number row reads as nameless and gets
    skipped.
    """
    if on_conflict not in CONFLICT_POLICIES:
        raise ValueError(f"unknown conflict policy {on_conflict!r}. "
                         f"Use one of: {', '.join(CONFLICT_POLICIES)}")
    out: list[dict] = []
    for item in source_items:
        name = str(item.get(name_field, "")).strip()
        if not name:
            out.append({"action": "skip", "item": item, "existing": None,
                        "reason": f"the object has no {name_field}, so it "
                                  "cannot be matched against the target safely"})
            continue
        match = existing.get(name.lower())
        if not match:
            out.append({"action": "create", "item": item, "existing": None,
                        "reason": "no object of this name in the target"})
        elif on_conflict == "skip":
            out.append({"action": "skip", "item": item, "existing": match,
                        "reason": f"{name!r} already exists in the target "
                                  "(default or previously imported)"})
        elif on_conflict == "update":
            out.append({"action": "update", "item": item, "existing": match,
                        "reason": f"{name!r} exists; updating it in place"})
        else:
            renamed = {**item, name_field: _free_name(name, existing)}
            out.append({"action": "rename", "item": renamed, "existing": match,
                        "reason": f"{name!r} exists; creating a renamed copy"})
    return out
