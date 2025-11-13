"""Environment driven configuration for the validator."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr

from .azure_cli import discover_pat
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
    def from_environment(
        cls,
        repo_root: Path | None = None,
        *,
        organization: str | None = None,
        project: str | None = None,
        pipeline_id: int | str | None = None,
        personal_access_token: str | None = None,
        ref_name: str | None = None,
        timeout_seconds: float | str | None = None,
    ) -> "Settings":
        """Create settings by reading Azure DevOps variables or explicit overrides."""

        resolved_root = (repo_root or Path.cwd()).resolve()
        org_value = organization or os.getenv("AZDO_ORG")
        if not org_value:
            raise SettingsError("Environment variable AZDO_ORG is required")

        project_value = project or os.getenv("AZDO_PROJECT")
        if not project_value:
            raise SettingsError("Environment variable AZDO_PROJECT is required")

        pipeline_value = pipeline_id or os.getenv("AZDO_PIPELINE_ID")
        if pipeline_value is None:
            raise SettingsError("Environment variable AZDO_PIPELINE_ID is required")

        try:
            pipeline_numeric = int(pipeline_value)
        except (TypeError, ValueError) as exc:
            raise SettingsError("AZDO_PIPELINE_ID must be an integer") from exc

        ref_value = ref_name or os.getenv("AZDO_REFNAME") or "refs/heads/main"

        timeout_value: float
        if timeout_seconds is not None:
            timeout_value = float(timeout_seconds)
        else:
            timeout_raw = os.getenv("AZDO_TIMEOUT_SECONDS")
            timeout_value = float(timeout_raw) if timeout_raw else AZURE_TIMEOUT_DEFAULT

        token = (
            personal_access_token
            or os.getenv("AZDO_PAT")
            or os.getenv("SYSTEM_ACCESSTOKEN")
            or discover_pat(org_value)
        )
        if not token:
            raise SettingsError(
                "Preview validation requires AZDO_PAT (SYSTEM_ACCESSTOKEN) or an `az "
                "devops login` session."
            )

        return cls(
            organization=org_value,
            project=project_value,
            pipeline_id=pipeline_numeric,
            personal_access_token=SecretStr(token),
            ref_name=ref_value,
            repo_root=resolved_root,
            request_timeout_seconds=timeout_value,
        )


AZURE_TIMEOUT_DEFAULT: Final[float] = 30.0
