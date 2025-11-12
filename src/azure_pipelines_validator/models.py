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


@dataclass(slots=True)
class YamllintFinding:
    path: Path
    line: int
    column: int
    level: str
    message: str


@dataclass(slots=True)
class SchemaFinding:
    path: Path
    json_pointer: str
    message: str


@dataclass(slots=True)
class PreviewFinding:
    path: Path
    message: str
    level: str | None


@dataclass(slots=True)
class FileValidationResult:
    path: Path
    yamllint: Sequence[YamllintFinding]
    schema: Sequence[SchemaFinding]
    preview: Sequence[PreviewFinding]
    final_yaml: str | None

    @property
    def is_successful(self) -> bool:
        return not any((self.yamllint, self.schema, self.preview))


@dataclass(slots=True)
class ValidationSummary:
    results: Sequence[FileValidationResult]

    @property
    def success(self) -> bool:
        return all(result.is_successful for result in self.results)

    @property
    def total_files(self) -> int:
        return len(self.results)

    @property
    def failing_files(self) -> int:
        return sum(1 for result in self.results if not result.is_successful)


@dataclass(slots=True)
class ValidationOptions:
    include_lint: bool = True
    include_schema: bool = True
    include_preview: bool = True
    fail_fast: bool = False
