from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from azure_pipelines_validator.azure_devops import AzureDevOpsClient, list_projects
from azure_pipelines_validator.exceptions import AzureDevOpsError
from azure_pipelines_validator.models import PreviewResponse
from azure_pipelines_validator.settings import Settings


def make_settings(tmp_path):
    return Settings(
        organization="https://dev.azure.com/acme",
        project="demo",
        pipeline_id=7,
        personal_access_token=SecretStr("token"),
        ref_name="refs/heads/main",
        repo_root=tmp_path,
        request_timeout_seconds=5.0,
    )


def attach_transport(client: AzureDevOpsClient, handler):
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_preview_success(tmp_path):
    settings = make_settings(tmp_path)
    payload = PreviewResponse(
        final_yaml="trigger: none",
        validation_results=(),
        continuation_token=None,
    ).model_dump(by_alias=True)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "preview" in str(request.url)
        return httpx.Response(200, json=payload)

    client = attach_transport(AzureDevOpsClient(settings), handler)
    result = client.preview("trigger: none")
    client.close()

    assert result.final_yaml == "trigger: none"


def test_preview_failure_raises(tmp_path):
    settings = make_settings(tmp_path)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "bad"})

    client = attach_transport(AzureDevOpsClient(settings), handler)
    with pytest.raises(AzureDevOpsError) as excinfo:
        client.preview("broken")
    client.close()

    assert "bad" in str(excinfo.value)


def test_download_schema(tmp_path):
    settings = make_settings(tmp_path)
    schema_text = '{"type": "object"}'

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert (
            str(request.url)
            == "https://dev.azure.com/acme/_apis/distributedtask/yamlschema?api-version=7.1"
        )
        return httpx.Response(200, text=schema_text)

    client = attach_transport(AzureDevOpsClient(settings), handler)
    result = client.download_schema()
    client.close()

    assert result == schema_text


def test_list_projects(monkeypatch):
    payload = {
        "value": [
            {"id": "1", "name": "Alpha", "state": "well", "description": "demo"},
            {"id": "2", "name": "Beta", "state": "new"},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        assert url.startswith("https://dev.azure.com/acme/_apis/projects")
        assert "$top=2" in url or "top=2" in url
        assert "api-version" in url
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client_factory(*, timeout, headers):
        return real_client(transport=transport, timeout=timeout, headers=headers)

    monkeypatch.setattr(httpx, "Client", client_factory)

    result = list_projects("https://dev.azure.com/acme", SecretStr("token"), top=2)

    assert [project.name for project in result] == ["Alpha", "Beta"]
