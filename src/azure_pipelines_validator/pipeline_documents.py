"""YAML document loading and classification helpers.

This module normalizes source YAML into an internal document model used by the
validation engines.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

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
