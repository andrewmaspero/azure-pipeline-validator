"""Pretty console output for validation results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .models import StageName, StageStatus, ValidationSummary


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
        self._display_text(summary)

    def _emit_json_line(self, line: str) -> None:
        """Prints one JSON line without Rich soft wrapping."""
        self._console.print(line, no_wrap=True, soft_wrap=True, highlight=False, markup=False)

    def _display_text(self, summary: ValidationSummary) -> None:
        table = Table(title="Azure Pipelines YAML validation", expand=True, box=box.ROUNDED)
        table.add_column("File", overflow="fold")
        table.add_column("yamllint")
        table.add_column("schema")
        table.add_column("preview")
        table.add_column("vscode")

        for result in summary.results:
            table.add_row(
                self._format_path(result.path),
                _column_text(
                    result.yamllint,
                    status=result.stage_status(StageName.YAMLLINT, enabled=summary.include_lint),
                ),
                _column_text(
                    result.schema,
                    status=result.stage_status(StageName.SCHEMA, enabled=summary.include_schema),
                ),
                _column_text(
                    result.preview,
                    status=result.stage_status(StageName.PREVIEW, enabled=summary.include_preview),
                ),
                _column_text(
                    result.vscode,
                    status=result.stage_status(StageName.VSCODE, enabled=summary.include_vscode),
                ),
            )

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
                        "vscode": _stage_payload(
                            result.vscode,
                            status=result.stage_status(
                                StageName.VSCODE, enabled=summary.include_vscode
                            ),
                        ),
                    },
                    "final_yaml": result.final_yaml,
                }
            )

        return {
            "schema_version": 1,
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

    def as_ndjson(self, summary: ValidationSummary) -> list[dict[str, object]]:
        """Returns NDJSON records in stable order."""
        json_report = self.as_json(summary)
        records: list[dict[str, object]] = []
        for file_payload in json_report["files"]:
            records.append({"type": "file", **file_payload})
        records.append({"type": "summary", **json_report["summary"]})
        return records

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
