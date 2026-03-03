# ![Azure Pipeline Validator](https://img.shields.io/static/v1?label=&message=Azure%20Pipeline%20Validator&color=1D4ED8&style=for-the-badge&logo=azuredevops&logoColor=white)

Local-first Azure DevOps YAML validation with Azure-authoritative checks and Azure LSP parity by default.

<div align="left">
  <table>
    <tr>
      <td><strong>Lifecycle</strong></td>
      <td>
        <a href=".github/workflows/ci.yml"><img src="https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-1F4B99?style=flat&logo=githubactions&logoColor=white" alt="CI/CD" /></a>
        <a href="https://github.com/andrewmaspero/azure-pipeline-validator/releases"><img src="https://img.shields.io/github/v/release/andrewmaspero/azure-pipeline-validator?label=Release&style=flat&logo=github&logoColor=white" alt="Release" /></a>
        <a href="https://pypi.org/project/azure-pipeline-validator/"><img src="https://img.shields.io/pypi/v/azure-pipeline-validator?label=PyPI&style=flat&logo=pypi&logoColor=white" alt="PyPI" /></a>
        <a href="https://github.com/andrewmaspero/azure-pipeline-validator/pkgs/container/azure-pipeline-validator-dist"><img src="https://img.shields.io/badge/Packages-GHCR-0F172A?style=flat&logo=github&logoColor=white" alt="Packages" /></a>
      </td>
    </tr>
    <tr>
      <td><strong>Core Stack</strong></td>
      <td>
        <img src="https://img.shields.io/badge/Python-3.13-3776AB?style=flat&logo=python&logoColor=white" alt="Python" />
        <img src="https://img.shields.io/badge/CLI-Typer-0EA5E9?style=flat&logo=python&logoColor=white" alt="Typer" />
        <img src="https://img.shields.io/badge/Lint-Ruff-000000?style=flat&logo=ruff&logoColor=white" alt="Ruff" />
        <img src="https://img.shields.io/badge/Test-Pytest-0A9EDC?style=flat&logo=pytest&logoColor=white" alt="Pytest" />
        <img src="https://img.shields.io/badge/PM-uv-DE5FE9?style=flat&logo=astral&logoColor=white" alt="uv" />
        <img src="https://img.shields.io/badge/Validation-Azure%20Preview-2563EB?style=flat&logo=azuredevops&logoColor=white" alt="Azure preview" />
        <img src="https://img.shields.io/badge/Validation-Azure%20LSP-007ACC?style=flat&logo=azuredevops&logoColor=white" alt="Azure LSP" />
      </td>
    </tr>
    <tr>
      <td><strong>Navigation</strong></td>
      <td>
        <a href="#quick-start"><img src="https://img.shields.io/badge/Local%20Setup-Quick%20Start-059669?style=flat&logo=serverless&logoColor=white" alt="Quick Start" /></a>
        <a href="#features"><img src="https://img.shields.io/badge/Overview-Features-7C3AED?style=flat&logo=simpleicons&logoColor=white" alt="Features" /></a>
        <a href="#configuration"><img src="https://img.shields.io/badge/Config-Environment-0EA5E9?style=flat&logo=dotenv&logoColor=white" alt="Configuration" /></a>
        <a href="#cli-reference"><img src="https://img.shields.io/badge/CLI-Reference-0284C7?style=flat&logo=gnubash&logoColor=white" alt="CLI" /></a>
        <a href="#ci-cd"><img src="https://img.shields.io/badge/Deploy-CI%2FCD-1F4B99?style=flat&logo=githubactions&logoColor=white" alt="CI/CD" /></a>
        <a href="#architecture"><img src="https://img.shields.io/badge/Design-Architecture-1F2937?style=flat&logo=planetscale&logoColor=white" alt="Architecture" /></a>
        <a href="#operations"><img src="https://img.shields.io/badge/Health-Operations-0F172A?style=flat&logo=serverfault&logoColor=white" alt="Operations" /></a>
      </td>
    </tr>
  </table>
</div>

<a id="quick-start"></a>
## ![Quick Start](https://img.shields.io/badge/Quick%20Start-4%20steps-059669?style=for-the-badge&logo=serverless&logoColor=white)

1. Install `uv` if needed: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. Clone and enter the repo: `git clone https://github.com/andrewmaspero/azure-pipeline-validator.git && cd azure-pipeline-validator`
3. Install dependencies: `uv sync --dev`
4. Run the CLI: `uv run azure-pipeline-validator validate --help`

Package usage without cloning:

```bash
uvx azure-pipeline-validator validate --help
```

<a id="features"></a>
## ![Features](https://img.shields.io/badge/Features-Authoritative%20first-7C3AED?style=for-the-badge&logo=simpleicons&logoColor=white)

| Feature Badge | Details |
| --- | --- |
| ![Preview](https://img.shields.io/badge/Azure%20Preview-Authoritative-2563EB?style=flat&logo=azuredevops&logoColor=white) | Calls Azure DevOps pipeline preview API and returns real `validationResults` and `finalYaml`. |
| ![LSP](https://img.shields.io/badge/Azure%20LSP-Language%20Server-007ACC?style=flat&logo=azuredevops&logoColor=white) | Runs the Azure DevOps pipeline language server (LSP) for diagnostics aligned with editor behavior. |
| ![Gate](https://img.shields.io/badge/Gate%20Mode-authoritative%7Call-1F2937?style=flat&logo=simpleicons&logoColor=white) | Default gate mode is `authoritative`; optional strict mode is `all`. |
| ![Yamllint](https://img.shields.io/badge/yamllint-Advisory-0EA5E9?style=flat&logo=yaml&logoColor=white) | Optional style and structure checks, disabled by default. |
| ![Schema](https://img.shields.io/badge/Schema-Deprecated%20Advisory-F59E0B?style=flat&logo=json&logoColor=white) | Generic schema checks remain available via `--run-schema` with deprecation warning. |
| ![Output](https://img.shields.io/badge/Output-text%20%7C%20json%20%7C%20ndjson-334155?style=flat&logo=files&logoColor=white) | Rich text output plus machine-readable formats for CI consumers. |
| ![Templates](https://img.shields.io/badge/Templates-Auto%20wrap-10B981?style=flat&logo=azuredevops&logoColor=white) | Detects template shape and wraps steps/jobs/stages when needed. |

<a id="configuration"></a>
## ![Configuration](https://img.shields.io/badge/Configuration-Environment-0EA5E9?style=for-the-badge&logo=dotenv&logoColor=white)

### ![Azure Env](https://img.shields.io/badge/Azure%20DevOps-required%20for%20preview-2563EB?style=for-the-badge&logo=azuredevops&logoColor=white)

| Name | Required | Default | Format | Description |
| --- | --- | --- | --- | --- |
| `AZDO_ORG` | yes (preview) | - | URL | Azure DevOps org URL, for example `https://dev.azure.com/contoso`. |
| `AZDO_PROJECT` | yes (preview) | - | string | Project name that owns the pipeline definition. |
| `AZDO_PIPELINE_ID` | yes (preview) | - | integer | Existing pipeline ID used for preview expansion. |
| `AZDO_PAT` | yes (preview, unless CI token) | - | string | PAT with Build Read and Execute permissions, or `SYSTEM_ACCESSTOKEN` in CI. |
| `AZDO_REFNAME` | no | `refs/heads/main` | string | Git ref used while expanding templates during preview. |
| `AZDO_TIMEOUT_SECONDS` | no | `30` | integer | Timeout for Azure preview API calls. |

### ![Azure LSP Assets](https://img.shields.io/badge/Azure%20LSP-assets%20and%20cache-007ACC?style=for-the-badge&logo=azuredevops&logoColor=white)

| Name | Required | Default | Format | Description |
| --- | --- | --- | --- | --- |
| `AZP_VALIDATOR_LSP_OFFLINE` | no | `false` | boolean | Forces cache-only Azure LSP asset usage. |
| `AZP_VALIDATOR_LSP_CACHE_DIR` | no | `~/.azure-pipeline-validator/lsp-assets` | path | Cache directory for language-server assets. |
| `AZP_VALIDATOR_LSP_VERSION` | no | `latest` | string | Pins downloaded Azure Pipelines language-server asset version. |
| `AZP_VALIDATOR_LSP_SHA256` | no | - | hex | Optional checksum verification for language-server asset download. |
| `AZP_VALIDATOR_LSP_DOWNLOAD_TIMEOUT_SECONDS` | no | `30` | integer | Timeout for language-server asset download operations. |
| `AZP_VALIDATOR_NODE_VERSION` | no | `lts` | string | Node.js version for auto-install (`lts`, `latest`, or exact semver). |
| `AZP_VALIDATOR_NODE_CACHE_DIR` | no | `~/.azure-pipeline-validator/node-runtime` | path | Cache directory for downloaded Node.js runtimes. |
| `AZP_VALIDATOR_NODE_DOWNLOAD_TIMEOUT_SECONDS` | no | `30` | integer | Timeout for Node.js download operations. |

Notes:
- Default behavior runs `preview` and `lsp`; these require Azure credentials and a Node runtime.
- If `node` is not present on `PATH`, the CLI auto-downloads a compatible Node runtime into the user cache.
- `yamllint` and `schema` are advisory by default and disabled until explicitly enabled.
- If both authoritative stages are disabled while `--gate-mode authoritative` is requested, gating falls back to `all` with a warning.

<a id="cli-reference"></a>
## ![CLI](https://img.shields.io/badge/CLI-Reference-0284C7?style=for-the-badge&logo=gnubash&logoColor=white)

```text
Usage: azure-pipeline-validator validate [OPTIONS] [PATH]

Run authoritative Azure validation by default (preview + lsp), with optional advisory yamllint/schema stages.

Arguments:
  PATH  File or directory to validate. Directories are scanned recursively for *.yml and *.yaml files.  [default: .]

Options:
  --repo-root PATH                     Base path used when resolving template references (defaults to CWD).
  --run-yamllint / --skip-yamllint     Enable or disable optional advisory yamllint checks.  [default: skip-yamllint]
  --run-schema / --skip-schema         Enable or disable deprecated advisory schema checks.  [default: skip-schema]
  --run-preview / --skip-preview       Call the Azure DevOps preview endpoint to fetch the compiled finalYaml.
  --run-lsp / --skip-lsp             Validate via Azure DevOps pipeline language server (LSP).
  --lsp-server-path PATH             Path to language server entrypoint (dist/server.js).
  --lsp-schema-path PATH             Path to language server schema (service-schema.json).
  --lsp-timeout-seconds SECONDS     Diagnostics wait timeout per file.  [default: 5.0]
  --output-format FORMAT               Reporter output format.  [default: text]
  --gate-mode MODE                     Blocking policy for exit code: authoritative|all.  [default: authoritative]
  --hidden-mode MODE                   Hidden directory discovery: common|all|none.  [default: common]
  --fail-fast / --no-fail-fast         Stop immediately after the first file that fails validation.
  --help                               Show this message and exit.
```

### Hidden directories

Default hidden discovery mode is `common`, which auto-discovers Azure DevOps-oriented hidden directories such as:
`.azure-pipelines`, `.azure`, `.devops`, `.ado`, `.azdo`, `.azuredevops`, `.azure-devops`, `.azpipelines`, `.azp`, `.pipelines`, `.pipeline`, `.ci`, `.cicd`.

Examples:

```bash
# default (common): includes common Azure DevOps hidden directories
uv run azure-pipeline-validator validate . --repo-root $(pwd)

# strict: skip hidden directories during directory scans
uv run azure-pipeline-validator validate --hidden-mode none . --repo-root $(pwd)

# broad: include all hidden directories (except hard exclusions like .git/.github)
uv run azure-pipeline-validator validate --hidden-mode all . --repo-root $(pwd)

# explicit hidden target is included in common mode
uv run azure-pipeline-validator validate .devops/ --repo-root $(pwd)
```

<a id="output-format"></a>
## ![Output](https://img.shields.io/badge/Output-Formats-334155?style=for-the-badge&logo=files&logoColor=white)

- `text` (default): rounded table with per-stage status (`pass`, `skip`, `error`, or first finding).
- `json`: one stable payload containing `schema_version`, `summary`, and `files`.
- `ndjson`: one record per file plus one summary record.

Example text output:

```text
╭──────────────────────┬──────────┬────────┬──────────────────────┬──────────────────────╮
│ File                 │ yamllint │ schema │ preview              │ lsp                  │
├──────────────────────┼──────────┼────────┼──────────────────────┼──────────────────────┤
│ workflows/ci.yml     │ pass     │ skip   │ pass                 │ pass                 │
│ workflows/deploy.yml │ skip     │ skip   │ pass                 │ L12 C9: pattern ...  │
╰──────────────────────┴──────────┴────────┴──────────────────────┴──────────────────────╯
Validated 2 file(s). Blocking failures: 1. Advisory-only files: 0. Gate mode: authoritative.
```

<a id="ci-cd"></a>
## ![CI/CD](https://img.shields.io/badge/CI%2FCD-Release%20Automation-1F4B99?style=for-the-badge&logo=githubactions&logoColor=white)

This repo uses three GitHub workflows:

1. [CI](.github/workflows/ci.yml)
   - PR semantic-title enforcement.
   - Ruff, format check, pytest, and coverage gate (`>=90%`).
2. [Release Please](.github/workflows/release-please.yml)
   - Conventional commits drive semantic versioning.
   - Updates `pyproject.toml` version, creates tag, and creates GitHub Release.
3. [Publish](.github/workflows/publish.yml)
   - Publishes to PyPI via Trusted Publishing.
   - Publishes OCI dist artifact to GHCR for Packages visibility.

### ![PyPI Setup](https://img.shields.io/badge/PyPI-Trusted%20Publishing-0EA5E9?style=for-the-badge&logo=pypi&logoColor=white)

| Setting | Value |
| --- | --- |
| PyPI project name | `azure-pipeline-validator` |
| GitHub owner | `andrewmaspero` |
| GitHub repository | `azure-pipeline-validator` |
| Workflow file | `publish.yml` |
| Environment name | `pypi` |

<a id="developer-workflow"></a>
## ![Developer Workflow](https://img.shields.io/badge/Developer-Workflow-6366F1?style=for-the-badge&logo=git&logoColor=white)

```bash
# Install dependencies
uv sync --dev

# Lint and format checks
uv run ruff check
uv run ruff format --check

# Test suite
uv run python -m pytest

# Coverage gate
uv run python -m pytest --cov=src/azure_pipelines_validator --cov-report=term-missing --cov-fail-under=90

# Google docstring style checks
uvx --from pydocstyle pydocstyle --convention=google src
```

<a id="operations"></a>
## ![Operations](https://img.shields.io/badge/Operations-Runbook-10B981?style=for-the-badge&logo=serverfault&logoColor=white)

- Validate a repo quickly: `uv run azure-pipeline-validator validate . --repo-root $(pwd)`
- Authoritative-only gate (default): preview and lsp determine exit code.
- Strict all-stage gate: `--run-yamllint --run-schema --gate-mode all`
- Fail fast for CI cost control: add `--fail-fast`.
- Treat schema warnings as advisory; schema stage is soft-deprecated for Azure correctness.

<a id="architecture"></a>
## ![Architecture](https://img.shields.io/badge/Architecture-Stack%20Map-1F2937?style=for-the-badge&logo=planetscale&logoColor=white)

- CLI and orchestration: Typer-based command surface and validation service pipeline.
- Azure-authoritative engines:
  - Azure DevOps Preview API (`yamlOverride` against existing pipeline definition).
  - Azure DevOps pipeline language server (LSP) diagnostics.
- Advisory engines:
  - `yamllint` for style and structure.
  - JSON schema checks for generic coverage.
- Output and gating model:
  - Stage-level statuses: `passed`, `failed`, `error`, `skipped`.
  - Gate modes: `authoritative` and `all`.
  - Reporter supports text, JSON, and NDJSON for CI ingestion.

<a id="troubleshooting"></a>
## ![Troubleshooting](https://img.shields.io/badge/Troubleshooting-Playbook-F59E0B?style=for-the-badge&logo=googledocs&logoColor=white)

- Symptom: many Red Hat YAML warnings but one Azure error.
  - Cause: generic YAML schema validation and Azure template semantics diverge.
  - Action: rely on `preview` and `lsp` as source of truth for Azure correctness.
- Symptom: Azure LSP stage cannot start.
  - Cause: unavailable Node runtime or language-server assets.
  - Action: rerun with network access so runtime/assets can auto-bootstrap, or provide `--lsp-server-path` and `--lsp-schema-path` plus a valid Node binary.
- Symptom: preview failures in CI.
  - Cause: missing Azure credentials or insufficient PAT scope.
  - Action: ensure `AZDO_*` values are present and token has Build Read and Execute permissions.

<a id="license"></a>
## ![License](https://img.shields.io/badge/License-MIT-1D4ED8?style=for-the-badge&logo=open-source-initiative&logoColor=white)

MIT. See [LICENSE](LICENSE).
