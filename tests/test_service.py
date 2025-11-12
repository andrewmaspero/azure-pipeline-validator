from __future__ import annotations

from pathlib import Path

from azure_pipelines_validator.models import (
    ValidationOptions,
    YamlKind,
)
from azure_pipelines_validator.service import ValidationService
from azure_pipelines_validator.yaml_processing import TemplateWrapper, YamlDocument


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


def build_service(paths):
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
    )
    return service, client


def test_validation_service_runs_all_steps(tmp_path):
    file_paths = (tmp_path / "first.yml", tmp_path / "schema.yml")
    for path in file_paths:
        path.write_text("steps: []", encoding="utf-8")

    service, client = build_service(file_paths)

    summary = service.validate(tmp_path, ValidationOptions())

    assert summary.total_files == 2
    assert client.calls == 2
    assert not summary.success


def test_validation_service_fail_fast(tmp_path):
    file_one = tmp_path / "fail.yml"
    file_two = tmp_path / "later.yml"
    for path in (file_one, file_two):
        path.write_text("steps: []", encoding="utf-8")

    service, _ = build_service((file_one, file_two))

    summary = service.validate(tmp_path, ValidationOptions(fail_fast=True))

    assert summary.total_files == 1
