from __future__ import annotations

from pathlib import Path

import pytest

from azure_pipelines_validator.exceptions import SettingsError
from azure_pipelines_validator.settings import AZURE_TIMEOUT_DEFAULT, Settings


def test_from_environment_reads_values(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AZDO_ORG", "https://dev.azure.com/org")
    monkeypatch.setenv("AZDO_PROJECT", "project")
    monkeypatch.setenv("AZDO_PIPELINE_ID", "99")
    monkeypatch.setenv("AZDO_PAT", "abc123")
    monkeypatch.setenv("AZDO_REFNAME", "refs/heads/dev")
    monkeypatch.setenv("AZDO_TIMEOUT_SECONDS", "12.5")

    settings = Settings.from_environment(repo_root=tmp_path)

    assert str(settings.organization) == "https://dev.azure.com/org"
    assert settings.project == "project"
    assert settings.pipeline_id == 99
    assert settings.personal_access_token.get_secret_value() == "abc123"
    assert settings.ref_name == "refs/heads/dev"
    assert settings.repo_root == tmp_path
    assert settings.request_timeout_seconds == 12.5


def test_from_environment_prefers_system_access_token(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AZDO_ORG", "https://dev.azure.com/org")
    monkeypatch.setenv("AZDO_PROJECT", "project")
    monkeypatch.setenv("AZDO_PIPELINE_ID", "5")
    monkeypatch.setenv("SYSTEM_ACCESSTOKEN", "from-system")

    settings = Settings.from_environment(repo_root=tmp_path)

    assert settings.personal_access_token.get_secret_value() == "from-system"
    assert settings.request_timeout_seconds == AZURE_TIMEOUT_DEFAULT


def test_from_environment_allows_overrides(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AZDO_ORG", raising=False)
    monkeypatch.delenv("AZDO_PROJECT", raising=False)
    monkeypatch.delenv("AZDO_PIPELINE_ID", raising=False)
    monkeypatch.delenv("AZDO_PAT", raising=False)

    settings = Settings.from_environment(
        repo_root=tmp_path,
        organization="https://dev.azure.com/inline",
        project="inline-project",
        pipeline_id=123,
        personal_access_token="inline-pat",
        ref_name="refs/heads/feature",
        timeout_seconds=45,
    )

    assert str(settings.organization) == "https://dev.azure.com/inline"
    assert settings.project == "inline-project"
    assert settings.pipeline_id == 123
    assert settings.personal_access_token.get_secret_value() == "inline-pat"
    assert settings.ref_name == "refs/heads/feature"
    assert settings.request_timeout_seconds == 45


def test_missing_variables_raise_settings_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AZDO_ORG", raising=False)
    monkeypatch.delenv("AZDO_PROJECT", raising=False)
    monkeypatch.delenv("AZDO_PIPELINE_ID", raising=False)
    monkeypatch.delenv("AZDO_PAT", raising=False)
    monkeypatch.delenv("SYSTEM_ACCESSTOKEN", raising=False)

    with pytest.raises(SettingsError):
        Settings.from_environment(repo_root=tmp_path)


def test_invalid_pipeline_id(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AZDO_ORG", "https://dev.azure.com/org")
    monkeypatch.setenv("AZDO_PROJECT", "project")
    monkeypatch.setenv("AZDO_PIPELINE_ID", "not-a-number")
    monkeypatch.setenv("AZDO_PAT", "token")

    with pytest.raises(SettingsError):
        Settings.from_environment(repo_root=tmp_path)


def test_azure_cli_token_used_when_env_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AZDO_ORG", "https://dev.azure.com/org")
    monkeypatch.setenv("AZDO_PROJECT", "project")
    monkeypatch.setenv("AZDO_PIPELINE_ID", "17")
    monkeypatch.delenv("AZDO_PAT", raising=False)
    monkeypatch.delenv("SYSTEM_ACCESSTOKEN", raising=False)

    monkeypatch.setattr("azure_pipelines_validator.settings.discover_pat", lambda org: "from-az-cli")

    settings = Settings.from_environment(repo_root=tmp_path)

    assert settings.personal_access_token.get_secret_value() == "from-az-cli"
