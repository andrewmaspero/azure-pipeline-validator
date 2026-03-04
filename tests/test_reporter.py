from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.console import Console

from azure_pipelines_validator.models import (
    FileValidationResult,
    GateMode,
    PreviewFinding,
    SchemaFinding,
    ValidationSummary,
    YamllintFinding,
)
from azure_pipelines_validator.reporter import REPORT_SCHEMA_VERSION, Reporter


def test_reporter_renders_summary(tmp_path: Path) -> None:
    console = Console(record=True)
    file_path = tmp_path / "pipeline.yml"
    file_path.write_text("trigger: none", encoding="utf-8")

    summary = ValidationSummary(
        (
            FileValidationResult(
                path=file_path,
                yamllint=tuple(),
                schema=tuple(),
                preview=tuple(),
                lsp=tuple(),
                final_yaml="trigger: none",
            ),
            FileValidationResult(
                path=file_path,
                yamllint=(
                    YamllintFinding(
                        path=file_path,
                        line=1,
                        column=1,
                        level="error",
                        message="indent",
                    ),
                ),
                schema=(
                    SchemaFinding(
                        path=file_path,
                        json_pointer="/trigger",
                        message="missing",
                    ),
                ),
                preview=(
                    PreviewFinding(
                        path=file_path,
                        message="preview error",
                        level="error",
                    ),
                ),
                lsp=tuple(),
                final_yaml=None,
            ),
        )
    )

    reporter = Reporter(repo_root=tmp_path, console=console)
    reporter.display(summary)

    output = console.export_text()
    assert "Blocking failures: 1" in output
    assert "pipeline.yml" in output


def test_reporter_hides_disabled_stage_columns_in_text(tmp_path: Path) -> None:
    console = Console(record=True)
    file_path = tmp_path / "pipeline.yml"
    file_path.write_text("trigger: none", encoding="utf-8")

    summary = ValidationSummary(
        (
            FileValidationResult(
                path=file_path,
                yamllint=tuple(),
                schema=tuple(),
                preview=tuple(),
                lsp=tuple(),
                final_yaml="trigger: none",
            ),
        ),
        include_lsp=False,
        include_lint=False,
        include_schema=False,
    )

    reporter = Reporter(repo_root=tmp_path, console=console)
    reporter.display(summary)

    output = console.export_text()
    assert "yamllint" not in output
    assert "schema" not in output
    assert "lsp" not in output
    assert "preview" in output


def test_reporter_json_output_contract(tmp_path: Path) -> None:
    console = Console(record=True)
    file_path = tmp_path / "pipeline.yml"
    file_path.write_text("trigger: none", encoding="utf-8")

    summary = ValidationSummary(
        (
            FileValidationResult(
                path=file_path,
                yamllint=tuple(),
                schema=tuple(),
                preview=(
                    PreviewFinding(
                        path=file_path,
                        message="api timeout",
                        level=None,
                    ),
                ),
                lsp=tuple(),
                final_yaml=None,
                preview_error=True,
            ),
        ),
        fail_fast=True,
        stopped_early=True,
        discovered_files=3,
    )
    reporter = Reporter(repo_root=tmp_path, console=console)
    reporter.display(summary, output_format="json")

    payload = json.loads(console.export_text())
    assert payload["schema_version"] == REPORT_SCHEMA_VERSION
    assert payload["summary"]["fail_fast"] is True
    assert payload["summary"]["stopped_early"] is True
    assert payload["summary"]["discovered_files"] == 3
    assert payload["summary"]["gate_mode"] == GateMode.ALL.value
    assert payload["summary"]["effective_gate_mode"] == GateMode.ALL.value
    assert payload["summary"]["warnings"] == []
    assert payload["files"][0]["path"] == "pipeline.yml"
    assert payload["files"][0]["stages"]["preview"]["status"] == "error"


def test_reporter_renders_warnings_in_text_and_json(tmp_path: Path) -> None:
    console = Console(record=True)
    file_path = tmp_path / "pipeline.yml"
    file_path.write_text("trigger: none", encoding="utf-8")

    summary = ValidationSummary(
        (
            FileValidationResult(
                path=file_path,
                yamllint=tuple(),
                schema=tuple(),
                preview=tuple(),
                lsp=tuple(),
                final_yaml="trigger: none",
            ),
        ),
        warnings=("Schema stage is deprecated for Azure correctness; prefer preview+lsp.",),
    )
    reporter = Reporter(repo_root=tmp_path, console=console)
    reporter.display(summary)

    output = console.export_text()
    assert "Warning: Schema stage is deprecated" in output

    console = Console(record=True)
    reporter = Reporter(repo_root=tmp_path, console=console)
    reporter.display(summary, output_format="json")
    payload = json.loads(console.export_text())
    assert any(
        "Schema stage is deprecated" in warning for warning in payload["summary"]["warnings"]
    )


def test_reporter_raises_on_unknown_output_format(tmp_path: Path) -> None:
    console = Console(record=True)
    file_path = tmp_path / "pipeline.yml"
    file_path.write_text("trigger: none", encoding="utf-8")

    summary = ValidationSummary(
        (
            FileValidationResult(
                path=file_path,
                yamllint=tuple(),
                schema=tuple(),
                preview=tuple(),
                lsp=tuple(),
                final_yaml="trigger: none",
            ),
        )
    )

    reporter = Reporter(repo_root=tmp_path, console=console)
    with pytest.raises(ValueError, match="Unsupported output_format 'xml'"):
        reporter.display(summary, output_format="xml")


def test_reporter_ndjson_includes_per_diagnostic_records(tmp_path: Path) -> None:
    console = Console(record=True)
    file_path = tmp_path / "pipeline.yml"
    file_path.write_text("trigger: none", encoding="utf-8")
    summary = ValidationSummary(
        (
            FileValidationResult(
                path=file_path,
                yamllint=tuple(),
                schema=tuple(),
                preview=(
                    PreviewFinding(
                        path=file_path,
                        message="preview error",
                        level="error",
                    ),
                ),
                lsp=tuple(),
                final_yaml=None,
            ),
        ),
        include_lint=False,
        include_schema=False,
        include_preview=True,
        include_lsp=False,
    )

    reporter = Reporter(repo_root=tmp_path, console=console)
    reporter.display(summary, output_format="ndjson")

    records = [json.loads(line) for line in console.export_text().splitlines() if line.strip()]
    assert any(record.get("type") == "diagnostic" for record in records)
    diagnostic = next(record for record in records if record.get("type") == "diagnostic")
    assert diagnostic["stage"] == "preview"
    assert diagnostic["message"] == "preview error"
