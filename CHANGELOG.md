# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Breaking Changes
- Renamed CLI flags from `vscode` to `lsp`:
  - `--run-vscode/--skip-vscode` -> `--run-lsp/--skip-lsp`
  - `--vscode-server-path` -> `--lsp-server-path`
  - `--vscode-schema-path` -> `--lsp-schema-path`
  - `--vscode-timeout-seconds` -> `--lsp-timeout-seconds`
- Renamed environment variables from `AZP_VALIDATOR_VSCODE_*` to `AZP_VALIDATOR_LSP_*`.
- Renamed machine-readable stage key from `vscode` to `lsp` in JSON/NDJSON payloads.
- Renamed internal Python symbols:
  - `VscodeValidator` -> `LspValidator`
  - `VscodeValidationError` -> `LspValidationError`
  - `VscodeFinding` -> `LspFinding`
  - module `vscode_engine.py` -> `lsp_engine.py`

### Migration
- Replace CLI usage:
  - `azure-pipeline-validator validate --run-vscode`
  - with `azure-pipeline-validator validate --run-lsp`
- Replace env vars in CI and local scripts:
  - `AZP_VALIDATOR_VSCODE_CACHE_DIR` -> `AZP_VALIDATOR_LSP_CACHE_DIR`
  - `AZP_VALIDATOR_VSCODE_OFFLINE` -> `AZP_VALIDATOR_LSP_OFFLINE`
  - `AZP_VALIDATOR_VSCODE_VERSION` -> `AZP_VALIDATOR_LSP_VERSION`
  - `AZP_VALIDATOR_VSCODE_SHA256` -> `AZP_VALIDATOR_LSP_SHA256`
  - `AZP_VALIDATOR_VSCODE_DOWNLOAD_TIMEOUT_SECONDS` -> `AZP_VALIDATOR_LSP_DOWNLOAD_TIMEOUT_SECONDS`
