"""Asking a long restore run to stop, without tearing it apart mid-page.

A full restore is days of work across a pool of worker processes, each driving gmic
subprocesses that are minutes long. Interrupting that from the terminal kills the whole
process group at once, which leaves half-written intermediates behind and tells you
nothing about where it got to.

So a stop is asked for rather than forced, by writing a file into the run's work
directory. Any terminal can write it, the run does not have to be in the foreground, and
the worker processes can see it directly because it is on the filesystem - which matters,
since a flag set in the parent would never reach them.

There are two levels, because how long a clean stop takes depends on where the run is:

``PAGES``
    Pages already started go through every remaining phase, so they come out finished
    and recorded. Nothing new is picked up. Worst case is about an hour - the pages in
    flight when part 1 was interrupted still have smoothing and inpainting ahead of them.

``STEP``
    Every worker finishes the step it is in and then stops. About ten minutes at worst,
    the length of one smoothing step. Pages are left part way through with their work
    files intact, so ``--use-existing-work-files`` picks them up where they left off.

Asking twice escalates from the first to the second, which is the same instinct as
pressing an interrupt twice, and lets the decision be made later - when you know how
long you are actually willing to wait.
"""

import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger

from barks_comic_building.cli_setup import init_logging
from barks_comic_building.restore.ledger_common import now

APP_LOGGING_NAME = "stop"

STOP_FILENAME = "STOP"

_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600

_DURATION_UNITS = {"h": _SECONDS_PER_HOUR, "m": _SECONDS_PER_MINUTE, "s": 1}
_DURATION_PART = re.compile(r"(\d+)\s*([hms])", re.IGNORECASE)


class StopMode(StrEnum):
    """How much a run should finish before it stops."""

    NONE = "none"
    """No stop asked for."""

    PAGES = "pages"
    """Let pages that have started finish every remaining phase, and start nothing new.

    The pages in flight come out complete and recorded, so the run leaves no partial
    work behind. Costs as long as those pages have left to run - up to about an hour if
    the stop lands early, when the pages in flight still have smoothing and inpainting
    ahead of them."""

    STEP = "step"
    """Let each worker finish the step it is in, then stop.

    About ten minutes at worst, the length of one smoothing step. Pages are left part
    way through, but every intermediate on disk is a complete file, so the next run
    resumes from them with --use-existing-work-files."""

    @property
    def stops_pages_that_have_started(self) -> bool:
        """Whether a page already under way should be cut short rather than finished."""
        return self is StopMode.STEP

    @property
    def describe(self) -> str:
        """Return what this mode means, for a human reading a log line."""
        if self is StopMode.PAGES:
            return (
                "pages already started will finish all their remaining steps;"
                " no new pages will be started"
            )
        if self is StopMode.STEP:
            return (
                "each worker will finish the step it is in and then stop;"
                " part-finished pages resume next run with --use-existing-work-files"
            )
        return "no stop requested"


def get_stop_file(work_dir: Path) -> Path:
    """Return where the stop request for a run using this work directory lives.

    Args:
        work_dir: The run's work directory.

    Returns:
        The stop file's path, whether or not it exists.

    """
    return work_dir / STOP_FILENAME


def read_stop_mode(stop_file: Path | None) -> StopMode:
    """Return the stop asked for, if any.

    Called from the worker processes as well as the parent, between steps and at the
    start of each phase, so it stays a single stat and a short read.

    A file that exists but cannot be read is treated as ``PAGES`` rather than as no
    request at all: somebody clearly asked for a stop, and the safe reading of a damaged
    request is the gentler of the two.

    Args:
        stop_file: The stop file to look for. None means stopping is not wired up.

    Returns:
        The mode asked for, or ``NONE``.

    """
    if stop_file is None or not stop_file.is_file():
        return StopMode.NONE

    try:
        first_line = stop_file.read_text(encoding="utf-8").strip().splitlines()[0]
        return StopMode(first_line.strip().lower())
    except (OSError, IndexError, ValueError):
        return StopMode.PAGES


def request_stop(work_dir: Path, mode: StopMode = StopMode.PAGES) -> StopMode:
    """Ask a run using this work directory to stop, escalating a request already there.

    Asking again for a stop that has already been asked for moves it up to ``STEP``, so
    a second ask means "sooner" without having to remember a flag.

    Args:
        work_dir: The run's work directory.
        mode: The mode to ask for.

    Returns:
        The mode now in force, which may be further along than the one asked for.

    Raises:
        ValueError: If asked to request ``NONE``, which would mean clearing the request.
            `clear_stop` does that, and saying so plainly beats writing a file that
            reads as a stop but is not one.

    """
    if mode is StopMode.NONE:
        msg = "Use clear_stop() to withdraw a stop request."
        raise ValueError(msg)

    # A second ask means sooner, and a gentler one must never undo an urgent one that
    # came before it - somebody who asked to stop at the current step should not have
    # that quietly relaxed back into waiting out whole pages. With STEP the strongest
    # mode there is, both cases come to the same thing: once anything has been asked
    # for, asking again gives STEP.
    if read_stop_mode(get_stop_file(work_dir)) is not StopMode.NONE:
        mode = StopMode.STEP

    stop_file = get_stop_file(work_dir)
    stop_file.parent.mkdir(parents=True, exist_ok=True)
    stop_file.write_text(f"{mode}\nrequested {now()}\n{mode.describe}\n", encoding="utf-8")

    return mode


def clear_stop(work_dir: Path) -> bool:
    """Withdraw any stop request for this work directory.

    Called at the start of every run, so that a request left over from the last one
    cannot stop the next before it has done anything.

    Args:
        work_dir: The run's work directory.

    Returns:
        Whether there was a request to withdraw.

    """
    stop_file = get_stop_file(work_dir)
    if not stop_file.is_file():
        return False

    stop_file.unlink(missing_ok=True)

    return True


def parse_duration(text: str) -> float:
    """Return a duration in seconds from something like ``8h``, ``90m`` or ``1h30m``.

    Args:
        text: The duration to parse.

    Returns:
        The duration in seconds.

    Raises:
        ValueError: If nothing in the text parses, or a unit is repeated. A silently
            misread duration would leave a run stopping at the wrong time, which is
            worse than being told the spelling is wrong.

    """
    cleaned = text.strip()
    parts = _DURATION_PART.findall(cleaned)
    if not parts:
        msg = f'Could not read "{text}" as a duration. Try something like 8h, 90m or 1h30m.'
        raise ValueError(msg)

    if len(_DURATION_PART.sub("", cleaned).strip()) > 0:
        msg = f'Did not understand all of "{text}" as a duration. Try 8h, 90m or 1h30m.'
        raise ValueError(msg)

    units_seen = [unit.lower() for _, unit in parts]
    if len(set(units_seen)) != len(units_seen):
        msg = f'Duration "{text}" repeats a unit.'
        raise ValueError(msg)

    return float(sum(int(amount) * _DURATION_UNITS[unit.lower()] for amount, unit in parts))


app = typer.Typer()


@app.command(help="Ask a running restore to stop cleanly")
def main(
    work_dir: Annotated[
        Path,
        typer.Option(help="The work directory the run was started with."),
    ],
    now_: Annotated[
        bool,
        typer.Option("--now", help="Stop after the current step rather than the current pages."),
    ] = False,
    withdraw: Annotated[
        bool,
        typer.Option("--withdraw", help="Take back a stop request, letting the run carry on."),
    ] = False,
    log_level_str: Annotated[str, typer.Option("--log-level")] = "INFO",
) -> None:
    init_logging(APP_LOGGING_NAME, "restore-stop.log", log_level_str)

    if not work_dir.is_dir():
        msg = f'Work directory not found: "{work_dir}".'
        raise typer.BadParameter(msg)

    if withdraw:
        if clear_stop(work_dir):
            logger.info("Stop request withdrawn - the run will carry on.")
        else:
            logger.info("There was no stop request to withdraw.")
        return

    mode = request_stop(work_dir, StopMode.STEP if now_ else StopMode.PAGES)

    logger.info(f"Stop requested ({mode}): {mode.describe}.")
    if mode is StopMode.PAGES:
        logger.info("Ask again to stop sooner, after the current step instead.")


if __name__ == "__main__":
    app()
