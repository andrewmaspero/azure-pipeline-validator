"""Collect YAML files that should be validated."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence


class FileScanner:
    """Responsible for producing the list of YAML files to validate."""

    def __init__(
        self,
        repo_root: Path,
        include_patterns: Sequence[str] | None = None,
        exclude_patterns: Sequence[str] | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.include_patterns = include_patterns or ("**/*.yml", "**/*.yaml")
        self.exclude_patterns = tuple(str(pattern) for pattern in (exclude_patterns or ()))

    def collect(self, target: Path) -> tuple[Path, ...]:
        """Return every YAML file beneath *target* (or the file itself)."""

        resolved_target = self._resolve_target(target)
        if resolved_target.is_file():
            return (resolved_target,)
        if not resolved_target.exists():
            raise FileNotFoundError(resolved_target)

        collected: list[Path] = []
        for pattern in self.include_patterns:
            collected.extend(
                path for path in resolved_target.glob(pattern) if self._is_candidate(path)
            )

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
        if candidate.is_absolute():
            return candidate
        return (self.repo_root / candidate).resolve()

    def _is_candidate(self, path: Path) -> bool:
        if not path.is_file():
            return False
        excluded_dirs = {".git", ".github", "azure-pipeline-validator"}
        allowed_hidden = {".azure-pipelines"}
        for part in path.parts:
            if part in excluded_dirs:
                return False
            if part.startswith(".") and part not in allowed_hidden:
                return False
        if self._matches_exclude(path):
            return False
        return True

    def _matches_exclude(self, path: Path) -> bool:
        if not self.exclude_patterns:
            return False
        relative = self._relative_to_repo(path)
        for pattern in self.exclude_patterns:
            pattern_path = Path(pattern)
            if self._matches_glob(relative, pattern):
                return True
            if relative == pattern_path:
                return True
            if self._is_relative_to(relative, pattern_path):
                return True
        return False

    @staticmethod
    def _matches_glob(path: Path, pattern: str) -> bool:
        special_chars = {"*", "?", "[", "]"}
        if not any(char in pattern for char in special_chars):
            return False
        return path.match(pattern)

    def _relative_to_repo(self, path: Path) -> Path:
        try:
            return path.resolve().relative_to(self.repo_root)
        except ValueError:
            return path.resolve()

    @staticmethod
    def _is_relative_to(path: Path, parent: Path) -> bool:
        try:
            return path.is_relative_to(parent)
        except AttributeError:  # pragma: no cover - Py<3.9 compatibility guard
            try:
                path.relative_to(parent)
                return True
            except ValueError:
                return False


def iter_single_file(path: Path) -> Iterable[Path]:
    """Yield a single file, handy for tests."""

    yield path
