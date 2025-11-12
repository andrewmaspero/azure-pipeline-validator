"""Command-line interface using Typer."""

from __future__ import annotations

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


@app.command(help="Run yamllint, schema validation, and Azure preview against YAML files.")
def validate(
    target: TargetArg = Path("."),
    repo_root: RepoRootOption = None,
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
        uv run azure-pipelines-validator validate .

        uvx --from git+https://github.com/your-org/azure-pipelines-validator \
            azure-pipelines-validator workflows/
    """

    console = Console()
    effective_repo_root = repo_root or Path.cwd()

    try:
        settings = Settings.from_environment(repo_root=effective_repo_root)
    except SettingsError as error:
        console.print(f"[bold red]{error}")
        raise typer.Exit(code=2) from error

    scanner = FileScanner(settings.repo_root)
    loader = DocumentLoader()
    wrapper = TemplateWrapper()
    yamllint_runner = YamllintRunner() if run_yamllint else None

    with AzureDevOpsClient(settings) as client:
        schema_validator = None
        if run_schema:
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

    reporter = Reporter(repo_root=settings.repo_root, console=console)
    reporter.display(summary)
    if not summary.success:
        raise typer.Exit(code=1)
