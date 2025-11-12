"""Environment driven configuration for the validator."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr

from .exceptions import SettingsError


class Settings(BaseModel):
    """Strongly typed configuration sourced from environment variables."""

    model_config = ConfigDict(frozen=True)

    organization: AnyHttpUrl
    project: str
    pipeline_id: int = Field(..., gt=0)
    personal_access_token: SecretStr
    ref_name: str = Field(default="refs/heads/main")
    repo_root: Path
    request_timeout_seconds: float = Field(default=30.0, gt=0)

    @classmethod
    def from_environment(cls, repo_root: Path | None = None) -> "Settings":
        """Create settings by reading the documented Azure DevOps variables."""

        resolved_root = (repo_root or Path.cwd()).resolve()
        token = os.getenv("AZDO_PAT") or os.getenv("SYSTEM_ACCESSTOKEN")
        if not token:
            raise SettingsError(
                "Set AZDO_PAT or expose SYSTEM_ACCESSTOKEN before running validation."
            )

        organization = _require_env("AZDO_ORG")
        project = _require_env("AZDO_PROJECT")
        pipeline_raw = _require_env("AZDO_PIPELINE_ID")
        ref_name = os.getenv("AZDO_REFNAME") or "refs/heads/main"
        timeout_raw = os.getenv("AZDO_TIMEOUT_SECONDS")

        try:
            pipeline_id = int(pipeline_raw)
        except ValueError as exc:
            raise SettingsError("AZDO_PIPELINE_ID must be an integer") from exc

        timeout = float(timeout_raw) if timeout_raw else AZURE_TIMEOUT_DEFAULT

        return cls(
            organization=organization,
            project=project,
            pipeline_id=pipeline_id,
            personal_access_token=SecretStr(token),
            ref_name=ref_name,
            repo_root=resolved_root,
            request_timeout_seconds=timeout,
        )


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SettingsError(f"Environment variable {name} is required")
    return value


AZURE_TIMEOUT_DEFAULT: Final[float] = 30.0
