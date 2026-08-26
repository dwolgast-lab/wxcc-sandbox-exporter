"""The export archive: a zip whose manifest is the contract with the importer.

A partial export must never look like a complete one, so every recorded failure
is promoted into manifest["errors"] AND restated in prose in UNSUPPORTED.md.
"""

from __future__ import annotations

import datetime
import json
import re
import zipfile
from pathlib import Path

from . import registry

SCHEMA_VERSION = 1
TOOL_NAME = "wxcc-sandbox-exporter"
TOOL_VERSION = "0.1.0"

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_component(text: str) -> str:
    return _SAFE_NAME.sub("_", (text or "").strip()) or "unnamed"


class ArchiveWriter:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._zip = zipfile.ZipFile(self.path, "w", zipfile.ZIP_DEFLATED)

    def _check(self, name: str) -> str:
        if name.startswith("/") or ".." in Path(name).parts:
            raise ValueError(f"refusing to write outside the archive: {name!r}")
        return name

    def add_json(self, name: str, obj: object) -> None:
        self._zip.writestr(self._check(name),
                           json.dumps(obj, indent=2, sort_keys=True))

    def add_text(self, name: str, text: str) -> None:
        self._zip.writestr(self._check(name), text)

    def add_bytes(self, name: str, data: bytes) -> None:
        self._zip.writestr(self._check(name), data)

    def close(self) -> None:
        self._zip.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def build_manifest(source: dict, sections: dict, errors: list[dict]) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "toolVersion": TOOL_VERSION,
        "exportedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "sections": sections,
        "unsupported": sorted(registry.UNSUPPORTED),
        "errors": errors,
    }


def render_unsupported(errors: list[dict],
                       unsupported: dict[str, str] | None = None) -> str:
    unsupported = registry.UNSUPPORTED if unsupported is None else unsupported
    lines = [
        "# What this archive does NOT contain",
        "",
        "Read this before assuming the import produced a complete tenant.",
        "",
        "## Objects with no public API",
        "",
        "These cannot be exported by any tool, because Cisco publishes no",
        "endpoint for them. They must be recreated by hand.",
        "",
    ]
    for name in sorted(unsupported):
        lines += [f"### {name}", "", unsupported[name], ""]

    lines += ["## Objects that failed during THIS export", ""]
    if not errors:
        lines += ["No errors. Every object in scope was captured.", ""]
    else:
        lines += ["| section | object | detail |", "|---|---|---|"]
        for e in errors:
            detail = str(e.get("detail", "")).replace("|", "\\|")[:200]
            lines.append(f"| {e.get('section','')} | {e.get('object','')} "
                         f"| {detail} |")
        lines += ["",
                  "Each row above is configuration that is **missing** from this",
                  "archive. Re-run the export after fixing the cause, or recreate",
                  "those objects by hand.", ""]
    return "\n".join(lines)


def write_export(path, source: dict, cc: dict, children: dict, audio: dict,
                 flows: dict, functions: dict, calling: dict,
                 users: dict) -> dict:
    """Assemble the archive and return the manifest that was written."""
    errors: list[dict] = []
    sections: dict = {}

    with ArchiveWriter(path) as w:
        # --- contact center entities ---
        entity_index: dict = {}
        for entity, result in (cc or {}).items():
            fname = f"cc/{entity}.json"
            w.add_json(fname, {"entity": entity, "items": result.get("items", [])})
            entity_index[entity] = {"count": result.get("count", 0), "file": fname}
            if result.get("error"):
                errors.append({"section": "cc", "object": entity,
                               "detail": result["error"]})
        sections["cc"] = {"entities": entity_index}

        # --- child collections ---
        child_index: dict = {}
        for entity, per_parent in (children or {}).items():
            for parent_id, record in per_parent.items():
                fname = f"cc/children/{entity}__{_safe_component(parent_id)}.json"
                w.add_json(fname, {"entity": entity, "parentId": parent_id,
                                   "items": record.get("items", [])})
                child_index.setdefault(entity, {})[parent_id] = {
                    "count": record.get("count", 0), "file": fname}
                if record.get("error"):
                    errors.append({"section": "cc-children",
                                   "object": f"{entity}/{parent_id}",
                                   "detail": record["error"]})
        if child_index:
            sections["cc"]["children"] = child_index

        # --- audio bytes ---
        audio_index: dict = {}
        for item_id, blob in (audio or {}).items():
            fname = (f"cc/audio/{_safe_component(item_id)}__"
                     f"{_safe_component(blob.get('name', 'audio'))}")
            w.add_bytes(fname, blob["bytes"])
            audio_index[item_id] = {"file": fname, "bytes": len(blob["bytes"])}
        if audio_index:
            sections["cc"]["audio"] = audio_index

        # --- flows / subflows / functions ---
        for bucket in ("flows", "subflows"):
            for flow_id, payload in (flows or {}).get(bucket, {}).items():
                w.add_json(f"flows/{bucket}/{_safe_component(flow_id)}.json", payload)
        for fn_id, payload in (functions or {}).get("functions", {}).items():
            w.add_json(f"flows/functions/{_safe_component(fn_id)}.json", payload)
        sections["flows"] = {
            "flows": len((flows or {}).get("flows", {})),
            "subflows": len((flows or {}).get("subflows", {})),
            "functions": len((functions or {}).get("functions", {})),
            "projectId": (flows or {}).get("projectId"),
        }
        for detail in (flows or {}).get("errors", []):
            errors.append({"section": "flows", "object": "flow", "detail": detail})
        for detail in (functions or {}).get("errors", []):
            errors.append({"section": "flows", "object": "function",
                           "detail": detail})

        # --- calling ---
        calling_index: dict = {}
        if (calling or {}).get("locations"):
            w.add_json("calling/locations.json",
                       {"object": "locations", "items": calling["locations"]})
            calling_index["locations"] = {"count": len(calling["locations"]),
                                          "file": "calling/locations.json"}
        for name, result in (calling or {}).get("objects", {}).items():
            fname = f"calling/{name}.json"
            w.add_json(fname, {"object": name, "items": result.get("items", [])})
            calling_index[name] = {"count": result.get("count", 0), "file": fname}
            if result.get("error"):
                errors.append({"section": "calling", "object": name,
                               "detail": result["error"]})
        if (calling or {}).get("error"):
            errors.append({"section": "calling", "object": "locations",
                           "detail": calling["error"]})
        sections["calling"] = {"objects": calling_index}

        # --- users (reference only) ---
        w.add_json("users/users.json", {"users": (users or {}).get("rows", []),
                                        "writable": False})
        w.add_text("users/users.csv", (users or {}).get("csv", ""))
        sections["users"] = {"count": len((users or {}).get("rows", [])),
                             "writable": False}

        manifest = build_manifest(source, sections, errors)
        w.add_json("manifest.json", manifest)
        w.add_text("UNSUPPORTED.md", render_unsupported(errors))

    return manifest


class IncompatibleArchive(Exception):
    """The zip is not an archive this tool version can read."""


class ArchiveReader:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        try:
            self._zip = zipfile.ZipFile(self.path)
        except zipfile.BadZipFile as exc:
            raise IncompatibleArchive(f"{self.path.name} is not a zip file") from exc
        try:
            self.manifest = json.loads(self._zip.read("manifest.json"))
        except KeyError as exc:
            raise IncompatibleArchive(
                f"{self.path.name} has no manifest.json - it was not produced by "
                f"{TOOL_NAME}") from exc
        version = self.manifest.get("schemaVersion")
        if version != SCHEMA_VERSION:
            raise IncompatibleArchive(
                f"archive schemaVersion {version} but this tool reads "
                f"{SCHEMA_VERSION}. Re-export with a matching tool version.")

    # --- raw access ---
    def read_json(self, name: str) -> object:
        try:
            return json.loads(self._zip.read(name))
        except KeyError:
            return None

    def read_bytes(self, name: str) -> bytes | None:
        try:
            return self._zip.read(name)
        except KeyError:
            return None

    # --- typed access ---
    def entity_items(self, entity: str) -> list[dict]:
        entry = (self.manifest["sections"].get("cc", {})
                 .get("entities", {}).get(entity))
        if not entry:
            return []
        doc = self.read_json(entry["file"]) or {}
        return doc.get("items", [])

    def children(self, entity: str) -> dict[str, list[dict]]:
        index = (self.manifest["sections"].get("cc", {})
                 .get("children", {}).get(entity, {}))
        out: dict[str, list[dict]] = {}
        for parent_id, entry in index.items():
            doc = self.read_json(entry["file"]) or {}
            out[parent_id] = doc.get("items", [])
        return out

    def audio_blob(self, item_id: str) -> bytes | None:
        entry = (self.manifest["sections"].get("cc", {})
                 .get("audio", {}).get(item_id))
        return self.read_bytes(entry["file"]) if entry else None

    def flows(self, bucket: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        prefix = f"flows/{bucket}/"
        for name in self._zip.namelist():
            if name.startswith(prefix) and name.endswith(".json"):
                out[Path(name).stem] = self.read_json(name)
        return out

    def functions(self) -> dict[str, dict]:
        return self.flows("functions")

    def calling_items(self, name: str) -> list[dict]:
        entry = (self.manifest["sections"].get("calling", {})
                 .get("objects", {}).get(name))
        if not entry:
            return []
        doc = self.read_json(entry["file"]) or {}
        return doc.get("items", [])

    def users(self) -> list[dict]:
        doc = self.read_json("users/users.json") or {}
        return doc.get("users", [])

    def close(self) -> None:
        self._zip.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def _group_of(entity: str) -> str:
    for group, members in registry.SPEC_GROUPS.items():
        if entity in members:
            return group
    return "Other"


def available_selections(manifest: dict) -> list[dict]:
    """Everything in the archive that has at least one item to import.

    An empty entity is omitted rather than offered: a checkbox that imports
    nothing is a checkbox that wastes a decision.
    """
    out: list[dict] = []
    sections = manifest.get("sections", {})

    for entity, entry in sections.get("cc", {}).get("entities", {}).items():
        if entry.get("count"):
            out.append({"key": f"cc:{entity}", "label": entity,
                        "group": _group_of(entity), "count": entry["count"],
                        "writable": registry.CC_ENTITIES.get(
                            entity, {}).get("writable", False)})

    flows = sections.get("flows", {})
    for bucket in ("flows", "subflows", "functions"):
        if flows.get(bucket):
            out.append({"key": f"flows:{bucket}", "label": bucket,
                        "group": "Flows", "count": flows[bucket],
                        "writable": True})

    for name, entry in sections.get("calling", {}).get("objects", {}).items():
        if entry.get("count"):
            out.append({"key": f"calling:{name}", "label": name,
                        "group": "Webex Calling", "count": entry["count"],
                        "writable": True})
    return out


def parse_selection(spec: str, manifest: dict) -> list[str]:
    """Turn a CLI selection string into concrete keys.

    Accepts `all`, a section name (`cc`, `flows`, `calling`), or a
    comma-separated list of explicit keys. An unknown key is an error, not a
    silent no-op: a typo that imports nothing looks exactly like success.
    """
    available = {s["key"] for s in available_selections(manifest)}
    spec = (spec or "").strip()
    if not spec or spec == "all":
        return sorted(available)
    keys: list[str] = []
    for token in (t.strip() for t in spec.split(",") if t.strip()):
        if token in ("cc", "flows", "calling"):
            keys += sorted(k for k in available if k.startswith(f"{token}:"))
        elif token in available:
            keys.append(token)
        else:
            raise ValueError(
                f"unknown selection {token!r}. Available: "
                f"{', '.join(sorted(available)) or '(archive is empty)'}")
    return keys
