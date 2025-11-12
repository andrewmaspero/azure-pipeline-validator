from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from azure_pipelines_validator import cli
from azure_pipelines_validator.exceptions import AzureDevOpsError
from azure_pipelines_validator.models import PreviewResponse

runner = CliRunner()


def env_vars() -> dict[str, str]:
    return {
        "AZDO_ORG": "https://dev.azure.com/example",
        "AZDO_PROJECT": "demo",
        "AZDO_PIPELINE_ID": "9",
        "AZDO_PAT": "token",
        "AZDO_REFNAME": "refs/heads/main",
        "AZDO_TIMEOUT_SECONDS": "5",
    }


def test_cli_happy_path(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "pipeline.yml"
    target.write_text("trigger: none\n", encoding="utf-8")

    monkeypatch.setattr(
        cli.AzureDevOpsClient,
        "download_schema",
        lambda self: '{"type": "object"}',
        raising=False,
    )
    monkeypatch.setattr(
        cli.AzureDevOpsClient,
        "preview",
        lambda self, override: PreviewResponse(
            final_yaml=override,
            validation_results=(),
            continuation_token=None,
        ),
        raising=False,
    )

    result = runner.invoke(
        cli.app,
        [str(tmp_path), "--repo-root", str(tmp_path)],
        env=env_vars(),
    )

    assert result.exit_code == 0
    assert "Validated" in result.stdout


def test_cli_reports_settings_error(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        [str(tmp_path)],
        env={},
    )

    assert result.exit_code == 2
    assert "Set AZDO_PAT" in result.stdout


def test_cli_handles_azure_devops_error(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "pipeline.yml"
    target.write_text("trigger: none\n", encoding="utf-8")

    def raise_error(*_, **__):
        raise AzureDevOpsError(500, "boom")

    monkeypatch.setattr(cli.AzureDevOpsClient, "preview", raise_error, raising=False)
    monkeypatch.setattr(
        cli.AzureDevOpsClient,
        "download_schema",
        lambda self: '{"type": "object"}',
        raising=False,
    )

    result = runner.invoke(
        cli.app,
        [str(tmp_path), "--repo-root", str(tmp_path)],
        env=env_vars(),
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert "Azure DevOps responded" in result.stdout
