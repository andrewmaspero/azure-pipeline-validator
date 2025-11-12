"""JSON schema validation against Microsoft's published contract."""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Sequence

import yaml
from jsonschema import validators
from jsonschema.protocols import Validator as SchemaValidatorProtocol
from yaml import YAMLError

from .exceptions import SchemaUnavailableError
from .models import SchemaFinding


class SchemaValidator:
    """Validates YAML documents using the official Azure DevOps schema."""

    def __init__(self, schema_supplier: Callable[[], str]) -> None:
        self._schema_supplier = schema_supplier
        self._validator: SchemaValidatorProtocol | None = None

    def validate(self, path: Path, content: str) -> Sequence[SchemaFinding]:
        validator = self._ensure_validator()
        try:
            parsed = yaml.safe_load(content)
        except YAMLError as exc:
            return (
                SchemaFinding(
                    path=path,
                    json_pointer="<load>",
                    message=str(exc),
                ),
            )

        parsed_root = parsed if parsed is not None else MappingProxyType({})
        findings: list[SchemaFinding] = []
        for error in validator.iter_errors(parsed_root):
            pointer = _format_pointer(error.path)
            findings.append(SchemaFinding(path=path, json_pointer=pointer, message=error.message))
        return tuple(findings)

    def _ensure_validator(self) -> SchemaValidatorProtocol:
        if self._validator is not None:
            return self._validator
        schema_text = self._schema_supplier()
        if not schema_text:
            raise SchemaUnavailableError("Schema download returned empty content")
        schema_payload = json.loads(schema_text)
        validator_cls = validators.validator_for(schema_payload)
        validator_cls.check_schema(schema_payload)
        self._validator = validator_cls(schema_payload)
        return self._validator


def _format_pointer(parts) -> str:
    joined = "/".join(str(part) for part in parts)
    return f"/{joined}" if joined else "/"
