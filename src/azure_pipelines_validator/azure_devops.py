"""HTTP client for Azure DevOps preview and schema endpoints.

This module provides a small authenticated client used by validation services to
fetch preview results and schema payloads from Azure DevOps.
"""

from __future__ import annotations

from base64 import b64encode
from contextlib import AbstractContextManager

import httpx
from pydantic import SecretStr

from .exceptions import AzureDevOpsError
from .models import (
    PreviewRequest,
    PreviewResponse,
    RepositoryContainer,
    RepositoryReference,
    RepositoryResources,
    ServiceMessage,
)
from .settings import Settings

API_VERSION = "7.1"


class AzureDevOpsClient(AbstractContextManager["AzureDevOpsClient"]):
    """Handles authenticated calls to Azure DevOps.

    The client owns an underlying ``httpx.Client`` and should be closed after
    use, either explicitly or through the context manager protocol.
    """

    def __init__(self, settings: Settings) -> None:
        """Initializes an authenticated Azure DevOps HTTP client.

        Args:
            settings: Runtime settings containing organization, project, pipeline,
                auth, and timeout configuration.
        """
        self._settings = settings
        self._client = httpx.Client(
            timeout=settings.request_timeout_seconds,
            headers=self._default_headers(settings.personal_access_token),
        )
        self._base = str(settings.organization).rstrip("/")

    def __exit__(self, exc_type, exc, exc_tb):
        """Closes the HTTP client when leaving a context manager block.

        Args:
            exc_type: Exception type raised in the context block, if any.
            exc: Exception instance raised in the context block, if any.
            exc_tb: Traceback associated with ``exc``, if any.

        Returns:
            ``None`` so any exception is propagated by the runtime.
        """
        self.close()
        return None

    def close(self) -> None:
        """Closes the underlying HTTP client."""
        self._client.close()

    def preview(self, yaml_override: str) -> PreviewResponse:
        """Requests a server-side pipeline preview for YAML content.

        Args:
            yaml_override: Pipeline YAML content to preview.

        Returns:
            Parsed preview response from Azure DevOps.

        Raises:
            AzureDevOpsError: If Azure DevOps returns a non-success status.
        """
        request_model = PreviewRequest(
            yaml_override=yaml_override,
            resources=RepositoryResources(
                repositories=RepositoryContainer(
                    self_alias=RepositoryReference(ref_name=self._settings.ref_name)
                )
            ),
        )
        endpoint = (
            f"{self._base}/{self._settings.project}/_apis/pipelines/"
            f"{self._settings.pipeline_id}/preview?api-version={API_VERSION}"
        )
        response = self._client.post(
            endpoint,
            content=request_model.model_dump_json(by_alias=True, exclude_none=True),
        )
        if response.is_success:
            return PreviewResponse.model_validate_json(response.text)
        raise AzureDevOpsError(response.status_code, _extract_message(response))

    def download_schema(self) -> str:
        """Downloads the Azure DevOps YAML schema JSON payload.

        Returns:
            Raw schema content as text.

        Raises:
            AzureDevOpsError: If Azure DevOps returns a non-success status.
        """
        endpoint = f"{self._base}/_apis/distributedtask/yamlschema?api-version={API_VERSION}"
        response = self._client.get(endpoint)
        if response.is_success:
            return response.text
        raise AzureDevOpsError(response.status_code, _extract_message(response))

    @staticmethod
    def _default_headers(token: SecretStr) -> httpx.Headers:
        """Builds default request headers for Azure DevOps API calls.

        Args:
            token: Personal access token used for Basic authentication.

        Returns:
            Preconfigured HTTP headers with auth and JSON content types.
        """
        encoded = _encode_pat(token)
        return httpx.Headers(
            {
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )


def _encode_pat(token: SecretStr) -> str:
    """Encodes a personal access token for Basic authorization headers.

    Args:
        token: Personal access token to encode.

    Returns:
        Base64-encoded ``:<token>`` credential string.
    """
    raw = f":{token.get_secret_value()}".encode("ascii")
    return b64encode(raw).decode("ascii")


def _extract_message(response: httpx.Response) -> str:
    """Extracts a human-readable message from an Azure DevOps response.

    Args:
        response: HTTP response from Azure DevOps.

    Returns:
        Parsed service message when available, otherwise raw response text.
    """
    try:
        service_message = ServiceMessage.model_validate_json(response.text)
        return service_message.message
    except Exception:  # pragma: no cover - fall back to status line
        return response.text
