"""Azure Pipelines YAML validation toolkit."""

from importlib import metadata

try:
    __version__ = metadata.version("azure-pipelines-validator")
except metadata.PackageNotFoundError:  # pragma: no cover - fallback for editable installs
    __version__ = "0.0.0"

__all__ = ["__version__"]
