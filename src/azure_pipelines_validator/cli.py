"""Command-line interface using Typer."""

from __future__ import annotations

import os
import re
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import Annotated, MutableMapping, Sequence

import typer
from rich.console import Console

from .azure_devops import AzureDevOpsClient
from .exceptions import AzureDevOpsError, SchemaUnavailableError, SettingsError
from .file_scanner import FileScanner
from .models import ValidationOptions
from .reporter import Reporter
from .schema_engine import SchemaValidator
from .service import ValidationService
from .schema_sources import download_public_schema
from .settings import AZURE_TIMEOUT_DEFAULT, Settings
from .yaml_processing import DocumentLoader, TemplateWrapper
from .yamllint_engine import YamllintRunner

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="markdown",
    help=(
        "Validate Azure Pipelines YAML files using yamllint, the official schema, "
        "and the preview REST API so you see the exact `finalYaml` Azure would run."
    ),
)


_INLINE_ENV_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*=.*")


def _consume_inline_env(
    args: Sequence[str],
    *,
    environ: MutableMapping[str, str] | None = None,
) -> list[str]:
    """Apply KEY=VALUE style arguments to the environment.

    Allows commands such as `azure-pipeline-validator AZDO_PAT=foo workflows/` so the
    user does not need to preface the invocation with shell-specific `VAR=value`
    syntax. Only bare KEY=VALUE tokens (no leading option flag) are interpreted to
    avoid swallowing legitimate `--flag=value` options or file paths that contain an
    equals sign.
    """

    remaining: list[str] = []
    target_env = environ if environ is not None else os.environ
    for token in args:
        if token.startswith("--"):
            remaining.append(token)
            continue
        if _INLINE_ENV_PATTERN.match(token):
            key, value = token.split("=", 1)
            target_env[key] = value
            continue
        remaining.append(token)
    return remaining


TargetArg = Annotated[
    Path,
    typer.Argument(
        exists=True,
        file_okay=True,
        dir_okay=True,
        readable=True,
        metavar="[PATH]",
        show_default=True,
        help=(
            "File or directory to validate. Directories are scanned recursively for "
            "*.yml and *.yaml files."
        ),
    ),
]

RepoRootOption = Annotated[
    Path | None,
    typer.Option(
        "--repo-root",
        metavar="PATH",
        show_default=False,
        rich_help_panel="Context",
        help="Base path used when resolving template references (defaults to CWD).",
    ),
]

AzureOrgOption = Annotated[
    str | None,
    typer.Option(
        "--azdo-org",
        metavar="URL",
        show_default=False,
        rich_help_panel="Azure connection",
        help="Organization URL (overrides AZDO_ORG).",
    ),
]

AzureProjectOption = Annotated[
    str | None,
    typer.Option(
        "--azdo-project",
        metavar="NAME",
        show_default=False,
        rich_help_panel="Azure connection",
        help="Project name (overrides AZDO_PROJECT).",
    ),
]

AzurePipelineIdOption = Annotated[
    int | None,
    typer.Option(
        "--azdo-pipeline-id",
        metavar="ID",
        show_default=False,
        rich_help_panel="Azure connection",
        help="Pipeline ID used for preview (overrides AZDO_PIPELINE_ID).",
    ),
]

AzurePatOption = Annotated[
    str | None,
    typer.Option(
        "--azdo-pat",
        metavar="TOKEN",
        show_default=False,
        rich_help_panel="Azure connection",
        help="PAT or OAuth token (overrides AZDO_PAT / SYSTEM_ACCESSTOKEN).",
    ),
]

AzureRefOption = Annotated[
    str | None,
    typer.Option(
        "--azdo-ref-name",
        metavar="REF",
        show_default=False,
        rich_help_panel="Azure connection",
        help="Ref name for template expansion (overrides AZDO_REFNAME).",
    ),
]

AzureTimeoutOption = Annotated[
    float | None,
    typer.Option(
        "--azdo-timeout-seconds",
        metavar="SECONDS",
        show_default=False,
        rich_help_panel="Azure connection",
        help="HTTP timeout override (overrides AZDO_TIMEOUT_SECONDS).",
    ),
]


@app.command(help="Run yamllint, schema validation, and Azure preview against YAML files.")
def validate(
    target: TargetArg = Path("."),
    repo_root: RepoRootOption = None,
    azdo_org: AzureOrgOption = None,
    azdo_project: AzureProjectOption = None,
    azdo_pipeline_id: AzurePipelineIdOption = None,
    azdo_pat: AzurePatOption = None,
    azdo_ref_name: AzureRefOption = None,
    azdo_timeout_seconds: AzureTimeoutOption = None,
    run_yamllint: Annotated[
        bool,
        typer.Option(
            "--run-yamllint / --skip-yamllint",
            "--lint / --no-lint",
            "-l / --no-l",
            rich_help_panel="Validation toggles",
            help="Run yamllint (aliases: --lint, -l).",
        ),
    ] = False,
    run_schema: Annotated[
        bool,
        typer.Option(
            "--run-schema / --skip-schema",
            "--schema / --no-schema",
            "-s / --no-s",
            rich_help_panel="Validation toggles",
            help="Validate against Microsoft's published YAML schema (aliases: --schema, -s).",
        ),
    ] = False,
    run_preview: Annotated[
        bool,
        typer.Option(
            "--run-preview / --skip-preview",
            "--preview / --no-preview",
            "-p / --no-p",
            rich_help_panel="Validation toggles",
            help="Call the Azure DevOps preview endpoint (aliases: --preview, -p).",
        ),
    ] = False,
    fail_fast: Annotated[
        bool,
        typer.Option(
            "--fail-fast / --no-fail-fast",
            rich_help_panel="Execution control",
            help="Stop immediately after the first file that fails validation.",
        ),
    ] = False,
) -> None:
    """Validate Azure Pipelines YAML locally before committing.

    Examples:
        uv run azure-pipeline-validator validate .

        uvx --from git+https://github.com/your-org/azure-pipeline-validator \
            azure-pipeline-validator workflows/
    """

    console = Console()
    effective_repo_root = (repo_root or Path.cwd()).resolve()

    if not any((run_yamllint, run_schema, run_preview)):
        console.print(
            "[bold yellow]Select at least one validation toggle (e.g. --lint/-l, --schema/-s, --preview/-p)."
        )
        raise typer.Exit(code=2)

    settings = None
    if run_preview:
        try:
            settings = Settings.from_environment(
                repo_root=effective_repo_root,
                organization=azdo_org,
                project=azdo_project,
                pipeline_id=azdo_pipeline_id,
                personal_access_token=azdo_pat,
                ref_name=azdo_ref_name,
                timeout_seconds=azdo_timeout_seconds,
            )
        except SettingsError as error:
            console.print(f"[bold red]{error}")
            raise typer.Exit(code=2) from error

    scanner = FileScanner(effective_repo_root)
    loader = DocumentLoader()
    wrapper = TemplateWrapper(repo_root=effective_repo_root)
    yamllint_runner = YamllintRunner() if run_yamllint else None

    client_context = (
        AzureDevOpsClient(settings) if settings is not None else nullcontext(None)
    )

    with client_context as client:
        schema_validator = None
        if run_schema:
            schema_supplier = None
            if client is not None:
                schema_supplier = client.download_schema
            else:
                timeout_override = (
                    settings.request_timeout_seconds
                    if settings is not None
                    else (
                        float(azdo_timeout_seconds)
                        if azdo_timeout_seconds is not None
                        else AZURE_TIMEOUT_DEFAULT
                    )
                )

                def _download_schema() -> str:
                    return download_public_schema(timeout_override)

                schema_supplier = _download_schema

            schema_validator = SchemaValidator(schema_supplier)
        service = ValidationService(
            client=client,
            scanner=scanner,
            loader=loader,
            wrapper=wrapper,
            yamllint_runner=yamllint_runner,
            schema_validator=schema_validator,
        )
        options = ValidationOptions(
            include_lint=run_yamllint,
            include_schema=run_schema,
            include_preview=run_preview,
            fail_fast=fail_fast,
        )
        try:
            summary = service.validate(target=target, options=options)
        except (AzureDevOpsError, SchemaUnavailableError) as error:
            console.print(f"[bold red]{error}")
            raise typer.Exit(code=1) from error

    reporter = Reporter(repo_root=effective_repo_root, console=console)
    reporter.display(summary)
    if not summary.success:
        raise typer.Exit(code=1)


def main() -> None:
    """Entry point used by the console script."""

    new_args = _consume_inline_env(sys.argv[1:])
    sys.argv = [sys.argv[0], *new_args]
    app()


if __name__ == "__main__":  # pragma: no cover - manual execution helper
    main()
