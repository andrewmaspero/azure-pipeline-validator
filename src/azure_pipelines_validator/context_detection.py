"""Git-based Azure DevOps context detection helpers."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

HTTPS_REMOTE_PATTERN = re.compile(
    r"dev\.azure\.com/(?P<org>[^/]+)/(?P<project>[^/]+)/_git/(?P<repo>[^/\s]+)"
)
SSH_REMOTE_PATTERN = re.compile(
    r"ssh\.dev\.azure\.com:v3/(?P<org>[^/]+)/(?P<project>[^/]+)/(?P<repo>[^/\s]+)"
)
LEGACY_REMOTE_PATTERN = re.compile(
    r"(?P<org>[^@/]+)\.visualstudio\.com/(?P<project>[^/]+)/_git/(?P<repo>[^/\s]+)"
)


class DetectionSource(StrEnum):
    """Source labels for resolved Azure context values."""

    FLAG = "flag"
    ENV = "env"
    KEYCHAIN = "keychain"
    GIT_REMOTE = "git_remote"
    AZ_CLI = "az_cli"
    USER_PROMPT = "user_prompt"
    CACHE = "cache"
    UNSET = "unset"


@dataclass(frozen=True, slots=True)
class RemoteInfo:
    """Parsed Azure DevOps remote components."""

    org: str
    project: str
    repo: str


@dataclass(frozen=True, slots=True)
class GitContext:
    """Git context detected from the current working directory."""

    remote_name: str
    remote_url: str | None
    remote: RemoteInfo | None
    current_branch: str | None
    repo_root: Path | None


def parse_remote_url(url: str) -> RemoteInfo | None:
    """Parse an Azure DevOps git remote URL.

    Supports:
    - HTTPS: ``https://dev.azure.com/{org}/{project}/_git/{repo}``
    - SSH: ``git@ssh.dev.azure.com:v3/{org}/{project}/{repo}``
    - Legacy: ``https://{org}.visualstudio.com/{project}/_git/{repo}``

    Args:
        url: Remote URL string.

    Returns:
        Parsed ``RemoteInfo`` if recognized, otherwise ``None``.
    """
    for pattern in (HTTPS_REMOTE_PATTERN, SSH_REMOTE_PATTERN, LEGACY_REMOTE_PATTERN):
        match = pattern.search(url)
        if match is not None:
            return RemoteInfo(
                org=match.group("org"),
                project=match.group("project"),
                repo=match.group("repo"),
            )
    return None


def detect_git_context(remote_name: str = "origin") -> GitContext:
    """Detect Azure DevOps context from local git metadata.

    Args:
        remote_name: Remote name to inspect.

    Returns:
        A ``GitContext`` containing detected git metadata.
    """
    remote_url = _run_git("remote", "get-url", remote_name)
    remote = parse_remote_url(remote_url) if remote_url else None
    current_branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    repo_root_raw = _run_git("rev-parse", "--show-toplevel")
    repo_root = Path(repo_root_raw).expanduser().resolve() if repo_root_raw else None
    return GitContext(
        remote_name=remote_name,
        remote_url=remote_url,
        remote=remote,
        current_branch=current_branch,
        repo_root=repo_root,
    )


def _run_git(*args: str) -> str | None:
    """Run a git command and return stripped stdout.

    Args:
        *args: Git command arguments.

    Returns:
        Command stdout without surrounding whitespace, or ``None`` on failure.
    """
    result = subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    return value or None
