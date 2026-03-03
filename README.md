# Azure Pipeline Validator

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?logo=open-source-initiative&logoColor=white)](LICENSE)
[![Python Version](https://img.shields.io/badge/Python-3.13+-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Tests](https://img.shields.io/badge/Tests-pytest-0A9EDC?logo=pytest&logoColor=white)](https://docs.pytest.org/)
[![Lint](https://img.shields.io/badge/Lint-Ruff-000000?logo=ruff&logoColor=white)](https://docs.astral.sh/ruff/)
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)](./.github/workflows/ci.yml)

`azure-pipeline-validator` is a batteries‑included Azure DevOps YAML inspector that runs the same validations you rely on in the service, but locally.

It is **authoritative-first by default**:
1. **Preview REST API** – invokes `POST .../_apis/pipelines/{id}/preview` with `yamlOverride`, returning real `finalYaml` + `validationResults`.
2. **VS Code extension language server** – runs the Azure Pipelines language server (`ms-azure-devops.azure-pipelines`) so diagnostics align with editor behavior.

Optional advisory checks are still available:
3. **yamllint** – fast structural/style linting.
4. **JSON Schema** – generic schema check (soft-deprecated for Azure correctness decisions).

The CLI understands both single files and whole repositories, wraps templates automatically (steps/jobs/stages), and mirrors the live API response schema (including `continuation_token`).

## Table of contents

- [Azure Pipeline Validator](#azure-pipeline-validator)
  - [Table of contents](#table-of-contents)
  - [Features](#features)
  - [Installation \& invocation](#installation--invocation)
  - [Required environment](#required-environment)
  - [Usage examples](#usage-examples)
  - [CLI reference](#cli-reference)
  - [Output format](#output-format)
  - [CI integration](#ci-integration)
  - [Development workflow](#development-workflow)
  - [Publishing the package](#publishing-the-package)
  - [Troubleshooting](#troubleshooting)
  - [License](#license)

## Features

- **Template auto-wrapping** – detects steps/jobs/stages templates, wrapping them into runnable pipelines before previewing.
- **Authoritative-first defaults** – defaults to preview + vscode for correctness gating.
- **Schema soft-deprecation** – schema check remains available but is flagged as advisory/deprecated for correctness.
- **Rich reporting** – console output shows passed/failed/skipped/error per file with the first offending message per stage.
- **Machine-readable output** – emit `json` (single payload) or `ndjson` (file records + summary) for CI ingestion.
- **VS Code parity checks** – catches extension-level diagnostics (template-expression aware) that generic YAML tooling can miss.
- **Toggleable stages** – enable/disable advisory and authoritative stages explicitly.
- **Blocking policy controls** – `--gate-mode authoritative|all` plus explicit blocking/advisory counts.
- **UV-native** – built with [uv](https://docs.astral.sh/uv/), so you can run it via `uv run`, `uvx`, or install it as a global tool.

## Installation & invocation

Local development (inside this repo):

```bash
cd /path/to/azure-pipeline-validator
uv run azure-pipeline-validator --help
```

Published usage via `uvx` (no clone required):

```bash
uvx azure-pipeline-validator --help
```

Global install with uv (install once, use anywhere):

```bash
uv tool install git+https://github.com/andrewmaspero/azure-pipeline-validator.git
azure-pipeline-validator --help
```

Once published to PyPI, you can also use:
```bash
uv tool install azure-pipeline-validator
azure-pipeline-validator --help
```

Pip install will also work once published (`pip install azure-pipeline-validator`).

## Required environment

Environment variables (or their CLI equivalents) are required for default authoritative validation (`preview` is on by default). Pure local lint-only runs (`--skip-preview --skip-vscode --run-yamllint`) do not need Azure credentials.

Export the same variables you would in an Azure Pipelines job, or pass them via the `--azdo-*` options:

| Variable | Description |
| --- | --- |
| `AZDO_ORG` / `--azdo-org` | Organization URL, e.g. `https://dev.azure.com/contoso`. |
| `AZDO_PROJECT` / `--azdo-project` | Project that owns the pipeline. |
| `AZDO_PIPELINE_ID` / `--azdo-pipeline-id` | ID of an existing YAML pipeline (any pipeline is fine). |
| `AZDO_PAT` / `--azdo-pat` | PAT with Build (Read & Execute); use `SYSTEM_ACCESSTOKEN` inside CI. |
| `AZDO_REFNAME` | Optional ref used when expanding templates (default `refs/heads/main`). |
| `AZDO_TIMEOUT_SECONDS` | Optional HTTP timeout override (default 30). |

> **Tip:** Inside Azure Pipelines you can skip `AZDO_PAT` by enabling “Allow scripts to access the OAuth token” and mapping it to `SYSTEM_ACCESSTOKEN`.

## Usage examples

Run the authoritative default (recommended):

```bash
uv run azure-pipeline-validator validate . \
  --repo-root $(pwd)
```

Run strict all-stage gating (legacy-like strictness):

```bash
uv run azure-pipeline-validator validate . \
  --repo-root $(pwd) \
  --run-yamllint --run-schema \
  --gate-mode all
```

Run authoritative-only checks explicitly:

```bash
uv run azure-pipeline-validator validate workflows/ \
  --skip-yamllint --skip-schema \
  --gate-mode authoritative
```

Validate with explicit VS Code extension artifacts:

```bash
uv run azure-pipeline-validator validate . \
  --run-vscode \
  --vscode-server-path ~/.cursor/extensions/ms-azure-devops.azure-pipelines-1.261.1/dist/server.js \
  --vscode-schema-path ~/.cursor/extensions/ms-azure-devops.azure-pipelines-1.261.1/service-schema.json
```

Self-contained VS Code mode (no local extension install required):
- If no local Azure Pipelines extension is found and no explicit `--vscode-*` paths are provided, the validator auto-downloads the extension VSIX and caches `dist/server.js` + `service-schema.json`.
- Optional environment controls:
  - `AZP_VALIDATOR_VSCODE_OFFLINE=true` forces cache-only behavior.
  - `AZP_VALIDATOR_VSCODE_CACHE_DIR=/path/to/cache` sets the cache directory (default: `~/.azure-pipeline-validator/vscode-assets`).
  - `AZP_VALIDATOR_VSCODE_VERSION=latest` pins extension version (defaults to `latest`).
  - `AZP_VALIDATOR_VSCODE_SHA256=<hex>` enforces archive checksum verification.
  - `AZP_VALIDATOR_VSCODE_DOWNLOAD_TIMEOUT_SECONDS=30` sets download timeout.

## CLI reference

```text
Usage: azure-pipeline-validator [OPTIONS] [PATH]

Run authoritative Azure validation by default (preview + vscode), with optional advisory yamllint/schema checks.

Arguments:
  PATH  File or directory to validate. Directories are scanned recursively for *.yml and *.yaml files.  [default: .]

Options:
  --repo-root PATH                     Base path used when resolving template references (defaults to CWD).
  --run-yamllint / --skip-yamllint     Enable or disable optional advisory yamllint checks.  [default: skip-yamllint]
  --run-schema / --skip-schema         Enable or disable deprecated advisory schema checks.  [default: skip-schema]
  --run-preview / --skip-preview       Call the Azure DevOps preview endpoint to fetch the compiled finalYaml.
  --run-vscode / --skip-vscode         Validate via Azure Pipelines VS Code language server.
  --vscode-server-path PATH            Path to extension server (dist/server.js).
  --vscode-schema-path PATH            Path to extension schema (service-schema.json).
  --vscode-timeout-seconds SECONDS     Diagnostics wait timeout per file.  [default: 5.0]
  --output-format FORMAT               Reporter output format.  [default: text]
  --gate-mode MODE                     Blocking policy for exit code: authoritative|all.  [default: authoritative]
  --fail-fast / --no-fail-fast         Stop immediately after the first file that fails validation.
  --help                               Show this message and exit.
```

## Output format

`--output-format text` (default): every file gets one row with four columns (yamllint / schema / preview / vscode). A passing stage prints `pass`; skipped stages print `skip`; failing/error stages show the first message (plus a “(+N more)” suffix when applicable). Example:

```text
╭──────────────────────┬──────────┬────────┬──────────────────────┬──────────────────────╮
│ File                 │ yamllint │ schema │ preview              │ vscode               │
├──────────────────────┼──────────┼────────┼──────────────────────┼──────────────────────┤
│ workflows/ci.yml     │ pass     │ pass   │ pass                 │ pass                 │
│ workflows/deploy.yml │ pass     │ pass   │ pass                 │ L12 C9: pattern ...  │
╰──────────────────────┴──────────┴────────┴──────────────────────┴──────────────────────╯
Validated 2 file(s). Blocking failures: 1. Advisory-only files: 0. Gate mode: authoritative.
```

`--output-format json`: emits one stable JSON object with `schema_version`, `summary`, and `files`.

`--output-format ndjson`: emits one JSON object per line (`type=file` records followed by a final `type=summary` record).

Summary metadata includes `fail_fast`, `stopped_early`, and `discovered_files`.
Summary metadata also includes `warnings` for deprecations/fallbacks.

Exit code behavior follows the active gate mode and still returns non-zero for runtime errors (for example preview/schema/vscode engine failures).

Blocking behavior is controlled by `--gate-mode`:

- `authoritative` (default): only Azure-authoritative stages (`preview`, `vscode`) fail the command.
- `all`: any enabled stage (`yamllint`, `schema`, `preview`, `vscode`) can fail the command.

Schema stage is **soft-deprecated** for Azure correctness decisions and emits a warning when enabled.

Migration note:
- If your CI previously relied on schema/yamllint failures as blockers, switch to:
  `--run-yamllint --run-schema --gate-mode all`

## Authoritative-First Defaults

Default behavior:
- `preview`: on
- `vscode`: on
- `yamllint`: off (opt-in advisory)
- `schema`: off (opt-in, deprecated advisory)
- gate mode: `authoritative`

## Source Of Truth (Azure Pipelines vs Red Hat YAML)

If you see a large error count in VS Code (for example dozens of errors) but only one Azure Pipelines error, you are usually seeing two validators at once:

- Azure Pipelines extension (`ms-azure-devops.azure-pipelines`)
- Red Hat YAML extension (`redhat.vscode-yaml`) using `yaml.schemas`

For Azure DevOps pipeline/template syntax, the practical source-of-truth order is:

1. Azure DevOps service preview API (`--run-preview`)
2. Azure Pipelines VS Code language server (`--run-vscode`)
3. Generic schema/yamllint checks (`--run-schema`, `--run-yamllint`) as supplemental signals

Why counts differ:
- The Red Hat YAML extension performs generic YAML+JSON-Schema validation and does not fully emulate Azure template-expression semantics.
- Azure Pipelines language server understands Azure-specific constructs and usually reports the actionable pipeline error set.

Recommended VS Code setup:
- Do not pin Azure Pipelines files to Microsoft schema via Red Hat `yaml.schemas` when the Azure Pipelines extension is enabled.
- Keep Red Hat YAML for non-pipeline YAML files.
- Treat Azure Pipelines diagnostics (plus service preview) as authoritative for pipeline correctness.

## CI integration

Add a job that installs uv, exports `AZDO_*`, and runs the command. When running inside Azure Pipelines you can reuse `$(System.AccessToken)` and the current pipeline id:

```yaml
- job: Validate
  pool:
    vmImage: ubuntu-latest
  steps:
    - task: UsePythonVersion@0
      inputs:
        versionSpec: '3.12'

    - script: |
        uv tool install azure-pipeline-validator
        azure-pipeline-validator workflows/
      env:
        AZDO_ORG: $(System.TeamFoundationCollectionUri)
        AZDO_PROJECT: $(System.TeamProject)
        AZDO_PIPELINE_ID: $(System.DefinitionId)
        AZDO_PAT: $(System.AccessToken)
        AZDO_REFNAME: $(Build.SourceBranch)
```

The preview call runs with `yamlOverride`, so no build is queued.

## Development workflow

```bash
# Format and lint
uv run ruff format --check
uv run ruff format
uv run ruff check

# Run the test suite
uv run python -m pytest

# Run coverage gate (recommended before release)
uv run python -m pytest --cov=src/azure_pipelines_validator --cov-report=term-missing --cov-fail-under=90

# Enforce Google-style docstrings
uvx --from pydocstyle pydocstyle --convention=google src tests
```

`pyproject.toml` configures Ruff (line length 100, py313) and pytest/coverage. The tests include CLI help verification plus mock preview responses that mirror the real API payload captured from Azure DevOps.

## Publishing the package

Publishing is fully automated with GitHub Actions:

1. `CI` workflow (`.github/workflows/ci.yml`)
   - Validates Conventional Commit-compatible PR titles (blocking check).
   - Runs lint, format check, tests, and coverage gate.
2. `Release Please` workflow (`.github/workflows/release-please.yml`)
   - Creates/updates a release PR from conventional commits.
   - On merge, bumps semantic version in `pyproject.toml`, creates a tag, and creates a GitHub Release.
3. `Publish` workflow (`.github/workflows/publish.yml`)
   - On `release.published`, publishes to PyPI via Trusted Publishing (OIDC).
   - Publishes an OCI artifact to GHCR so the repository **Packages** section is populated.

### First-time setup (required)

1. **Create project on PyPI**
   - Go to https://pypi.org/manage/projects/
   - Create project `azure-pipeline-validator` (must match `name` in `pyproject.toml`).

2. **Configure PyPI Trusted Publisher**
   - Go to https://pypi.org/manage/account/publishing/
   - Add trusted publisher:
     - **PyPI project name**: `azure-pipeline-validator`
     - **Owner**: `andrewmaspero`
     - **Repository name**: `azure-pipeline-validator`
     - **Workflow filename**: `publish.yml`
     - **Environment name**: `pypi`

3. **Enable GitHub Actions permissions**
   - Repository Settings -> Actions -> General:
     - Allow actions and reusable workflows.
     - Allow `GITHUB_TOKEN` write permissions (required for release/tag creation and GHCR publishing).

### Release flow

1. Open PRs with conventional titles (for example `feat: add vscode fallback cache`).
2. Merge PRs to `main`.
3. Release Please opens/updates a release PR.
4. Merge the release PR to create:
   - semver bump in `pyproject.toml`
   - Git tag
   - GitHub Release
5. Publish workflow runs automatically from the release event.

Consumers can install and use the package via:

```bash
# Using uvx (no installation needed)
uvx azure-pipeline-validator --help

# Or install globally
uv tool install azure-pipeline-validator
azure-pipeline-validator --help

# Or with pip
pip install azure-pipeline-validator
azure-pipeline-validator --help
```

For manual publishing, use uv directly:

```bash
uv build
uv publish
```

For manual publishing, you'll need to set `UV_PUBLISH_USERNAME` / `UV_PUBLISH_PASSWORD` environment variables, or use a PyPI API token.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Set AZDO_PAT ... before running validation.` | Export `AZDO_PAT` or `SYSTEM_ACCESSTOKEN` so the preview call can authenticate. |
| Preview API returns 401/403 | Confirm `AZDO_PIPELINE_ID` is correct and the PAT has Build Read & Execute permissions. |
| Templates reference other repos/branches | Set `AZDO_REFNAME` appropriately; cross-repo templates may require additional repository resources in the payload. |
| yamllint errors but schema/preview pass | Use `--skip-yamllint` temporarily if needed, though linting often surfaces indentation issues before Azure does. |
| Release Please does not open a release PR | Confirm `.github/workflows/release-please.yml` exists on `main`, actions are enabled, and PR titles/commits follow Conventional Commit types. |
| PyPI publish fails with trusted publishing/OIDC errors | Verify PyPI trusted publisher is configured for workflow `publish.yml`, environment `pypi`, and project name `azure-pipeline-validator`. |
| GHCR package publish fails or Packages panel is empty | Ensure workflow has `packages: write`, `GITHUB_TOKEN` write permissions are enabled at repo level, and release workflow completed for the tag. |

---

Feel free to fork, contribute improvements, or publish your own build. This README should give you everything you need to adopt the validator in local workflows, UV-based tooling, and CI/CD.

## License

`azure-pipeline-validator` is open source software released under the [MIT License](LICENSE). Contributions are welcome—just open an issue or pull request so we can review changes together.
