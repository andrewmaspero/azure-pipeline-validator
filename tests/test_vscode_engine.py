from __future__ import annotations

import io
import json
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from azure_pipelines_validator.exceptions import VscodeValidationError
from azure_pipelines_validator.models import VscodeFinding, YamlKind
from azure_pipelines_validator.vscode_engine import (
    VscodeValidator,
    _bootstrap_extension_assets,
    _discover_installed_extension,
    _env_flag,
    _env_float,
    _extract_version_key,
    _LspSession,
    _resolve_bootstrapped_extension,
    _resolve_server_and_schema,
    _severity_label,
    _try_parse_message,
    _validate_paths,
    _wait_for_fd,
)
from azure_pipelines_validator.yaml_processing import YamlDocument


def _make_vsix_bytes(*, include_required_files: bool = True) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        if include_required_files:
            archive.writestr("extension/dist/server.js", "// test server")
            archive.writestr("extension/service-schema.json", "{}")
        else:
            archive.writestr("extension/README.md", "noop")
    return stream.getvalue()


def test_extract_version_key_parses_semver() -> None:
    assert _extract_version_key("ms-azure-devops.azure-pipelines-1.261.1") == (1, 261, 1)


def test_extract_version_key_falls_back_when_missing() -> None:
    assert _extract_version_key("ms-azure-devops.azure-pipelines-latest") == (0, 0, 0)


def test_env_flag_truthy_and_falsey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZP_VALIDATOR_VSCODE_OFFLINE", raising=False)
    assert _env_flag("AZP_VALIDATOR_VSCODE_OFFLINE") is False

    monkeypatch.setenv("AZP_VALIDATOR_VSCODE_OFFLINE", "  YES ")
    assert _env_flag("AZP_VALIDATOR_VSCODE_OFFLINE") is True

    monkeypatch.setenv("AZP_VALIDATOR_VSCODE_OFFLINE", "0")
    assert _env_flag("AZP_VALIDATOR_VSCODE_OFFLINE") is False


def test_env_float_default_and_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZP_VALIDATOR_VSCODE_DOWNLOAD_TIMEOUT_SECONDS", raising=False)
    assert _env_float("AZP_VALIDATOR_VSCODE_DOWNLOAD_TIMEOUT_SECONDS", 10.0) == 10.0

    monkeypatch.setenv("AZP_VALIDATOR_VSCODE_DOWNLOAD_TIMEOUT_SECONDS", "2.5")
    assert _env_float("AZP_VALIDATOR_VSCODE_DOWNLOAD_TIMEOUT_SECONDS", 10.0) == 2.5


@pytest.mark.parametrize("raw", ["abc", "0", "-1"])
def test_env_float_rejects_invalid(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZP_VALIDATOR_VSCODE_DOWNLOAD_TIMEOUT_SECONDS", raw)
    with pytest.raises(VscodeValidationError):
        _env_float("AZP_VALIDATOR_VSCODE_DOWNLOAD_TIMEOUT_SECONDS", 10.0)


def test_severity_label_mapping() -> None:
    assert _severity_label(1) == "error"
    assert _severity_label("2") == "warning"
    assert _severity_label(3) == "info"
    assert _severity_label(4) == "hint"
    assert _severity_label("oops") == "unknown"


def test_validate_paths_raises_for_missing_files(tmp_path: Path) -> None:
    server = tmp_path / "dist" / "server.js"
    schema = tmp_path / "service-schema.json"
    server.parent.mkdir(parents=True)

    with pytest.raises(VscodeValidationError, match="language server not found"):
        _validate_paths(server, schema)

    server.write_text("// test", encoding="utf-8")
    with pytest.raises(VscodeValidationError, match="schema file not found"):
        _validate_paths(server, schema)


def test_resolve_server_and_schema_uses_explicit_paths(tmp_path: Path) -> None:
    server = tmp_path / "dist" / "server.js"
    schema = tmp_path / "service-schema.json"
    server.parent.mkdir(parents=True)
    server.write_text("// test", encoding="utf-8")
    schema.write_text("{}", encoding="utf-8")

    resolved_server, resolved_schema = _resolve_server_and_schema(
        server_path=server,
        schema_path=schema,
    )

    assert resolved_server == server.resolve()
    assert resolved_schema == schema.resolve()


def test_resolve_server_and_schema_requires_real_files(tmp_path: Path) -> None:
    missing_server = tmp_path / "server.js"
    schema = tmp_path / "service-schema.json"
    schema.write_text("{}", encoding="utf-8")

    with pytest.raises(VscodeValidationError):
        _resolve_server_and_schema(server_path=missing_server, schema_path=schema)


def test_resolve_server_and_schema_requires_both_override_paths(tmp_path: Path) -> None:
    server = tmp_path / "dist" / "server.js"
    server.parent.mkdir(parents=True)
    server.write_text("// test", encoding="utf-8")

    with pytest.raises(
        VscodeValidationError, match="Pass both --vscode-server-path and --vscode-schema-path"
    ):
        _resolve_server_and_schema(server_path=server, schema_path=None)


def test_resolve_server_and_schema_prefers_discovered_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = tmp_path / "dist" / "server.js"
    schema = tmp_path / "service-schema.json"
    server.parent.mkdir(parents=True)
    server.write_text("// discovered", encoding="utf-8")
    schema.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine._discover_installed_extension",
        lambda: (server, schema),
    )

    called: dict[str, bool] = {"bootstrapped": False}

    def _should_not_call() -> tuple[Path, Path]:
        called["bootstrapped"] = True
        return server, schema

    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine._resolve_bootstrapped_extension",
        _should_not_call,
    )

    resolved_server, resolved_schema = _resolve_server_and_schema(
        server_path=None,
        schema_path=None,
    )

    assert called["bootstrapped"] is False
    assert resolved_server == server.resolve()
    assert resolved_schema == schema.resolve()


def test_resolve_server_and_schema_bootstraps_when_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine._discover_installed_extension",
        lambda: None,
    )
    monkeypatch.setenv("AZP_VALIDATOR_VSCODE_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("AZP_VALIDATOR_VSCODE_VERSION", "test-version")

    def _fake_bootstrap(
        *, download_url: str, cache_dir: Path, timeout_seconds: float, expected_sha256: str | None
    ) -> None:
        del download_url, timeout_seconds, expected_sha256
        server = cache_dir / "dist" / "server.js"
        schema = cache_dir / "service-schema.json"
        server.parent.mkdir(parents=True, exist_ok=True)
        server.write_text("// test", encoding="utf-8")
        schema.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine._bootstrap_extension_assets",
        _fake_bootstrap,
    )

    server, schema = _resolve_server_and_schema(server_path=None, schema_path=None)

    assert (
        server
        == (
            tmp_path / "ms-azure-devops.azure-pipelines" / "test-version" / "dist" / "server.js"
        ).resolve()
    )
    assert (
        schema
        == (
            tmp_path / "ms-azure-devops.azure-pipelines" / "test-version" / "service-schema.json"
        ).resolve()
    )


def test_resolve_server_and_schema_respects_offline_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine._discover_installed_extension",
        lambda: None,
    )
    monkeypatch.setenv("AZP_VALIDATOR_VSCODE_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("AZP_VALIDATOR_VSCODE_OFFLINE", "true")

    with pytest.raises(VscodeValidationError, match="offline mode is enabled"):
        _resolve_server_and_schema(server_path=None, schema_path=None)


def test_resolve_bootstrapped_extension_uses_cached_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AZP_VALIDATOR_VSCODE_CACHE_DIR", str(tmp_path))
    cache_dir = tmp_path / "ms-azure-devops.azure-pipelines" / "latest"
    server = cache_dir / "dist" / "server.js"
    schema = cache_dir / "service-schema.json"
    server.parent.mkdir(parents=True)
    server.write_text("// cached", encoding="utf-8")
    schema.write_text("{}", encoding="utf-8")

    resolved_server, resolved_schema = _resolve_bootstrapped_extension()

    assert resolved_server == server.resolve()
    assert resolved_schema == schema.resolve()


def test_resolve_bootstrapped_extension_bootstrap_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AZP_VALIDATOR_VSCODE_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("AZP_VALIDATOR_VSCODE_PUBLISHER", "publisher")
    monkeypatch.setenv("AZP_VALIDATOR_VSCODE_EXTENSION", "extension")
    monkeypatch.setenv("AZP_VALIDATOR_VSCODE_VERSION", "1.2.3")
    monkeypatch.setenv("AZP_VALIDATOR_VSCODE_SHA256", "abc123")
    monkeypatch.setenv("AZP_VALIDATOR_VSCODE_DOWNLOAD_TIMEOUT_SECONDS", "11")

    captured: dict[str, object] = {}

    def _fake_bootstrap(
        *, download_url: str, cache_dir: Path, timeout_seconds: float, expected_sha256: str | None
    ) -> None:
        captured["download_url"] = download_url
        captured["cache_dir"] = cache_dir
        captured["timeout_seconds"] = timeout_seconds
        captured["expected_sha256"] = expected_sha256

    expected_server = tmp_path / "publisher.extension" / "1.2.3" / "dist" / "server.js"
    expected_schema = tmp_path / "publisher.extension" / "1.2.3" / "service-schema.json"

    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine._bootstrap_extension_assets", _fake_bootstrap
    )
    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine._validate_paths",
        lambda server_path, schema_path: (server_path, schema_path),
    )

    server, schema = _resolve_bootstrapped_extension()

    assert captured["download_url"] == (
        "https://publisher.gallery.vsassets.io/_apis/public/gallery/publisher/"
        "publisher/extension/extension/1.2.3/assetbyname/"
        "Microsoft.VisualStudio.Services.VSIXPackage"
    )
    assert captured["cache_dir"] == tmp_path / "publisher.extension" / "1.2.3"
    assert captured["timeout_seconds"] == 11.0
    assert captured["expected_sha256"] == "abc123"
    assert server == expected_server.resolve()
    assert schema == expected_schema.resolve()


def test_bootstrap_extension_assets_extracts_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = tmp_path / "cache" / "assets"
    temp_target = cache_dir.parent / f".{cache_dir.name}.tmp"
    temp_target.mkdir(parents=True)
    (temp_target / "stale.txt").write_text("old", encoding="utf-8")

    class _Response:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, exc_type, exc, exc_tb) -> None:
            return None

        def read(self) -> bytes:
            return self._payload

    payload = _make_vsix_bytes()
    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine.urlopen",
        lambda *_args, **_kwargs: _Response(payload),
    )

    _bootstrap_extension_assets(
        download_url="https://example.invalid/vsix",
        cache_dir=cache_dir,
        timeout_seconds=1.0,
        expected_sha256=None,
    )

    assert (cache_dir / "dist" / "server.js").read_text(encoding="utf-8") == "// test server"
    assert (cache_dir / "service-schema.json").read_text(encoding="utf-8") == "{}"


def test_bootstrap_extension_assets_wraps_download_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = tmp_path / "cache" / "assets"

    def _raise(*_args, **_kwargs):
        raise URLError("no network")

    monkeypatch.setattr("azure_pipelines_validator.vscode_engine.urlopen", _raise)

    with pytest.raises(VscodeValidationError, match="Unable to download"):
        _bootstrap_extension_assets(
            download_url="https://example.invalid/vsix",
            cache_dir=cache_dir,
            timeout_seconds=1.0,
            expected_sha256=None,
        )


def test_bootstrap_extension_assets_detects_checksum_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = tmp_path / "cache" / "assets"

    class _Response:
        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, exc_type, exc, exc_tb) -> None:
            return None

        def read(self) -> bytes:
            return _make_vsix_bytes()

    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine.urlopen",
        lambda *_args, **_kwargs: _Response(),
    )

    with pytest.raises(VscodeValidationError, match="checksum mismatch"):
        _bootstrap_extension_assets(
            download_url="https://example.invalid/vsix",
            cache_dir=cache_dir,
            timeout_seconds=1.0,
            expected_sha256="deadbeef",
        )


def test_bootstrap_extension_assets_rejects_invalid_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = tmp_path / "cache" / "assets"

    class _Response:
        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, exc_type, exc, exc_tb) -> None:
            return None

        def read(self) -> bytes:
            return _make_vsix_bytes(include_required_files=False)

    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine.urlopen",
        lambda *_args, **_kwargs: _Response(),
    )

    with pytest.raises(VscodeValidationError, match="missing required files"):
        _bootstrap_extension_assets(
            download_url="https://example.invalid/vsix",
            cache_dir=cache_dir,
            timeout_seconds=1.0,
            expected_sha256=None,
        )


def test_try_parse_message_happy_path() -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    body = json.dumps(payload).encode("utf-8")
    raw = bytearray(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)

    parsed = _try_parse_message(raw)

    assert parsed is not None
    message, consumed = parsed
    assert message == payload
    assert consumed == len(raw)


def test_try_parse_message_partial_or_missing_headers() -> None:
    assert _try_parse_message(bytearray(b"no headers")) is None

    with pytest.raises(VscodeValidationError, match="Missing Content-Length"):
        _try_parse_message(bytearray(b"Header: x\r\n\r\n{}"))

    with pytest.raises(VscodeValidationError, match="Invalid content-length"):
        _try_parse_message(bytearray(b"Content-Length: nan\r\n\r\n{}"))

    body = b'{"jsonrpc":"2.0"}'
    assert _try_parse_message(bytearray(b"Content-Length: 100\r\n\r\n" + body)) is None


def test_wait_for_fd_delegates_to_select(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine.select.select",
        lambda *_args, **_kwargs: ([1], [], []),
    )
    assert _wait_for_fd(1, 0.1) is True

    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine.select.select",
        lambda *_args, **_kwargs: ([], [], []),
    )
    assert _wait_for_fd(1, 0.1) is False


def test_handle_server_request_branches(tmp_path: Path) -> None:
    session = _LspSession.__new__(_LspSession)
    session._schema_uri = "file:///schema.json"
    session._schema_text = '{"type": "object"}'

    assert session._handle_server_request("custom/schema/request", None) == "file:///schema.json"
    assert (
        session._handle_server_request("custom/schema/content", "file:///schema.json")
        == '{"type": "object"}'
    )

    local_file = tmp_path / "schema.json"
    local_file.write_text('{"title": "local"}', encoding="utf-8")
    assert (
        session._handle_server_request("custom/schema/content", local_file.resolve().as_uri())
        == '{"title": "local"}'
    )
    assert session._handle_server_request("custom/schema/content", "file:///missing.json") == ""
    assert session._handle_server_request("vscode/content", None) == ""
    assert session._handle_server_request("unknown", None) is None


def test_pump_once_diagnostics_and_response_paths() -> None:
    session = _LspSession.__new__(_LspSession)
    session._diagnostics_by_uri = {}
    session._responses = {}

    diagnostics_message = {
        "method": "textDocument/publishDiagnostics",
        "params": {"uri": "file:///a.yml", "diagnostics": [{"message": "x"}]},
    }
    session._read_message = lambda _timeout: diagnostics_message

    session._pump_once(0.1)
    assert session._diagnostics_by_uri == {"file:///a.yml": [{"message": "x"}]}

    sent: list[dict[str, object]] = []
    session._read_message = lambda _timeout: {
        "id": 4,
        "method": "custom/schema/request",
        "params": {},
    }
    session._handle_server_request = lambda _method, _params: "ok"
    session._send = lambda payload: sent.append(payload)

    session._pump_once(0.1)
    assert sent == [{"jsonrpc": "2.0", "id": 4, "result": "ok"}]

    session._read_message = lambda _timeout: {"id": 9, "result": {"done": True}}
    session._pump_once(0.1)
    assert session._responses == {9: {"id": 9, "result": {"done": True}}}


def test_send_raises_when_stdin_missing() -> None:
    session = _LspSession.__new__(_LspSession)
    session._process = SimpleNamespace(stdin=None)

    with pytest.raises(VscodeValidationError, match="stdin is unavailable"):
        session._send({"jsonrpc": "2.0"})


def test_send_writes_length_prefixed_payload() -> None:
    class _Stdin:
        def __init__(self) -> None:
            self.buffer = bytearray()
            self.flushed = False

        def write(self, data: bytes) -> int:
            self.buffer.extend(data)
            return len(data)

        def flush(self) -> None:
            self.flushed = True

    session = _LspSession.__new__(_LspSession)
    stdin = _Stdin()
    session._process = SimpleNamespace(stdin=stdin)

    payload = {"jsonrpc": "2.0", "method": "initialized", "params": {}}
    session._send(payload)

    encoded = json.dumps(payload).encode("utf-8")
    expected_prefix = f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii")
    assert bytes(stdin.buffer).startswith(expected_prefix)
    assert bytes(stdin.buffer)[len(expected_prefix) :] == encoded
    assert stdin.flushed is True


def test_vscode_validator_init_and_properties(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = tmp_path / "dist" / "server.js"
    schema = tmp_path / "service-schema.json"

    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine._resolve_server_and_schema",
        lambda **_kwargs: (server, schema),
    )

    validator = VscodeValidator(repo_root=tmp_path)

    assert validator.server_path == server
    assert validator.schema_path == schema


def test_vscode_validator_run_empty_short_circuits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine._resolve_server_and_schema",
        lambda **_kwargs: (tmp_path / "dist" / "server.js", tmp_path / "service-schema.json"),
    )

    called = {"entered": False}

    class _ShouldNotEnter:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def __enter__(self):
            called["entered"] = True
            return self

        def __exit__(self, exc_type, exc, exc_tb) -> None:
            return None

    monkeypatch.setattr("azure_pipelines_validator.vscode_engine._LspSession", _ShouldNotEnter)

    validator = VscodeValidator(repo_root=tmp_path)
    assert validator.run([]) == {}
    assert called["entered"] is False


def test_vscode_validator_run_with_mocked_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = tmp_path / "dist" / "server.js"
    schema = tmp_path / "service-schema.json"

    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine._resolve_server_and_schema",
        lambda **_kwargs: (server, schema),
    )

    doc_a = YamlDocument(path=tmp_path / "a.yml", content="trigger: none", kind=YamlKind.PIPELINE)
    doc_b = YamlDocument(path=tmp_path / "b.yml", content="stages: []", kind=YamlKind.PIPELINE)

    findings = {
        doc_a.path: (
            VscodeFinding(
                path=doc_a.path,
                line=1,
                column=1,
                severity="warning",
                message="a",
                code="A1",
            ),
        ),
        doc_b.path: tuple(),
    }

    captured: dict[str, object] = {}

    class _FakeSession:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def __enter__(self) -> "_FakeSession":
            return self

        def __exit__(self, exc_type, exc, exc_tb) -> None:
            return None

        def validate_document(self, document: YamlDocument) -> tuple[VscodeFinding, ...]:
            return findings[document.path]

    monkeypatch.setattr("azure_pipelines_validator.vscode_engine._LspSession", _FakeSession)

    validator = VscodeValidator(repo_root=tmp_path, timeout_seconds=12.0, node_binary="node-test")
    result = validator.run([doc_a, doc_b])

    assert captured["repo_root"] == tmp_path.resolve()
    assert captured["server_path"] == server
    assert captured["schema_path"] == schema
    assert captured["timeout_seconds"] == 12.0
    assert captured["node_binary"] == "node-test"
    assert result == findings


def test_lsp_session_init_sets_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema = tmp_path / "service-schema.json"
    schema.write_text('{"type":"object"}', encoding="utf-8")
    server = tmp_path / "dist" / "server.js"
    server.parent.mkdir(parents=True)
    server.write_text("// server", encoding="utf-8")

    process = SimpleNamespace(stdin=object(), stdout=object(), stderr=object())
    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine.subprocess.Popen",
        lambda *a, **k: process,
    )
    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine._LspSession._initialize",
        lambda self: None,
    )

    session = _LspSession(
        repo_root=tmp_path,
        server_path=server,
        schema_path=schema,
        timeout_seconds=3.0,
        node_binary="node",
    )

    assert session._schema_uri == schema.resolve().as_uri()
    assert session._schema_text == '{"type":"object"}'
    assert session._timeout_seconds == 3.0
    assert session._next_id == 1
    assert session._responses == {}
    assert session._diagnostics_by_uri == {}
    assert session._read_buffer == bytearray()


def test_lsp_session_exit_terminates_and_kills_on_timeout() -> None:
    class _Process:
        def __init__(self) -> None:
            self.terminated = False
            self.killed = False
            self.wait_called = False

        def poll(self):
            return None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float):
            del timeout
            self.wait_called = True
            raise subprocess.TimeoutExpired(cmd="node", timeout=1)

        def kill(self) -> None:
            self.killed = True

    session = _LspSession.__new__(_LspSession)
    process = _Process()
    session._process = process
    session._shutdown = lambda: None

    session.__exit__(None, None, None)

    assert process.terminated is True
    assert process.wait_called is True
    assert process.killed is True


def test_lsp_session_exit_no_terminate_when_process_already_closed() -> None:
    class _Process:
        def __init__(self) -> None:
            self.terminated = False

        def poll(self):
            return 0

        def terminate(self) -> None:
            self.terminated = True

    session = _LspSession.__new__(_LspSession)
    process = _Process()
    session._process = process
    session._shutdown = lambda: None

    session.__exit__(None, None, None)
    assert process.terminated is False


def test_validate_document_success_and_timeout(tmp_path: Path) -> None:
    doc = YamlDocument(
        path=tmp_path / "pipeline.yml",
        content="trigger: none",
        kind=YamlKind.PIPELINE,
    )
    session = _LspSession.__new__(_LspSession)
    session._timeout_seconds = 1.0
    session._diagnostics_by_uri = {}
    calls: list[tuple[str, dict[str, object]]] = []
    session._send_notification = lambda method, params: calls.append((method, params))
    session._wait_for_diagnostics = lambda *_args: [
        {
            "range": {"start": {"line": 2, "character": 3}},
            "severity": 1,
            "message": " bad ",
            "code": "E1",
        }
    ]

    findings = session.validate_document(doc)
    assert len(findings) == 1
    assert findings[0].line == 3
    assert findings[0].column == 4
    assert findings[0].severity == "error"
    assert findings[0].message == "bad"
    assert calls[0][0] == "textDocument/didOpen"
    assert calls[1][0] == "textDocument/didClose"

    timeout_session = _LspSession.__new__(_LspSession)
    timeout_session._timeout_seconds = 1.0
    timeout_session._diagnostics_by_uri = {}
    timeout_session._send_notification = lambda *_args: None
    timeout_session._wait_for_diagnostics = lambda *_args: None
    timeout_session._drain_stderr = lambda: "stderr message"

    with pytest.raises(VscodeValidationError, match="Timed out waiting for VS Code diagnostics"):
        timeout_session.validate_document(doc)


def test_initialize_sends_configuration_and_handles_error(tmp_path: Path) -> None:
    session = _LspSession.__new__(_LspSession)
    session._repo_root = tmp_path
    session._schema_uri = "file:///schema.json"
    notifications: list[tuple[str, dict[str, object]]] = []
    session._send_notification = lambda method, params: notifications.append((method, params))
    session._send_request = (
        lambda method, params: {"result": "ok"} if method == "initialize" else {}
    )

    session._initialize()
    assert [name for name, _ in notifications] == [
        "initialized",
        "workspace/didChangeConfiguration",
        "json/schemaAssociations",
    ]

    bad = _LspSession.__new__(_LspSession)
    bad._repo_root = tmp_path
    bad._schema_uri = "file:///schema.json"
    bad._send_request = lambda *_args: {"error": "boom"}
    bad._send_notification = lambda *_args: None
    with pytest.raises(VscodeValidationError, match="initialize failed"):
        bad._initialize()


def test_shutdown_handles_exceptions() -> None:
    session = _LspSession.__new__(_LspSession)
    called: list[tuple[str, dict[str, object]]] = []
    session._send_request = lambda method, params: {"result": "ok"}
    session._send_notification = lambda method, params: called.append((method, params))
    session._shutdown()
    assert called == [("exit", {})]

    failing = _LspSession.__new__(_LspSession)
    failing._send_request = lambda *_args: (_ for _ in ()).throw(RuntimeError("nope"))
    failing._send_notification = lambda *_args: called.append(("unexpected", {}))
    failing._shutdown()
    assert ("unexpected", {}) not in called


def test_send_request_success_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _LspSession.__new__(_LspSession)
    session._timeout_seconds = 1.0
    session._next_id = 1
    session._responses = {}
    sent: list[dict[str, object]] = []
    session._send = lambda payload: sent.append(payload)

    def _pump_once(_remaining: float) -> None:
        session._responses[1] = {"id": 1, "result": {"ok": True}}

    session._pump_once = _pump_once

    response = session._send_request("initialize", {"a": 1})
    assert response == {"id": 1, "result": {"ok": True}}
    assert sent[0]["method"] == "initialize"

    timeout_session = _LspSession.__new__(_LspSession)
    timeout_session._timeout_seconds = 0.0
    timeout_session._next_id = 1
    timeout_session._responses = {}
    timeout_session._send = lambda *_args: None
    timeout_session._pump_once = lambda *_args: None
    monkeypatch.setattr("azure_pipelines_validator.vscode_engine.time.monotonic", lambda: 1.0)
    with pytest.raises(VscodeValidationError, match="Timed out waiting for LSP response"):
        timeout_session._send_request("hover", {})


def test_send_notification_and_wait_for_diagnostics() -> None:
    session = _LspSession.__new__(_LspSession)
    sent: list[dict[str, object]] = []
    session._send = lambda payload: sent.append(payload)
    session._send_notification("initialized", {"x": 1})
    assert sent == [{"jsonrpc": "2.0", "method": "initialized", "params": {"x": 1}}]

    session._diagnostics_by_uri = {"file:///a.yml": [{"message": "ok"}]}
    session._pump_once = lambda *_args: None
    assert session._wait_for_diagnostics("file:///a.yml", 0.1) == [{"message": "ok"}]
    assert session._wait_for_diagnostics("file:///missing.yml", 0.0) is None


def test_read_message_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    missing = _LspSession.__new__(_LspSession)
    missing._process = SimpleNamespace(stdout=None)
    missing._read_buffer = bytearray()
    with pytest.raises(VscodeValidationError, match="stdout is unavailable"):
        missing._read_message(0.1)

    payload = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    body = json.dumps(payload).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")

    buffered = _LspSession.__new__(_LspSession)
    buffered._process = SimpleNamespace(stdout=SimpleNamespace(fileno=lambda: 10))
    buffered._read_buffer = bytearray(header + body)
    assert buffered._read_message(0.1) == payload

    no_ready = _LspSession.__new__(_LspSession)
    no_ready._process = SimpleNamespace(stdout=SimpleNamespace(fileno=lambda: 11))
    no_ready._read_buffer = bytearray()
    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine._wait_for_fd",
        lambda *_args: False,
    )
    assert no_ready._read_message(0.1) is None

    closed = _LspSession.__new__(_LspSession)
    closed._process = SimpleNamespace(stdout=SimpleNamespace(fileno=lambda: 12))
    closed._read_buffer = bytearray()
    monkeypatch.setattr("azure_pipelines_validator.vscode_engine._wait_for_fd", lambda *_args: True)
    monkeypatch.setattr("azure_pipelines_validator.vscode_engine.os.read", lambda *_args: b"")
    with pytest.raises(VscodeValidationError, match="closed unexpectedly"):
        closed._read_message(0.1)


def test_drain_stderr_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    missing = _LspSession.__new__(_LspSession)
    missing._process = SimpleNamespace(stderr=None)
    assert missing._drain_stderr() == ""

    stderr = SimpleNamespace(
        fileno=lambda: 1,
        read=lambda: b"  message from stderr  ",
    )
    readable = _LspSession.__new__(_LspSession)
    readable._process = SimpleNamespace(stderr=stderr)
    monkeypatch.setattr("azure_pipelines_validator.vscode_engine._wait_for_fd", lambda *_args: True)
    assert readable._drain_stderr() == "message from stderr"

    broken = _LspSession.__new__(_LspSession)
    broken._process = SimpleNamespace(stderr=SimpleNamespace(fileno=lambda: 2))
    monkeypatch.setattr(
        "azure_pipelines_validator.vscode_engine._wait_for_fd",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("bad fd")),
    )
    assert broken._drain_stderr() == ""


def test_discover_installed_extension_selects_latest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("azure_pipelines_validator.vscode_engine.Path.home", lambda: tmp_path)
    cursor_root = tmp_path / ".cursor" / "extensions"
    vscode_root = tmp_path / ".vscode" / "extensions"
    cursor_root.mkdir(parents=True)
    vscode_root.mkdir(parents=True)

    old = cursor_root / "ms-azure-devops.azure-pipelines-1.0.0"
    new = vscode_root / "ms-azure-devops.azure-pipelines-2.0.0"
    incomplete = vscode_root / "ms-azure-devops.azure-pipelines-3.0.0"
    for candidate in (old, new, incomplete):
        (candidate / "dist").mkdir(parents=True)
    (old / "dist" / "server.js").write_text("// old", encoding="utf-8")
    (old / "service-schema.json").write_text("{}", encoding="utf-8")
    (new / "dist" / "server.js").write_text("// new", encoding="utf-8")
    (new / "service-schema.json").write_text("{}", encoding="utf-8")
    (incomplete / "service-schema.json").write_text("{}", encoding="utf-8")

    old_mtime = 1_000_000
    new_mtime = 2_000_000
    for file in old.rglob("*"):
        file.touch()
    for file in new.rglob("*"):
        file.touch()
    import os as _os

    _os.utime(old, (old_mtime, old_mtime))
    _os.utime(new, (new_mtime, new_mtime))

    server, schema = _discover_installed_extension()
    assert server == (new / "dist" / "server.js").resolve()
    assert schema == (new / "service-schema.json").resolve()
