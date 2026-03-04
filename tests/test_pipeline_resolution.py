from __future__ import annotations

from pathlib import Path

from azure_pipelines_validator.models import PipelineSummary
from azure_pipelines_validator.pipeline_resolution import (
    load_cached_pipeline_id,
    save_cached_pipeline_id,
    select_pipeline_candidates,
)


def _pipeline(
    pipeline_id: int,
    name: str,
    repository_name: str | None = None,
) -> PipelineSummary:
    return PipelineSummary(
        id=pipeline_id,
        name=name,
        folder=None,
        url=None,
        repository_name=repository_name,
        repository_id=None,
        default_branch=None,
    )


def test_select_pipeline_candidates_prefers_repo_and_hint() -> None:
    candidates = select_pipeline_candidates(
        repo_name="transcription-stack-deployment",
        name_hint="orchestrator",
        all_pipelines=[
            _pipeline(1, "lint"),
            _pipeline(2, "build-orchestrator", repository_name="transcription-stack-deployment"),
            _pipeline(3, "transcription-ci"),
        ],
    )
    assert candidates[0].id == 2


def test_cache_roundtrip(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    save_cached_pipeline_id(
        org="acme",
        project="demo",
        repo="repo",
        pipeline_id=42,
        cache_dir=cache_dir,
    )
    assert (
        load_cached_pipeline_id(
            org="acme",
            project="demo",
            repo="repo",
            cache_dir=cache_dir,
            ttl_seconds=300,
        )
        == 42
    )


def test_cache_expiry(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    save_cached_pipeline_id(
        org="acme",
        project="demo",
        repo="repo",
        pipeline_id=42,
        cache_dir=cache_dir,
    )
    assert (
        load_cached_pipeline_id(
            org="acme",
            project="demo",
            repo="repo",
            cache_dir=cache_dir,
            ttl_seconds=0,
        )
        is None
    )
