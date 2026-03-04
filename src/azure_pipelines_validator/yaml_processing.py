"""Backward-compatible imports for legacy YAML processing module paths.

This module remains as a compatibility shim. New code should import from:

- ``azure_pipelines_validator.pipeline_documents``
- ``azure_pipelines_validator.preview_wrapper``
"""

from __future__ import annotations

from .pipeline_documents import DocumentLoader, YamlDocument, classify_document
from .preview_wrapper import TemplateWrapper

__all__ = [
    "DocumentLoader",
    "TemplateWrapper",
    "YamlDocument",
    "classify_document",
]
