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


def test_template_wrapper_variants() -> None:
    wrapper = TemplateWrapper()

    stages_document = YamlDocument(
        path=Path("stages/deploy.yml"),
        content="stages: []",
        kind=YamlKind.STAGES_TEMPLATE,
    )
    jobs_document = YamlDocument(
        path=Path("jobs/build.yml"),
        content="jobs: []",
        kind=YamlKind.JOBS_TEMPLATE,
    )
    steps_document = YamlDocument(
        path=Path("steps/lint.yml"),
        content="steps: []",
        kind=YamlKind.STEPS_TEMPLATE,
    )

    stages_wrapped = wrapper.wrap(stages_document)
    jobs_wrapped = wrapper.wrap(jobs_document)
    steps_wrapped = wrapper.wrap(steps_document)

    assert "template: stages/deploy.yml" in stages_wrapped
    assert "jobs:" in jobs_wrapped and "template: jobs/build.yml" in jobs_wrapped
    assert "steps:" in steps_wrapped and "template: steps/lint.yml" in steps_wrapped
