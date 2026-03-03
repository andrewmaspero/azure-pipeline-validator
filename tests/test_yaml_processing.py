from __future__ import annotations

from pathlib import Path

from azure_pipelines_validator.models import YamlKind
from azure_pipelines_validator.yaml_processing import (
    DocumentLoader,
    TemplateWrapper,
    YamlDocument,
    classify_document,
)


def test_classify_document_detects_pipeline() -> None:
    content = """\ntrigger: none\nresources:\n  repositories: []\n""".strip()
    path = Path("pipeline.yml")

    kind = classify_document(content, path)

    assert kind == YamlKind.PIPELINE


def test_classify_document_uses_path_segments() -> None:
    path = Path("common/stages/deploy.yml")

    kind = classify_document("", path)

    assert kind == YamlKind.STAGES_TEMPLATE


def test_document_loader_detects_kind(tmp_path: Path) -> None:
    file_path = tmp_path / "templates" / "steps" / "deploy.yml"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("steps:\n- script: echo hi\n", encoding="utf-8")

    loader = DocumentLoader()
    document = loader.load(file_path)

    assert document.kind == YamlKind.STEPS_TEMPLATE
    assert document.path == file_path


def test_template_wrapper_variants(tmp_path: Path) -> None:
    wrapper = TemplateWrapper(repo_root=tmp_path)

    stages_document = YamlDocument(
        path=tmp_path / "stages/deploy.yml",
        content="stages: []",
        kind=YamlKind.STAGES_TEMPLATE,
    )
    jobs_document = YamlDocument(
        path=tmp_path / "jobs/build.yml",
        content="jobs: []",
        kind=YamlKind.JOBS_TEMPLATE,
    )
    steps_document = YamlDocument(
        path=tmp_path / "steps/lint.yml",
        content="steps: []",
        kind=YamlKind.STEPS_TEMPLATE,
    )

    stages_wrapped = wrapper.wrap(stages_document)
    jobs_wrapped = wrapper.wrap(jobs_document)
    steps_wrapped = wrapper.wrap(steps_document)

    assert "template: /stages/deploy.yml" in stages_wrapped
    assert "jobs:" in jobs_wrapped and "template: /jobs/build.yml" in jobs_wrapped
    assert "steps:" in steps_wrapped and "template: /steps/lint.yml" in steps_wrapped


def test_template_wrapper_injects_parameter_placeholders(tmp_path: Path) -> None:
    wrapper = TemplateWrapper(repo_root=tmp_path)

    document = YamlDocument(
        path=tmp_path / "jobs/apply.yml",
        content=(
            "parameters:\n  - name: imageName\n  - name: enableScan\n    type: boolean\njobs: []\n"
        ),
        kind=YamlKind.JOBS_TEMPLATE,
    )

    wrapped = wrapper.wrap(document)

    assert "template: /jobs/apply.yml" in wrapped
    assert "parameters:" in wrapped
    assert "imageName: validator-placeholder" in wrapped
    assert "enableScan: false" in wrapped


def test_template_wrapper_uses_non_empty_array_placeholders(tmp_path: Path) -> None:
    wrapper = TemplateWrapper(repo_root=tmp_path)

    document = YamlDocument(
        path=tmp_path / "jobs/build.yml",
        content=("parameters:\n  - name: repositories\n    type: array\njobs: []\n"),
        kind=YamlKind.JOBS_TEMPLATE,
    )

    wrapped = wrapper.wrap(document)

    assert "repositories:" in wrapped
    assert "- validator-placeholder" in wrapped


def test_template_wrapper_uses_absolute_path_when_outside_repo_root(tmp_path: Path) -> None:
    wrapper = TemplateWrapper(repo_root=tmp_path)
    external = tmp_path.parent / "external.yml"
    document = YamlDocument(path=external, content="steps: []", kind=YamlKind.STEPS_TEMPLATE)

    wrapped = wrapper.wrap(document)

    assert f"template: {external.as_posix()}" in wrapped


def test_collect_required_parameters_handles_invalid_shapes(tmp_path: Path) -> None:
    wrapper = TemplateWrapper(repo_root=tmp_path)

    invalid_yaml = YamlDocument(
        path=tmp_path / "invalid.yml",
        content="[",
        kind=YamlKind.STEPS_TEMPLATE,
    )
    assert wrapper._collect_required_parameters(invalid_yaml) == {}

    non_mapping = YamlDocument(
        path=tmp_path / "list.yml",
        content="- item",
        kind=YamlKind.STEPS_TEMPLATE,
    )
    assert wrapper._collect_required_parameters(non_mapping) == {}

    mixed_parameters = YamlDocument(
        path=tmp_path / "params.yml",
        content=(
            "parameters:\n"
            "  - not-a-map\n"
            "  - name: 123\n"
            "  - name: withDefault\n"
            "    default: value\n"
            "  - name: requiredParam\n"
            "    type: string\n"
        ),
        kind=YamlKind.STEPS_TEMPLATE,
    )
    assert wrapper._collect_required_parameters(mixed_parameters) == {
        "requiredParam": "validator-placeholder"
    }


def test_placeholder_value_variants() -> None:
    assert TemplateWrapper._placeholder_value("number") == 0
    assert TemplateWrapper._placeholder_value("object") == {
        "name": "validator-placeholder",
        "alias": "validatorAlias",
        "title": "validatorTitle",
    }
    assert TemplateWrapper._placeholder_value("steplist") == [
        {"script": "echo validator-placeholder"}
    ]
    assert TemplateWrapper._placeholder_value("joblist") == [
        {"job": "validator", "steps": [{"script": "echo validator-placeholder"}]}
    ]
    assert TemplateWrapper._placeholder_value("stagelist") == [
        {
            "stage": "Validator",
            "jobs": [{"job": "validator", "steps": [{"script": "echo validator-placeholder"}]}],
        }
    ]


def test_classify_document_covers_remaining_branches() -> None:
    assert classify_document("[", Path("broken.yml")) == YamlKind.RAW
    assert classify_document("jobs: []", Path("template.yml")) == YamlKind.JOBS_TEMPLATE
    assert classify_document("steps: []", Path("template.yml")) == YamlKind.STEPS_TEMPLATE
    assert classify_document("{}", Path("ci/jobs/template.yml")) == YamlKind.JOBS_TEMPLATE
    assert classify_document("{}", Path("ci/steps/template.yml")) == YamlKind.STEPS_TEMPLATE
    assert classify_document("{}", Path("ci/misc/template.yml")) == YamlKind.STEPS_TEMPLATE
