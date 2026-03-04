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
    PipelineSummary,
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
            headers=self._default_headers(settings.personal_access_token, settings.token_kind),
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

    def list_pipelines(self, project: str, top: int = 200) -> list[PipelineSummary]:
        """List pipelines in a project.

        Args:
            project: Azure DevOps project name.
            top: Maximum number of pipelines to return.

        Returns:
            Parsed list of pipeline summaries.

        Raises:
            AzureDevOpsError: If Azure DevOps returns a non-success status.
        """
        endpoint = (
            f"{self._base}/{project}/_apis/pipelines?api-version={API_VERSION}&$top={int(top)}"
        )
        response = self._client.get(endpoint)
        if not response.is_success:
            raise AzureDevOpsError(response.status_code, _extract_message(response))

        payload = response.json()
        values = payload.get("value", []) if isinstance(payload, dict) else []
        results: list[PipelineSummary] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            configuration = item.get("configuration")
            repository_name = None
            repository_id = None
            default_branch = None
            yaml_path = None
            if isinstance(configuration, dict):
                config_path = configuration.get("path")
                yaml_path = str(config_path) if config_path is not None else None
                repository = configuration.get("repository")
                if isinstance(repository, dict):
                    name = repository.get("name")
                    repo_id = repository.get("id")
                    branch = repository.get("defaultBranch")
                    repository_name = str(name) if name is not None else None
                    repository_id = str(repo_id) if repo_id is not None else None
                    default_branch = str(branch) if branch is not None else None

            pipeline_id = item.get("id")
            if not isinstance(pipeline_id, int):
                continue
            results.append(
                PipelineSummary(
                    id=pipeline_id,
                    name=str(item.get("name", "")),
                    folder=str(item.get("folder")) if item.get("folder") is not None else None,
                    url=str(item.get("url")) if item.get("url") is not None else None,
                    repository_name=repository_name,
                    repository_id=repository_id,
                    default_branch=default_branch,
                    yaml_path=yaml_path,
                )
            )
        return results

    def find_pipelines_by_name(self, project: str, name_hint: str) -> list[PipelineSummary]:
        """Find pipelines by case-insensitive name match.

        Args:
            project: Azure DevOps project name.
            name_hint: Pipeline name hint.

        Returns:
            Matching pipelines.
        """
        hint = name_hint.strip().lower()
        if not hint:
            return []
        pipelines = self.list_pipelines(project)
        return [pipeline for pipeline in pipelines if hint in pipeline.name.lower()]

    def find_pipelines_for_repo(self, project: str, repo_name: str) -> list[PipelineSummary]:
        """Find pipelines associated with a repository name.

        Args:
            project: Azure DevOps project name.
            repo_name: Repository name hint.

        Returns:
            Matching pipelines based on repository metadata and name heuristics.
        """
        normalized_repo = repo_name.strip().lower()
        if not normalized_repo:
            return []
        pipelines = self.list_pipelines(project)
        matches: list[PipelineSummary] = []
        for pipeline in pipelines:
            if pipeline.repository_name and pipeline.repository_name.lower() == normalized_repo:
                matches.append(pipeline)
                continue
            if normalized_repo in pipeline.name.lower():
                matches.append(pipeline)
        return matches

    @staticmethod
    def _default_headers(token: SecretStr, token_kind: str) -> httpx.Headers:
        """Builds default request headers for Azure DevOps API calls.

        Args:
            token: Personal access token used for Basic authentication.
            token_kind: Token kind string (``pat`` or ``bearer``).

        Returns:
            Preconfigured HTTP headers with auth and JSON content types.
        """
        normalized_kind = token_kind.strip().lower()
        if normalized_kind == "bearer":
            auth_value = f"Bearer {token.get_secret_value()}"
        else:
            encoded = _encode_pat(token)
            auth_value = f"Basic {encoded}"
        return httpx.Headers(
            {
                "Authorization": auth_value,
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
