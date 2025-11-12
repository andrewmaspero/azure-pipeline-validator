"""Core orchestration logic for the validator."""

from __future__ import annotations

from pathlib import Path

from .azure_devops import AzureDevOpsClient
from .file_scanner import FileScanner
from .models import (
    FileValidationResult,
    PreviewFinding,
    SchemaFinding,
    ValidationOptions,
    ValidationSummary,
    YamllintFinding,
)
from .schema_engine import SchemaValidator
from .yaml_processing import DocumentLoader, TemplateWrapper, YamlDocument
from .yamllint_engine import YamllintRunner


class ValidationService:
    """Coordinates linting, schema checks, and preview dry-runs."""

    def __init__(
        self,
        client: AzureDevOpsClient,
        scanner: FileScanner,
        loader: DocumentLoader,
        wrapper: TemplateWrapper,
        yamllint_runner: YamllintRunner | None = None,
        schema_validator: SchemaValidator | None = None,
    ) -> None:
        self._client = client
        self._scanner = scanner
        self._loader = loader
        self._wrapper = wrapper
        self._yamllint_runner = yamllint_runner
        self._schema_validator = schema_validator

    def validate(self, target: Path, options: ValidationOptions) -> ValidationSummary:
        files = self._scanner.collect(target)
        results: list[FileValidationResult] = []
        for file_path in files:
            document = self._loader.load(file_path)
            lint_findings = self._run_lint(document, options)
            schema_findings = self._run_schema(document, options)
            preview_findings, final_yaml = self._run_preview(document, options)

            result = FileValidationResult(
                path=file_path,
                yamllint=lint_findings,
                schema=schema_findings,
                preview=preview_findings,
                final_yaml=final_yaml,
            )
            results.append(result)
            if options.fail_fast and not result.is_successful:
                break
        return ValidationSummary(tuple(results))

    def _run_lint(
        self, document: YamlDocument, options: ValidationOptions
    ) -> tuple[YamllintFinding, ...]:
        if not options.include_lint or self._yamllint_runner is None:
            return tuple()
        return self._yamllint_runner.run(document.path, document.content)

    def _run_schema(
        self, document: YamlDocument, options: ValidationOptions
    ) -> tuple[SchemaFinding, ...]:
        if not options.include_schema or self._schema_validator is None:
            return tuple()
        return self._schema_validator.validate(document.path, document.content)

    def _run_preview(
        self, document: YamlDocument, options: ValidationOptions
    ) -> tuple[tuple[PreviewFinding, ...], str | None]:
        if not options.include_preview:
            return tuple(), None
        wrapped = self._wrapper.wrap(document)
        response = self._client.preview(wrapped)
        findings: list[PreviewFinding] = []
        for message in response.validation_results:
            findings.append(
                PreviewFinding(
                    path=document.path,
                    message=message.message,
                    level=message.message_level,
                )
            )
        return tuple(findings), response.final_yaml
