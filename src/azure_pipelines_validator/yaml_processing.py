"""YAML IO helpers: loading, classifying, and wrapping."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import yaml
from yaml import YAMLError

from .models import YamlKind


@dataclass(slots=True)
class YamlDocument:
    """In-memory representation of a YAML file."""

    path: Path
    content: str
    kind: YamlKind


class DocumentLoader:
    """Reads YAML files from disk with UTF-8 guarantees."""

    def __init__(self, encoding: str = "utf-8") -> None:
        self.encoding = encoding

    def load(self, path: Path) -> YamlDocument:
        text = path.read_text(encoding=self.encoding)
        kind = classify_document(text, path)
        return YamlDocument(path=path, content=text, kind=kind)


class TemplateWrapper:
    """Wrap templates into runnable pipelines for preview validation."""

    def wrap(self, document: YamlDocument) -> str:
        match document.kind:
            case YamlKind.PIPELINE:
                return document.content
            case YamlKind.STAGES_TEMPLATE:
                return self._wrap_stages(document)
            case YamlKind.JOBS_TEMPLATE:
                return self._wrap_jobs(document)
            case _:
                return self._wrap_steps(document)

    @staticmethod
    def _wrap_stages(document: YamlDocument) -> str:
        template_path = document.path.as_posix()
        return f"trigger: none\npr: none\nstages:\n  - template: {template_path}\n"

    @staticmethod
    def _wrap_jobs(document: YamlDocument) -> str:
        template_path = document.path.as_posix()
        return (
            "trigger: none\n"
            "pr: none\n"
            "stages:\n"
            "  - stage: Validator\n"
            "    jobs:\n"
            f"      - template: {template_path}\n"
        )

    @staticmethod
    def _wrap_steps(document: YamlDocument) -> str:
        template_path = document.path.as_posix()
        return (
            "trigger: none\n"
            "pr: none\n"
            "stages:\n"
            "  - stage: Validator\n"
            "    jobs:\n"
            "      - job: Validator\n"
            "        steps:\n"
            f"          - template: {template_path}\n"
        )


def classify_document(content: str, path: Path) -> YamlKind:
    """Best-effort detection of YAML template type."""

    try:
        parsed = yaml.safe_load(content)
    except YAMLError:
        return YamlKind.RAW

    if isinstance(parsed, Mapping):
        key_names = tuple(str(name) for name in parsed.keys())
        if _contains_any(key_names, ("extends", "trigger", "pr", "resources")):
            return YamlKind.PIPELINE
        if "stages" in key_names:
            return YamlKind.STAGES_TEMPLATE
        if "jobs" in key_names:
            return YamlKind.JOBS_TEMPLATE
        if "steps" in key_names:
            return YamlKind.STEPS_TEMPLATE

    lowered_parts = tuple(segment.lower() for segment in path.parts)
    if "stages" in lowered_parts:
        return YamlKind.STAGES_TEMPLATE
    if "jobs" in lowered_parts:
        return YamlKind.JOBS_TEMPLATE
    if "steps" in lowered_parts:
        return YamlKind.STEPS_TEMPLATE
    return YamlKind.STEPS_TEMPLATE


def _contains_any(source: Sequence[str], candidates: Sequence[str]) -> bool:
    return any(candidate in source for candidate in candidates)
