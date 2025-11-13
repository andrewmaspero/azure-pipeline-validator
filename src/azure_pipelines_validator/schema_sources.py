"""Helpers for retrieving the public Azure Pipelines schema."""

from __future__ import annotations

import httpx

from .exceptions import SchemaUnavailableError
from .settings import AZURE_TIMEOUT_DEFAULT

PUBLIC_SCHEMA_URL = (
    "https://raw.githubusercontent.com/microsoft/azure-pipelines-vscode/master/service-schema.json"
)


def download_public_schema(timeout: float | None = None) -> str:
    """Fetch the Azure Pipelines schema from the public VS Code extension repo.

    The VS Code extension ships the same schema used by Azure DevOps and is hosted
    on GitHub without any authentication requirements. We follow redirects and
    raise a `SchemaUnavailableError` when the content cannot be retrieved.
    """

    request_timeout = timeout if timeout is not None else AZURE_TIMEOUT_DEFAULT
    try:
        response = httpx.get(
            PUBLIC_SCHEMA_URL,
            timeout=request_timeout,
            follow_redirects=True,
        )
    except (
        httpx.HTTPError
    ) as exc:  # pragma: no cover - network failures exercised via exception branch
        raise SchemaUnavailableError(f"Unable to download schema: {exc}") from exc

    if response.is_success:
        return response.text
    raise SchemaUnavailableError(
        f"Unable to download schema (HTTP {response.status_code}): {response.text[:200]}"
    )
