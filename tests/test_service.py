from __future__ import annotations

from pathlib import Path

import pytest

from azure_pipelines_validator.exceptions import AzureDevOpsError, LspValidationError
from azure_pipelines_validator.models import (
    FileValidationResult,
    GateMode,
    LspFinding,
    StageName,
    StageStatus,
    ValidationMessage,
    ValidationOptions,
    YamlKind,
)
from azure_pipelines_validator.pipeline_documents import YamlDocument
from azure_pipelines_validator.preview_wrapper import TemplateWrapper
from azure_pipelines_validator.service import ValidationService


class FakeClient:
    def __init__(self, validation_messages=None):
        self.calls = 0
        self.validation_messages = validation_messages or tuple()

    def preview(self, yaml_override: str):
        from azure_pipelines_validator.models import PreviewResponse

        self.calls += 1
        return PreviewResponse(final_yaml="final", validation_results=self.validation_messages)


class FakeScanner:
    def __init__(self, paths):
        self.paths = paths

    def collect(self, target: Path):
        return self.paths


class FakeLoader:
    def __init__(self):
        self.loads = 0

    def load(self, path: Path):
        self.loads += 1
        return YamlDocument(path=path, content="steps: []", kind=YamlKind.STEPS_TEMPLATE)


class FakeYamllintRunner:
    def run(self, path: Path, content: str):
        from azure_pipelines_validator.models import YamllintFinding

        if "fail" in path.name:
            return (
                YamllintFinding(
                    path=path,
                    line=1,
                    column=1,
                    level="error",
                    message="indentation",
                ),
            )
        return tuple()


class FakeSchemaValidator:
    def validate(self, path: Path, content: str):
        from azure_pipelines_validator.models import SchemaFinding

        if "schema" in path.name:
            return (SchemaFinding(path=path, json_pointer="/trigger", message="missing"),)
        return tuple()


def build_service(paths, *, lsp_validator=None):
    client = FakeClient()
    scanner = FakeScanner(paths)
    loader = FakeLoader()
    wrapper = TemplateWrapper()
    service = ValidationService(
        client=client,
        scanner=scanner,
        loader=loader,
        wrapper=wrapper,
        yamllint_runner=FakeYamllintRunner(),
        schema_validator=FakeSchemaValidator(),
        lsp_validator=lsp_validator,
    )
    return service, client


def test_validation_service_runs_all_steps(tmp_path):
    file_paths = (tmp_path / "first.yml", tmp_path / "schema.yml")
    for path in file_paths:
        path.write_text("steps: []", encoding="utf-8")

    service, client = build_service(file_paths)

    summary = service.validate(
        tmp_path,
        ValidationOptions(include_lint=True, include_schema=True, gate_mode=GateMode.ALL),
    )

    assert summary.total_files == 2
    assert client.calls == 2
    assert not summary.success


def test_validation_service_scopes_preview_to_target_file(tmp_path: Path) -> None:
    main = tmp_path / "azure-pipelines.yml"
    secondary = tmp_path / "templates" / "steps.yml"
    secondary.parent.mkdir(parents=True)
    main.write_text("trigger: none\n", encoding="utf-8")
    secondary.write_text("steps: []\n", encoding="utf-8")

    service, client = build_service((main, secondary))

    summary = service.validate(
        tmp_path,
        ValidationOptions(
            include_lint=False,
            include_schema=False,
            include_preview=True,
            include_lsp=False,
            preview_target_path=main.resolve(),
        ),
    )

    assert client.calls == 1
    assert summary.results[0].path == main
    assert summary.results[0].preview_ran is True
    assert summary.results[1].path == secondary
    assert summary.results[1].preview_ran is False
    assert summary.results[1].stage_status(StageName.PREVIEW, enabled=True) == StageStatus.SKIPPED


def test_validation_service_fail_fast(tmp_path):
    file_one = tmp_path / "fail.yml"
    file_two = tmp_path / "later.yml"
    for path in (file_one, file_two):
        path.write_text("steps: []", encoding="utf-8")

    service, _ = build_service((file_one, file_two))

    summary = service.validate(
        tmp_path,
        ValidationOptions(include_lint=True, fail_fast=True),
    )

    assert summary.total_files == 1


def test_validation_service_preview_requires_client(tmp_path: Path) -> None:
    target = tmp_path / "preview.yml"
    target.write_text("steps: []", encoding="utf-8")
    scanner = FakeScanner((target,))
    loader = FakeLoader()
    service = ValidationService(
        client=None,
        scanner=scanner,
        loader=loader,
        wrapper=TemplateWrapper(),
    )

    with pytest.raises(RuntimeError, match="Azure DevOps client"):
        service.validate(target, ValidationOptions(include_lint=False, include_schema=False))


def test_validation_service_preview_error_reraises_when_fail_fast(tmp_path: Path) -> None:
    target = tmp_path / "preview.yml"
    target.write_text("steps: []", encoding="utf-8")

    class ErrorClient:
        def preview(self, yaml_override: str):
            raise AzureDevOpsError(500, "preview failed")

    service = ValidationService(
        client=ErrorClient(),
        scanner=FakeScanner((target,)),
        loader=FakeLoader(),
        wrapper=TemplateWrapper(),
    )

    with pytest.raises(AzureDevOpsError, match="preview failed"):
        service.validate(
            target,
            ValidationOptions(
                include_lint=False,
                include_schema=False,
                include_preview=True,
                include_lsp=False,
                fail_fast=True,
            ),
        )


def test_validation_service_collects_preview_messages_and_lsp_findings(tmp_path: Path) -> None:
    target = tmp_path / "preview.yml"
    target.write_text("steps: []", encoding="utf-8")
    client = FakeClient(
        validation_messages=(ValidationMessage(message="bad template", messageLevel="error"),)
    )

    class FakeLspValidator:
        def run(self, documents):
            document = documents[0]
            return {
                document.path: (
                    LspFinding(
                        path=document.path,
                        line=1,
                        column=1,
                        severity="error",
                        message="lsp diagnostic",
                    ),
                )
            }

    service = ValidationService(
        client=client,
        scanner=FakeScanner((target,)),
        loader=FakeLoader(),
        wrapper=TemplateWrapper(),
        yamllint_runner=None,
        schema_validator=None,
        lsp_validator=FakeLspValidator(),
    )

    summary = service.validate(target, ValidationOptions(include_schema=False))

    assert summary.total_files == 1
    assert summary.results[0].preview[0].message == "bad template"
    assert summary.results[0].preview[0].level == "error"
    assert summary.results[0].lsp[0].message == "lsp diagnostic"


def test_validation_service_adds_schema_deprecation_warning(tmp_path: Path) -> None:
    target = tmp_path / "pipeline.yml"
    target.write_text("steps: []", encoding="utf-8")
    service, _ = build_service((target,))

    summary = service.validate(
        target,
        ValidationOptions(include_lint=False, include_schema=True),
    )

    assert any("Schema stage is deprecated" in warning for warning in summary.warnings)


def test_validation_service_warns_when_authoritative_gate_falls_back_to_all(
    tmp_path: Path,
) -> None:
    target = tmp_path / "fail.yml"
    target.write_text("steps: []", encoding="utf-8")
    service, _ = build_service((target,))

    summary = service.validate(
        target,
        ValidationOptions(
            include_lint=True,
            include_schema=False,
            include_preview=False,
            include_lsp=False,
            gate_mode=GateMode.AUTHORITATIVE,
        ),
    )

    assert summary.effective_gate_mode == GateMode.ALL
    assert any("falling back to 'all'" in warning for warning in summary.warnings)
    assert summary.failing_files == 1


def test_file_validation_result_not_successful_when_stage_error_flag_set(tmp_path: Path) -> None:
    target = tmp_path / "pipeline.yml"
    target.write_text("steps: []", encoding="utf-8")

    result = FileValidationResult(
        path=target,
        yamllint=tuple(),
        schema=tuple(),
        preview=tuple(),
        lsp=tuple(),
        final_yaml=None,
        preview_error=True,
    )

    assert result.is_successful is False


def test_validation_service_fail_fast_stops_before_extra_lsp_runs(tmp_path: Path) -> None:
    file_one = tmp_path / "fail.yml"
    file_two = tmp_path / "later.yml"
    for path in (file_one, file_two):
        path.write_text("steps: []", encoding="utf-8")

    class CountingLspValidator:
        def __init__(self) -> None:
            self.calls = 0
            self.document_names: list[str] = []

        def run(self, documents):
            self.calls += 1
            self.document_names.extend(document.path.name for document in documents)
            return {document.path: tuple() for document in documents}

    lsp_validator = CountingLspValidator()
    service, _ = build_service((file_one, file_two), lsp_validator=lsp_validator)

    summary = service.validate(
        tmp_path,
        ValidationOptions(include_lint=True, include_lsp=True, fail_fast=True),
    )

    assert summary.total_files == 1
    assert lsp_validator.calls == 1
    assert lsp_validator.document_names == ["fail.yml"]


def test_validation_service_records_lsp_error_without_aborting(tmp_path: Path) -> None:
    target = tmp_path / "pipeline.yml"
    target.write_text("steps: []", encoding="utf-8")

    class RaisingLspValidator:
        def run(self, documents):
            raise LspValidationError("lsp unavailable")

    service, _ = build_service((target,), lsp_validator=RaisingLspValidator())

    summary = service.validate(
        target,
        ValidationOptions(include_lint=False, include_schema=False, include_preview=False),
    )

    assert summary.total_files == 1
    assert summary.results[0].lsp_error is True
    assert summary.results[0].lsp[0].message == "lsp unavailable"


def test_validation_service_reraises_lsp_error_when_fail_fast(tmp_path: Path) -> None:
    target = tmp_path / "pipeline.yml"
    target.write_text("steps: []", encoding="utf-8")

    class RaisingLspValidator:
        def run(self, documents):
            raise LspValidationError("lsp unavailable")

    service, _ = build_service((target,), lsp_validator=RaisingLspValidator())

    with pytest.raises(LspValidationError, match="lsp unavailable"):
        service.validate(
            target,
            ValidationOptions(
                include_lint=False,
                include_schema=False,
                include_preview=False,
                fail_fast=True,
            ),
        )
