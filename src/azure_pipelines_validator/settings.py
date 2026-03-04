"""Environment driven configuration for the validator."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr

from .exceptions import SettingsError

AZURE_TIMEOUT_DEFAULT: Final[float] = 30.0
AZURE_DEVOPS_ORG_BASE_URL: Final[str] = "https://dev.azure.com"


class Settings(BaseModel):
    """Strongly typed configuration sourced from environment variables."""

    model_config = ConfigDict(frozen=True)

    organization: AnyHttpUrl = Field(
        description="Azure DevOps organization base URL, for example https://dev.azure.com/org.",
    )
    project: str = Field(description="Azure DevOps project name that owns the target pipeline.")
    pipeline_id: int = Field(
        ...,
        gt=0,
        description="Numeric Azure DevOps pipeline identifier used for preview validation.",
    )
    personal_access_token: SecretStr = Field(
        description="Azure DevOps personal access token used for authenticated API calls.",
    )
    ref_name: str = Field(
        default="refs/heads/main",
        description="Git ref used by Azure DevOps to resolve template includes.",
    )
    repo_root: Path = Field(
        description="Repository root directory used for resolving local file paths.",
    )
    request_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="HTTP timeout in seconds for Azure DevOps preview requests.",
    )

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
        """Create settings from explicit values or Azure DevOps environment variables.

        Args:
            repo_root: Optional repository root used for path resolution.
            organization: Optional organization override.
            project: Optional project override.
            pipeline_id: Optional pipeline ID override.
            personal_access_token: Optional PAT override.
            ref_name: Optional ref name override.
            timeout_seconds: Optional timeout override.

        Returns:
            Parsed and validated settings instance.

        Raises:
            SettingsError: If required settings are missing or malformed.
            ValueError: If numeric conversion fails.
        """
        resolved_root = (repo_root or Path.cwd()).resolve()
        token = personal_access_token or os.getenv("AZDO_PAT") or os.getenv("SYSTEM_ACCESSTOKEN")
        if not token:
            raise SettingsError(
                "Set AZDO_PAT (or SYSTEM_ACCESSTOKEN) before running preview/schema validation."
            )

        org_raw_value = organization or os.getenv("AZDO_ORG")
        if not org_raw_value:
            raise SettingsError("Environment variable AZDO_ORG is required")
        org_value = normalize_organization(org_raw_value)

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

        return cls(
            organization=org_value,
            project=project_value,
            pipeline_id=pipeline_numeric,
            personal_access_token=SecretStr(token),
            ref_name=ref_value,
            repo_root=resolved_root,
            request_timeout_seconds=timeout_value,
        )


def normalize_organization(organization: str) -> str:
    """Normalize Azure DevOps organization input into a full URL."""
    trimmed = organization.strip().strip("/")
    if "://" in trimmed:
        return trimmed
    return f"{AZURE_DEVOPS_ORG_BASE_URL}/{trimmed}"
