# Agent Guidelines

## Python Code Style
- Follow Google Python Style Guide for all Python code changes.
- Keep functions focused, use clear names, and prefer explicit typing.
- Run formatting/linting before completion:
  - `uv run ruff check`
  - `uv run ruff format --check`

## Docstrings
- Use Google-style docstrings for all public modules, classes, and functions.
- Keep docstrings accurate and update them whenever behavior changes.
- Validate docstring style with:
  - `uvx --from pydocstyle pydocstyle --convention=google src tests`

## Pydantic Models
- Every Pydantic field must include a human-readable `description`.
- Descriptions should explain intent and expected value in plain language.
- Keep aliases and constraints (`gt`, `pattern`, etc.) alongside descriptions.

## Validation Gates
- Before merging, run:
  - `uv run ruff check`
  - `uv run ruff format --check`
  - `uv run python -m pytest`
  - `uv run python -m pytest --cov=src/azure_pipelines_validator --cov-report=term-missing --cov-fail-under=90`

## Runtime Expectations
- Azure LSP validation requires Node.js.
- The validator auto-detects `node` on `PATH` and auto-installs a compatible runtime to user cache when missing.
- Stage naming uses `lsp` (not `vscode`) in code, CLI options, and machine-readable output.
