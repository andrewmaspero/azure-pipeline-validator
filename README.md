# Azure Pipeline Validator

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?logo=open-source-initiative&logoColor=white)](LICENSE)
[![Python Version](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Tests](https://img.shields.io/badge/Tests-pytest-0A9EDC?logo=pytest&logoColor=white)](https://docs.pytest.org/)
[![Lint](https://img.shields.io/badge/Lint-Ruff-000000?logo=ruff&logoColor=white)](https://docs.astral.sh/ruff/)
[![CI Ready](https://img.shields.io/badge/CI-Azure%20Pipelines-0078D7?logo=azure-devops&logoColor=white)](#ci-integration)

`azure-pipeline-validator` is a batteries‑included Azure DevOps YAML inspector that runs the same validations you rely on in the service, but locally. It combines three feedback loops:

1. **yamllint** – fast structural linting using a tuned configuration for Azure Pipelines quirks.
2. **JSON Schema** – offline validation against Microsoft’s published schema (`/distributedtask/yamlschema`).
3. **Preview REST API** – invokes `POST .../_apis/pipelines/{id}/preview` with `yamlOverride`, returning the real `finalYaml` and any `validationResults` that Azure DevOps would produce.

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
- **Schema caching** – fetches the official schema once per run and reuses it for every file, keeping validation snappy.
- **Rich reporting** – console output shows pass/fail per file with the first offending message per stage.
- **Toggleable stages** – disable lint/schema/preview individually for quick iteration.
- **Failure ergonomics** – `--fail-fast` stops on first failure; exit codes are 0 (success) or 1 (any failures/API issues).
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

Environment variables (or their CLI equivalents) are only required when schema or preview validation is enabled. Pure yamllint runs (`--skip-schema --skip-preview`) no longer need Azure credentials.

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

Validate the entire repo and show every check:

```bash
uv run azure-pipeline-validator validate . \
  --repo-root $(pwd) \
  --run-preview --run-schema --run-yamllint
```

Validate a single template file and skip schema:

```bash
uv run azure-pipeline-validator validate common/templates/steps/build.yml \
  --skip-schema
```

Run preview only (fast structural checks off):

```bash
uv run azure-pipeline-validator validate workflows/ --skip-yamllint --skip-schema
```

## CLI reference

```text
Usage: azure-pipeline-validator [OPTIONS] [PATH]

Run yamllint, schema validation, and Azure preview against YAML files.

Arguments:
  PATH  File or directory to validate. Directories are scanned recursively for *.yml and *.yaml files.  [default: .]

Options:
  --repo-root PATH                     Base path used when resolving template references (defaults to CWD).
  --run-yamllint / --skip-yamllint     Enable or disable yamllint for fast structural checks.
  --run-schema / --skip-schema         Validate against Microsoft's published YAML schema before previewing.
  --run-preview / --skip-preview       Call the Azure DevOps preview endpoint to fetch the compiled finalYaml.
  --fail-fast / --no-fail-fast         Stop immediately after the first file that fails validation.
  --help                               Show this message and exit.
```

## Output format

Every file gets one row with three columns (yamllint / schema / preview). A passing stage prints `pass`; the first error message is shown otherwise (plus a “(+N more)” suffix when applicable). Example:

```
┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ File                 ┃ yamllint ┃ schema ┃ preview                      ┃
┣━━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━╋━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ workflows/ci.yml     ┃ pass     ┃ pass   ┃ pass                         ┃
┃ workflows/deploy.yml ┃ L3 C5: … ┃ pass   ┃ path not found (+2 more)     ┃
┗━━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━┻━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
Validated 2 file(s). Failures: 1.
```

Exit code is non-zero whenever any file fails or when the preview/schema endpoints error.

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
uv run ruff format
uv run ruff check

# Run the test suite
uv run python -m pytest
```

`pyproject.toml` configures Ruff (line length 100, py313) and pytest/coverage. The tests include CLI help verification plus mock preview responses that mirror the real API payload captured from Azure DevOps.

## Publishing the package

The package is published to PyPI automatically via GitHub Actions when a new tag is pushed using Trusted Publishing (OIDC) - no API tokens needed!

### First-time Setup (Required Before First Publish)

**Important:** Trusted Publishing cannot create new projects on PyPI. You must create the project manually first:

1. **Create the project on PyPI:**
   - Go to https://pypi.org/manage/projects/
   - Click "Add new project"
   - Enter project name: `azure-pipeline-validator` (must match `name` in `pyproject.toml`)
     - Click "Create"

2. **Set up Trusted Publishing:**
   - Go to https://pypi.org/manage/account/publishing/
   - Click "Add a new trusted publisher"
   - Fill in:
     - **PyPI project name**: `azure-pipeline-validator`
     - **Owner**: `andrewmaspero` (your GitHub username)
     - **Repository name**: `azure-pipeline-validator`
     - **Workflow filename**: `pipeline.yml`
     - **Environment name**: `pypi` (optional but recommended)
   - Click "Add trusted publisher"

### Publishing a New Version

1. Update `version` in `pyproject.toml`.
2. Commit and push the changes.
3. Create and push a tag: `git tag v0.x.y && git push --tags`.

The CI pipeline will automatically:
- Run all tests
- Build the package
- Publish to PyPI using Trusted Publishing (OIDC)

Once published, consumers can install and use it via:

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

---

Feel free to fork, contribute improvements, or publish your own build. This README should give you everything you need to adopt the validator in local workflows, UV-based tooling, and CI/CD.

## License

`azure-pipeline-validator` is open source software released under the [MIT License](LICENSE). Contributions are welcome—just open an issue or pull request so we can review changes together.
  --azdo-org URL                       Organization URL (overrides AZDO_ORG).
  --azdo-project NAME                  Project name (overrides AZDO_PROJECT).
  --azdo-pipeline-id ID                Pipeline ID used for preview (overrides
                                       AZDO_PIPELINE_ID).
  --azdo-pat TOKEN                     PAT or OAuth token (overrides AZDO_PAT /
                                       SYSTEM_ACCESSTOKEN).
  --azdo-ref-name REF                  Ref name for template expansion
                                       (overrides AZDO_REFNAME).
  --azdo-timeout-seconds SECONDS       HTTP timeout override (overrides
                                       AZDO_TIMEOUT_SECONDS).
