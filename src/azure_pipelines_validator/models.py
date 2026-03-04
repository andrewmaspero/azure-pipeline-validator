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

    ref_name: str = Field(
        alias="refName",
        description="Git ref used by Azure DevOps while expanding templates.",
    )


class RepositoryContainer(BaseModel):
    """Container for the self-repository alias required by the API."""

    model_config = ConfigDict(populate_by_name=True)

    self_alias: RepositoryReference = Field(
        alias="self",
        description="Reference metadata for the repository being validated.",
    )


class RepositoryResources(BaseModel):
    """Repositories section for the preview payload."""

    repositories: RepositoryContainer = Field(
        description="Repository references included in the preview payload.",
    )


class PreviewRequest(BaseModel):
    """Payload sent to the preview REST API."""

    model_config = ConfigDict(populate_by_name=True)

    preview_run: bool = Field(
        default=True,
        alias="previewRun",
        description="Whether Azure DevOps should execute preview expansion logic.",
    )
    yaml_override: str = Field(
        alias="yamlOverride",
        description="Raw YAML content submitted for preview compilation.",
    )
    resources: RepositoryResources = Field(
        description="Repository context used while resolving templates and resources.",
    )


class ValidationMessage(BaseModel):
    """Single validation issue reported by Azure DevOps."""

    message: str = Field(description="Human-readable validation message from Azure DevOps.")
    message_level: str | None = Field(
        default=None,
        alias="messageLevel",
        description="Severity level reported by Azure DevOps for the validation message.",
    )
    issue_code: str | None = Field(
        default=None,
        alias="issueCode",
        description="Stable issue identifier returned by Azure DevOps when available.",
    )


class PreviewResponse(BaseModel):
    """Important parts of the preview response."""

    model_config = ConfigDict(populate_by_name=True)

    final_yaml: str | None = Field(
        default=None,
        alias="finalYaml",
        description="Fully expanded Azure Pipelines YAML returned by preview.",
    )
    validation_results: Sequence[ValidationMessage] = Field(
        default_factory=tuple,
        alias="validationResults",
        description="Validation findings produced by the Azure preview endpoint.",
    )
    continuation_token: str | None = Field(
        default=None,
        alias="continuation_token",
        description="Pagination token included when preview results are chunked.",
    )


class ServiceMessage(BaseModel):
    """Minimal error payload returned by Azure DevOps."""

    message: str = Field(description="Error message returned by the Azure DevOps service.")


class PipelineSummary(BaseModel):
    """Minimal Azure DevOps pipeline metadata used for auto-selection."""

    id: int = Field(description="Numeric Azure DevOps pipeline identifier.")
    name: str = Field(description="Azure DevOps pipeline display name.")
    folder: str | None = Field(
        default=None,
        description="Pipeline folder path reported by Azure DevOps when available.",
    )
    url: str | None = Field(
        default=None,
        description="REST URL for this pipeline when provided by Azure DevOps.",
    )
    repository_name: str | None = Field(
        default=None,
        description="Repository name inferred from pipeline configuration metadata.",
    )
    repository_id: str | None = Field(
        default=None,
        description="Repository ID inferred from pipeline configuration metadata.",
    )
    default_branch: str | None = Field(
        default=None,
        description="Default branch configured for the pipeline repository resource.",
    )


class ResolvedAzureContext(BaseModel):
    """Resolved Azure context inputs used to build runtime settings."""

    organization: str = Field(description="Azure DevOps organization URL or slug.")
    project: str = Field(description="Azure DevOps project name.")
    pipeline_id: int = Field(description="Resolved Azure DevOps pipeline ID.")
    personal_access_token: str = Field(
        description="Resolved token string used to authenticate Azure API calls.",
    )
    token_kind: str = Field(
        description="Token kind used for auth header strategy, for example 'pat' or 'bearer'.",
    )
    ref_name: str = Field(description="Git ref used for template expansion.")
    timeout_seconds: float = Field(description="Azure DevOps request timeout in seconds.")


class AuthStatusResult(BaseModel):
    """Authentication status payload for CLI diagnostics."""

    resolved_org: str | None = Field(
        default=None,
        description="Organization value resolved for auth lookups.",
    )
    keyring_backend_available: bool = Field(
        description="Whether an OS keyring backend is available.",
    )
    keyring_backend_detail: str = Field(
        description="Human-readable keyring backend detail or failure reason.",
    )
    default_org_stored: str | None = Field(
        default=None,
        description="Default organization currently stored in keyring.",
    )
    pat_present_for_org: bool = Field(
        description="Whether a keychain PAT exists for the resolved organization.",
    )
    env_pat_present: bool = Field(
        description="Whether PAT-related environment variables are currently set.",
    )
    azure_cli_available: bool = Field(
        description="Whether Azure CLI access token fallback appears available.",
    )


class ContextDetectResult(BaseModel):
    """Context detection payload for machine-readable diagnostics."""

    organization: str | None = Field(
        default=None,
        description="Detected Azure DevOps organization.",
    )
    project: str | None = Field(
        default=None,
        description="Detected Azure DevOps project.",
    )
    repository: str | None = Field(
        default=None,
        description="Detected Azure DevOps repository.",
    )
    remote_name: str = Field(description="Git remote name used for detection.")
    remote_url: str | None = Field(default=None, description="Git remote URL used for parsing.")
    branch: str | None = Field(default=None, description="Detected git branch name.")
    repo_root: str | None = Field(default=None, description="Detected repository root path.")
    organization_source: str = Field(description="Source used to resolve organization.")
    project_source: str = Field(description="Source used to resolve project.")
    repository_source: str = Field(description="Source used to resolve repository.")
    pipeline_id: int | None = Field(default=None, description="Resolved or selected pipeline ID.")
    pipeline_source: str = Field(description="Source used to resolve pipeline ID.")


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
    LSP = "lsp"


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
class LspFinding:
    """Finding returned by the Azure LSP language server."""

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
    lsp: Sequence[LspFinding]
    final_yaml: str | None
    yamllint_error: bool = False
    schema_error: bool = False
    preview_error: bool = False
    lsp_error: bool = False

    @property
    def is_successful(self) -> bool:
        """Return whether all enabled stages passed without findings."""
        return not any(
            (
                self.yamllint,
                self.schema,
                self.preview,
                self.lsp,
                self.yamllint_error,
                self.schema_error,
                self.preview_error,
                self.lsp_error,
            )
        )

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
            StageName.LSP: self.lsp,
        }[stage]
        errored = {
            StageName.YAMLLINT: self.yamllint_error,
            StageName.SCHEMA: self.schema_error,
            StageName.PREVIEW: self.preview_error,
            StageName.LSP: self.lsp_error,
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
    include_lsp: bool = True
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
            self.include_preview or self.include_lsp
        ):
            return GateMode.ALL
        return self.gate_mode

    def _is_blocking_failure(self, result: FileValidationResult) -> bool:
        if self.effective_gate_mode == GateMode.ALL:
            return not result.is_successful

        preview_status = result.stage_status(StageName.PREVIEW, enabled=self.include_preview)
        lsp_status = result.stage_status(StageName.LSP, enabled=self.include_lsp)
        blocking_statuses = {StageStatus.FAILED, StageStatus.ERROR}
        return (preview_status in blocking_statuses) or (lsp_status in blocking_statuses)


@dataclass(slots=True)
class ValidationOptions:
    """Execution options used when running a validation pass."""

    include_lint: bool = False
    include_schema: bool = False
    include_preview: bool = True
    include_lsp: bool = True
    gate_mode: GateMode = GateMode.AUTHORITATIVE
    fail_fast: bool = False
