"""Azure Pipelines language-server backed validation.

This module executes validation through the Azure DevOps pipeline language
server (LSP) so diagnostics match editor behavior.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import platform
import re
import select
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence
from urllib.error import URLError
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile

from .exceptions import LspValidationError
from .models import LspFinding
from .pipeline_documents import YamlDocument

_EXTENSION_PREFIX = "ms-azure-devops.azure-pipelines-"
_DEFAULT_TIMEOUT_SECONDS = 5.0
_DEFAULT_EXTENSION_PUBLISHER = "ms-azure-devops"
_DEFAULT_EXTENSION_NAME = "azure-pipelines"
_DEFAULT_EXTENSION_VERSION = "latest"
_DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 30.0
_DEFAULT_CACHE_DIR = Path.home() / ".azure-pipeline-validator" / "lsp-assets"
_VSIX_ASSET_NAME = "Microsoft.VisualStudio.Services.VSIXPackage"
_DEFAULT_NODE_VERSION = "lts"
_DEFAULT_NODE_CACHE_DIR = Path.home() / ".azure-pipeline-validator" / "node-runtime"
_NODE_INDEX_URL = "https://nodejs.org/dist/index.json"
_NODE_SHASUMS_URL_TEMPLATE = "https://nodejs.org/dist/v{version}/SHASUMS256.txt"


class LspValidator:
    """Runs diagnostics using the Azure DevOps pipeline language server (LSP)."""

    def __init__(
        self,
        repo_root: Path,
        *,
        server_path: Path | None = None,
        schema_path: Path | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        node_binary: str = "node",
    ) -> None:
        """Initializes an Azure LSP language-server validator.

        Args:
            repo_root: Repository root used for LSP workspace initialization.
            server_path: Optional explicit path to the language server JavaScript
                entrypoint.
            schema_path: Optional explicit path to the language-server schema file.
            timeout_seconds: Per-request timeout budget for LSP communication.
            node_binary: Node.js executable used to launch the language server.

        Raises:
            LspValidationError: If server/schema paths cannot be resolved.
        """
        self._repo_root = repo_root.resolve()
        self._timeout_seconds = timeout_seconds
        self._node_binary = _resolve_node_binary(node_binary)
        resolved_server, resolved_schema = _resolve_server_and_schema(
            server_path=server_path,
            schema_path=schema_path,
        )
        self._server_path = resolved_server
        self._schema_path = resolved_schema

    @property
    def server_path(self) -> Path:
        """Returns the resolved language server path."""
        return self._server_path

    @property
    def schema_path(self) -> Path:
        """Returns the resolved schema path used by the language server."""
        return self._schema_path

    def run(self, documents: Sequence[YamlDocument]) -> dict[Path, tuple[LspFinding, ...]]:
        """Runs LSP diagnostics for a batch of YAML documents.

        Args:
            documents: Documents to validate.

        Returns:
            Mapping from document path to the tuple of emitted findings.

        Raises:
            LspValidationError: If the language server cannot initialize or a
                document diagnostic request times out.
        """
        if not documents:
            return {}
        with _LspSession(
            repo_root=self._repo_root,
            server_path=self._server_path,
            schema_path=self._schema_path,
            timeout_seconds=self._timeout_seconds,
            node_binary=self._node_binary,
        ) as session:
            results: dict[Path, tuple[LspFinding, ...]] = {}
            for document in documents:
                results[document.path] = session.validate_document(document)
            return results


class _LspSession:
    def __init__(
        self,
        *,
        repo_root: Path,
        server_path: Path,
        schema_path: Path,
        timeout_seconds: float,
        node_binary: str,
    ) -> None:
        self._repo_root = repo_root
        self._schema_path = schema_path
        self._schema_uri = schema_path.resolve().as_uri()
        self._schema_text = schema_path.read_text(encoding="utf-8")
        self._timeout_seconds = timeout_seconds
        try:
            self._process = subprocess.Popen(
                [node_binary, str(server_path), "--stdio"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                env={**os.environ, "VSCODE_NLS_CONFIG": "{}"},
            )
        except FileNotFoundError as error:
            raise LspValidationError(
                f"Unable to launch Azure LSP language server because '{node_binary}' was not found."
            ) from error
        self._next_id = 1
        self._responses: dict[int, dict[str, Any]] = {}
        self._diagnostics_by_uri: dict[str, list[dict[str, Any]]] = {}
        self._read_buffer = bytearray()
        self._initialize()

    def __enter__(self) -> "_LspSession":
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        try:
            self._shutdown()
        finally:
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self._process.kill()

    def validate_document(self, document: YamlDocument) -> tuple[LspFinding, ...]:
        uri = document.path.resolve().as_uri()
        self._diagnostics_by_uri.pop(uri, None)

        self._send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": "yaml",
                    "version": 1,
                    "text": document.content,
                }
            },
        )

        diagnostics = self._wait_for_diagnostics(uri, self._timeout_seconds)
        self._send_notification("textDocument/didClose", {"textDocument": {"uri": uri}})

        if diagnostics is None:
            stderr = self._drain_stderr()
            details = f" (stderr: {stderr})" if stderr else ""
            raise LspValidationError(
                f"Timed out waiting for Azure LSP diagnostics for {document.path}{details}"
            )

        findings: list[LspFinding] = []
        for item in diagnostics:
            start = item.get("range", {}).get("start", {})
            line = int(start.get("line", 0)) + 1
            column = int(start.get("character", 0)) + 1
            findings.append(
                LspFinding(
                    path=document.path,
                    line=line,
                    column=column,
                    severity=_severity_label(item.get("severity")),
                    message=str(item.get("message", "")).strip(),
                    code=item.get("code"),
                )
            )
        return tuple(findings)

    def _initialize(self) -> None:
        response = self._send_request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": self._repo_root.as_uri(),
                "capabilities": {},
                "workspaceFolders": [
                    {"uri": self._repo_root.as_uri(), "name": self._repo_root.name}
                ],
            },
        )
        if response.get("error"):
            raise LspValidationError(
                f"Azure LSP language server initialize failed: {response['error']}"
            )

        self._send_notification("initialized", {})
        self._send_notification(
            "workspace/didChangeConfiguration",
            {
                "settings": {
                    "yaml": {
                        "validate": True,
                        "schemaStore": {"enable": False},
                        "schemas": {self._schema_uri: ["*"]},
                    }
                }
            },
        )
        self._send_notification("json/schemaAssociations", {"*": [self._schema_uri]})

    def _shutdown(self) -> None:
        try:
            self._send_request("shutdown", {})
        except Exception:
            return
        self._send_notification("exit", {})

    def _send_request(self, method: str, params: Any) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self._timeout_seconds
        while time.monotonic() < deadline:
            remaining = max(deadline - time.monotonic(), 0.01)
            self._pump_once(remaining)
            if request_id in self._responses:
                return self._responses.pop(request_id)
        raise LspValidationError(f"Timed out waiting for LSP response to '{method}'")

    def _send_notification(self, method: str, params: Any) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _wait_for_diagnostics(
        self, uri: str, timeout_seconds: float
    ) -> list[dict[str, Any]] | None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if uri in self._diagnostics_by_uri:
                return self._diagnostics_by_uri.pop(uri)
            remaining = max(deadline - time.monotonic(), 0.01)
            self._pump_once(remaining)
        return None

    def _pump_once(self, timeout_seconds: float) -> None:
        message = self._read_message(timeout_seconds)
        if message is None:
            return
        method = message.get("method")
        message_id = message.get("id")

        if method == "textDocument/publishDiagnostics":
            params = message.get("params") or {}
            uri = params.get("uri")
            if uri:
                self._diagnostics_by_uri[str(uri)] = list(params.get("diagnostics") or [])
            return

        if method and message_id is not None:
            result = self._handle_server_request(method, message.get("params"))
            self._send({"jsonrpc": "2.0", "id": message_id, "result": result})
            return

        if message_id is not None and "method" not in message:
            self._responses[int(message_id)] = message

    def _handle_server_request(self, method: str, params: Any) -> Any:
        if method == "custom/schema/request":
            return self._schema_uri
        if method == "custom/schema/content":
            uri = str(params or "")
            if uri == self._schema_uri:
                return self._schema_text
            if uri.startswith("file://"):
                try:
                    return Path(uri.replace("file://", "", 1)).read_text(encoding="utf-8")
                except Exception:
                    return ""
            return ""
        if method == "vscode/content":
            return ""
        return None

    def _send(self, payload: dict[str, Any]) -> None:
        if self._process.stdin is None:
            raise LspValidationError("Azure LSP language server stdin is unavailable")
        content = json.dumps(payload).encode("utf-8")
        header = f"Content-Length: {len(content)}\r\n\r\n".encode("ascii")
        self._process.stdin.write(header + content)
        self._process.stdin.flush()

    def _read_message(self, timeout_seconds: float) -> dict[str, Any] | None:
        if self._process.stdout is None:
            raise LspValidationError("Azure LSP language server stdout is unavailable")
        fd = self._process.stdout.fileno()
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            parsed = _try_parse_message(self._read_buffer)
            if parsed is not None:
                message, consumed = parsed
                del self._read_buffer[:consumed]
                return message

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            if not _wait_for_fd(fd, remaining):
                return None
            chunk = os.read(fd, 8192)
            if not chunk:
                raise LspValidationError("Azure LSP language server closed unexpectedly")
            self._read_buffer.extend(chunk)
        return None

    def _drain_stderr(self) -> str:
        if self._process.stderr is None:
            return ""
        fd = self._process.stderr.fileno()
        chunks: list[bytes] = []
        try:
            while _wait_for_fd(fd, 0.05):
                try:
                    chunk = os.read(fd, 8192)
                except OSError as error:
                    if error.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                        break
                    raise
                if not chunk:
                    break
                chunks.append(chunk)
        except Exception:
            return ""
        return b"".join(chunks).decode("utf-8", errors="replace").strip()


def _wait_for_fd(fd: int, timeout_seconds: float) -> bool:
    try:
        ready, _, _ = select.select([fd], [], [], timeout_seconds)
        return bool(ready)
    except Exception:
        # Fallback for platforms/selectors where subprocess pipes are unsupported.
        return True


def _try_parse_message(buffer: bytearray) -> tuple[dict[str, Any], int] | None:
    header_end = buffer.find(b"\r\n\r\n")
    if header_end < 0:
        return None

    header_bytes = bytes(buffer[:header_end])
    content_length = 0
    for line in header_bytes.splitlines():
        text = line.decode("ascii", errors="replace")
        if text.lower().startswith("content-length:"):
            try:
                content_length = int(text.split(":", 1)[1].strip())
            except ValueError as exc:
                raise LspValidationError(f"Invalid content-length header: {text}") from exc
            break
    if content_length <= 0:
        raise LspValidationError("Missing Content-Length header from language server")

    payload_start = header_end + 4
    payload_end = payload_start + content_length
    if len(buffer) < payload_end:
        return None

    payload = bytes(buffer[payload_start:payload_end])
    return json.loads(payload.decode("utf-8")), payload_end


def _severity_label(raw: Any) -> str:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return "unknown"
    if value == 1:
        return "error"
    if value == 2:
        return "warning"
    if value == 3:
        return "info"
    if value == 4:
        return "hint"
    return "unknown"


def _resolve_server_and_schema(
    *,
    server_path: Path | None,
    schema_path: Path | None,
) -> tuple[Path, Path]:
    if (server_path is None) != (schema_path is None):
        raise LspValidationError("Pass both --lsp-server-path and --lsp-schema-path together.")

    if server_path and schema_path:
        return _validate_paths(server_path.resolve(), schema_path.resolve())

    discovered = _discover_installed_extension()
    if discovered is not None:
        discovered_server, discovered_schema = discovered
        return _validate_paths(discovered_server, discovered_schema)

    discovered_server, discovered_schema = _resolve_bootstrapped_extension()
    return _validate_paths(
        server_path.resolve() if server_path else discovered_server,
        schema_path.resolve() if schema_path else discovered_schema,
    )


def _validate_paths(server_path: Path, schema_path: Path) -> tuple[Path, Path]:
    if not server_path.exists():
        raise LspValidationError(f"Azure LSP language server not found: {server_path}")
    if not schema_path.exists():
        raise LspValidationError(f"Azure LSP schema file not found: {schema_path}")
    return server_path, schema_path


def _discover_installed_extension() -> tuple[Path, Path] | None:
    roots = (
        Path.home() / ".cursor" / "extensions",
        Path.home() / ".vscode" / "extensions",
    )
    installations: list[tuple[tuple[int, int, int], float, Path, Path]] = []
    for root in roots:
        if not root.exists():
            continue
        for candidate in root.glob(f"{_EXTENSION_PREFIX}*"):
            if not candidate.is_dir():
                continue
            server_path = candidate / "dist" / "server.js"
            schema_path = candidate / "service-schema.json"
            if not server_path.exists() or not schema_path.exists():
                continue
            stat = candidate.stat()
            installations.append(
                (_extract_version_key(candidate.name), stat.st_mtime, server_path, schema_path)
            )

    if not installations:
        return None

    installations.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, _, server, schema = installations[0]
    return server.resolve(), schema.resolve()


def _resolve_bootstrapped_extension() -> tuple[Path, Path]:
    publisher = os.getenv("AZP_VALIDATOR_LSP_PUBLISHER", _DEFAULT_EXTENSION_PUBLISHER)
    extension = os.getenv("AZP_VALIDATOR_LSP_EXTENSION", _DEFAULT_EXTENSION_NAME)
    version = os.getenv("AZP_VALIDATOR_LSP_VERSION", _DEFAULT_EXTENSION_VERSION)
    cache_root = Path(
        os.getenv("AZP_VALIDATOR_LSP_CACHE_DIR", str(_DEFAULT_CACHE_DIR))
    ).expanduser()
    cache_dir = cache_root / f"{publisher}.{extension}" / version
    server_path = cache_dir / "dist" / "server.js"
    schema_path = cache_dir / "service-schema.json"
    if server_path.exists() and schema_path.exists():
        return server_path.resolve(), schema_path.resolve()

    if _env_flag("AZP_VALIDATOR_LSP_OFFLINE"):
        raise LspValidationError(
            "Azure LSP assets are not cached and offline mode is enabled. "
            "Pre-seed the cache or disable AZP_VALIDATOR_LSP_OFFLINE."
        )

    download_url = (
        f"https://{publisher}.gallery.vsassets.io/_apis/public/gallery/publisher/"
        f"{publisher}/extension/{extension}/{version}/assetbyname/{_VSIX_ASSET_NAME}"
    )
    expected_sha256 = os.getenv("AZP_VALIDATOR_LSP_SHA256")
    timeout_seconds = _env_float(
        "AZP_VALIDATOR_LSP_DOWNLOAD_TIMEOUT_SECONDS",
        _DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    )
    _bootstrap_extension_assets(
        download_url=download_url,
        cache_dir=cache_dir,
        timeout_seconds=timeout_seconds,
        expected_sha256=expected_sha256,
    )
    return _validate_paths(server_path.resolve(), schema_path.resolve())


def _bootstrap_extension_assets(
    *,
    download_url: str,
    cache_dir: Path,
    timeout_seconds: float,
    expected_sha256: str | None,
) -> None:
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lsp-assets-") as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / "extension.vsix"
        extract_path = temp_path / "extract"
        try:
            with urlopen(download_url, timeout=timeout_seconds) as response:
                archive_path.write_bytes(response.read())
        except URLError as exc:
            raise LspValidationError(
                f"Unable to download Azure Pipelines language-server assets: {exc}"
            ) from exc

        if expected_sha256:
            actual_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            if actual_sha256.lower() != expected_sha256.lower():
                raise LspValidationError(
                    "Downloaded VSIX checksum mismatch. "
                    f"expected={expected_sha256.lower()} actual={actual_sha256.lower()}"
                )

        try:
            with ZipFile(archive_path) as archive:
                _extract_vsix_member(
                    archive, "extension/dist/server.js", extract_path / "dist" / "server.js"
                )
                _extract_vsix_member(
                    archive,
                    "extension/service-schema.json",
                    extract_path / "service-schema.json",
                )
        except (BadZipFile, KeyError) as exc:
            raise LspValidationError(
                "Downloaded VSIX archive is invalid or missing required files."
            ) from exc

        target_parent = cache_dir.parent
        target_name = cache_dir.name
        temp_target = target_parent / f".{target_name}.tmp"
        if temp_target.exists():
            shutil.rmtree(temp_target)
        shutil.move(str(extract_path), str(temp_target))
        shutil.rmtree(cache_dir, ignore_errors=True)
        temp_target.replace(cache_dir)


def _extract_vsix_member(archive: ZipFile, member_name: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(member_name) as source, target_path.open("wb") as destination:
        shutil.copyfileobj(source, destination)


def _resolve_node_binary(node_binary: str) -> str:
    resolved = shutil.which(node_binary)
    if resolved:
        return resolved

    if node_binary != "node":
        raise LspValidationError(
            f"Unable to launch Azure LSP language server because '{node_binary}' was not found."
        )

    timeout_seconds = _env_float(
        "AZP_VALIDATOR_NODE_DOWNLOAD_TIMEOUT_SECONDS",
        _DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    )
    version_spec = os.getenv("AZP_VALIDATOR_NODE_VERSION", _DEFAULT_NODE_VERSION)
    cache_root = Path(
        os.getenv("AZP_VALIDATOR_NODE_CACHE_DIR", str(_DEFAULT_NODE_CACHE_DIR))
    ).expanduser()
    try:
        return str(
            _install_node_runtime(
                version_spec=version_spec,
                cache_root=cache_root,
                timeout_seconds=timeout_seconds,
            )
        )
    except LspValidationError:
        raise
    except Exception as exc:
        raise LspValidationError(
            "Node.js runtime auto-install failed. Install Node.js manually or set "
            "AZP_VALIDATOR_NODE_VERSION/AZP_VALIDATOR_NODE_CACHE_DIR."
        ) from exc


def _install_node_runtime(*, version_spec: str, cache_root: Path, timeout_seconds: float) -> Path:
    platform_key = _detect_node_platform_key()
    cached_alias_binary = _find_cached_node_binary_for_alias(
        version_spec=version_spec,
        cache_root=cache_root,
        platform_key=platform_key,
    )
    if cached_alias_binary is not None:
        return cached_alias_binary.resolve()

    version = _resolve_node_version(version_spec, timeout_seconds=timeout_seconds)
    install_dir = cache_root / f"node-v{version}" / platform_key
    node_path = _node_binary_path_for_install(install_dir, platform_key)
    if node_path.exists():
        return node_path.resolve()

    base_name = f"node-v{version}-{platform_key}"
    extension = "zip" if platform_key.startswith("win-") else "tar.xz"
    archive_filename = f"{base_name}.{extension}"
    download_url = f"https://nodejs.org/dist/v{version}/{archive_filename}"
    expected_sha256 = _resolve_node_archive_sha256(
        version=version,
        archive_filename=archive_filename,
        timeout_seconds=timeout_seconds,
    )

    cache_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="node-runtime-") as temp_dir:
        temp_path = Path(temp_dir)
        archive_download_path = temp_path / f"{archive_filename}.download"
        archive_path = temp_path / archive_filename
        extract_path = temp_path / "extract"
        try:
            actual_sha256 = _download_file_with_sha256(
                download_url=download_url,
                destination_path=archive_download_path,
                timeout_seconds=timeout_seconds,
            )
        except URLError as exc:
            raise LspValidationError(
                f"Unable to download Node.js runtime archive from {download_url}: {exc}"
            ) from exc
        if actual_sha256.lower() != expected_sha256.lower():
            raise LspValidationError(
                "Downloaded Node.js archive checksum mismatch. "
                f"expected={expected_sha256.lower()} actual={actual_sha256.lower()}"
            )
        archive_download_path.replace(archive_path)

        try:
            if extension == "zip":
                with ZipFile(archive_path) as archive:
                    _safe_extract_zip_archive(archive, extract_path)
            else:
                with tarfile.open(archive_path, mode="r:*") as archive:
                    _safe_extract_tar_archive(archive, extract_path)
        except (BadZipFile, tarfile.TarError, OSError) as exc:
            raise LspValidationError("Downloaded Node.js archive is invalid.") from exc

        extracted_root = extract_path / base_name
        if not extracted_root.exists():
            raise LspValidationError(
                "Downloaded Node.js archive did not contain expected runtime layout."
            )

        target_parent = install_dir.parent
        target_name = install_dir.name
        temp_target = target_parent / f".{target_name}.tmp"
        if temp_target.exists():
            shutil.rmtree(temp_target)
        shutil.move(str(extracted_root), str(temp_target))
        shutil.rmtree(install_dir, ignore_errors=True)
        temp_target.replace(install_dir)

    if not node_path.exists():
        raise LspValidationError(
            "Node.js runtime install completed but the node executable was not found."
        )
    if not platform_key.startswith("win-"):
        node_path.chmod(node_path.stat().st_mode | 0o111)
    return node_path.resolve()


def _find_cached_node_binary_for_alias(
    *, version_spec: str, cache_root: Path, platform_key: str
) -> Path | None:
    alias = version_spec.strip().lower()
    if alias not in {"lts", "latest"}:
        return None

    candidates: list[tuple[tuple[int, int, int], float, Path]] = []
    for version_root in cache_root.glob("node-v*"):
        if not version_root.is_dir():
            continue
        install_dir = version_root / platform_key
        node_path = _node_binary_path_for_install(install_dir, platform_key)
        if not node_path.exists():
            continue
        candidates.append(
            (_extract_version_key(version_root.name), node_path.stat().st_mtime, node_path)
        )

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _node_binary_path_for_install(install_dir: Path, platform_key: str) -> Path:
    if platform_key.startswith("win-"):
        return install_dir / "node.exe"
    return install_dir / "bin" / "node"


def _resolve_node_archive_sha256(
    *, version: str, archive_filename: str, timeout_seconds: float
) -> str:
    shasums_url = _NODE_SHASUMS_URL_TEMPLATE.format(version=version)
    try:
        with urlopen(shasums_url, timeout=timeout_seconds) as response:
            content = response.read().decode("utf-8")
    except (URLError, UnicodeDecodeError) as exc:
        raise LspValidationError(
            f"Unable to resolve Node.js archive checksum from {shasums_url}: {exc}"
        ) from exc

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        checksum, filename = parts
        normalized_filename = filename.lstrip("*").strip()
        if normalized_filename != archive_filename:
            continue
        if not re.fullmatch(r"[0-9a-fA-F]{64}", checksum):
            break
        return checksum.lower()

    raise LspValidationError(
        f"Unable to find a SHA256 checksum for Node.js archive '{archive_filename}'."
    )


def _download_file_with_sha256(
    *, download_url: str, destination_path: Path, timeout_seconds: float
) -> str:
    sha256 = hashlib.sha256()
    with (
        urlopen(download_url, timeout=timeout_seconds) as response,
        destination_path.open("wb") as destination,
    ):
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            destination.write(chunk)
            sha256.update(chunk)
    return sha256.hexdigest()


def _safe_extract_zip_archive(archive: ZipFile, extract_root: Path) -> None:
    for member in archive.infolist():
        member_path = _validate_archive_member_path(member.filename)
        target_path = extract_root / member_path
        _ensure_within_extract_root(extract_root, target_path)
        if member.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            continue
        _extract_vsix_member(archive, member.filename, target_path)


def _safe_extract_tar_archive(archive: tarfile.TarFile, extract_root: Path) -> None:
    for member in archive.getmembers():
        member_path = _validate_archive_member_path(member.name)
        target_path = extract_root / member_path
        _ensure_within_extract_root(extract_root, target_path)

        if member.isdir():
            target_path.mkdir(parents=True, exist_ok=True)
            continue

        if member.isfile():
            source = archive.extractfile(member)
            if source is None:
                raise LspValidationError(
                    "Downloaded Node.js archive contains an unreadable file entry."
                )
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with source, target_path.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            target_path.chmod(member.mode & 0o777)
            continue

        if member.issym():
            link_target = Path(member.linkname)
            if link_target.is_absolute():
                raise LspValidationError(
                    "Downloaded Node.js archive contains an absolute symlink target."
                )
            resolved_link = (target_path.parent / link_target).resolve()
            _ensure_within_extract_root(extract_root, resolved_link)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists() or target_path.is_symlink():
                target_path.unlink()
            os.symlink(member.linkname, target_path)
            continue

        if member.islnk():
            hard_link_source = extract_root / _validate_archive_member_path(member.linkname)
            _ensure_within_extract_root(extract_root, hard_link_source)
            if not hard_link_source.exists():
                raise LspValidationError(
                    "Downloaded Node.js archive contains a hard-link entry to a missing target."
                )
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists() or target_path.is_symlink():
                target_path.unlink()
            os.link(hard_link_source, target_path)
            continue

        raise LspValidationError("Downloaded Node.js archive contains unsupported entry types.")


def _validate_archive_member_path(member_name: str) -> Path:
    path = Path(member_name)
    if path.is_absolute() or ".." in path.parts:
        raise LspValidationError(
            f"Downloaded archive contains an unsafe entry path: {member_name!r}"
        )
    normalized_parts = tuple(part for part in path.parts if part not in {"", "."})
    if not normalized_parts:
        raise LspValidationError("Downloaded archive contains an empty entry path.")
    return Path(*normalized_parts)


def _ensure_within_extract_root(extract_root: Path, target_path: Path) -> None:
    root = extract_root.resolve()
    resolved_target = target_path.resolve()
    try:
        resolved_target.relative_to(root)
    except ValueError as exc:
        raise LspValidationError(
            f"Downloaded archive path escapes extraction root: {target_path!s}"
        ) from exc


def _resolve_node_version(version_spec: str, *, timeout_seconds: float) -> str:
    value = version_spec.strip().lower()
    if re.fullmatch(r"v?\d+\.\d+\.\d+", value):
        return value.lstrip("v")
    if value not in {"lts", "latest"}:
        raise LspValidationError(
            "Environment variable AZP_VALIDATOR_NODE_VERSION must be 'lts', 'latest', "
            "or a full semantic version like '22.13.1'."
        )

    try:
        with urlopen(_NODE_INDEX_URL, timeout=timeout_seconds) as response:
            releases = json.loads(response.read().decode("utf-8"))
    except (URLError, json.JSONDecodeError) as exc:
        raise LspValidationError(f"Unable to resolve Node.js {value} version: {exc}") from exc

    if not isinstance(releases, list):
        raise LspValidationError("Node.js release index response was not a list.")

    for release in releases:
        if not isinstance(release, dict):
            continue
        if value == "lts" and not release.get("lts"):
            continue
        raw_version = str(release.get("version", ""))
        if re.fullmatch(r"v\d+\.\d+\.\d+", raw_version):
            return raw_version.lstrip("v")
    raise LspValidationError(f"Could not find a Node.js {value} release in the upstream index.")


def _detect_node_platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    aliases = {
        "x86_64": "x64",
        "amd64": "x64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }
    normalized_machine = aliases.get(machine, machine)

    if system == "darwin" and normalized_machine in {"x64", "arm64"}:
        return f"darwin-{normalized_machine}"
    if system == "linux" and normalized_machine in {"x64", "arm64"}:
        return f"linux-{normalized_machine}"
    if system == "windows" and normalized_machine in {"x64", "arm64"}:
        return f"win-{normalized_machine}"
    raise LspValidationError(
        f"Automatic Node.js installation is not supported on this platform: {system}/{machine}"
    )


def _env_flag(name: str) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise LspValidationError(f"Environment variable {name} must be a number.") from exc
    if value <= 0:
        raise LspValidationError(f"Environment variable {name} must be greater than zero.")
    return value


def _extract_version_key(folder_name: str) -> tuple[int, int, int]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", folder_name)
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())
