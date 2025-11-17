from __future__ import annotations

from pathlib import Path

import pytest

from azure_pipelines_validator.file_scanner import FileScanner


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


def test_exclude_directory(tmp_path: Path) -> None:
    included_dir = tmp_path / "keep"
    included_dir.mkdir()
    included_file = included_dir / "keep.yml"
    included_file.write_text("jobs: []", encoding="utf-8")
    excluded_dir = tmp_path / "skip"
    excluded_dir.mkdir()
    excluded_file = excluded_dir / "skip.yml"
    excluded_file.write_text("jobs: []", encoding="utf-8")

    scanner = FileScanner(tmp_path, exclude_patterns=("skip",))

    collected = scanner.collect(tmp_path)

    assert collected == (included_file.resolve(),)


def test_exclude_glob_pattern(tmp_path: Path) -> None:
    keep = tmp_path / "nested" / "ok" / "pipe.yml"
    keep.parent.mkdir(parents=True)
    keep.write_text("jobs: []", encoding="utf-8")
    skip = tmp_path / "nested" / "generated" / "auto.yml"
    skip.parent.mkdir(parents=True)
    skip.write_text("jobs: []", encoding="utf-8")

    scanner = FileScanner(tmp_path, exclude_patterns=("**/generated/*.yml",))

    collected = scanner.collect(tmp_path)

    assert collected == (keep.resolve(),)
