"""Pipeline ID auto-resolution helpers for Azure DevOps context."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .context_detection import DetectionSource
from .models import PipelineSummary

DEFAULT_CACHE_TTL_SECONDS = 300
DEFAULT_CONTEXT_CACHE_DIR = Path.home() / ".azure-pipeline-validator" / "context"


@dataclass(frozen=True, slots=True)
class PipelineResolution:
    """Resolved pipeline selection payload."""

    pipeline_id: int
    source: DetectionSource
    candidates: Sequence[PipelineSummary]


def select_pipeline_candidates(
    *,
    repo_name: str | None,
    name_hint: str | None,
    all_pipelines: Sequence[PipelineSummary],
) -> list[PipelineSummary]:
    """Rank candidate pipelines using repo and optional name hints.

    Args:
        repo_name: Repository name hint.
        name_hint: Optional pipeline name hint.
        all_pipelines: Full pipeline list from Azure DevOps.

    Returns:
        Sorted candidate list.
    """
    hint = (name_hint or "").strip().lower()
    repo = (repo_name or "").strip().lower()

    scored: list[tuple[int, PipelineSummary]] = []
    for pipeline in all_pipelines:
        score = 0
        if pipeline.repository_name and repo and pipeline.repository_name.lower() == repo:
            score += 50
        if repo and repo in pipeline.name.lower():
            score += 20
        if hint and hint in pipeline.name.lower():
            score += 30
        if hint and pipeline.name.lower() == hint:
            score += 40
        if score > 0:
            scored.append((score, pipeline))

    if not scored:
        return list(all_pipelines)
    scored.sort(key=lambda item: (-item[0], item[1].name.lower(), item[1].id))
    return [pipeline for _, pipeline in scored]


def load_cached_pipeline_id(
    *,
    org: str,
    project: str,
    repo: str,
    cache_dir: Path | None = None,
    ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> int | None:
    """Load cached pipeline ID for the ``(org, project, repo)`` key.

    Args:
        org: Azure DevOps organization.
        project: Azure DevOps project.
        repo: Azure DevOps repository.
        cache_dir: Optional cache directory override.
        ttl_seconds: Maximum age for cached data.

    Returns:
        Cached pipeline ID when present and fresh, otherwise ``None``.
    """
    resolved_cache_dir = cache_dir or _resolve_cache_dir()
    cache_file = resolved_cache_dir / "pipeline-selection-cache.json"
    if not cache_file.exists():
        return None
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    key = _cache_key(org=org, project=project, repo=repo)
    item = payload.get(key)
    if not isinstance(item, dict):
        return None
    timestamp = item.get("timestamp")
    pipeline_id = item.get("pipeline_id")
    if not isinstance(timestamp, (int, float)) or not isinstance(pipeline_id, int):
        return None
    if int(ttl_seconds) <= 0:
        return None
    if time.time() - float(timestamp) > int(ttl_seconds):
        return None
    return pipeline_id


def save_cached_pipeline_id(
    *,
    org: str,
    project: str,
    repo: str,
    pipeline_id: int,
    cache_dir: Path | None = None,
) -> None:
    """Persist selected pipeline ID for future local auto-resolution.

    Args:
        org: Azure DevOps organization.
        project: Azure DevOps project.
        repo: Azure DevOps repository.
        pipeline_id: Selected pipeline ID.
        cache_dir: Optional cache directory override.
    """
    resolved_cache_dir = cache_dir or _resolve_cache_dir()
    resolved_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = resolved_cache_dir / "pipeline-selection-cache.json"
    existing: dict[str, object] = {}
    if cache_file.exists():
        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                existing = payload
        except (OSError, json.JSONDecodeError):
            existing = {}
    key = _cache_key(org=org, project=project, repo=repo)
    existing[key] = {"pipeline_id": int(pipeline_id), "timestamp": time.time()}
    cache_file.write_text(json.dumps(existing, sort_keys=True), encoding="utf-8")


def _cache_key(*, org: str, project: str, repo: str) -> str:
    """Build cache key for a repository-scoped pipeline entry.

    Args:
        org: Organization value.
        project: Project value.
        repo: Repository value.

    Returns:
        Lowercase composite cache key.
    """
    return f"{org.strip().lower()}::{project.strip().lower()}::{repo.strip().lower()}"


def _resolve_cache_dir() -> Path:
    """Resolve context cache directory from environment configuration.

    Returns:
        Cache directory path for context artifacts.
    """
    raw = os.getenv("AZP_VALIDATOR_CONTEXT_CACHE_DIR", "").strip()
    if not raw:
        return DEFAULT_CONTEXT_CACHE_DIR
    return Path(raw).expanduser().resolve()
