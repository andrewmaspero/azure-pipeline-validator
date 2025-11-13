from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from azure_pipelines_validator import cli
from azure_pipelines_validator.cli import _consume_inline_env
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
        [
            str(tmp_path),
            "--repo-root",
            str(tmp_path),
            "--lint",
            "--schema",
            "--preview",
        ],
        env=env_vars(),
    )

    assert result.exit_code == 0
    assert "Validated" in result.stdout


def test_cli_accepts_inline_overrides(monkeypatch, tmp_path: Path) -> None:
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
        [
            str(tmp_path),
            "--repo-root",
            str(tmp_path),
            "--azdo-org",
            "https://dev.azure.com/example",
            "--azdo-project",
            "demo",
            "--azdo-pipeline-id",
            "9",
            "--azdo-pat",
            "token",
            "--azdo-ref-name",
            "refs/heads/dev",
            "--azdo-timeout-seconds",
            "12",
            "--lint",
            "--schema",
            "--preview",
        ],
        env={},
    )

    assert result.exit_code == 0
    assert "Validated" in result.stdout


def test_cli_reports_settings_error(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        [str(tmp_path), "--preview"],
        env={},
    )

    assert result.exit_code == 2
    assert "AZDO_ORG" in result.stdout


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
        [
            str(tmp_path),
            "--repo-root",
            str(tmp_path),
            "--lint",
            "--schema",
            "--preview",
        ],
        env=env_vars(),
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert "boom" in result.stdout


def test_cli_yamllint_only_runs_without_env(tmp_path: Path) -> None:
    target = tmp_path / "pipeline.yml"
    target.write_text("trigger: none\n", encoding="utf-8")

    result = runner.invoke(
        cli.app,
        [str(tmp_path), "--repo-root", str(tmp_path), "--lint"],
        env={},
    )

    assert result.exit_code == 0
    assert "Validated" in result.stdout


def test_cli_requires_toggle(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        [str(tmp_path)],
        env={},
    )

    assert result.exit_code == 2
    assert "Select at least one" in result.stdout


def test_schema_runs_without_preview(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "pipeline.yml"
    target.write_text("trigger: none\n", encoding="utf-8")

    monkeypatch.setattr(
        cli, "download_public_schema", lambda timeout: "{\"type\": \"object\"}", raising=False
    )

    result = runner.invoke(
        cli.app,
        [str(tmp_path), "--schema"],
        env={},
    )

    assert result.exit_code == 0
    assert "Validated" in result.stdout


def test_inline_env_assignments(tmp_path: Path) -> None:
    env: dict[str, str] = {}

    remaining = _consume_inline_env(
        ["AZDO_PAT=123", "--flag=value", "AZDO_ORG=https://dev.azure.com/example", str(tmp_path)],
        environ=env,
    )

    assert env["AZDO_PAT"] == "123"
    assert env["AZDO_ORG"] == "https://dev.azure.com/example"
    assert remaining == ["--flag=value", str(tmp_path)]
