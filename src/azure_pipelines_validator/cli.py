"""Command-line interface using Typer."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import Annotated, Literal, Mapping, Sequence

import typer
from rich.console import Console

from .auth_chain import TokenSource, resolve_token
from .azure_devops import AzureDevOpsClient
from .context_detection import DetectionSource, detect_git_context
from .exceptions import (
    AuthResolutionError,
    AzureDevOpsError,
    ContextResolutionError,
    LspValidationError,
    SchemaUnavailableError,
    SettingsError,
)
from .file_scanner import FileScanner
from .keyring_store import (
    clear_default_org,
    clear_pat,
    keyring_backend_status,
    read_default_org,
    read_pat,
    resolve_org,
    store_default_org,
    store_pat,
)
from .lsp_engine import LspValidator
from .models import (
    AuthStatusResult,
    ContextDetectResult,
    GateMode,
    ValidationOptions,
    ValidationSummary,
)
from .pipeline_documents import DocumentLoader
from .pipeline_resolution import (
    DEFAULT_CACHE_TTL_SECONDS,
    load_cached_pipeline_id,
    save_cached_pipeline_id,
    select_pipeline_candidates,
)
from .preview_wrapper import TemplateWrapper
from .reporter import Reporter
from .schema_engine import SchemaValidator
from .service import ValidationService
from .settings import Settings
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
auth_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Manage local keychain-backed Azure authentication defaults.",
)
context_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Inspect detected Azure DevOps context and pipeline candidates.",
)
app.add_typer(auth_app, name="auth")
app.add_typer(context_app, name="context")


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
        help=(
            "Organization URL or slug (overrides AZDO_ORG), for example "
            "'https://dev.azure.com/contoso' or 'contoso'."
        ),
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
            "'authoritative' blocks only on preview + lsp error-level findings; "
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

RemoteNameOption = Annotated[
    str,
    typer.Option(
        "--remote-name",
        metavar="NAME",
        show_default=True,
        rich_help_panel="Context",
        help="Git remote used for Azure DevOps URL inference.",
    ),
]

AutoContextOption = Annotated[
    bool,
    typer.Option(
        "--auto-context / --no-auto-context",
        rich_help_panel="Context",
        help="Enable or disable Azure context auto-detection.",
    ),
]

PromptOption = Annotated[
    bool,
    typer.Option(
        "--prompt / --no-prompt",
        rich_help_panel="Context",
        help="Allow interactive pipeline selection when multiple candidates match.",
    ),
]

PipelineNameOption = Annotated[
    str | None,
    typer.Option(
        "--pipeline-name",
        metavar="NAME",
        show_default=False,
        rich_help_panel="Context",
        help="Optional pipeline name hint for auto-resolution.",
    ),
]

PipelineCacheTtlOption = Annotated[
    int,
    typer.Option(
        "--pipeline-id-cache-ttl-seconds",
        metavar="SECONDS",
        show_default=True,
        rich_help_panel="Context",
        help="Cache TTL for repository-scoped pipeline selections.",
    ),
]

PreviewTargetOption = Annotated[
    Path | None,
    typer.Option(
        "--preview-target",
        metavar="PATH",
        show_default=False,
        rich_help_panel="Validation toggles",
        help=(
            "Run preview against a single YAML file. "
            "When omitted, local directory runs auto-detect the main pipeline YAML "
            "from Azure DevOps CLI and preview only that file."
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
    remote_name: RemoteNameOption = "origin",
    auto_context: AutoContextOption = True,
    prompt: PromptOption = True,
    pipeline_name: PipelineNameOption = None,
    pipeline_id_cache_ttl_seconds: PipelineCacheTtlOption = DEFAULT_CACHE_TTL_SECONDS,
    preview_target: PreviewTargetOption = None,
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
        azdo_org: Optional Azure DevOps organization URL or slug.
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
        remote_name: Git remote used for Azure DevOps inference.
        auto_context: Enables auto-resolution for Azure context.
        prompt: Enables interactive local candidate selection.
        pipeline_name: Optional pipeline name hint.
        pipeline_id_cache_ttl_seconds: Cache TTL for selected pipeline IDs.
        preview_target: Optional explicit file path for single-file preview.
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
    warnings: list[str] = []
    effective_remote_name = (
        os.getenv("AZP_VALIDATOR_REMOTE_NAME", remote_name).strip() or remote_name
    )
    effective_auto_context = _resolve_bool_env("AZP_VALIDATOR_AUTO_CONTEXT", auto_context)
    effective_prompt = _resolve_bool_env("AZP_VALIDATOR_PROMPT", prompt)
    effective_pipeline_name = pipeline_name or os.getenv("AZP_VALIDATOR_PIPELINE_NAME")
    effective_cache_ttl = int(
        os.getenv(
            "AZP_VALIDATOR_CONTEXT_CACHE_TTL_SECONDS",
            str(max(pipeline_id_cache_ttl_seconds, 1)),
        )
    )

    settings = None
    if requires_azure:
        try:
            settings, resolve_warnings = _resolve_settings(
                repo_root=effective_repo_root,
                azdo_org=azdo_org,
                azdo_project=azdo_project,
                azdo_pipeline_id=azdo_pipeline_id,
                azdo_pat=azdo_pat,
                azdo_ref_name=azdo_ref_name,
                azdo_timeout_seconds=azdo_timeout_seconds,
                remote_name=effective_remote_name,
                auto_context=effective_auto_context,
                prompt=effective_prompt,
                pipeline_name=effective_pipeline_name,
                pipeline_cache_ttl_seconds=effective_cache_ttl,
                console=console,
            )
            warnings.extend(resolve_warnings)
        except (SettingsError, ContextResolutionError, AuthResolutionError) as error:
            console.print(f"[bold red]{error}")
            raise typer.Exit(code=2) from error

    try:
        resolved_preview_target, preview_warnings = _resolve_preview_target(
            target=target,
            repo_root=effective_repo_root,
            run_preview=run_preview,
            explicit_preview_target=preview_target,
            settings=settings,
        )
        warnings.extend(preview_warnings)
    except ContextResolutionError as error:
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
            preview_target_path=resolved_preview_target,
        )
        try:
            summary = service.validate(target=target, options=options)
        except (AzureDevOpsError, SchemaUnavailableError, LspValidationError) as error:
            console.print(f"[bold red]{error}")
            raise typer.Exit(code=1) from error

    summary = _attach_warnings(summary, warnings)
    reporter = Reporter(repo_root=effective_repo_root, console=console)
    reporter.display(summary, output_format=output_format)
    if not summary.success:
        raise typer.Exit(code=1)


@auth_app.command("set-pat", help="Store a PAT in OS keychain for an organization.")
def auth_set_pat(
    org: Annotated[
        str | None,
        typer.Option("--org", metavar="ORG", show_default=False, help="Organization slug or URL."),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option("--token", metavar="PAT", show_default=False, help="PAT value to store."),
    ] = None,
) -> None:
    """Persist a PAT in keychain storage."""
    resolved_org = resolve_org(org)
    if not resolved_org:
        raise typer.Exit(code=2)
    resolved_token = token or typer.prompt("Azure DevOps PAT", hide_input=True).strip()
    if not resolved_token:
        raise typer.Exit(code=2)
    try:
        store_pat(token=resolved_token, org=resolved_org)
    except RuntimeError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Stored PAT for org '{resolved_org}'.")


@auth_app.command("clear-pat", help="Delete a keychain PAT for an organization.")
def auth_clear_pat(
    org: Annotated[
        str | None,
        typer.Option("--org", metavar="ORG", show_default=False, help="Organization slug or URL."),
    ] = None,
) -> None:
    """Delete a stored PAT from keychain storage."""
    resolved_org = resolve_org(org)
    if not resolved_org:
        raise typer.Exit(code=2)
    removed = clear_pat(org=resolved_org)
    if removed:
        typer.echo(f"Deleted PAT for org '{resolved_org}'.")
    else:
        typer.echo(f"No PAT found for org '{resolved_org}'.")


@auth_app.command("set-org", help="Store a default Azure DevOps organization in keychain.")
def auth_set_org(
    org: Annotated[str, typer.Option("--org", metavar="ORG", help="Organization slug or URL.")],
) -> None:
    """Persist the default Azure DevOps organization."""
    try:
        store_default_org(org)
    except RuntimeError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Stored default org '{org}'.")


@auth_app.command("clear-org", help="Delete the default Azure DevOps organization.")
def auth_clear_org() -> None:
    """Delete the stored default organization."""
    removed = clear_default_org()
    if removed:
        typer.echo("Deleted default org.")
    else:
        typer.echo("No default org stored.")


@auth_app.command("status", help="Show resolved auth state for local diagnostics.")
def auth_status(
    org: Annotated[
        str | None,
        typer.Option("--org", metavar="ORG", show_default=False, help="Organization slug or URL."),
    ] = None,
    output_format: Annotated[
        Literal["text", "json"],
        typer.Option("--format", metavar="FORMAT", show_default=True, help="Output format."),
    ] = "text",
) -> None:
    """Display auth-chain readiness details."""
    resolved_org = resolve_org(org)
    resolved_token = resolve_token(explicit_token=None, org_hint=resolved_org)
    backend_available, backend_detail = keyring_backend_status()
    result = AuthStatusResult(
        resolved_org=resolved_org,
        keyring_backend_available=backend_available,
        keyring_backend_detail=backend_detail,
        default_org_stored=read_default_org(),
        pat_present_for_org=bool(read_pat(resolved_org)) if resolved_org else False,
        env_pat_present=any(
            bool(os.getenv(name, "").strip()) for name in ("AZDO_PAT", "SYSTEM_ACCESSTOKEN", "PAT")
        ),
        azure_cli_available=(
            resolved_token is not None and resolved_token.source == TokenSource.AZ_CLI
        ),
    )
    if output_format == "json":
        typer.echo(result.model_dump_json())
        return
    typer.echo(f"Resolved org: {result.resolved_org or '(none)'}")
    typer.echo(f"Keyring backend available: {result.keyring_backend_available}")
    typer.echo(f"Keyring backend detail: {result.keyring_backend_detail}")
    typer.echo(f"Default org stored: {result.default_org_stored or '(none)'}")
    typer.echo(f"PAT present for org: {result.pat_present_for_org}")
    typer.echo(f"PAT env present: {result.env_pat_present}")
    typer.echo(f"Azure CLI fallback available: {result.azure_cli_available}")


@context_app.command("detect", help="Detect Azure context from flags/env/git/keychain.")
def context_detect(
    remote_name: RemoteNameOption = "origin",
    output_format: Annotated[
        Literal["text", "json"],
        typer.Option("--format", metavar="FORMAT", show_default=True, help="Output format."),
    ] = "text",
) -> None:
    """Display detected Azure context and source metadata."""
    git_context = detect_git_context(remote_name=remote_name)
    resolved_org = resolve_org(remote_name=remote_name)
    organization_source = (
        DetectionSource.GIT_REMOTE.value if git_context.remote else DetectionSource.UNSET.value
    )
    project = git_context.remote.project if git_context.remote else None
    repository = git_context.remote.repo if git_context.remote else None
    result = ContextDetectResult(
        organization=resolved_org,
        project=project,
        repository=repository,
        remote_name=git_context.remote_name,
        remote_url=git_context.remote_url,
        branch=git_context.current_branch,
        repo_root=str(git_context.repo_root) if git_context.repo_root else None,
        organization_source=organization_source,
        project_source=DetectionSource.GIT_REMOTE.value if project else DetectionSource.UNSET.value,
        repository_source=DetectionSource.GIT_REMOTE.value
        if repository
        else DetectionSource.UNSET.value,
        pipeline_id=None,
        pipeline_source=DetectionSource.UNSET.value,
    )
    if output_format == "json":
        typer.echo(result.model_dump_json())
        return
    typer.echo(f"Org: {result.organization or '(none)'} [{result.organization_source}]")
    typer.echo(f"Project: {result.project or '(none)'} [{result.project_source}]")
    typer.echo(f"Repository: {result.repository or '(none)'} [{result.repository_source}]")
    typer.echo(f"Remote ({result.remote_name}): {result.remote_url or '(none)'}")
    typer.echo(f"Branch: {result.branch or '(none)'}")
    typer.echo(f"Repo root: {result.repo_root or '(none)'}")


@context_app.command("pipelines", help="List candidate pipelines for detected or provided context.")
def context_pipelines(
    azdo_org: AzureOrgOption = None,
    azdo_project: AzureProjectOption = None,
    azdo_pat: AzurePatOption = None,
    repo: Annotated[
        str | None,
        typer.Option("--repo", metavar="NAME", show_default=False, help="Repository name hint."),
    ] = None,
    branch: Annotated[
        str | None,
        typer.Option("--branch", metavar="REF", show_default=False, help="Branch hint."),
    ] = None,
    remote_name: RemoteNameOption = "origin",
) -> None:
    """List pipeline candidates using repository and optional hints."""
    del branch  # Reserved for future branch-aware narrowing.
    git_context = detect_git_context(remote_name=remote_name)
    remote = git_context.remote
    resolved_ref_name = _resolve_ref_name(None, current_branch=git_context.current_branch)
    resolved_org = azdo_org or os.getenv("AZDO_ORG") or (remote.org if remote else None)
    resolved_project = (
        azdo_project or os.getenv("AZDO_PROJECT") or (remote.project if remote else None)
    )
    if not resolved_org or not resolved_project:
        raise typer.Exit(code=2)
    resolved_token = resolve_token(explicit_token=azdo_pat, org_hint=resolved_org)
    if resolved_token is None:
        raise typer.Exit(code=2)
    settings = Settings.from_resolved_context(
        organization=resolved_org,
        project=resolved_project,
        pipeline_id=1,
        personal_access_token=resolved_token.value,
        token_kind=resolved_token.kind.value,
        repo_root=Path.cwd(),
        ref_name=resolved_ref_name,
        timeout_seconds=float(os.getenv("AZDO_TIMEOUT_SECONDS", "30")),
    )
    client = AzureDevOpsClient(settings)
    try:
        repo_name = repo or (remote.repo if remote else "")
        all_pipelines = client.list_pipelines(project=resolved_project)
        candidates = select_pipeline_candidates(
            repo_name=repo_name,
            name_hint=os.getenv("AZP_VALIDATOR_PIPELINE_NAME"),
            all_pipelines=all_pipelines,
        )
    finally:
        client.close()
    for pipeline in candidates:
        typer.echo(f"{pipeline.id}\t{pipeline.name}\t{pipeline.yaml_path or '-'}")


def _resolve_settings(
    *,
    repo_root: Path,
    azdo_org: str | None,
    azdo_project: str | None,
    azdo_pipeline_id: int | None,
    azdo_pat: str | None,
    azdo_ref_name: str | None,
    azdo_timeout_seconds: float | None,
    remote_name: str,
    auto_context: bool,
    prompt: bool,
    pipeline_name: str | None,
    pipeline_cache_ttl_seconds: int,
    console: Console,
) -> tuple[Settings, list[str]]:
    """Resolve runtime settings with layered auto-detection."""
    warnings: list[str] = []
    git_context_for_ref = detect_git_context(remote_name=remote_name)
    resolved_ref_name = _resolve_ref_name(
        azdo_ref_name,
        current_branch=git_context_for_ref.current_branch,
    )
    if not auto_context:
        return (
            Settings.from_environment(
                repo_root=repo_root,
                organization=azdo_org,
                project=azdo_project,
                pipeline_id=azdo_pipeline_id,
                personal_access_token=azdo_pat,
                ref_name=resolved_ref_name,
                timeout_seconds=azdo_timeout_seconds,
            ),
            warnings,
        )

    git_context = git_context_for_ref
    remote = git_context.remote

    resolved_org, org_source = _resolve_org_value(azdo_org, remote)
    resolved_project, project_source = _resolve_project_value(azdo_project, remote)
    if not resolved_org or not resolved_project:
        raise ContextResolutionError(
            "Unable to resolve Azure organization/project. Provide --azdo-org and --azdo-project "
            "or set AZDO_ORG/AZDO_PROJECT."
        )

    resolved_token = resolve_token(explicit_token=azdo_pat, org_hint=resolved_org)
    if resolved_token is None:
        raise AuthResolutionError(
            "Unable to resolve Azure auth token. Use --azdo-pat, set AZDO_PAT/SYSTEM_ACCESSTOKEN, "
            "store a keychain PAT (auth set-pat), or sign in with Azure CLI."
        )
    warnings.append(f"Using {resolved_token.source.value} token provider.")

    explicit_pipeline = azdo_pipeline_id
    if explicit_pipeline is None:
        env_pipeline = os.getenv("AZDO_PIPELINE_ID", "").strip()
        if env_pipeline:
            explicit_pipeline = int(env_pipeline)
    if explicit_pipeline is not None:
        pipeline_id = int(explicit_pipeline)
        pipeline_source = (
            DetectionSource.FLAG if azdo_pipeline_id is not None else DetectionSource.ENV
        )
    else:
        repo_name = remote.repo if remote else ""
        cached_pipeline = None
        if repo_name:
            cached_pipeline = load_cached_pipeline_id(
                org=resolved_org,
                project=resolved_project,
                repo=repo_name,
                ttl_seconds=max(pipeline_cache_ttl_seconds, 1),
            )
        if cached_pipeline is not None:
            pipeline_id = cached_pipeline
            pipeline_source = DetectionSource.CACHE
        else:
            discovery_settings = Settings.from_resolved_context(
                organization=resolved_org,
                project=resolved_project,
                pipeline_id=1,
                personal_access_token=resolved_token.value,
                token_kind=resolved_token.kind.value,
                repo_root=repo_root,
                ref_name=resolved_ref_name,
                timeout_seconds=azdo_timeout_seconds
                if azdo_timeout_seconds is not None
                else float(os.getenv("AZDO_TIMEOUT_SECONDS", "30")),
            )
            client = AzureDevOpsClient(discovery_settings)
            try:
                all_pipelines = client.list_pipelines(project=resolved_project)
            finally:
                client.close()
            candidates = select_pipeline_candidates(
                repo_name=repo_name,
                name_hint=pipeline_name or os.getenv("AZP_VALIDATOR_PIPELINE_NAME"),
                all_pipelines=all_pipelines,
            )
            if not candidates:
                raise ContextResolutionError(
                    "No pipelines found for the resolved project. Provide --azdo-pipeline-id "
                    "or run 'azure-pipeline-validator context pipelines'."
                )
            if len(candidates) == 1:
                pipeline_id = candidates[0].id
                pipeline_source = DetectionSource.GIT_REMOTE
            else:
                can_prompt = prompt and _is_interactive_terminal()
                if can_prompt:
                    pipeline_id = _prompt_for_pipeline(candidates=candidates, console=console)
                    pipeline_source = DetectionSource.USER_PROMPT
                else:
                    candidate_lines = "\n".join(
                        f"  - {candidate.id}: {candidate.name}" for candidate in candidates[:20]
                    )
                    raise ContextResolutionError(
                        "Multiple pipeline candidates found. Re-run with --azdo-pipeline-id or "
                        "use interactive prompt in a TTY.\nCandidates:\n"
                        f"{candidate_lines}"
                    )
            if repo_name:
                save_cached_pipeline_id(
                    org=resolved_org,
                    project=resolved_project,
                    repo=repo_name,
                    pipeline_id=pipeline_id,
                )
    warnings.append(
        "Resolved context "
        f"(org={resolved_org} [{org_source.value}], "
        f"project={resolved_project} [{project_source.value}], "
        f"pipeline={pipeline_id} [{pipeline_source.value}])."
    )

    settings = Settings.from_resolved_context(
        organization=resolved_org,
        project=resolved_project,
        pipeline_id=pipeline_id,
        personal_access_token=resolved_token.value,
        token_kind=resolved_token.kind.value,
        repo_root=repo_root,
        ref_name=resolved_ref_name,
        timeout_seconds=azdo_timeout_seconds
        if azdo_timeout_seconds is not None
        else float(os.getenv("AZDO_TIMEOUT_SECONDS", "30")),
    )
    return settings, warnings


def _resolve_org_value(
    azdo_org: str | None,
    remote: object | None,
) -> tuple[str | None, DetectionSource]:
    """Resolve organization value and source metadata."""
    if azdo_org and azdo_org.strip():
        return azdo_org.strip(), DetectionSource.FLAG
    env_org = os.getenv("AZDO_ORG", "").strip()
    if env_org:
        return env_org, DetectionSource.ENV
    if remote is not None and getattr(remote, "org", None):
        return str(remote.org), DetectionSource.GIT_REMOTE
    keyring_org = read_default_org()
    if keyring_org:
        return keyring_org, DetectionSource.KEYCHAIN
    return None, DetectionSource.UNSET


def _resolve_project_value(
    azdo_project: str | None,
    remote: object | None,
) -> tuple[str | None, DetectionSource]:
    """Resolve project value and source metadata."""
    if azdo_project and azdo_project.strip():
        return azdo_project.strip(), DetectionSource.FLAG
    env_project = os.getenv("AZDO_PROJECT", "").strip()
    if env_project:
        return env_project, DetectionSource.ENV
    if remote is not None and getattr(remote, "project", None):
        return str(remote.project), DetectionSource.GIT_REMOTE
    return None, DetectionSource.UNSET


def _prompt_for_pipeline(*, candidates: Sequence[object], console: Console) -> int:
    """Prompt user to select a pipeline candidate by index."""
    console.print("[bold yellow]Multiple pipelines matched. Select one:[/bold yellow]")
    for index, candidate in enumerate(candidates, start=1):
        console.print(f"  [{index}] {candidate.id}: {candidate.name}")
    selection = typer.prompt("Pipeline selection", type=int)
    if selection < 1 or selection > len(candidates):
        raise ContextResolutionError("Invalid pipeline selection index.")
    chosen = candidates[selection - 1]
    return int(chosen.id)


def _is_interactive_terminal() -> bool:
    """Return whether the current process has an interactive TTY."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _resolve_ref_name(explicit_ref: str | None, *, current_branch: str | None) -> str:
    """Resolve Azure DevOps ref name for preview/template expansion.

    Resolution order:
    1. Explicit ``--azdo-ref-name`` value.
    2. ``AZDO_REFNAME`` environment variable.
    3. Current git branch mapped to ``refs/heads/<branch>``.
    4. ``refs/heads/main`` fallback.

    Args:
        explicit_ref: Explicit ref override from CLI.
        current_branch: Current git branch name when available.

    Returns:
        A normalized ref name string.
    """
    if explicit_ref and explicit_ref.strip():
        return explicit_ref.strip()
    env_ref = os.getenv("AZDO_REFNAME", "").strip()
    if env_ref:
        return env_ref
    if current_branch and current_branch.strip() and current_branch.strip() != "HEAD":
        branch = current_branch.strip()
        if branch.startswith("refs/"):
            return branch
        return f"refs/heads/{branch}"
    return "refs/heads/main"


def _resolve_preview_target(
    *,
    target: Path,
    repo_root: Path,
    run_preview: bool,
    explicit_preview_target: Path | None,
    settings: Settings | None,
) -> tuple[Path | None, list[str]]:
    """Resolve preview target behavior for local and CI execution.

    Args:
        target: User-selected validation target.
        repo_root: Repository root for relative path resolution.
        run_preview: Whether preview stage is enabled.
        explicit_preview_target: Optional explicit preview target path.
        settings: Resolved Azure settings used for auto-detection.

    Returns:
        Tuple of resolved preview target path (or ``None`` for per-file preview)
        and user-facing warnings.

    Raises:
        ContextResolutionError: If an explicit preview target path does not exist.
    """
    warnings: list[str] = []
    if not run_preview:
        return None, warnings

    resolved_target = _resolve_target_path(repo_root=repo_root, candidate=target)
    env_preview_target = os.getenv("AZP_VALIDATOR_PREVIEW_TARGET", "").strip()
    effective_preview_target = explicit_preview_target or (
        Path(env_preview_target) if env_preview_target else None
    )
    if effective_preview_target is not None:
        resolved_preview = _resolve_target_path(
            repo_root=repo_root, candidate=effective_preview_target
        )
        if not resolved_preview.exists():
            raise ContextResolutionError(f"Preview target path does not exist: {resolved_preview}")
        if resolved_preview.is_dir():
            raise ContextResolutionError(
                f"Preview target must be a file, not a directory: {resolved_preview}"
            )
        return resolved_preview, warnings

    if resolved_target.is_file():
        return resolved_target, warnings

    if _is_ci_environment():
        warnings.append(
            "CI environment detected; preview runs per file unless --preview-target "
            "(or AZP_VALIDATOR_PREVIEW_TARGET) is set."
        )
        return None, warnings

    if settings is None:
        return None, warnings

    discovered_path = _discover_pipeline_yaml_path_with_az(settings=settings)
    if not discovered_path:
        warnings.append(
            "Unable to auto-detect main pipeline YAML via Azure DevOps CLI; "
            "preview will run per file."
        )
        return None, warnings

    normalized_discovered_path = discovered_path.strip()
    path_candidate = Path(normalized_discovered_path)
    if normalized_discovered_path.startswith("/"):
        # Azure DevOps commonly reports repo-relative YAML paths with a leading slash.
        resolved_preview = (repo_root / normalized_discovered_path.lstrip("/")).resolve()
    elif path_candidate.is_absolute():
        resolved_preview = path_candidate.resolve()
    else:
        resolved_preview = (repo_root / normalized_discovered_path).resolve()

    if not resolved_preview.exists():
        warnings.append(
            "Azure DevOps reported main pipeline YAML path "
            f"'{discovered_path}', but it was not found locally; preview will run per file."
        )
        return None, warnings
    if resolved_preview.is_dir():
        warnings.append(
            "Azure DevOps reported a directory as the main pipeline target; "
            "preview will run per file."
        )
        return None, warnings

    try:
        display_path = resolved_preview.relative_to(repo_root).as_posix()
    except ValueError:
        display_path = resolved_preview.as_posix()
    warnings.append(f"Local mode: preview is scoped to main pipeline file '{display_path}'.")
    return resolved_preview, warnings


def _discover_pipeline_yaml_path_with_az(*, settings: Settings) -> str | None:
    """Discover the configured pipeline YAML path using Azure DevOps CLI.

    Args:
        settings: Resolved settings containing org/project/pipeline context.

    Returns:
        Pipeline configuration path from Azure DevOps when available.
    """
    show_command = [
        "az",
        "pipelines",
        "show",
        "--id",
        str(settings.pipeline_id),
        "--org",
        str(settings.organization),
        "--project",
        settings.project,
        "--output",
        "json",
    ]
    show_payload = _run_az_json(show_command)
    discovered = _extract_pipeline_yaml_path(show_payload)
    if discovered:
        return discovered

    # Some projects surface YAML path only through the legacy build definition
    # payload (`process.yamlFilename`), so keep this as a CLI fallback.
    fallback_command = [
        "az",
        "devops",
        "invoke",
        "--area",
        "build",
        "--resource",
        "definitions",
        "--route-parameters",
        f"project={settings.project}",
        f"definitionId={settings.pipeline_id}",
        "--api-version",
        "7.1",
        "--org",
        str(settings.organization),
        "--output",
        "json",
    ]
    fallback_payload = _run_az_json(fallback_command)
    return _extract_pipeline_yaml_path(fallback_payload)


def _run_az_json(command: Sequence[str]) -> Mapping[str, object] | None:
    """Run an Azure CLI command and parse JSON output when successful.

    Args:
        command: Azure CLI command sequence.

    Returns:
        Parsed JSON object payload when available; otherwise ``None``.
    """
    try:
        result = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, Mapping):
        return payload
    return None


def _extract_pipeline_yaml_path(payload: Mapping[str, object] | None) -> str | None:
    """Extract a pipeline YAML path from CLI payload variants.

    Args:
        payload: Parsed CLI JSON payload.

    Returns:
        Normalized YAML path when present.
    """
    if payload is None:
        return None

    candidates: list[object] = []
    configuration = payload.get("configuration")
    if isinstance(configuration, Mapping):
        candidates.append(configuration.get("path"))

    process = payload.get("process")
    if isinstance(process, Mapping):
        candidates.extend((process.get("yamlFilename"), process.get("yamlFileName")))

    candidates.extend((payload.get("yamlFilename"), payload.get("yamlFileName")))

    for candidate in candidates:
        if isinstance(candidate, str):
            normalized = candidate.strip()
            if normalized:
                return normalized
    return None


def _resolve_target_path(*, repo_root: Path, candidate: Path) -> Path:
    """Resolve a candidate path relative to the repo root when needed.

    Args:
        repo_root: Repository root path.
        candidate: User-provided or discovered path.

    Returns:
        Absolute resolved path.
    """
    if candidate.is_absolute():
        return candidate.resolve()
    return (repo_root / candidate).resolve()


def _is_ci_environment() -> bool:
    """Return whether current process appears to run in CI."""
    return any(
        bool(os.getenv(name, "").strip())
        for name in (
            "CI",
            "TF_BUILD",
            "GITHUB_ACTIONS",
            "BUILDKITE",
            "JENKINS_URL",
            "BUILD_BUILDID",
        )
    )


def _resolve_bool_env(env_name: str, default_value: bool) -> bool:
    """Resolve a boolean option with environment override support.

    Args:
        env_name: Environment variable name.
        default_value: Fallback boolean value.

    Returns:
        Parsed boolean value from environment or the provided default.
    """
    raw = os.getenv(env_name)
    if raw is None:
        return default_value
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default_value


def _attach_warnings(summary: ValidationSummary, warnings: list[str]) -> ValidationSummary:
    """Attach contextual warnings to the validation summary."""
    if not warnings:
        return summary
    return ValidationSummary(
        results=summary.results,
        include_lint=summary.include_lint,
        include_schema=summary.include_schema,
        include_preview=summary.include_preview,
        include_lsp=summary.include_lsp,
        gate_mode=summary.gate_mode,
        fail_fast=summary.fail_fast,
        stopped_early=summary.stopped_early,
        discovered_files=summary.discovered_files,
        warnings=tuple([*summary.warnings, *warnings]),
    )
