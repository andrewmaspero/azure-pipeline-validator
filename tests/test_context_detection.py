from __future__ import annotations

from pathlib import Path

from azure_pipelines_validator import context_detection
from azure_pipelines_validator.context_detection import detect_git_context, parse_remote_url


def test_parse_remote_url_https() -> None:
    parsed = parse_remote_url("https://dev.azure.com/acme/demo/_git/repo")
    assert parsed is not None
    assert parsed.org == "acme"
    assert parsed.project == "demo"
    assert parsed.repo == "repo"


def test_parse_remote_url_ssh() -> None:
    parsed = parse_remote_url("git@ssh.dev.azure.com:v3/acme/demo/repo")
    assert parsed is not None
    assert parsed.org == "acme"
    assert parsed.project == "demo"
    assert parsed.repo == "repo"


def test_parse_remote_url_legacy() -> None:
    parsed = parse_remote_url("https://acme.visualstudio.com/demo/_git/repo")
    assert parsed is not None
    assert parsed.org == "acme"
    assert parsed.project == "demo"
    assert parsed.repo == "repo"


def test_parse_remote_url_unknown() -> None:
    assert parse_remote_url("https://github.com/acme/repo.git") is None


def test_detect_git_context_uses_remote_name(monkeypatch, tmp_path: Path) -> None:
    def fake_run_git(*args: str) -> str | None:
        if args == ("remote", "get-url", "upstream"):
            return "https://dev.azure.com/acme/demo/_git/repo"
        if args == ("rev-parse", "--abbrev-ref", "HEAD"):
            return "main"
        if args == ("rev-parse", "--show-toplevel"):
            return str(tmp_path)
        return None

    monkeypatch.setattr(context_detection, "_run_git", fake_run_git)
    detected = detect_git_context(remote_name="upstream")
    assert detected.remote_name == "upstream"
    assert detected.remote is not None
    assert detected.remote.org == "acme"
    assert detected.current_branch == "main"
    assert detected.repo_root == tmp_path.resolve()
