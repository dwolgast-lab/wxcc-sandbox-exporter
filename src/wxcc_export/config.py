"""Configuration loading.

One env file per tenant, selected by profile, each with its own token store.
There is deliberately no "current tenant" pointer: a mutable global is how a
write meant for the new sandbox lands on the old one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _base_dir() -> Path:
    """Where .env files and the .wxcc/ token store live.

    From source: the checkout root. As a PyInstaller executable: the folder
    holding the executable - a one-file build runs from a temp dir that is
    deleted on exit, so resolving from __file__ there would lose every token.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


REPO_DIR = _base_dir()

WXCC_DEFAULT_API_BASE = "https://api.wxcc-us1.cisco.com"
WEBEX_API_BASE = "https://webexapis.com/v1"


class ConfigError(Exception):
    """Configuration is missing or unusable."""


def env_file(profile: str | None) -> Path:
    return REPO_DIR / (f".env.{profile}" if profile else ".env")


def token_store(profile: str | None) -> Path:
    name = f"tokens.{profile}.json" if profile else "tokens.json"
    return REPO_DIR / ".wxcc" / name


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        val = raw.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key.strip()] = val
    return values


def load_config(profile: str | None = None) -> dict:
    """Read the profile's env file, with the real environment taking priority."""
    path = env_file(profile)
    if not path.exists():
        raise ConfigError(
            f"no config at {path.name}. Copy .env.example to {path.name} and fill it in."
        )
    raw = _parse_env(path)

    def get(key: str, default: str = "") -> str:
        return os.environ.get(key) or raw.get(key, default)

    api_base = get("WXCC_API_BASE", WXCC_DEFAULT_API_BASE).rstrip("/")
    return {
        "profile": profile,
        "client_id": get("WXCC_CLIENT_ID"),
        "client_secret": get("WXCC_CLIENT_SECRET"),
        "redirect_uri": get("WXCC_REDIRECT_URI", "http://localhost:8484/callback"),
        "scopes": get("WXCC_SCOPES", "cjp:config_read"),
        "api_base": api_base,
        "webex_base": WEBEX_API_BASE,
        "org_id": get("WXCC_ORG_ID") or None,
        "bearer_token": get("WXCC_BEARER_TOKEN") or None,
    }


def require(cfg: dict, *keys: str) -> None:
    """Fail with the env var name the user must set, not the internal key."""
    missing = [k for k in keys if not cfg.get(k)]
    if missing:
        names = ", ".join(f"WXCC_{k.upper()}" for k in missing)
        raise ConfigError(f"missing required setting(s): {names}")
