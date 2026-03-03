"""JSON schema validation against Microsoft's published contract.

This module validates YAML documents using the Azure DevOps schema and returns
normalized findings for schema violations and YAML parse failures.
"""

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
        """Initializes a lazy schema validator.

        Args:
            schema_supplier: Callable that returns schema JSON text when first
                needed.
        """
        self._schema_supplier = schema_supplier
        self._validator: SchemaValidatorProtocol | None = None

    def validate(self, path: Path, content: str) -> Sequence[SchemaFinding]:
        """Validates a YAML document and returns schema findings.

        Args:
            path: Source path attached to each emitted finding.
            content: YAML content to parse and validate.

        Returns:
            A sequence of schema findings. If YAML parsing fails, the sequence
            contains a single synthetic finding at ``<load>``.

        Raises:
            SchemaUnavailableError: If the schema supplier returns empty content.
            json.JSONDecodeError: If supplied schema text is not valid JSON.
            jsonschema.exceptions.SchemaError: If the supplied schema is invalid.
        """
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
    """Formats a JSON pointer from iterable path parts.

    Args:
        parts: Sequence-like path parts from a schema validation error.

    Returns:
        A JSON pointer string rooted at ``/``.
    """
    joined = "/".join(str(part) for part in parts)
    return f"/{joined}" if joined else "/"
