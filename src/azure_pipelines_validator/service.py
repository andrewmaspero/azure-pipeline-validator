"""Core orchestration logic for the validator."""

from __future__ import annotations

from pathlib import Path

from .azure_devops import AzureDevOpsClient
from .exceptions import AzureDevOpsError, LspValidationError
from .file_scanner import FileScanner
from .lsp_engine import LspValidator
from .models import (
    FileValidationResult,
    GateMode,
    LspFinding,
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
        client: AzureDevOpsClient | None,
        scanner: FileScanner,
        loader: DocumentLoader,
        wrapper: TemplateWrapper,
        yamllint_runner: YamllintRunner | None = None,
        schema_validator: SchemaValidator | None = None,
        lsp_validator: LspValidator | None = None,
    ) -> None:
        """Initialize the validation service.

        Args:
            client: Optional Azure DevOps client for preview validation.
            scanner: Resolver for which files should be validated.
            loader: YAML document loader for pipeline files.
            wrapper: Template wrapper used for preview/schema inputs.
            yamllint_runner: Optional yamllint runner, enabled when requested.
            schema_validator: Optional Azure schema validator for soft checks.
            lsp_validator: Optional Azure LSP language-server validator.
        """
        self._client = client
        self._scanner = scanner
        self._loader = loader
        self._wrapper = wrapper
        self._yamllint_runner = yamllint_runner
        self._schema_validator = schema_validator
        self._lsp_validator = lsp_validator

    def validate(self, target: Path, options: ValidationOptions) -> ValidationSummary:
        """Validate a target file or directory and produce a summary report.

        Args:
            target: A file or directory path to validate.
            options: Runtime toggles that control which stages run.

        Returns:
            A validation summary containing per-file findings and gate state.

        Raises:
            AzureDevOpsError: When preview validation fails in fail-fast mode.
        """
        files = self._scanner.collect(target)
        warnings = self._build_warnings(options)

        results: list[FileValidationResult] = []
        for file_path in files:
            document = self._loader.load(file_path)
            lint_findings = self._run_lint(document, options)
            lsp_findings, lsp_error = self._run_lsp(document, options)

            wrapped_content: str | None = None
            if options.include_schema or options.include_preview:
                wrapped_content = self._wrapper.wrap(document)

            schema_findings = self._run_schema(document, options, wrapped_content)
            preview_findings, final_yaml, preview_error = self._run_preview(
                document, options, wrapped_content
            )

            result = FileValidationResult(
                path=document.path,
                yamllint=lint_findings,
                schema=schema_findings,
                preview=preview_findings,
                lsp=lsp_findings,
                final_yaml=final_yaml,
                preview_error=preview_error,
                lsp_error=lsp_error,
            )
            results.append(result)
            if options.fail_fast and not result.is_successful:
                break
        return ValidationSummary(
            tuple(results),
            include_lint=options.include_lint,
            include_schema=options.include_schema,
            include_preview=options.include_preview,
            include_lsp=options.include_lsp,
            gate_mode=options.gate_mode,
            fail_fast=options.fail_fast,
            stopped_early=options.fail_fast and len(results) < len(files),
            discovered_files=len(files),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _build_warnings(options: ValidationOptions) -> list[str]:
        warnings: list[str] = []
        if options.include_schema:
            warnings.append("Schema stage is deprecated for Azure correctness; prefer preview+lsp.")
        if (
            options.gate_mode == GateMode.AUTHORITATIVE
            and not options.include_preview
            and not options.include_lsp
        ):
            warnings.append(
                "Gate mode 'authoritative' requires preview or lsp; "
                "falling back to 'all' for blocking behavior."
            )
        return warnings

    def _run_lint(
        self, document: YamlDocument, options: ValidationOptions
    ) -> tuple[YamllintFinding, ...]:
        if not options.include_lint or self._yamllint_runner is None:
            return tuple()
        return self._yamllint_runner.run(document.path, document.content)

    def _run_schema(
        self,
        document: YamlDocument,
        options: ValidationOptions,
        wrapped_content: str | None,
    ) -> tuple[SchemaFinding, ...]:
        if not options.include_schema or self._schema_validator is None:
            return tuple()
        content = wrapped_content if wrapped_content is not None else document.content
        return self._schema_validator.validate(document.path, content)

    def _run_preview(
        self,
        document: YamlDocument,
        options: ValidationOptions,
        wrapped_content: str | None,
    ) -> tuple[tuple[PreviewFinding, ...], str | None, bool]:
        if not options.include_preview:
            return tuple(), None, False
        if self._client is None:
            raise RuntimeError("Preview requested but Azure DevOps client is not configured")
        wrapped = wrapped_content if wrapped_content is not None else self._wrapper.wrap(document)
        try:
            response = self._client.preview(wrapped)
        except AzureDevOpsError as error:
            if options.fail_fast:
                raise
            finding = PreviewFinding(
                path=document.path,
                message=error.detail,
                level=None,
            )
            return (finding,), None, True
        findings: list[PreviewFinding] = []
        for message in response.validation_results:
            findings.append(
                PreviewFinding(
                    path=document.path,
                    message=message.message,
                    level=message.message_level,
                )
            )
        return tuple(findings), response.final_yaml, False

    def _run_lsp(
        self, document: YamlDocument, options: ValidationOptions
    ) -> tuple[tuple[LspFinding, ...], bool]:
        if not options.include_lsp or self._lsp_validator is None:
            return tuple(), False
        try:
            findings = self._lsp_validator.run([document]).get(document.path, tuple())
            return findings, False
        except LspValidationError as error:
            if options.fail_fast:
                raise
            finding = LspFinding(
                path=document.path,
                line=1,
                column=1,
                severity="error",
                message=str(error),
            )
            return (finding,), True
