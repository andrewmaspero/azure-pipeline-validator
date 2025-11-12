"""Pretty console output for validation results."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .models import ValidationSummary


class Reporter:
    """Renders a concise summary using Rich tables."""

    def __init__(self, repo_root: Path, console: Console | None = None) -> None:
        self._repo_root = repo_root
        self._console = console or Console()

    def display(self, summary: ValidationSummary) -> None:
        table = Table(title="Azure Pipelines YAML validation", expand=True)
        table.add_column("File", overflow="fold")
        table.add_column("yamllint")
        table.add_column("schema")
        table.add_column("preview")

        for result in summary.results:
            table.add_row(
                self._format_path(result.path),
                _column_text(result.yamllint),
                _column_text(result.schema),
                _column_text(result.preview),
            )

        self._console.print(table)
        status_style = "bold green" if summary.success else "bold red"
        summary_line = (
            f"Validated {summary.total_files} file(s). Failures: {summary.failing_files}."
        )
        self._console.print(Text(summary_line, style=status_style))

    def _format_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self._repo_root))
        except ValueError:
            return str(path)


def _column_text(findings: Sequence[object]) -> Text:
    if not findings:
        return Text("pass", style="green")
    first = findings[0]
    remaining = len(findings) - 1
    message = f"{first.message}"
    if hasattr(first, "line") and hasattr(first, "column"):
        message = f"L{first.line} C{first.column}: {message}"
    if remaining > 0:
        message = f"{message} (+{remaining} more)"
    return Text(message, style="red")
