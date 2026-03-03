from __future__ import annotations

from pathlib import Path

import pytest

from azure_pipelines_validator.file_scanner import (
    COMMON_HIDDEN_DIRS,
    FileScanner,
    iter_single_file,
)


def test_collect_common_mode_includes_common_hidden_dirs(tmp_path: Path) -> None:
    (tmp_path / ".azure-pipelines").mkdir()
    (tmp_path / ".azure-pipelines" / "ci.yml").write_text("steps: []", encoding="utf-8")
    (tmp_path / ".azure").mkdir()
    (tmp_path / ".azure" / "deploy.yaml").write_text("steps: []", encoding="utf-8")
    (tmp_path / ".devops").mkdir()
    (tmp_path / ".devops" / "build.yml").write_text("steps: []", encoding="utf-8")
    (tmp_path / ".ado").mkdir()
    (tmp_path / ".ado" / "release.yml").write_text("steps: []", encoding="utf-8")
    (tmp_path / ".ignored").mkdir()
    (tmp_path / ".ignored" / "skip.yml").write_text("steps: []", encoding="utf-8")

    scanner = FileScanner(tmp_path)
    collected = scanner.collect(tmp_path)

    assert collected == (
        (tmp_path / ".ado" / "release.yml").resolve(),
        (tmp_path / ".azure" / "deploy.yaml").resolve(),
        (tmp_path / ".azure-pipelines" / "ci.yml").resolve(),
        (tmp_path / ".devops" / "build.yml").resolve(),
    )


def test_collect_common_mode_allows_explicit_hidden_target(tmp_path: Path) -> None:
    (tmp_path / ".customhidden").mkdir()
    yaml_file = tmp_path / ".customhidden" / "pipeline.yml"
    yaml_file.write_text("steps: []", encoding="utf-8")

    scanner = FileScanner(tmp_path, hidden_mode="common")
    collected = scanner.collect(Path(".customhidden"))

    assert collected == (yaml_file.resolve(),)


@pytest.mark.parametrize("hidden_dir_name", sorted(COMMON_HIDDEN_DIRS))
def test_collect_common_mode_includes_every_common_hidden_dir(
    tmp_path: Path, hidden_dir_name: str
) -> None:
    hidden_dir = tmp_path / hidden_dir_name
    hidden_dir.mkdir()
    target = hidden_dir / "ci.yml"
    target.write_text("steps: []", encoding="utf-8")

    scanner = FileScanner(tmp_path, hidden_mode="common")
    collected = scanner.collect(tmp_path)

    assert collected == (target.resolve(),)


def test_collect_none_mode_skips_hidden_dirs(tmp_path: Path) -> None:
    (tmp_path / ".devops").mkdir()
    (tmp_path / ".devops" / "ci.yml").write_text("steps: []", encoding="utf-8")
    (tmp_path / "visible").mkdir()
    visible = tmp_path / "visible" / "pipeline.yaml"
    visible.write_text("steps: []", encoding="utf-8")

    scanner = FileScanner(tmp_path, hidden_mode="none")
    collected = scanner.collect(tmp_path)

    assert collected == (visible.resolve(),)


def test_collect_none_mode_returns_no_files_for_hidden_directory_target(tmp_path: Path) -> None:
    (tmp_path / ".devops").mkdir()
    hidden_yaml = tmp_path / ".devops" / "ci.yml"
    hidden_yaml.write_text("steps: []", encoding="utf-8")

    scanner = FileScanner(tmp_path, hidden_mode="none")
    collected = scanner.collect(Path(".devops"))

    assert collected == tuple()


def test_collect_all_mode_includes_all_hidden_dirs_except_hard_exclusions(tmp_path: Path) -> None:
    (tmp_path / ".customhidden").mkdir()
    custom = tmp_path / ".customhidden" / "custom.yml"
    custom.write_text("steps: []", encoding="utf-8")
    (tmp_path / ".github").mkdir()
    excluded = tmp_path / ".github" / "workflow.yml"
    excluded.write_text("steps: []", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored.yaml").write_text("steps: []", encoding="utf-8")

    scanner = FileScanner(tmp_path, hidden_mode="all")
    collected = scanner.collect(tmp_path)

    assert collected == (custom.resolve(),)
    assert excluded.resolve() not in collected


def test_collect_accepts_single_hidden_file_for_any_mode(tmp_path: Path) -> None:
    (tmp_path / ".devops").mkdir()
    hidden_file = tmp_path / ".devops" / "single.yml"
    hidden_file.write_text("steps: []", encoding="utf-8")

    scanner = FileScanner(tmp_path, hidden_mode="none")
    collected = scanner.collect(hidden_file)

    assert collected == (hidden_file.resolve(),)


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


def test_iter_single_file_yields_path(tmp_path: Path) -> None:
    target = tmp_path / "single.yml"
    target.write_text("trigger: none", encoding="utf-8")

    assert tuple(iter_single_file(target)) == (target,)
