"""Integrations with the Azure CLI DevOps extension."""

from __future__ import annotations

import os
from configparser import ConfigParser, NoOptionError, NoSectionError
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

try:  # pragma: no cover - optional dependency, exercised conditionally
    import keyring  # type: ignore
except Exception:  # pragma: no cover - missing optional dependency
    keyring = None  # type: ignore

AZURE_CONFIG_DIR_ENV = "AZURE_CONFIG_DIR"
DEVOPS_CONFIG_DIR_ENV = "AZURE_DEVOPS_EXT_CONFIG_DIR"
DEVOPS_PAT_ENV = "AZURE_DEVOPS_EXT_PAT"
_DEFAULT_USERNAME = "Personal Access Token"
_DEFAULT_KEY = "azdevops-cli: default"


def discover_pat(
    organization: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Return the PAT cached by `az devops login`, if any."""

    env_map = env or os.environ
    env_override = env_map.get(DEVOPS_PAT_ENV)
    if env_override:
        return env_override

    reader = _CredentialReader(env_map)
    return reader.get_token(organization)


class _CredentialReader:
    def __init__(self, env: Mapping[str, str]):
        self._env = env
        self._config_dir = _resolve_config_dir(env)
        self._pat_file = self._config_dir / "personalAccessTokens"

    def get_token(self, organization: str | None) -> str | None:
        key = self._service_name(organization)
        token = self._read_from_keyring(key)
        if token:
            return token
        token = self._read_from_file(key)
        if token:
            return token
        if organization:
            return self._read_from_keyring(_DEFAULT_KEY) or self._read_from_file(_DEFAULT_KEY)
        return None

    def _read_from_keyring(self, key: str) -> str | None:
        if keyring is None:
            return None
        try:
            return keyring.get_password(key, _DEFAULT_USERNAME)
        except Exception:  # pragma: no cover - backend specific failures
            return None

    def _read_from_file(self, key: str) -> str | None:
        if not self._pat_file.exists():
            return None
        parser = ConfigParser(interpolation=None)
        parser.read(self._pat_file)
        try:
            return parser.get(key, _DEFAULT_USERNAME)
        except (NoOptionError, NoSectionError):
            return None

    @staticmethod
    def _service_name(organization: str | None) -> str:
        if not organization:
            return _DEFAULT_KEY
        normalized = _normalize_org_url(organization)
        return f"azdevops-cli: {normalized}"


def _resolve_config_dir(env: Mapping[str, str]) -> Path:
    override = env.get(DEVOPS_CONFIG_DIR_ENV)
    if override:
        return Path(override).expanduser()
    azure_root = env.get(AZURE_CONFIG_DIR_ENV)
    if azure_root:
        return Path(azure_root).expanduser() / "azuredevops"
    return Path.home() / ".azure" / "azuredevops"


def _normalize_org_url(organization: str) -> str:
    source = organization if "://" in organization else f"https://{organization}"
    parsed = urlparse(source)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower() or parsed.path.split("/")[0].lower()
    normalized = f"{scheme}://{netloc}"
    path = parsed.path.lower()
    if path and "visualstudio.com" not in source.lower():
        parts = [segment for segment in path.split("/") if segment]
        if parts:
            normalized += f"/{parts[0]}"
    return normalized


__all__ = ["discover_pat"]
