"""Command-line entry point for AI University."""

from __future__ import annotations

from collections.abc import Callable

import click

from aiu.logging import configure_logging
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
def init_command(output_path: str) -> None:
    """Initialize an empty AI University course project."""

    _not_implemented("Task 2")(output_path=output_path)


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
def auth_login(provider: str, api_key_env: str | None) -> None:
    """Configure credentials for an AI provider."""

    _not_implemented("Task 5")(provider=provider, api_key_env=api_key_env)


@auth.command("status")
def auth_status() -> None:
    """Show configured AI providers without printing secrets."""

    _not_implemented("Task 5")()


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
    "--output",
    "output_path",
    type=click.Path(file_okay=False, dir_okay=True, path_type=str),
    required=False,
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
def course_create(
    prompt_text: str | None,
    prompt_file: str | None,
    from_stdin: bool,
    context_paths: tuple[str, ...],
    output_path: str | None,
    weeks: int,
    lectures_per_week: int,
    lecture_hours: float,
    lab_policy: str,
    level: str,
    provider: str,
    yes: bool,
    init_only: bool,
) -> None:
    """Create a course project from a learning prompt and optional context."""

    _not_implemented("Task 3")(
        prompt_text=prompt_text,
        prompt_file=prompt_file,
        from_stdin=from_stdin,
        context_paths=context_paths,
        output_path=output_path,
        weeks=weeks,
        lectures_per_week=lectures_per_week,
        lecture_hours=lecture_hours,
        lab_policy=lab_policy,
        level=level,
        provider=provider,
        yes=yes,
        init_only=init_only,
    )


@course.command("plan")
@click.argument("course_root", type=click.Path(exists=False, path_type=str))
def course_plan(course_root: str) -> None:
    """Generate or inspect a course blueprint before full generation."""

    _not_implemented("Task 7")(course_root=course_root)


@course.command("approve")
@click.argument("course_root", type=click.Path(exists=False, path_type=str))
def course_approve(course_root: str) -> None:
    """Approve a course blueprint for generation."""

    _not_implemented("Task 8")(course_root=course_root)


@course.command("generate")
@click.argument("course_root", type=click.Path(exists=False, path_type=str))
@click.option("--from", "from_ref", metavar="REF", help="Starting week or artifact reference.")
@click.option("--to", "to_ref", metavar="REF", help="Ending week or artifact reference.")
def course_generate(course_root: str, from_ref: str | None, to_ref: str | None) -> None:
    """Generate course artifacts for all or part of a project."""

    _not_implemented("Task 9")(course_root=course_root, from_ref=from_ref, to_ref=to_ref)


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

    _not_implemented("Task 18")(course_root=course_root, artifact_ref=artifact_ref)


@course.command("status")
@click.argument("course_root", type=click.Path(exists=False, path_type=str))
def course_status(course_root: str) -> None:
    """Show generation progress and checkpoint state for a course project."""

    _not_implemented("Task 15")(course_root=course_root)


@course.command("validate")
@click.argument("course_root", type=click.Path(exists=False, path_type=str))
def course_validate(course_root: str) -> None:
    """Validate completeness, consistency, citations, and schemas."""

    _not_implemented("Task 14")(course_root=course_root)


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

    _not_implemented("Task 19")(course_root=course_root, formats=formats)
