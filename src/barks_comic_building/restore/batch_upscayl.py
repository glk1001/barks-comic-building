import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, NamedTuple

import typer
from barks_fantagraphics.comic_book import ModifiedType
from barks_fantagraphics.comic_book_info import is_non_comic_title
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_utils import get_abbrev_path
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from loguru import logger

from barks_comic_building.cli_setup import get_comic_titles, init_logging
from barks_comic_building.restore.report_format import format_duration
from barks_comic_building.restore.upscale_image import (
    DEFAULT_UPSCALER,
    Upscaler,
    UpscalerArg,
    check_upscaler_is_usable,
    upscale_image_file,
)
from barks_comic_building.restore.upscale_ledger import (
    OUTCOME_FAILED,
    OUTCOME_OK,
    UpscaleLedgerWriter,
    get_default_upscale_ledger_file,
    read_upscale_ledger,
)
from barks_comic_building.restore.upscale_recipe import UpscaleRecipe, get_current_recipe
from barks_comic_building.restore.upscale_state import (
    UpscalePageState,
    get_upscale_page_status,
)

APP_LOGGING_NAME = "bups"

SCALE = 4

# Give up after this many pages fail in a row. A GPU that has stopped producing usable
# images fails every page the same way, and grinding through the rest of a volume to
# record a thousand identical failures helps nobody.
MAX_CONSECUTIVE_FAILURES = 5


class _PageJob(NamedTuple):
    """One page the upscale is going to do."""

    title: str
    volume: int
    page: str
    srce_file: Path
    dest_file: Path


def get_title_jobs(
    comics_database: ComicsDatabase,
    title: str,
    recipe: UpscaleRecipe,
    counts: dict[str, int],
    *,
    force: bool,
) -> list[_PageJob]:
    """Return the pages of a title that need upscayling, counting the ones that do not.

    Args:
        comics_database: The comics database.
        title: The story to look at.
        recipe: The settings the upscale would use now.
        counts: Per-state tally, added to in place, for reporting what the run skipped.
        force: Queue pages that are already current.

    Returns:
        A job per page that needs doing.

    """
    comic = comics_database.get_comic_book(title)
    volume = comics_database.get_fanta_volume_int(title)

    srce_files = comic.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES)
    upscayl_files = comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)

    jobs: list[_PageJob] = []
    for (srce_file, _srce_mod), (dest_file, dest_mod) in zip(
        srce_files, upscayl_files, strict=True
    ):
        status = get_upscale_page_status(
            srce_file,
            dest_file,
            recipe.recipe_id,
            # A non-ORIGINAL dest is not the upscayled page at all - it is the hand-edited
            # file standing in for it, and this run's output would be written over the top.
            is_fixes_file=dest_mod is not ModifiedType.ORIGINAL,
        )
        counts[status.state] = counts.get(status.state, 0) + 1

        # Neither of these two is queued even under --force.

        # Hand edits cannot be remade, and carry no recipe of ours, so they read as stale
        # and would be overwritten on every run.
        if status.state == UpscalePageState.FIXES:
            logger.debug(f'Page is a hand-edited fixes file - skipping: "{dest_file}".')
            continue

        # This page is a symlink to another volume's, and forcing it would write through
        # the link over a page that is not this title's.
        if status.state == UpscalePageState.LINKED:
            logger.debug(f'Page belongs to another volume - skipping: "{dest_file}".')
            continue

        if status.state == UpscalePageState.NO_SRCE:
            logger.warning(f'No srce file - cannot upscayl: "{get_abbrev_path(srce_file)}".')
            continue

        if not status.needs_upscayling and not force:
            continue

        jobs.append(
            _PageJob(
                title=title,
                volume=volume,
                page=Path(srce_file).stem,
                srce_file=Path(srce_file),
                dest_file=dest_file,
            )
        )

    return jobs


def upscayl(
    comics_database: ComicsDatabase,
    title_list: list[str],
    upscaler: Upscaler,
    ledger_file: Path,
    *,
    force: bool,
) -> None:
    """Upscayl every page of every given title that is not already up to date.

    Args:
        comics_database: The comics database.
        title_list: The titles to upscayl.
        upscaler: Which backend to run.
        ledger_file: Where to append the record of what was done.
        force: Upscayl pages that are already current.

    """
    start = time.time()

    # Up front, and allowed to raise. A missing binary or an impossible scale is true for
    # every page or none, so finding out per page would write one identical failure record
    # per queued page - thousands of them - and call that a completed run.
    check_upscaler_is_usable(upscaler, SCALE)

    recipe = get_current_recipe(upscaler, SCALE)
    logger.info(f"Upscale recipe {recipe.recipe_id}: {recipe.as_json()}")

    jobs: list[_PageJob] = []
    counts: dict[str, int] = {}
    for title in title_list:
        if is_non_comic_title(title):
            logger.info(f'Not a comic title - not upscayling "{title}".')
            continue

        jobs += get_title_jobs(comics_database, title, recipe, counts, force=force)

    _log_run_estimate(jobs, counts, ledger_file, recipe)
    if not jobs:
        return

    num_upscayled = 0
    consecutive_failures = 0
    with UpscaleLedgerWriter(ledger_file, recipe) as ledger:
        for job in jobs:
            if _upscayl_page(job, upscaler, ledger):
                num_upscayled += 1
                consecutive_failures = 0
                continue

            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    f"Giving up: {consecutive_failures} page(s) failed in a row."
                    f" Something is wrong with the upscaler rather than with these pages."
                    f" {num_upscayled} of {len(jobs)} done.",
                )
                break

    logger.info(
        f"\nTime taken to upscayl {num_upscayled} of {len(jobs)} file(s):"
        f" {format_duration(time.time() - start)}.",
    )


def _log_run_estimate(
    jobs: list[_PageJob], counts: dict[str, int], ledger_file: Path, recipe: UpscaleRecipe
) -> None:
    """Log what is queued, what is being skipped, and what the work is expected to cost."""
    skipped = ", ".join(f"{count} {state}" for state, count in sorted(counts.items()))
    logger.info(f"Page states: {skipped or 'none'}.")

    if not jobs:
        logger.info("Nothing to upscayl - every page is already up to date with this recipe.")
        return

    stats = read_upscale_ledger(ledger_file).timing_stats(recipe.recipe_id)
    if stats is None:
        logger.info(f"{len(jobs)} page(s) to upscayl. No timings yet for this recipe.")
        return

    logger.info(
        f"{len(jobs)} page(s) to upscayl."
        f" Previous pages on this recipe averaged {int(stats.mean_seconds)}s,"
        f" so expect around {format_duration(len(jobs) * stats.mean_seconds)}.",
    )


def _upscayl_page(job: _PageJob, upscaler: Upscaler, ledger: UpscaleLedgerWriter) -> bool:
    """Upscayl one page, recording what happened either way.

    A failure is logged and recorded rather than raised, so that one bad page does not
    abandon the rest of a run measured in hours. `upscale_image_file` has already deleted
    the unusable output, so the page stays queued for next time.

    Args:
        job: The page to do.
        upscaler: Which backend to run.
        ledger: Where to record the outcome.

    Returns:
        Whether the page was upscayled.

    """
    logger.info(
        f'Upscayling srce file "{get_abbrev_path(job.srce_file)}"'
        f' to dest upscayl file "{get_abbrev_path(job.dest_file)}" using {upscaler}.',
    )

    started = datetime.now().astimezone().isoformat(timespec="seconds")
    page_start = time.time()
    srce_bytes = job.srce_file.stat().st_size if job.srce_file.is_file() else 0

    error = None
    try:
        upscale_image_file(job.srce_file, job.dest_file, SCALE, upscaler)
    except (OSError, RuntimeError, ValueError) as exc:
        error = str(exc)
        logger.error(f'Could not upscayl "{get_abbrev_path(job.srce_file)}": {exc}')

    seconds = time.time() - page_start
    ledger.write_page(
        title=job.title,
        volume=job.volume,
        page=job.page,
        outcome=OUTCOME_FAILED if error else OUTCOME_OK,
        started=started,
        total_seconds=seconds,
        error=error,
        srce_bytes=srce_bytes,
        dest_bytes=job.dest_file.stat().st_size if job.dest_file.is_file() else 0,
    )

    if error:
        return False

    logger.info(f"\nTime taken to upscayl file: {int(seconds)}s.")

    return True


app = typer.Typer()


@app.command(help="Make upscayled files")
def main(  # noqa: PLR0913
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    upscaler: UpscalerArg = DEFAULT_UPSCALER,
    ledger_file: Annotated[
        Path | None,
        typer.Option("--ledger", help="Where to append the record of what was upscayled."),
    ] = None,
    force: bool = typer.Option(
        default=False,
        help="Upscayl pages even when they are already up to date with the current recipe.",
    ),
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "batch-upscayl.log", log_level_str)

    comics_database, titles = get_comic_titles(volumes_str, title_str)

    upscayl(
        comics_database,
        titles,
        upscaler,
        ledger_file or get_default_upscale_ledger_file(),
        force=force,
    )


if __name__ == "__main__":
    app()
