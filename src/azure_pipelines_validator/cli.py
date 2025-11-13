"""Command-line interface using Typer."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .azure_devops import AzureDevOpsClient
from .exceptions import AzureDevOpsError, SchemaUnavailableError, SettingsError
from .file_scanner import FileScanner
from .models import ValidationOptions
from .reporter import Reporter
from .schema_engine import SchemaValidator
from .service import ValidationService
from .settings import Settings
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
            rich_help_panel="Validation toggles",
            help="Enable or disable yamllint for fast structural checks.",
        ),
    ] = True,
    run_schema: Annotated[
        bool,
        typer.Option(
            "--run-schema / --skip-schema",
            rich_help_panel="Validation toggles",
            help="Validate against Microsoft's published YAML schema before previewing.",
        ),
    ] = True,
    run_preview: Annotated[
        bool,
        typer.Option(
            "--run-preview / --skip-preview",
            rich_help_panel="Validation toggles",
            help="Call the Azure DevOps preview endpoint to fetch the compiled finalYaml.",
        ),
    ] = True,
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
    requires_azure = run_schema or run_preview

    settings = None
    if requires_azure:
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
        if run_schema and client is not None:
            schema_validator = SchemaValidator(client.download_schema)
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
