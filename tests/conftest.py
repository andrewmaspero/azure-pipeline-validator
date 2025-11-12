"""Shared fixtures for validator tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from azure_pipelines_validator.settings import Settings


@pytest.fixture()
def settings_factory(tmp_path: Path):
    """Return a helper that creates Settings objects bound to tmp_path."""

    def _factory(**overrides):
        return Settings(
            organization=overrides.get("organization", "https://dev.azure.com/example"),
            project=overrides.get("project", "demo"),
            pipeline_id=overrides.get("pipeline_id", 42),
            personal_access_token=overrides.get("personal_access_token", SecretStr("token")),
            ref_name=overrides.get("ref_name", "refs/heads/main"),
            repo_root=overrides.get("repo_root", tmp_path),
            request_timeout_seconds=overrides.get("request_timeout_seconds", 5.0),
        )

    return _factory
