"""Collect YAML files that should be validated."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Literal, Sequence

HiddenMode = Literal["common", "all", "none"]
VALID_HIDDEN_MODES = frozenset({"common", "all", "none"})

ALWAYS_EXCLUDED_DIRS = frozenset({".git", ".github"})
COMMON_HIDDEN_DIRS = frozenset(
    {
        ".azure-pipelines",
        ".azure-pipeline",
        ".azure-pipelines-templates",
        ".azure-pipeline-templates",
        ".azure_pipelines",
        ".azure_pipeline",
        ".azure_pipeline_templates",
        ".azure",
        ".azure-devops-pipelines",
        ".azuredevops-pipelines",
        ".azure_devops",
        ".azure_devops_pipelines",
        ".devops",
        ".devops-pipelines",
        ".devops-pipeline",
        ".devops-templates",
        ".devops-ci",
        ".devops-cicd",
        ".ado",
        ".ado-pipelines",
        ".ado-pipeline",
        ".ado-templates",
        ".azdo",
        ".azdo-pipelines",
        ".azdo-pipeline",
        ".azdo-templates",
        ".azuredevops",
        ".azure-devops",
        ".azpipelines",
        ".azp",
        ".azp-pipelines",
        ".azp-templates",
        ".pipelines",
        ".pipeline",
        ".pipelines-templates",
        ".pipeline-templates",
        ".release-pipelines",
        ".build-pipelines",
        ".ci",
        ".cicd",
        ".ci-cd",
    }
)


class FileScanner:
    """Responsible for producing the list of YAML files to validate."""

    def __init__(
        self,
        repo_root: Path,
        include_patterns: Sequence[str] | None = None,
        hidden_mode: HiddenMode = "common",
    ) -> None:
        """Initialize the file scanner.

        Args:
            repo_root: Repository root used to resolve relative targets.
            include_patterns: Optional glob patterns used for YAML discovery.
            hidden_mode: Hidden directory behavior (common, all, none).
        """
        if hidden_mode not in VALID_HIDDEN_MODES:
            raise ValueError(
                f"hidden_mode must be one of: common, all, none (received: {hidden_mode!r})."
            )

        self.repo_root = repo_root
        self.include_patterns = include_patterns or ("**/*.yml", "**/*.yaml")
        self.hidden_mode = hidden_mode

    def collect(self, target: Path) -> tuple[Path, ...]:
        """Return every YAML file beneath *target* (or the file itself)."""
        resolved_target = self._resolve_target(target)
        if resolved_target.is_file():
            return (resolved_target,)
        if not resolved_target.exists():
            raise FileNotFoundError(resolved_target)
        if self.hidden_mode == "none" and self._is_explicit_hidden_target(resolved_target):
            return tuple()

        collected = self._collect_yaml_files(resolved_target)

        seen: set[Path] = set()
        ordered: list[Path] = []
        for path in sorted(collected):
            normalized = path.resolve()
            if normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return tuple(ordered)

    def _resolve_target(self, candidate: Path) -> Path:
        """Resolve a candidate path as absolute."""
        if candidate.is_absolute():
            return candidate
        return (self.repo_root / candidate).resolve()

    def _collect_yaml_files(self, root: Path) -> list[Path]:
        explicit_hidden_target = self._is_explicit_hidden_target(root)
        include_matches = self._glob_include_matches(root)
        discovered: list[Path] = []

        for current_root, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current_root)
            dirnames[:] = sorted(
                name
                for name in dirnames
                if self._should_descend_directory(
                    name, explicit_hidden_target=explicit_hidden_target
                )
            )

            for filename in sorted(filenames):
                file_path = current_path / filename
                if file_path.resolve() in include_matches:
                    discovered.append(file_path)

        return discovered

    def _glob_include_matches(self, root: Path) -> set[Path]:
        matches: set[Path] = set()
        for pattern in self.include_patterns:
            for candidate in root.glob(pattern):
                if candidate.is_file():
                    matches.add(candidate.resolve())
        return matches

    def _is_explicit_hidden_target(self, target: Path) -> bool:
        """Return whether the user explicitly targeted a hidden path segment."""
        target_parts = self._parts_relative_to_repo(target)
        return any(part.startswith(".") for part in target_parts)

    def _parts_relative_to_repo(self, path: Path) -> tuple[str, ...]:
        try:
            return path.relative_to(self.repo_root.resolve()).parts
        except ValueError:
            return path.parts

    def _should_descend_directory(self, name: str, *, explicit_hidden_target: bool) -> bool:
        if name in ALWAYS_EXCLUDED_DIRS:
            return False
        if not name.startswith("."):
            return True
        if self.hidden_mode == "all":
            return True
        if self.hidden_mode == "none":
            return False
        if explicit_hidden_target:
            return True
        return name in COMMON_HIDDEN_DIRS


def iter_single_file(path: Path) -> Iterable[Path]:
    """Yield a single file, handy for tests."""
    yield path
