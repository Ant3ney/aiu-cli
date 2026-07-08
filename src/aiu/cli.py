"""Command-line entry point for AI University."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import click

from aiu.approval import ApprovalError, approve_course
from aiu.auth import AuthConfigurationError, AuthStore
from aiu.config import CourseSettings
from aiu.exports import ExportError, export_course
from aiu.extract import extract_and_chunk_sources
from aiu.generation import GenerationError, generate_course
from aiu.ingest import inventory_context_paths, write_inventory_artifacts
from aiu.logging import CourseLoadingView, configure_logging, emit_progress, log_project_event
from aiu.planning import PlanningError, plan_course
from aiu.project import ProjectInitializationError, initialize_project, write_project_prompt
from aiu.prompt import PromptIntakeError, read_prompt_text
from aiu.regeneration import RegenerationError, regenerate_artifact
from aiu.resume import ResumeError, resume_course
from aiu.state import status_lines
from aiu.validation import CourseValidationError, validate_course
from aiu.version import __version__

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def _not_implemented(task: str) -> Callable[..., None]:
    """Return a command callback that documents planned implementation scope."""

    def callback(*_args: object, **_kwargs: object) -> None:
        raise click.ClickException(f"This command is scaffolded and will be implemented in {task}.")

    return callback


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(__version__, prog_name="aiu")
@click.option("-v", "--verbose", count=True, help="Increase log verbosity.")
def main(verbose: int) -> None:
    """Generate complete AI University course packages from prompts and source material."""

    configure_logging(verbosity=verbose)


@main.command("init")
@click.option(
    "--output",
    "output_path",
    type=click.Path(file_okay=False, dir_okay=True, path_type=str),
    default=".",
    show_default=True,
    help="Course project directory to initialize.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Allow initialization in a non-empty directory and overwrite AIU metadata files.",
)
def init_command(output_path: str, force: bool) -> None:
    """Initialize an empty AI University course project."""

    try:
        project = initialize_project(output_path, force=force)
    except ProjectInitializationError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Initialized AI University project at {project.paths.root}")


@main.group(context_settings=CONTEXT_SETTINGS)
def auth() -> None:
    """Configure and inspect AI provider authentication."""


@auth.command("login")
@click.option(
    "--provider",
    type=click.Choice(["fake", "codex", "openai"], case_sensitive=False),
    required=True,
    help="Provider to configure.",
)
@click.option(
    "--api-key-env",
    metavar="NAME",
    help="Environment variable that contains the provider API key.",
)
@click.option(
    "--codex-command",
    default="codex",
    show_default=True,
    help="Codex executable to use when configuring the codex provider.",
)
def auth_login(provider: str, api_key_env: str | None, codex_command: str) -> None:
    """Configure credentials for an AI provider."""

    try:
        configured_provider = provider.lower()
        AuthStore().configure_provider(
            configured_provider,
            api_key_env=api_key_env,
            codex_command=codex_command,
        )
    except AuthConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Configured provider: {configured_provider}")


@auth.command("status")
def auth_status() -> None:
    """Show configured AI providers without printing secrets."""

    for line in AuthStore().status_lines():
        click.echo(line)


@main.group(context_settings=CONTEXT_SETTINGS)
def course() -> None:
    """Create, generate, validate, and export course packages."""


@course.command("create")
@click.argument("prompt_text", required=False)
@click.option(
    "--prompt",
    "prompt_file",
    type=click.Path(exists=True, dir_okay=False, path_type=str),
    help="Read the learning prompt from a Markdown/text file.",
)
@click.option("--stdin", "from_stdin", is_flag=True, help="Read the learning prompt from stdin.")
@click.option(
    "--context",
    "context_paths",
    multiple=True,
    type=click.Path(exists=True, path_type=str),
    help="File, archive, image, or directory to use as course source material.",
)
@click.option(
    "--exclude",
    "exclude_patterns",
    multiple=True,
    help="Glob pattern to exclude from context inventory. May be supplied more than once.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(file_okay=False, dir_okay=True, path_type=str),
    required=True,
    help="Course project output directory.",
)
@click.option("--weeks", type=click.IntRange(min=1), default=24, show_default=True)
@click.option("--lectures-per-week", type=click.IntRange(min=1), default=2, show_default=True)
@click.option("--lecture-hours", type=click.FloatRange(min=0.25), default=2.0, show_default=True)
@click.option(
    "--lab-policy",
    type=click.Choice(["auto", "always", "never"], case_sensitive=False),
    default="auto",
    show_default=True,
)
@click.option("--level", default="beginner", show_default=True, help="Target learner level.")
@click.option(
    "--provider",
    type=click.Choice(["fake", "codex", "openai"], case_sensitive=False),
    default="fake",
    show_default=True,
)
@click.option("--yes", is_flag=True, help="Proceed without interactive approval prompts.")
@click.option("--init-only", is_flag=True, help="Initialize project inputs without generation.")
@click.option(
    "--generate-until",
    type=click.Choice(["blueprint"], case_sensitive=False),
    help="Run the create pipeline through the selected stage.",
)
def course_create(
    prompt_text: str | None,
    prompt_file: str | None,
    from_stdin: bool,
    context_paths: tuple[str, ...],
    exclude_patterns: tuple[str, ...],
    output_path: str | None,
    weeks: int,
    lectures_per_week: int,
    lecture_hours: float,
    lab_policy: str,
    level: str,
    provider: str,
    yes: bool,
    init_only: bool,
    generate_until: str | None,
) -> None:
    """Create a course project from a learning prompt and optional context."""

    progress_view: CourseLoadingView | None = None
    try:
        prompt = read_prompt_text(
            prompt_text=prompt_text,
            prompt_file=prompt_file,
            from_stdin=from_stdin,
            stdin=click.get_text_stream("stdin"),
        )
        settings = CourseSettings(
            weeks=weeks,
            lectures_per_week=lectures_per_week,
            lecture_hours=lecture_hours,
            lab_policy=lab_policy.lower(),
            level=level,
            provider=provider.lower(),
        )
        project = initialize_project(output_path, settings=settings)
        progress_view = CourseLoadingView(project.paths.root)
        progress_view.start(
            "AI University course creation",
            detail=(
                f"{weeks} week(s), {lectures_per_week} lecture(s)/week, "
                f"provider {provider.lower()}"
            ),
        )
        emit_progress(
            progress_view,
            "project",
            "Initialized project workspace",
            artifact="manifest.json",
            detail=str(project.paths.root),
        )
        log_project_event(project.paths.root, "project initialized")
        write_project_prompt(project, prompt)
        emit_progress(
            progress_view,
            "inputs",
            "Stored learning prompt",
            artifact="prompt.md",
            detail=f"{len(prompt.split())} word(s), {len(prompt)} character(s)",
        )
        log_project_event(project.paths.root, "prompt stored")
        if context_paths:
            emit_progress(
                progress_view,
                "context",
                "Inventorying context paths",
                detail=f"{len(context_paths)} path(s) supplied.",
            )
            inventory = inventory_context_paths(context_paths, excludes=exclude_patterns)
            emit_progress(
                progress_view,
                "context",
                "Context inventory complete",
                artifact="source_manifest.json",
                detail=(
                    f"{len(inventory.sources)} accepted, {len(inventory.skipped)} skipped, "
                    f"{len(inventory.ignored)} ignored, {len(inventory.errors)} error(s)"
                ),
            )
            write_inventory_artifacts(project.paths.root, inventory)
            extract_and_chunk_sources(project.paths.root, inventory, progress=progress_view)
            log_project_event(project.paths.root, "context inventoried and extracted")
        if generate_until == "blueprint":
            plan_course(project.paths.root, progress=progress_view)
            log_project_event(project.paths.root, "blueprint generated")
        elif yes and not init_only:
            plan_course(project.paths.root, progress=progress_view)
            log_project_event(project.paths.root, "blueprint generated")
            approve_course(project.paths.root, mode="auto")
            emit_progress(
                progress_view,
                "approval",
                "Approved generated blueprint",
                artifact="approved_course_blueprint.json",
                detail="Automatic approval requested with --yes.",
            )
            log_project_event(project.paths.root, "blueprint approved")
            generate_course(project.paths.root, progress=progress_view)
            log_project_event(project.paths.root, "all generation stages completed")
            emit_progress(
                progress_view,
                "validation",
                "Running final course validation",
                artifact="validation_report.json",
            )
            report = validate_course(project.paths.root)
            emit_progress(
                progress_view,
                "validation",
                "Validation complete",
                artifact="validation_report.json",
                detail=f"status={report.status.value}; {len(report.checks)} check(s)",
            )
            log_project_event(
                project.paths.root, f"validation completed with status {report.status.value}"
            )
        if progress_view is not None:
            progress_view.finish("Course creation command finished.")
    except (
        ApprovalError,
        CourseValidationError,
        GenerationError,
        PlanningError,
        PromptIntakeError,
        ProjectInitializationError,
    ) as exc:
        if progress_view is not None:
            progress_view.fail(str(exc))
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Created AI University course project at {project.paths.root}")
    if context_paths:
        click.echo(f"Inventoried {len(inventory.sources)} context source(s).")
    if not init_only:
        if generate_until == "blueprint":
            click.echo("Generated course blueprint; full course generation is still pending.")
        elif yes:
            click.echo("Generated and validated AI University course package.")
        else:
            click.echo(
                "Prompt intake is complete; full course generation requires "
                "--yes or separate commands."
            )


@course.command("plan")
@click.argument("course_root", type=click.Path(exists=False, path_type=str))
@click.option(
    "--force",
    is_flag=True,
    help="Regenerate the blueprint even if planning was already completed.",
)
def course_plan(course_root: str, force: bool) -> None:
    """Generate or inspect a course blueprint before full generation."""

    progress_view: CourseLoadingView | None = None
    if Path(course_root).exists():
        progress_view = CourseLoadingView(course_root)
        progress_view.start("AI University course planning", detail=str(Path(course_root)))
    try:
        blueprint = plan_course(course_root, force=force, progress=progress_view)
    except PlanningError as exc:
        if progress_view is not None:
            progress_view.fail(str(exc))
        raise click.ClickException(str(exc)) from exc
    if progress_view is not None:
        progress_view.finish(f"Generated course blueprint: {blueprint.course_title}")
    click.echo(f"Generated course blueprint: {blueprint.course_title}")


@course.command("approve")
@click.argument("course_root", type=click.Path(exists=False, path_type=str))
def course_approve(course_root: str) -> None:
    """Approve a course blueprint for generation."""

    try:
        metadata = approve_course(course_root)
    except ApprovalError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Approved course blueprint: {metadata['approved_blueprint_ref']}")


@course.command("generate")
@click.argument("course_root", type=click.Path(exists=False, path_type=str))
@click.option("--yes", is_flag=True, help="Approve the current blueprint before generation.")
@click.option(
    "--dry-run", is_flag=True, help="Check generation readiness without writing artifacts."
)
@click.option(
    "--stage",
    type=click.Choice(["all", "syllabus", "lectures", "labs", "assessments"], case_sensitive=False),
    help="Generate a single stage.",
)
@click.option(
    "--force", is_flag=True, help="Regenerate completed artifacts for the selected stage."
)
@click.option("--from", "from_ref", metavar="REF", help="Starting week or artifact reference.")
@click.option("--to", "to_ref", metavar="REF", help="Ending week or artifact reference.")
def course_generate(
    course_root: str,
    yes: bool,
    dry_run: bool,
    stage: str | None,
    force: bool,
    from_ref: str | None,
    to_ref: str | None,
) -> None:
    """Generate course artifacts for all or part of a project."""

    progress_view: CourseLoadingView | None = None
    if not dry_run and Path(course_root).exists():
        selected_stage = stage.lower() if stage is not None else "all"
        progress_view = CourseLoadingView(course_root)
        progress_view.start(
            "AI University course generation",
            detail=f"stage={selected_stage}, force={force}",
        )
    try:
        result = generate_course(
            course_root,
            yes=yes,
            dry_run=dry_run,
            stage=stage.lower() if stage is not None else None,
            force=force,
            from_ref=from_ref,
            progress=progress_view,
            to_ref=to_ref,
        )
    except GenerationError as exc:
        if progress_view is not None:
            progress_view.fail(str(exc))
        raise click.ClickException(str(exc)) from exc

    if result["dry_run"]:
        click.echo(f"Generation dry run ready for stage: {result['stage']}")
    else:
        if progress_view is not None:
            progress_view.finish(str(result["message"]))
        click.echo(str(result["message"]))


@course.command("regenerate")
@click.argument("course_root", type=click.Path(exists=False, path_type=str))
@click.option(
    "--artifact",
    "artifact_ref",
    required=True,
    help="Artifact ID or range to regenerate.",
)
def course_regenerate(course_root: str, artifact_ref: str) -> None:
    """Regenerate selected weeks, lectures, labs, or assessments."""

    progress_view: CourseLoadingView | None = None
    if Path(course_root).exists():
        progress_view = CourseLoadingView(course_root)
        progress_view.start("AI University course regeneration", detail=artifact_ref)
    try:
        artifacts = regenerate_artifact(course_root, artifact_ref, progress=progress_view)
    except RegenerationError as exc:
        if progress_view is not None:
            progress_view.fail(str(exc))
        raise click.ClickException(str(exc)) from exc
    if progress_view is not None:
        progress_view.finish(f"Regenerated {len(artifacts)} artifact(s).")
    click.echo(f"Regenerated {len(artifacts)} artifact(s).")


@course.command("resume")
@click.argument("course_root", type=click.Path(exists=False, path_type=str))
@click.option(
    "--yes",
    is_flag=True,
    help="Approve an unapproved blueprint before resuming generation.",
)
def course_resume(course_root: str, yes: bool) -> None:
    """Resume an interrupted course creation run from checkpoints."""

    progress_view: CourseLoadingView | None = None
    if Path(course_root).exists():
        progress_view = CourseLoadingView(course_root)
        progress_view.start(
            "AI University course resume",
            detail="continue from durable checkpoints and existing artifacts",
        )
    try:
        result = resume_course(course_root, yes=yes, progress=progress_view)
    except ResumeError as exc:
        if progress_view is not None:
            progress_view.fail(str(exc))
        raise click.ClickException(str(exc)) from exc
    if progress_view is not None:
        progress_view.finish(f"Resume complete with validation status {result['status']}.")
    click.echo(f"Resumed AI University course package with status: {result['status']}")


@course.command("status")
@click.argument("course_root", type=click.Path(exists=False, path_type=str))
def course_status(course_root: str) -> None:
    """Show generation progress and checkpoint state for a course project."""

    for line in status_lines(course_root):
        click.echo(line)


@course.command("validate")
@click.argument("course_root", type=click.Path(exists=False, path_type=str))
def course_validate(course_root: str) -> None:
    """Validate completeness, consistency, citations, and schemas."""

    try:
        report = validate_course(course_root)
    except CourseValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Validation status: {report.status.value}")


@course.command("export")
@click.argument("course_root", type=click.Path(exists=False, path_type=str))
@click.option(
    "--format",
    "formats",
    default="markdown,json,vr",
    show_default=True,
    help="Comma-separated export formats.",
)
def course_export(course_root: str, formats: str) -> None:
    """Export generated course artifacts for humans or downstream systems."""

    try:
        artifacts = export_course(course_root, formats)
    except ExportError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Exported {len(artifacts)} artifact(s).")
