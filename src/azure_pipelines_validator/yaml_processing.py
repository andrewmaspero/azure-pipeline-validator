"""YAML IO helpers for loading, classifying, and wrapping templates.

The helpers in this module normalize source YAML into an internal document
model and optionally wrap templates so they can be validated as runnable
pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from yaml import YAMLError

from .models import YamlKind


@dataclass(slots=True)
class YamlDocument:
    """In-memory representation of a YAML file.

    Attributes:
        path: Filesystem path for the source document.
        content: Raw YAML source text.
        kind: Classified YAML kind used by downstream validators.
    """

    path: Path
    content: str
    kind: YamlKind


class DocumentLoader:
    """Reads YAML files from disk with UTF-8 guarantees."""

    def __init__(self, encoding: str = "utf-8") -> None:
        """Initializes the loader.

        Args:
            encoding: Text encoding used when reading files.
        """
        self.encoding = encoding

    def load(self, path: Path) -> YamlDocument:
        """Loads and classifies a YAML document from disk.

        Args:
            path: Path to the YAML file.

        Returns:
            Parsed document wrapper with file content and detected kind.
        """
        text = path.read_text(encoding=self.encoding)
        kind = classify_document(text, path)
        return YamlDocument(path=path, content=text, kind=kind)


class TemplateWrapper:
    """Wraps templates into runnable pipelines for preview validation.

    The wrapper preserves full pipeline YAML as-is and only synthesizes minimal
    pipeline scaffolding for template-style documents.
    """

    def __init__(self, repo_root: Path | None = None) -> None:
        """Initializes the wrapper.

        Args:
            repo_root: Optional repository root used to compute template paths
                relative to the repo.
        """
        self._repo_root = repo_root.resolve() if repo_root else None

    def wrap(self, document: YamlDocument) -> str:
        """Wraps a YAML document according to its classified kind.

        Args:
            document: YAML document to wrap.

        Returns:
            Either the original pipeline YAML or a generated wrapper pipeline for
            the template kind.
        """
        match document.kind:
            case YamlKind.PIPELINE:
                return document.content
            case YamlKind.STAGES_TEMPLATE:
                return self._wrap_stages(document)
            case YamlKind.JOBS_TEMPLATE:
                return self._wrap_jobs(document)
            case _:
                return self._wrap_steps(document)

    def _template_path(self, document: YamlDocument) -> str:
        """Builds a template path suitable for Azure DevOps template includes.

        Args:
            document: Source document being wrapped.

        Returns:
            Repo-root-relative path prefixed with ``/`` when possible; otherwise
            the document path as POSIX text.
        """
        path = document.path
        if self._repo_root:
            try:
                relative = path.relative_to(self._repo_root).as_posix()
                return f"/{relative}"
            except ValueError:
                pass
        return path.as_posix()

    def _wrap_stages(self, document: YamlDocument) -> str:
        template_path = self._template_path(document)
        parameters_block = self._format_parameters(document, indent="    ")
        parameters_section = f"\n{parameters_block}" if parameters_block else ""
        return (
            f"trigger: none\npr: none\nstages:\n  - template: {template_path}{parameters_section}\n"
        )

    def _wrap_jobs(self, document: YamlDocument) -> str:
        template_path = self._template_path(document)
        parameters_block = self._format_parameters(document, indent="        ")
        parameters_section = f"\n{parameters_block}" if parameters_block else ""
        return (
            "trigger: none\n"
            "pr: none\n"
            "stages:\n"
            "  - stage: Validator\n"
            "    jobs:\n"
            f"      - template: {template_path}{parameters_section}\n"
        )

    def _wrap_steps(self, document: YamlDocument) -> str:
        template_path = self._template_path(document)
        parameters_block = self._format_parameters(document, indent="            ")
        parameters_section = f"\n{parameters_block}" if parameters_block else ""
        return (
            "trigger: none\n"
            "pr: none\n"
            "stages:\n"
            "  - stage: Validator\n"
            "    jobs:\n"
            "      - job: Validator\n"
            "        steps:\n"
            f"          - template: {template_path}{parameters_section}\n"
        )

    def _format_parameters(self, document: YamlDocument, indent: str) -> str | None:
        overrides = self._collect_required_parameters(document)
        if not overrides:
            return None
        dumped_lines = (
            yaml.safe_dump(overrides, default_flow_style=False, sort_keys=False)
            .strip()
            .splitlines()
        )
        values = "\n".join(f"{indent}  {line}" for line in dumped_lines)
        return f"{indent}parameters:\n{values}"

    def _collect_required_parameters(self, document: YamlDocument) -> Mapping[str, Any]:
        try:
            parsed = yaml.safe_load(document.content)
        except YAMLError:
            return {}
        if not isinstance(parsed, Mapping):
            return {}
        raw_parameters = parsed.get("parameters")
        if not isinstance(raw_parameters, list):
            return {}
        overrides: dict[str, Any] = {}
        for entry in raw_parameters:
            if not isinstance(entry, Mapping):
                continue
            name = entry.get("name")
            if not name or not isinstance(name, str):
                continue
            if "default" in entry:
                continue
            param_type = str(entry.get("type", "string")).lower()
            overrides[name] = self._placeholder_value(param_type)
        return overrides

    @staticmethod
    def _placeholder_value(param_type: str) -> Any:
        match param_type:
            case "boolean" | "bool":
                return False
            case "number" | "int" | "integer":
                return 0
            case "object":
                return {
                    "name": "validator-placeholder",
                    "alias": "validatorAlias",
                    "title": "validatorTitle",
                }
            case "array" | "sequence" | "list" | "stringlist":
                return ["validator-placeholder"]
            case "steplist":
                return [{"script": "echo validator-placeholder"}]
            case "joblist":
                return [{"job": "validator", "steps": [{"script": "echo validator-placeholder"}]}]
            case "stagelist":
                return [
                    {
                        "stage": "Validator",
                        "jobs": [
                            {
                                "job": "validator",
                                "steps": [{"script": "echo validator-placeholder"}],
                            }
                        ],
                    }
                ]
            case _:
                return "validator-placeholder"


def classify_document(content: str, path: Path) -> YamlKind:
    """Classifies YAML content as pipeline or template kind.

    Args:
        content: Raw YAML document content.
        path: Source file path, used as a heuristic fallback.

    Returns:
        Detected YAML kind for validation routing.
    """
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
    """Returns whether any candidate key exists in the source sequence.

    Args:
        source: Sequence to search within.
        candidates: Candidate values to match against ``source``.

    Returns:
        ``True`` when at least one candidate is present; otherwise ``False``.
    """
    return any(candidate in source for candidate in candidates)
