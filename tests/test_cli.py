from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from azure_pipelines_validator import cli
from azure_pipelines_validator.exceptions import (
    AzureDevOpsError,
    LspValidationError,
    SchemaUnavailableError,
)
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


def env_vars_with_org_slug() -> dict[str, str]:
    return {
        "AZDO_ORG": "example",
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
        [str(tmp_path), "--repo-root", str(tmp_path), "--skip-lsp"],
        env=env_vars(),
    )

    assert result.exit_code == 0
    assert "Validated" in result.stdout


def test_cli_happy_path_with_org_slug(monkeypatch, tmp_path: Path) -> None:
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
        [str(tmp_path), "--repo-root", str(tmp_path), "--skip-lsp"],
        env=env_vars_with_org_slug(),
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
            "--skip-lsp",
        ],
        env={},
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
        [str(tmp_path), "--repo-root", str(tmp_path), "--skip-lsp"],
        env=env_vars(),
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert "boom" in result.stdout


def test_cli_yamllint_only_runs_without_env(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "pipeline.yml"
    target.write_text("trigger: none\n", encoding="utf-8")

    result = runner.invoke(
        cli.app,
        [
            str(tmp_path),
            "--repo-root",
            str(tmp_path),
            "--skip-schema",
            "--skip-preview",
            "--skip-lsp",
        ],
        env={},
    )

    assert result.exit_code == 0
    assert "Validated" in result.stdout


def test_cli_json_output_format(monkeypatch, tmp_path: Path) -> None:
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
            "--skip-lsp",
            "--output-format",
            "json",
        ],
        env=env_vars(),
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["summary"]["success"] is True
    assert payload["files"][0]["stages"]["lsp"]["status"] == "skipped"


def test_cli_ndjson_output_format(monkeypatch, tmp_path: Path) -> None:
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
            "--skip-lsp",
            "--output-format",
            "ndjson",
        ],
        env=env_vars(),
    )

    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) >= 2
    file_record = json.loads(lines[0])
    summary_record = json.loads(lines[-1])
    assert file_record["type"] == "file"
    assert summary_record["type"] == "summary"


def test_cli_default_authoritative_gate_ignores_yamllint_only_failures(
    monkeypatch, tmp_path: Path
) -> None:
    target = tmp_path / "fail.yml"
    target.write_text("trigger:\n\t- none\n", encoding="utf-8")

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
            "--skip-lsp",
            "--run-yamllint",
        ],
        env=env_vars(),
    )

    assert result.exit_code == 0
    assert "authoritative" in result.stdout


def test_cli_gate_mode_all_blocks_on_yamllint_failures(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "fail.yml"
    target.write_text("trigger:\n\t- none\n", encoding="utf-8")

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
            "--skip-lsp",
            "--run-yamllint",
            "--gate-mode",
            "all",
        ],
        env=env_vars(),
    )

    assert result.exit_code == 1
    assert "all" in result.stdout


def test_cli_run_schema_emits_deprecation_warning(monkeypatch, tmp_path: Path) -> None:
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
        [str(tmp_path), "--repo-root", str(tmp_path), "--skip-lsp", "--run-schema"],
        env=env_vars(),
    )

    assert result.exit_code == 0
    assert "Schema stage is deprecated" in result.stdout


def test_cli_json_summary_includes_warnings(monkeypatch, tmp_path: Path) -> None:
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
            "--skip-lsp",
            "--run-schema",
            "--output-format",
            "json",
        ],
        env=env_vars(),
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert any(
        "Schema stage is deprecated" in warning for warning in payload["summary"]["warnings"]
    )


def test_cli_reports_lsp_initialization_error(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "pipeline.yml"
    target.write_text("trigger: none\n", encoding="utf-8")

    class RaisingLspValidator:
        def __init__(self, *args, **kwargs):
            raise LspValidationError("lsp unavailable")

    monkeypatch.setattr(cli, "LspValidator", RaisingLspValidator)

    result = runner.invoke(
        cli.app,
        [str(tmp_path), "--repo-root", str(tmp_path), "--skip-schema", "--skip-preview"],
        env={},
    )

    assert result.exit_code == 2
    assert "lsp unavailable" in result.stdout


def test_cli_rejects_legacy_vscode_flags(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        [str(tmp_path), "--skip-vscode"],
        env=env_vars(),
    )

    # Error rendering varies across Typer/Rich versions in CI, but exit code is stable.
    assert result.exit_code == 2


def test_cli_handles_schema_unavailable_error(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "pipeline.yml"
    target.write_text("trigger: none\n", encoding="utf-8")

    monkeypatch.setattr(
        cli.AzureDevOpsClient,
        "download_schema",
        lambda self: '{"type": "object"}',
        raising=False,
    )
    monkeypatch.setattr(
        cli.ValidationService,
        "validate",
        lambda self, target, options: (_ for _ in ()).throw(SchemaUnavailableError("schema boom")),
    )

    result = runner.invoke(
        cli.app,
        [str(tmp_path), "--repo-root", str(tmp_path), "--skip-lsp"],
        env=env_vars(),
    )

    assert result.exit_code == 1
    assert "schema boom" in result.stdout


def run_hidden_mode_test(
    *,
    tmp_path: Path,
    hidden_name: str,
    hidden_mode: str | None,
    expected_substring: str,
) -> None:
    hidden_dir = tmp_path / hidden_name
    hidden_dir.mkdir()
    (hidden_dir / "ci.yml").write_text("steps: []\n", encoding="utf-8")

    args = [
        str(tmp_path),
        "--repo-root",
        str(tmp_path),
        "--skip-preview",
        "--skip-schema",
        "--skip-lsp",
        "--run-yamllint",
    ]
    if hidden_mode is not None:
        args.extend(["--hidden-mode", hidden_mode])

    result = runner.invoke(cli.app, args, env={})

    assert result.exit_code == 0
    assert expected_substring in result.stdout


def test_cli_default_common_mode_discovers_devops_hidden_directory(tmp_path: Path) -> None:
    run_hidden_mode_test(
        tmp_path=tmp_path,
        hidden_name=".devops",
        hidden_mode=None,
        expected_substring=".devops/ci.yml",
    )


def test_cli_hidden_mode_none_excludes_devops_hidden_directory(tmp_path: Path) -> None:
    run_hidden_mode_test(
        tmp_path=tmp_path,
        hidden_name=".devops",
        hidden_mode="none",
        expected_substring="Validated 0 file(s).",
    )


def test_cli_hidden_mode_all_includes_non_common_hidden_directory(tmp_path: Path) -> None:
    run_hidden_mode_test(
        tmp_path=tmp_path,
        hidden_name=".customhidden",
        hidden_mode="all",
        expected_substring=".customhidden/ci.yml",
    )
