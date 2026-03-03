from __future__ import annotations

from pathlib import Path

import pytest

from azure_pipelines_validator.file_scanner import FileScanner, iter_single_file


def test_collects_all_yaml_files(tmp_path: Path) -> None:
    (tmp_path / "visible").mkdir()
    file_one = tmp_path / "visible" / "pipe.yml"
    file_one.write_text("stages: []", encoding="utf-8")
    file_two = tmp_path / "visible" / "another.yaml"
    file_two.write_text("jobs: []", encoding="utf-8")
    hidden_dir = tmp_path / ".ignored"
    hidden_dir.mkdir()
    (hidden_dir / "skip.yml").write_text("steps: []", encoding="utf-8")

    scanner = FileScanner(tmp_path)

    collected = scanner.collect(tmp_path)

    assert collected == (file_two.resolve(), file_one.resolve())


def test_collect_accepts_single_file(tmp_path: Path) -> None:
    yaml_file = tmp_path / "single.yml"
    yaml_file.write_text("trigger: none", encoding="utf-8")

    scanner = FileScanner(tmp_path)

    collected = scanner.collect(yaml_file)

    assert collected == (yaml_file.resolve(),)


def test_collect_missing_path(tmp_path: Path) -> None:
    scanner = FileScanner(tmp_path)
    missing = tmp_path / "missing"

    with pytest.raises(FileNotFoundError):
        scanner.collect(missing)


def test_collect_resolves_relative_target_and_deduplicates(tmp_path: Path) -> None:
    nested = tmp_path / "pipelines"
    nested.mkdir()
    yaml_file = nested / "ci.yml"
    yaml_file.write_text("steps: []", encoding="utf-8")

    scanner = FileScanner(tmp_path, include_patterns=("**/*.yml", "**/*.yml"))

    collected = scanner.collect(Path("pipelines"))

    assert collected == (yaml_file.resolve(),)


def test_candidate_excludes_non_files_and_excluded_dirs(tmp_path: Path) -> None:
    directory = tmp_path / "folder"
    directory.mkdir()
    assert FileScanner._is_candidate(directory) is False

    github_file = tmp_path / ".github" / "workflow.yml"
    github_file.parent.mkdir()
    github_file.write_text("name: test", encoding="utf-8")
    assert FileScanner._is_candidate(github_file) is False


def test_iter_single_file_yields_path(tmp_path: Path) -> None:
    target = tmp_path / "single.yml"
    target.write_text("trigger: none", encoding="utf-8")

    assert tuple(iter_single_file(target)) == (target,)
