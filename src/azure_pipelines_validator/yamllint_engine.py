"""Run yamllint with project defaults and normalize the reported findings."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Sequence

from yamllint import linter
from yamllint.config import YamlLintConfig

from .models import YamllintFinding

DEFAULT_CONFIG = textwrap.dedent(
    """
    extends: default
    rules:
      document-start: disable
      line-length:
        max: 180
      truthy:
        allowed-values: ['on', 'off', 'true', 'false', 'yes', 'no']
      indentation:
        indent-sequences: consistent
    """
)


class YamllintRunner:
    """Executes yamllint and adapts the findings into dataclasses."""

    def __init__(self, config_text: str | None = None) -> None:
        """Initializes a yamllint runner.

        Args:
            config_text: Optional yamllint configuration content. When omitted,
                the module's default configuration is used.
        """
        self.config = YamlLintConfig(config_text or DEFAULT_CONFIG)

    def run(self, path: Path, content: str) -> Sequence[YamllintFinding]:
        """Runs yamllint on YAML content and returns typed findings.

        Args:
            path: Source path associated with lint problems.
            content: YAML content to lint.

        Returns:
            Tuple of lint findings emitted by yamllint.
        """
        problems = linter.run(content, self.config, str(path))
        findings: list[YamllintFinding] = []
        for problem in problems:
            findings.append(
                YamllintFinding(
                    path=path,
                    line=problem.line,
                    column=problem.column,
                    level=problem.level,
                    message=problem.message,
                )
            )
        return tuple(findings)
