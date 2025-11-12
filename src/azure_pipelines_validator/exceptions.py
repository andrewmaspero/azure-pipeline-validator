"""Domain specific exceptions for the validator."""

from __future__ import annotations


class SettingsError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


class AzureDevOpsError(RuntimeError):
    """Wraps errors returned by the Azure DevOps REST API."""

    def __init__(self, status_code: int, detail: str) -> None:
        message = f"Azure DevOps responded with HTTP {status_code}: {detail}"
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class SchemaUnavailableError(RuntimeError):
    """Raised when the remote schema cannot be retrieved."""


class ValidationHalt(RuntimeError):
    """Raised when validation stops early because of fail-fast."""
