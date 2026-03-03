"""Command-line interface using Typer."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console

from .azure_devops import AzureDevOpsClient
from .exceptions import (
    AzureDevOpsError,
    LspValidationError,
    SchemaUnavailableError,
    SettingsError,
)
from .file_scanner import FileScanner
from .lsp_engine import LspValidator
from .models import GateMode, ValidationOptions
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
    suggest_commands=True,
    help=(
        "Validate Azure Pipelines YAML with authoritative Azure signals by default "
        "(preview REST API + Azure LSP language server), plus optional advisory "
        "yamllint/schema checks."
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

LspServerPathOption = Annotated[
    Path | None,
    typer.Option(
        "--lsp-server-path",
        metavar="PATH",
        show_default=False,
        rich_help_panel="Azure LSP integration",
        help="Path to Azure DevOps pipeline language server entrypoint (dist/server.js).",
    ),
]

LspSchemaPathOption = Annotated[
    Path | None,
    typer.Option(
        "--lsp-schema-path",
        metavar="PATH",
        show_default=False,
        rich_help_panel="Azure LSP integration",
        help="Path to Azure DevOps pipeline language server schema (service-schema.json).",
    ),
]

LspTimeoutOption = Annotated[
    float,
    typer.Option(
        "--lsp-timeout-seconds",
        metavar="SECONDS",
        show_default=True,
        rich_help_panel="Azure LSP integration",
        help="Diagnostics wait timeout per file for Azure LSP language server.",
    ),
]

OutputFormatOption = Annotated[
    Literal["text", "json", "ndjson"],
    typer.Option(
        "--output-format",
        metavar="FORMAT",
        show_default=True,
        rich_help_panel="Output",
        help="Reporter output format.",
    ),
]

GateModeOption = Annotated[
    Literal["authoritative", "all"],
    typer.Option(
        "--gate-mode",
        metavar="MODE",
        show_default=True,
        rich_help_panel="Output",
        help=(
            "Blocking policy for exit code. "
            "'authoritative' blocks only on preview + lsp failures; "
            "'all' blocks on every enabled stage."
        ),
    ),
]

HiddenModeOption = Annotated[
    Literal["common", "all", "none"],
    typer.Option(
        "--hidden-mode",
        metavar="MODE",
        show_default=True,
        rich_help_panel="Execution control",
        help=(
            "Hidden directory discovery mode. "
            "'common' scans common CI/pipeline hidden dirs and explicit hidden targets; "
            "'all' scans all hidden dirs except hard exclusions; "
            "'none' skips hidden dirs during directory scans."
        ),
    ),
]


@app.command(
    help=(
        "Run authoritative Azure validation by default (preview + lsp). "
        "Optional advisory stages (yamllint/schema) can be enabled explicitly."
    )
)
def validate(
    target: TargetArg = Path("."),
    repo_root: RepoRootOption = None,
    azdo_org: AzureOrgOption = None,
    azdo_project: AzureProjectOption = None,
    azdo_pipeline_id: AzurePipelineIdOption = None,
    azdo_pat: AzurePatOption = None,
    azdo_ref_name: AzureRefOption = None,
    azdo_timeout_seconds: AzureTimeoutOption = None,
    lsp_server_path: LspServerPathOption = None,
    lsp_schema_path: LspSchemaPathOption = None,
    lsp_timeout_seconds: LspTimeoutOption = 5.0,
    output_format: OutputFormatOption = "text",
    gate_mode: GateModeOption = "authoritative",
    hidden_mode: HiddenModeOption = "common",
    run_yamllint: Annotated[
        bool,
        typer.Option(
            "--run-yamllint / --skip-yamllint",
            rich_help_panel="Validation toggles",
            help="Enable or disable optional advisory yamllint checks.",
        ),
    ] = False,
    run_schema: Annotated[
        bool,
        typer.Option(
            "--run-schema / --skip-schema",
            rich_help_panel="Validation toggles",
            help=(
                "Enable or disable deprecated advisory schema checks. "
                "Prefer preview+lsp for Azure correctness."
            ),
        ),
    ] = False,
    run_preview: Annotated[
        bool,
        typer.Option(
            "--run-preview / --skip-preview",
            rich_help_panel="Validation toggles",
            help="Call the Azure DevOps preview endpoint to fetch the compiled finalYaml.",
        ),
    ] = True,
    run_lsp: Annotated[
        bool,
        typer.Option(
            "--run-lsp / --skip-lsp",
            rich_help_panel="Validation toggles",
            help=(
                "Validate using the Azure DevOps pipeline language server (LSP), "
                "auto-detected from local editor extension installs by default."
            ),
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

    Args:
        target: File or directory to validate.
        repo_root: Optional repository root used to resolve template references.
        azdo_org: Optional Azure DevOps organization URL.
        azdo_project: Optional Azure DevOps project name.
        azdo_pipeline_id: Optional Azure DevOps pipeline ID.
        azdo_pat: Optional PAT or OAuth token override.
        azdo_ref_name: Optional git ref used for template expansion.
        azdo_timeout_seconds: Optional timeout override for Azure DevOps requests.
        lsp_server_path: Optional path to the language-server binary.
        lsp_schema_path: Optional path to the language-server schema file.
        lsp_timeout_seconds: Diagnostic timeout used by Azure LSP validation.
        output_format: Reporter output format.
        gate_mode: Gate mode used to determine blocking behavior.
        hidden_mode: Hidden directory discovery mode.
        run_yamllint: Enable advisory yamllint checks.
        run_schema: Enable advisory schema checks.
        run_preview: Enable preview validation against Azure DevOps.
        run_lsp: Enable Azure LSP language-server validation.
        fail_fast: Stop at the first failing file.

    Raises:
        typer.Exit: When configuration, validation, or runtime failures occur.

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

    scanner = FileScanner(effective_repo_root, hidden_mode=hidden_mode)
    loader = DocumentLoader()
    wrapper = TemplateWrapper(repo_root=effective_repo_root)
    yamllint_runner = YamllintRunner() if run_yamllint else None
    try:
        lsp_validator = (
            LspValidator(
                repo_root=effective_repo_root,
                server_path=lsp_server_path,
                schema_path=lsp_schema_path,
                timeout_seconds=lsp_timeout_seconds,
            )
            if run_lsp
            else None
        )
    except LspValidationError as error:
        console.print(f"[bold red]{error}")
        raise typer.Exit(code=2) from error

    client_context = AzureDevOpsClient(settings) if settings is not None else nullcontext(None)

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
            lsp_validator=lsp_validator,
        )
        options = ValidationOptions(
            include_lint=run_yamllint,
            include_schema=run_schema,
            include_preview=run_preview,
            include_lsp=run_lsp,
            gate_mode=GateMode(gate_mode),
            fail_fast=fail_fast,
        )
        try:
            summary = service.validate(target=target, options=options)
        except (AzureDevOpsError, SchemaUnavailableError, LspValidationError) as error:
            console.print(f"[bold red]{error}")
            raise typer.Exit(code=1) from error

    reporter = Reporter(repo_root=effective_repo_root, console=console)
    reporter.display(summary, output_format=output_format)
    if not summary.success:
        raise typer.Exit(code=1)
