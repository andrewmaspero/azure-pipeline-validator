"""OS keychain helpers for Azure DevOps PAT and default organization storage."""

from __future__ import annotations

import os

from .context_detection import detect_git_context

SERVICE_NAME = "azure-pipeline-validator"
DEFAULT_ORG_ACCOUNT = "__default_org__"
DEFAULT_COLLECTION_URI = "https://dev.azure.com/"


def is_keyring_backend_available() -> bool:
    """Check whether a usable keyring backend is available.

    Returns:
        ``True`` when a non-failing keyring backend is configured.
    """
    available, _ = keyring_backend_status()
    return available


def keyring_backend_status() -> tuple[bool, str]:
    """Return keyring backend availability and a human-readable detail.

    Returns:
        Tuple of ``(is_available, detail_message)``.
    """
    try:
        import keyring
    except Exception as exc:
        return False, f"keyring import failed: {exc}"

    backend = keyring.get_keyring()
    backend_module = backend.__class__.__module__
    backend_name = backend.__class__.__name__
    if "keyring.backends.fail" in backend_module.lower():
        return False, f"no usable keyring backend ({backend_module}.{backend_name})"
    return True, f"{backend_module}.{backend_name}"


def resolve_org(explicit_org: str | None = None, *, remote_name: str = "origin") -> str | None:
    """Resolve Azure DevOps org with local-first fallback ordering.

    Resolution order:
    1. Explicit org value
    2. ``AZDO_ORG`` environment variable
    3. Git remote auto-detection
    4. Keychain stored default org

    Args:
        explicit_org: Explicit organization override.
        remote_name: Git remote name used for organization auto-detection.

    Returns:
        Resolved organization slug or URL string when available.
    """
    if explicit_org and explicit_org.strip():
        return explicit_org.strip()

    env_org = os.getenv("AZDO_ORG", "").strip()
    if env_org:
        return env_org

    git_context = detect_git_context(remote_name=remote_name)
    if git_context.remote is not None:
        return git_context.remote.org

    return read_default_org()


def read_pat(org: str, collection_uri: str | None = None) -> str | None:
    """Read a PAT from keyring for an organization scope.

    Args:
        org: Azure DevOps organization slug or URL.
        collection_uri: Optional collection URI scope.

    Returns:
        PAT string when present, otherwise ``None``.
    """
    if not is_keyring_backend_available():
        return None
    account = _pat_account_name(org, collection_uri)
    try:
        import keyring

        token = keyring.get_password(SERVICE_NAME, account)
    except Exception:
        return None
    if not token or not token.strip():
        return None
    return token.strip()


def store_pat(token: str, org: str, collection_uri: str | None = None) -> None:
    """Store a PAT in keyring for an organization scope.

    Args:
        token: PAT token value.
        org: Azure DevOps organization slug or URL.
        collection_uri: Optional collection URI scope.

    Raises:
        RuntimeError: If keyring backend is unavailable or write fails.
    """
    clean_token = token.strip()
    if not clean_token:
        raise RuntimeError("PAT cannot be empty.")
    if not is_keyring_backend_available():
        raise RuntimeError("No usable keychain backend is available on this system.")
    account = _pat_account_name(org, collection_uri)
    try:
        import keyring

        keyring.set_password(SERVICE_NAME, account, clean_token)
    except Exception as exc:
        raise RuntimeError(f"Failed to store PAT in keychain: {exc}") from exc


def clear_pat(org: str, collection_uri: str | None = None) -> bool:
    """Delete a PAT from keyring for an organization scope.

    Args:
        org: Azure DevOps organization slug or URL.
        collection_uri: Optional collection URI scope.

    Returns:
        ``True`` when a PAT existed and was removed, ``False`` otherwise.
    """
    if not is_keyring_backend_available():
        return False
    account = _pat_account_name(org, collection_uri)
    had_value = read_pat(org, collection_uri) is not None
    try:
        import keyring
        from keyring.errors import PasswordDeleteError

        keyring.delete_password(SERVICE_NAME, account)
    except PasswordDeleteError:
        return False
    except Exception:
        return False
    return had_value


def store_default_org(org: str) -> None:
    """Store a default Azure DevOps org in keyring.

    Args:
        org: Azure DevOps org value.

    Raises:
        RuntimeError: If org is empty or keyring write fails.
    """
    clean = org.strip()
    if not clean:
        raise RuntimeError("Organization cannot be empty.")
    if not is_keyring_backend_available():
        raise RuntimeError("No usable keychain backend is available on this system.")
    try:
        import keyring

        keyring.set_password(SERVICE_NAME, DEFAULT_ORG_ACCOUNT, clean)
    except Exception as exc:
        raise RuntimeError(f"Failed to store default org in keychain: {exc}") from exc


def read_default_org() -> str | None:
    """Read the default Azure DevOps org from keyring.

    Returns:
        Default organization value when present, otherwise ``None``.
    """
    if not is_keyring_backend_available():
        return None
    try:
        import keyring

        value = keyring.get_password(SERVICE_NAME, DEFAULT_ORG_ACCOUNT)
    except Exception:
        return None
    if not value or not value.strip():
        return None
    return value.strip()


def clear_default_org() -> bool:
    """Delete the stored default organization.

    Returns:
        ``True`` if a default org existed and was removed.
    """
    if not is_keyring_backend_available():
        return False
    existing = read_default_org()
    try:
        import keyring
        from keyring.errors import PasswordDeleteError

        keyring.delete_password(SERVICE_NAME, DEFAULT_ORG_ACCOUNT)
    except PasswordDeleteError:
        return False
    except Exception:
        return False
    return existing is not None


def _pat_account_name(org: str, collection_uri: str | None = None) -> str:
    """Build a stable keyring account identifier for PAT storage.

    Args:
        org: Azure DevOps organization slug or URL.
        collection_uri: Optional collection URI scope.

    Returns:
        Account key string scoped by collection URI and org.

    Raises:
        RuntimeError: If organization is empty.
    """
    clean_org = org.strip()
    if not clean_org:
        raise RuntimeError("Azure DevOps organization is required for keychain PAT access.")
    uri = (collection_uri or DEFAULT_COLLECTION_URI).strip() or DEFAULT_COLLECTION_URI
    if not uri.endswith("/"):
        uri = f"{uri}/"
    return f"{uri}::{clean_org}"
