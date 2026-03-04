"""Authentication provider chain for Azure DevOps API access."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .keyring_store import read_pat

PAT_ENV_VARS = ("SYSTEM_ACCESSTOKEN", "AZDO_PAT", "PAT")
AZURE_DEVOPS_RESOURCE = "499b84ac-1321-427f-aa17-267ca6975798"


class TokenKind(StrEnum):
    """Kinds of supported Azure tokens."""

    PAT = "pat"
    BEARER = "bearer"


class TokenSource(StrEnum):
    """Source labels for resolved tokens."""

    EXPLICIT = "explicit"
    ENV = "env"
    KEYCHAIN = "keychain"
    AZ_CLI = "az_cli"


@dataclass(frozen=True, slots=True)
class ResolvedToken:
    """Resolved token payload from the provider chain."""

    value: str
    kind: TokenKind
    source: TokenSource


class TokenProvider(Protocol):
    """Protocol implemented by token providers."""

    def resolve(self, org_hint: str | None) -> ResolvedToken | None:
        """Resolve a token for an organization hint.

        Args:
            org_hint: Optional org hint for scoped providers.

        Returns:
            A ``ResolvedToken`` when available, otherwise ``None``.
        """


@dataclass(frozen=True, slots=True)
class ExplicitTokenProvider:
    """Provider for an explicit ``--azdo-pat`` token value."""

    token: str | None

    def resolve(self, org_hint: str | None) -> ResolvedToken | None:
        """Resolve an explicit PAT value.

        Args:
            org_hint: Optional org hint (unused for explicit tokens).

        Returns:
            Resolved token metadata when an explicit token is set.
        """
        del org_hint
        if self.token and self.token.strip():
            return ResolvedToken(
                value=self.token.strip(),
                kind=TokenKind.PAT,
                source=TokenSource.EXPLICIT,
            )
        return None


class PatEnvProvider:
    """Provider that resolves PAT values from environment variables."""

    def resolve(self, org_hint: str | None) -> ResolvedToken | None:
        """Resolve a PAT from supported environment variables.

        Args:
            org_hint: Optional org hint (unused for env PAT values).

        Returns:
            Resolved PAT metadata when an env variable is set.
        """
        del org_hint
        for env_name in PAT_ENV_VARS:
            value = os.getenv(env_name, "").strip()
            if value:
                return ResolvedToken(value=value, kind=TokenKind.PAT, source=TokenSource.ENV)
        return None


class KeyringPatProvider:
    """Provider that resolves org-scoped PAT values from keychain."""

    def resolve(self, org_hint: str | None) -> ResolvedToken | None:
        """Resolve an org-scoped PAT from keychain storage.

        Args:
            org_hint: Organization hint used for keychain lookup.

        Returns:
            Resolved PAT metadata when keychain has an entry.
        """
        if not org_hint:
            return None
        token = read_pat(org_hint)
        if not token:
            return None
        return ResolvedToken(value=token, kind=TokenKind.PAT, source=TokenSource.KEYCHAIN)


class AzureCliBearerProvider:
    """Provider that resolves Azure CLI access tokens for Azure DevOps."""

    def resolve(self, org_hint: str | None) -> ResolvedToken | None:
        """Resolve a bearer token from Azure CLI.

        Args:
            org_hint: Optional org hint (unused by Azure CLI token retrieval).

        Returns:
            Resolved bearer token metadata when Azure CLI is available.
        """
        del org_hint
        output = _run_az_account_get_access_token(AZURE_DEVOPS_RESOURCE)
        if output is None:
            return None
        token = output.get("accessToken")
        if isinstance(token, str) and token.strip():
            return ResolvedToken(
                value=token.strip(),
                kind=TokenKind.BEARER,
                source=TokenSource.AZ_CLI,
            )
        return None


def resolve_token(explicit_token: str | None, org_hint: str | None) -> ResolvedToken | None:
    """Resolve token using the provider precedence chain.

    Precedence:
    1. Explicit token flag
    2. PAT environment variables
    3. Keychain PAT (org-scoped)
    4. Azure CLI bearer token

    Args:
        explicit_token: Explicit token argument from CLI.
        org_hint: Optional org hint for scoped providers.

    Returns:
        Resolved token metadata, or ``None`` if no provider yields a token.
    """
    providers: tuple[TokenProvider, ...] = (
        ExplicitTokenProvider(explicit_token),
        PatEnvProvider(),
        KeyringPatProvider(),
        AzureCliBearerProvider(),
    )
    for provider in providers:
        resolved = provider.resolve(org_hint)
        if resolved is not None:
            return resolved
    return None


def _run_az_account_get_access_token(resource: str) -> dict[str, object] | None:
    """Fetch an Azure CLI access token payload.

    Args:
        resource: Resource GUID or URL passed to ``--resource``.

    Returns:
        JSON payload from Azure CLI, or ``None`` when unavailable.
    """
    result = subprocess.run(
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            resource,
            "-o",
            "json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return payload
    return None
