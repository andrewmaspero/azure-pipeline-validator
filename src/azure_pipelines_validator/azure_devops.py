"""HTTP client for Azure DevOps preview and schema endpoints."""

from __future__ import annotations

from base64 import b64encode
from contextlib import AbstractContextManager

import httpx
from pydantic import BaseModel, SecretStr

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
    """Handles authenticated calls to Azure DevOps."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.Client(
            timeout=settings.request_timeout_seconds,
            headers=self._default_headers(settings.personal_access_token),
        )
        self._base = str(settings.organization).rstrip("/")

    def __exit__(self, exc_type, exc, exc_tb):
        self.close()
        return None

    def close(self) -> None:
        self._client.close()

    def preview(self, yaml_override: str) -> PreviewResponse:
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
        endpoint = f"{self._base}/_apis/distributedtask/yamlschema?api-version={API_VERSION}"
        response = self._client.get(endpoint)
        if response.is_success:
            return response.text
        raise AzureDevOpsError(response.status_code, _extract_message(response))

    @staticmethod
    def _default_headers(token: SecretStr) -> httpx.Headers:
        encoded = _encode_pat(token)
        return httpx.Headers(
            {
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )


def list_projects(
    organization: str,
    token: SecretStr,
    *,
    top: int | None = None,
    timeout_seconds: float = 30.0,
) -> list[ProjectSummary]:
    """Return projects visible to the PAT within the specified organization."""

    params = {"api-version": API_VERSION}
    if top is not None:
        params["$top"] = str(top)

    base = str(organization).rstrip("/")
    endpoint = f"{base}/_apis/projects"
    headers = AzureDevOpsClient._default_headers(token)
    with httpx.Client(timeout=timeout_seconds, headers=headers) as client:
        response = client.get(endpoint, params=params)
    if response.is_success:
        payload = response.json()
        return [ProjectSummary.model_validate(item) for item in payload.get("value", [])]
    raise AzureDevOpsError(response.status_code, _extract_message(response))


def _encode_pat(token: SecretStr) -> str:
    raw = f":{token.get_secret_value()}".encode("ascii")
    return b64encode(raw).decode("ascii")


def _extract_message(response: httpx.Response) -> str:
    try:
        service_message = ServiceMessage.model_validate_json(response.text)
        return service_message.message
    except Exception:  # pragma: no cover - fall back to status line
        return response.text
class ProjectSummary(BaseModel):
    """Minimal projection of an Azure DevOps project."""

    id: str
    name: str
    state: str
    description: str | None = None
