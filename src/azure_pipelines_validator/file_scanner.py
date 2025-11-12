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
    ) -> None:
        self.repo_root = repo_root
        self.include_patterns = include_patterns or ("**/*.yml", "**/*.yaml")

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

    @staticmethod
    def _is_candidate(path: Path) -> bool:
        return path.is_file() and not any(part.startswith(".") for part in path.parts)


def iter_single_file(path: Path) -> Iterable[Path]:
    """Yield a single file, handy for tests."""

    yield path
