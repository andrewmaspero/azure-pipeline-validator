from __future__ import annotations

from pathlib import Path

from azure_pipelines_validator.yamllint_engine import YamllintRunner


def test_yamllint_runner_reports_offenses(tmp_path: Path) -> None:
    runner = YamllintRunner()
    bad_yaml = "\n".join(
        (
            "jobs:",
            "- job:Bad",
            "  steps:",
            "    -script: echo hi",
        )
    )  # missing spaces around colon / hyphen
    path = tmp_path / "bad.yml"

    findings = runner.run(path, bad_yaml)

    assert findings
    assert findings[0].path == path
