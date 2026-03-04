"""Pretty console output for validation results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Sequence

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .models import FileValidationResult, StageName, StageStatus, ValidationSummary

REPORT_SCHEMA_VERSION = 2


class Reporter:
    """Renders a concise summary using Rich tables."""

    def __init__(self, repo_root: Path, console: Console | None = None) -> None:
        """Create a reporter for console and machine-readable output.

        Args:
            repo_root: Repository root used to render file paths relative to the project.
            console: Optional Rich console; defaults to a new console.
        """
        self._repo_root = repo_root
        self._console = console or Console()

    def display(self, summary: ValidationSummary, *, output_format: str = "text") -> None:
        """Render validation summary in the requested format.

        Args:
            summary: Validation summary to render.
            output_format: One of ``text``, ``json``, or ``ndjson``.

        Raises:
            ValueError: If ``output_format`` is not recognized.
        """
        if output_format == "json":
            self._emit_json_line(json.dumps(self.as_json(summary), separators=(",", ":")))
            return
        if output_format == "ndjson":
            for record in self.as_ndjson(summary):
                self._emit_json_line(json.dumps(record, separators=(",", ":")))
            return
        if output_format == "text":
            self._display_text(summary)
            return
        raise ValueError(f"Unsupported output_format '{output_format}'.")

    def _emit_json_line(self, line: str) -> None:
        """Prints one JSON line without Rich soft wrapping."""
        self._console.print(line, no_wrap=True, soft_wrap=True, highlight=False, markup=False)

    def _display_text(self, summary: ValidationSummary) -> None:
        table = Table(title="Azure Pipelines YAML validation", expand=True, box=box.ROUNDED)
        table.add_column("File", overflow="fold")

        stage_columns = _enabled_stage_columns(summary)
        for _, label, _ in stage_columns:
            table.add_column(label)

        for result in summary.results:
            row: list[Text | str] = [self._format_path(result.path)]
            for stage_name, _, enabled in stage_columns:
                findings = _stage_findings(result, stage_name)
                row.append(
                    _column_text(
                        findings,
                        status=result.stage_status(stage_name, enabled=enabled),
                    )
                )
            table.add_row(*row)

        self._console.print(table)
        status_style = "bold green" if summary.success else "bold red"
        summary_line = (
            f"Validated {summary.total_files} file(s). "
            f"Blocking failures: {summary.failing_files}. "
            f"Advisory-only files: {summary.advisory_failing_files}. "
            f"Gate mode: {summary.effective_gate_mode.value}."
        )
        self._console.print(Text(summary_line, style=status_style))
        for warning in summary.warnings:
            self._console.print(Text(f"Warning: {warning}", style="bold yellow"))

    def as_json(self, summary: ValidationSummary) -> dict[str, object]:
        """Returns a stable JSON-serializable report payload."""
        sorted_results = sorted(summary.results, key=lambda item: self._format_path(item.path))
        files: list[dict[str, object]] = []
        for result in sorted_results:
            files.append(
                {
                    "path": self._format_path(result.path),
                    "stages": {
                        "yamllint": _stage_payload(
                            result.yamllint,
                            status=result.stage_status(
                                StageName.YAMLLINT, enabled=summary.include_lint
                            ),
                        ),
                        "schema": _stage_payload(
                            result.schema,
                            status=result.stage_status(
                                StageName.SCHEMA, enabled=summary.include_schema
                            ),
                        ),
                        "preview": _stage_payload(
                            result.preview,
                            status=result.stage_status(
                                StageName.PREVIEW, enabled=summary.include_preview
                            ),
                        ),
                        "lsp": _stage_payload(
                            result.lsp,
                            status=result.stage_status(StageName.LSP, enabled=summary.include_lsp),
                        ),
                    },
                    "final_yaml": result.final_yaml,
                }
            )

        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "summary": {
                "success": summary.success,
                "total_files": summary.total_files,
                "failing_files": summary.failing_files,
                "advisory_failing_files": summary.advisory_failing_files,
                "gate_mode": summary.gate_mode.value,
                "effective_gate_mode": summary.effective_gate_mode.value,
                "discovered_files": summary.discovered_files,
                "fail_fast": summary.fail_fast,
                "stopped_early": summary.stopped_early,
                "warnings": list(summary.warnings),
            },
            "files": files,
        }

    def as_ndjson(self, summary: ValidationSummary) -> Iterator[dict[str, object]]:
        """Yields NDJSON records in stable order."""
        json_report = self.as_json(summary)
        for file_payload in json_report["files"]:
            yield {"type": "file", **file_payload}
        for result in sorted(summary.results, key=lambda item: self._format_path(item.path)):
            yield from self._diagnostic_records(result, summary)
        yield {"type": "summary", **json_report["summary"]}

    def _diagnostic_records(
        self, result: FileValidationResult, summary: ValidationSummary
    ) -> Iterator[dict[str, object]]:
        """Yield per-diagnostic NDJSON records for one file.

        Args:
            result: Validation result for a file.
            summary: Aggregate summary containing enabled stage configuration.

        Yields:
            One JSON-serializable dictionary per diagnostic.
        """
        stage_flags = {
            StageName.YAMLLINT: summary.include_lint,
            StageName.SCHEMA: summary.include_schema,
            StageName.PREVIEW: summary.include_preview,
            StageName.LSP: summary.include_lsp,
        }
        for stage_name, enabled in stage_flags.items():
            if not enabled:
                continue
            for finding in _stage_findings(result, stage_name):
                record: dict[str, object] = {
                    "type": "diagnostic",
                    "path": self._format_path(result.path),
                    "stage": stage_name.value,
                    "message": finding.message,
                }
                if hasattr(finding, "line"):
                    record["line"] = finding.line
                if hasattr(finding, "column"):
                    record["column"] = finding.column
                if hasattr(finding, "level"):
                    record["level"] = finding.level
                if hasattr(finding, "severity"):
                    record["severity"] = finding.severity
                if hasattr(finding, "code") and finding.code is not None:
                    record["code"] = finding.code
                if hasattr(finding, "json_pointer"):
                    record["json_pointer"] = finding.json_pointer
                yield record

    def _format_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self._repo_root))
        except ValueError:
            return str(path)


def _column_text(findings: Sequence[object], *, status: StageStatus) -> Text:
    if status == StageStatus.SKIPPED:
        return Text("skip", style="yellow")
    if status == StageStatus.ERROR:
        if findings:
            return Text(_first_message(findings), style="bold red")
        return Text("error", style="bold red")
    if not findings:
        return Text("pass", style="green")
    return Text(_first_message(findings), style="red")


def _first_message(findings: Sequence[object]) -> str:
    """Formats the first finding message and suffix."""
    first = findings[0]
    remaining = len(findings) - 1
    message = f"{first.message}"
    if hasattr(first, "line") and hasattr(first, "column"):
        message = f"L{first.line} C{first.column}: {message}"
    if remaining > 0:
        message = f"{message} (+{remaining} more)"
    return message


def _stage_payload(findings: Sequence[object], *, status: StageStatus) -> dict[str, object]:
    payload: dict[str, object] = {"status": status.value, "count": len(findings)}
    if findings:
        payload["first_message"] = _first_message(findings)
    return payload


def _enabled_stage_columns(summary: ValidationSummary) -> list[tuple[StageName, str, bool]]:
    """Return enabled stage columns for text table rendering.

    Args:
        summary: Validation summary containing stage include flags.

    Returns:
        A list of ``(stage_name, label, enabled)`` for stages shown in text output.
    """
    columns: list[tuple[StageName, str, bool]] = []
    if summary.include_lint:
        columns.append((StageName.YAMLLINT, "yamllint", True))
    if summary.include_schema:
        columns.append((StageName.SCHEMA, "schema", True))
    if summary.include_preview:
        columns.append((StageName.PREVIEW, "preview", True))
    if summary.include_lsp:
        columns.append((StageName.LSP, "lsp", True))
    return columns


def _stage_findings(result: FileValidationResult, stage: StageName) -> Sequence[object]:
    """Return findings for a specific stage on a file result."""
    return {
        StageName.YAMLLINT: result.yamllint,
        StageName.SCHEMA: result.schema,
        StageName.PREVIEW: result.preview,
        StageName.LSP: result.lsp,
    }[stage]
