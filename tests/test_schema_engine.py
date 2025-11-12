from __future__ import annotations

import textwrap
from pathlib import Path

from azure_pipelines_validator.schema_engine import SchemaValidator

SCHEMA_TEXT = textwrap.dedent(
    """
    {
      "type": "object",
      "properties": {
        "trigger": {"type": "string"}
      },
      "required": ["trigger"]
    }
    """
).strip()


def schema_supplier() -> str:
    return SCHEMA_TEXT


def test_schema_validator_reports_missing_fields(tmp_path: Path) -> None:
    validator = SchemaValidator(schema_supplier)
    yaml_path = tmp_path / "pipeline.yml"
    yaml_path.write_text("pr: none\n", encoding="utf-8")

    findings = validator.validate(yaml_path, yaml_path.read_text(encoding="utf-8"))

    assert findings
    assert "trigger" in findings[0].message


def test_schema_validator_handles_invalid_yaml(tmp_path: Path) -> None:
    validator = SchemaValidator(schema_supplier)
    yaml_path = tmp_path / "invalid.yml"
    yaml_path.write_text("steps: [", encoding="utf-8")

    findings = validator.validate(yaml_path, yaml_path.read_text(encoding="utf-8"))

    assert findings
    assert findings[0].json_pointer == "<load>"
