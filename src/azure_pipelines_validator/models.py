"""Shared dataclasses and pydantic models for validation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field


class RepositoryReference(BaseModel):
    """Represents the refs used when calling the preview endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    ref_name: str = Field(alias="refName")


class RepositoryContainer(BaseModel):
    """Container for the self-repository alias required by the API."""

    model_config = ConfigDict(populate_by_name=True)

    self_alias: RepositoryReference = Field(alias="self")


class RepositoryResources(BaseModel):
    """Repositories section for the preview payload."""

    repositories: RepositoryContainer


class PreviewRequest(BaseModel):
    """Payload sent to the preview REST API."""

    model_config = ConfigDict(populate_by_name=True)

    preview_run: bool = Field(default=True, alias="previewRun")
    yaml_override: str = Field(alias="yamlOverride")
    resources: RepositoryResources


class ValidationMessage(BaseModel):
    """Single validation issue reported by Azure DevOps."""

    message: str
    message_level: str | None = Field(default=None, alias="messageLevel")
    issue_code: str | None = Field(default=None, alias="issueCode")


class PreviewResponse(BaseModel):
    """Important parts of the preview response."""

    model_config = ConfigDict(populate_by_name=True)

    final_yaml: str | None = Field(default=None, alias="finalYaml")
    validation_results: Sequence[ValidationMessage] = Field(
        default_factory=tuple, alias="validationResults"
    )
    continuation_token: str | None = Field(default=None, alias="continuation_token")


class ServiceMessage(BaseModel):
    """Minimal error payload returned by Azure DevOps."""

    message: str


class YamlKind(StrEnum):
    """Classification of Azure Pipelines YAML files."""

    PIPELINE = "pipeline"
    STAGES_TEMPLATE = "stages"
    JOBS_TEMPLATE = "jobs"
    STEPS_TEMPLATE = "steps"
    RAW = "raw"


class StageName(StrEnum):
    """Validation stage names used in reporter outputs."""

    YAMLLINT = "yamllint"
    SCHEMA = "schema"
    PREVIEW = "preview"
    VSCODE = "vscode"


class StageStatus(StrEnum):
    """Per-stage status values for text and machine-readable reports."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class GateMode(StrEnum):
    """Blocking policy used to determine CLI success/failure."""

    AUTHORITATIVE = "authoritative"
    ALL = "all"


@dataclass(slots=True)
class YamllintFinding:
    """Finding produced by yamllint for a single YAML location.

    Attributes:
        path: Path of the validated file.
        line: Line number where the issue starts.
        column: Column number where the issue starts.
        level: Severity level string.
        message: Human-readable violation details.
    """

    path: Path
    line: int
    column: int
    level: str
    message: str


@dataclass(slots=True)
class SchemaFinding:
    """Finding produced by schema validation for a single JSON pointer."""

    path: Path
    json_pointer: str
    message: str


@dataclass(slots=True)
class PreviewFinding:
    """Finding returned by the Azure DevOps preview endpoint."""

    path: Path
    message: str
    level: str | None


@dataclass(slots=True)
class VscodeFinding:
    """Finding returned by the VS Code language server."""

    path: Path
    line: int
    column: int
    severity: str
    message: str
    code: str | int | None = None


@dataclass(slots=True)
class FileValidationResult:
    """Validation findings and status for a single file."""

    path: Path
    yamllint: Sequence[YamllintFinding]
    schema: Sequence[SchemaFinding]
    preview: Sequence[PreviewFinding]
    vscode: Sequence[VscodeFinding]
    final_yaml: str | None
    yamllint_error: bool = False
    schema_error: bool = False
    preview_error: bool = False
    vscode_error: bool = False

    @property
    def is_successful(self) -> bool:
        """Return whether all enabled stages passed without findings."""
        return not any((self.yamllint, self.schema, self.preview, self.vscode))

    def stage_status(self, stage: StageName, *, enabled: bool) -> StageStatus:
        """Compute the status for a stage.

        Args:
            stage: Stage to evaluate.
            enabled: Whether the stage ran for this file.

        Returns:
            The computed status for the stage.
        """
        if not enabled:
            return StageStatus.SKIPPED
        findings = {
            StageName.YAMLLINT: self.yamllint,
            StageName.SCHEMA: self.schema,
            StageName.PREVIEW: self.preview,
            StageName.VSCODE: self.vscode,
        }[stage]
        errored = {
            StageName.YAMLLINT: self.yamllint_error,
            StageName.SCHEMA: self.schema_error,
            StageName.PREVIEW: self.preview_error,
            StageName.VSCODE: self.vscode_error,
        }[stage]
        if errored:
            return StageStatus.ERROR
        if findings:
            return StageStatus.FAILED
        return StageStatus.PASSED


@dataclass(slots=True)
class ValidationSummary:
    """Aggregate results for a full validation run."""

    results: Sequence[FileValidationResult]
    include_lint: bool = True
    include_schema: bool = True
    include_preview: bool = True
    include_vscode: bool = True
    gate_mode: GateMode = GateMode.ALL
    fail_fast: bool = False
    stopped_early: bool = False
    discovered_files: int | None = None
    warnings: Sequence[str] = tuple()

    @property
    def success(self) -> bool:
        """Whether the run has zero blocking failures."""
        return self.failing_files == 0

    @property
    def total_files(self) -> int:
        """Return the number of discovered validation results."""
        return len(self.results)

    @property
    def failing_files(self) -> int:
        """Return the number of files with blocking failures."""
        return sum(1 for result in self.results if self._is_blocking_failure(result))

    @property
    def advisory_failing_files(self) -> int:
        """Return non-blocking failing file count under current gate mode."""
        return sum(
            1
            for result in self.results
            if (not result.is_successful) and (not self._is_blocking_failure(result))
        )

    @property
    def effective_gate_mode(self) -> GateMode:
        """Return gate mode after applying fallback logic."""
        if self.gate_mode == GateMode.AUTHORITATIVE and not (
            self.include_preview or self.include_vscode
        ):
            return GateMode.ALL
        return self.gate_mode

    def _is_blocking_failure(self, result: FileValidationResult) -> bool:
        if self.effective_gate_mode == GateMode.ALL:
            return not result.is_successful

        preview_status = result.stage_status(StageName.PREVIEW, enabled=self.include_preview)
        vscode_status = result.stage_status(StageName.VSCODE, enabled=self.include_vscode)
        blocking_statuses = {StageStatus.FAILED, StageStatus.ERROR}
        return (preview_status in blocking_statuses) or (vscode_status in blocking_statuses)


@dataclass(slots=True)
class ValidationOptions:
    """Execution options used when running a validation pass."""

    include_lint: bool = False
    include_schema: bool = False
    include_preview: bool = True
    include_vscode: bool = True
    gate_mode: GateMode = GateMode.AUTHORITATIVE
    fail_fast: bool = False
