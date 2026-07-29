"""Restore whole volumes of pages, keeping a record of what was done and when.

Restoring the library is hundreds of hours of work, so this driver is built around being
interrupted and resumed rather than around any one run finishing. Pages that are already
finished under the current recipe are skipped; everything else is put through the
pipeline, timed, and written to the ledger as it completes.

Work is done in phases across a batch of pages rather than page by page, because the two
gmic steps are memory hungry and have to be throttled to fewer workers than the machine
has cores. Batching across titles rather than within one keeps those throttled phases
full: a title is only eight to fourteen pages, so a six worker phase would spend much of
its time running a half empty round.
"""

import concurrent.futures
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, NamedTuple

import psutil
import typer
from barks_fantagraphics.comic_book_info import is_non_comic_title
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_utils import get_abbrev_path
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from comic_utils.pil_image_utils import copy_file_to_png
from loguru import logger

from barks_comic_building.cli_setup import get_comic_titles, init_logging
from barks_comic_building.restore.page_state import (
    PageState,
    get_page_status,
    get_upscaler_used,
)
from barks_comic_building.restore.report_format import format_duration
from barks_comic_building.restore.restore_ledger import (
    OUTCOME_FAILED,
    OUTCOME_OK,
    LedgerWriter,
    get_default_ledger_file,
    read_ledger,
)
from barks_comic_building.restore.restore_pipeline import RestorePipeline, check_for_errors
from barks_comic_building.restore.restore_recipe import RestoreRecipe, get_current_recipe

APP_LOGGING_NAME = "bres"


SCALE = 4
SMALL_RAM = 16 * 1024 * 1024 * 1024

# How many pages go through the phases together. Large enough that the throttled phases
# run full rounds, small enough that the work directory stays a few tens of gigabytes and
# that an interrupted run loses at most this much unfinished work.
DEFAULT_BATCH_SIZE = 64


class _PageJob(NamedTuple):
    """A page queued for restoring, with what the ledger needs to describe it."""

    pipeline: RestorePipeline
    title: str
    volume: int
    page: str


def restore(  # noqa: PLR0913
    comics_database: ComicsDatabase,
    title_list: list[str],
    work_dir: Path,
    ledger_file: Path,
    batch_size: int,
    *,
    use_existing_work_files: bool,
    debug_color_counts: bool,
    keep_work_files: bool,
    force: bool,
) -> None:
    """Restore every page of every given title that is not already up to date.

    Args:
        comics_database: The comics database.
        title_list: The titles to restore.
        work_dir: Where intermediates go. A subdirectory per title.
        ledger_file: Where to append the record of what was done.
        batch_size: How many pages go through the phases together.
        use_existing_work_files: Reuse surviving intermediates rather than regenerating.
        debug_color_counts: Write the slow colour-count debug files.
        keep_work_files: Leave intermediates behind instead of cleaning up after a page.
        force: Restore pages that are already current.

    """
    start = time.time()

    recipe = get_current_recipe(SCALE, do_palette_snap=True)
    logger.info(f"Restore recipe {recipe.recipe_id}: {recipe.as_json()}")

    jobs: list[_PageJob] = []
    num_copied = 0
    for title in title_list:
        if is_non_comic_title(title):
            num_copied += copy_title(comics_database, title)
        else:
            jobs += get_title_jobs(
                comics_database,
                title,
                work_dir,
                recipe,
                use_existing_work_files=use_existing_work_files,
                debug_color_counts=debug_color_counts,
                force=force,
            )

    if not jobs:
        logger.info(
            f"Nothing to restore across {len(title_list)} title(s)"
            f" - every page is already up to date with this recipe."
            f" Copied {num_copied} non-comic page(s).",
        )
        return

    _log_run_estimate(jobs, ledger_file, recipe)

    workers = {phase[0]: phase[2] or os.process_cpu_count() or 0 for phase in _PHASES}
    with LedgerWriter(ledger_file, recipe, workers) as ledger:
        num_done = 0
        for batch_start in range(0, len(jobs), batch_size):
            batch = jobs[batch_start : batch_start + batch_size]
            logger.info(
                f"\nBatch {batch_start // batch_size + 1}"
                f" of {(len(jobs) + batch_size - 1) // batch_size}:"
                f" {len(batch)} page(s).",
            )

            num_done += _run_batch(
                batch,
                ledger,
                num_done,
                len(jobs),
                start,
                keep_work_files=keep_work_files,
            )

    logger.info(
        f"\nTime taken to restore {len(jobs)} page(s)"
        f" and copy {num_copied}: {format_duration(time.time() - start)}.",
    )


def _log_run_estimate(jobs: list[_PageJob], ledger_file: Path, recipe: RestoreRecipe) -> None:
    """Log what the queued work is expected to cost, from previously measured pages."""
    stats = read_ledger(ledger_file).timing_stats(recipe.recipe_id)
    if stats is None:
        logger.info(f"{len(jobs)} page(s) to restore. No timings yet for this recipe.")
        return

    logger.info(
        f"{len(jobs)} page(s) to restore."
        f" Previous pages on this recipe averaged {int(stats.mean_seconds)}s,"
        f" so expect around {format_duration(len(jobs) * stats.mean_seconds)}.",
    )


def _run_batch(  # noqa: PLR0913
    batch: list[_PageJob],
    ledger: LedgerWriter,
    num_done_before: int,
    num_jobs: int,
    run_start: float,
    *,
    keep_work_files: bool,
) -> int:
    """Run one batch through all phases, then record and clean up after it.

    Returns:
        How many pages of the batch were attempted.

    """
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    batch_start_time = time.time()

    pipelines = [job.pipeline for job in batch]
    failed = run_restore(pipelines)
    check_for_errors(pipelines, failed)

    # A page's share of the batch's wall clock, which is the figure that multiplies out
    # to a useful estimate. Summing its step times would give the cpu cost of the page
    # instead, several times larger than the wall clock because the phases run many pages
    # at once - a per-page mean built from that would overstate a run by a factor of five.
    # The per-step breakdown is kept alongside it for anyone asking where the time went.
    seconds_each = (time.time() - batch_start_time) / len(batch)

    for i, job in enumerate(batch):
        ok = i not in failed and not job.pipeline.errors_occurred
        ledger.write_page(
            title=job.title,
            volume=job.volume,
            page=job.page,
            outcome=OUTCOME_OK if ok else OUTCOME_FAILED,
            started=started,
            total_seconds=seconds_each,
            step_seconds=job.pipeline.step_seconds,
            failed_step=job.pipeline.failed_step,
            dest_bytes=(
                job.pipeline.dest_restored_file.stat().st_size
                if job.pipeline.dest_restored_file.is_file()
                else 0
            ),
            upscaler=get_upscaler_used(job.pipeline.srce_upscale_file),
        )

        if ok and not keep_work_files:
            _clean_up_work_files(job.pipeline)

    num_done = num_done_before + len(batch)
    _log_progress(num_done, num_jobs, run_start)

    return len(batch)


def _log_progress(num_done: int, num_jobs: int, run_start: float) -> None:
    """Log how far through the run is and what is left, from this run's own pace."""
    elapsed = time.time() - run_start
    remaining = num_jobs - num_done
    estimate = (elapsed / num_done) * remaining if num_done else 0.0

    logger.info(
        f"\nProgress: {num_done}/{num_jobs} page(s) ({num_done / num_jobs:.1%})"
        f" - elapsed {format_duration(elapsed)},"
        f" {remaining} left, around {format_duration(estimate)} to go.",
    )


def _clean_up_work_files(pipeline: RestorePipeline) -> None:
    """Delete a finished page's intermediates.

    Only the files this page is known to have written, never the directory - the work
    directory is shared by a whole title, and a run this long cannot afford a cleanup
    that reaches further than it meant to. Pages that failed keep their intermediates so
    that a retry can resume from them.
    """
    num_freed = 0
    for file in pipeline.work_files:
        try:
            num_freed += file.stat().st_size
            file.unlink()
        except OSError:
            # Missing is the normal case for the steps that did not need to run.
            continue

    if num_freed:
        logger.debug(
            f"Cleaned up {num_freed / 1e6:.0f}MB of work files"
            f' for "{pipeline.srce_upscale_file.name}".',
        )


def copy_title(comics_database: ComicsDatabase, title_str: str) -> int:
    """Copy a non-comic title's pages through unrestored.

    Args:
        comics_database: The comics database.
        title_str: The title to copy.

    Returns:
        How many pages were actually copied.

    """
    logger.info(f'Copying non-comic title "{title_str}".')

    comic = comics_database.get_comic_book(title_str)
    srce_files = comic.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES)
    dest_restored_files = comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES)

    num_copied = 0
    for srce_file, dest_file in zip(srce_files, dest_restored_files, strict=True):
        if Path(dest_file).is_file():
            logger.warning(
                f'Dest file exists - skipping: "{get_abbrev_path(dest_file)}".',
            )
            continue

        logger.info(
            f'Copying "{get_abbrev_path(srce_file[0])}" to "{get_abbrev_path(dest_file)}".',
        )
        copy_file_to_png(srce_file[0], dest_file)
        num_copied += 1

    return num_copied


def get_title_jobs(  # noqa: PLR0913
    comics_database: ComicsDatabase,
    title: str,
    work_dir: Path,
    recipe: RestoreRecipe,
    *,
    use_existing_work_files: bool,
    debug_color_counts: bool,
    force: bool,
) -> list[_PageJob]:
    """Return the pages of a title that still need restoring.

    Args:
        comics_database: The comics database.
        title: The title to look at.
        work_dir: Where intermediates go. A subdirectory is made for this title.
        recipe: The settings this run restores with.
        use_existing_work_files: Reuse surviving intermediates rather than regenerating.
        debug_color_counts: Write the slow colour-count debug files.
        force: Include pages that are already current.

    Returns:
        A job per page that needs work.

    """
    logger.info(f'Processing story "{title}".')

    comic = comics_database.get_comic_book(title)
    volume = comics_database.get_fanta_volume_int(title)

    title_work_dir = work_dir / title
    title_work_dir.mkdir(parents=True, exist_ok=True)

    srce_files = comic.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES)
    srce_upscayl_files = comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)
    dest_restored_files = comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES)
    dest_restored_upscayled_files = comic.get_srce_restored_upscayled_story_files(
        RESTORABLE_PAGE_TYPES,
    )
    dest_restored_svg_files = comic.get_srce_restored_svg_story_files(RESTORABLE_PAGE_TYPES)

    jobs: list[_PageJob] = []
    num_by_state: dict[PageState, int] = {}

    for (
        srce_file,
        srce_upscayl_file,
        dest_restored_file,
        dest_upscayled_restored_file,
        dest_svg_restored_file,
    ) in zip(
        srce_files,
        srce_upscayl_files,
        dest_restored_files,
        dest_restored_upscayled_files,
        dest_restored_svg_files,
        strict=True,
    ):
        status = get_page_status(
            Path(srce_upscayl_file[0]),
            Path(dest_restored_file),
            Path(dest_upscayled_restored_file),
            Path(dest_svg_restored_file),
            recipe.recipe_id,
        )
        num_by_state[status.state] = num_by_state.get(status.state, 0) + 1

        if status.state is PageState.NO_SRCE:
            logger.error(
                f'Could not find srce upscayl file - skipping: "{srce_upscayl_file[0]}".',
            )
            continue

        # Not even under --force: this page's outputs are symlinks to another volume's,
        # and forcing it would write through them over pages that are not this title's.
        if status.state is PageState.LINKED:
            logger.debug(
                f"Page belongs to another volume - skipping:"
                f' "{get_abbrev_path(dest_restored_file)}".',
            )
            continue

        if not status.needs_restoring and not force:
            logger.debug(
                f"Already restored on this recipe - skipping:"
                f' "{get_abbrev_path(dest_restored_file)}".',
            )
            continue

        logger.info(
            f'Restoring ({status.state}) srce files "{get_abbrev_path(srce_file[0])}",'
            f' "{get_abbrev_path(srce_upscayl_file[0])}"'
            f' to dest "{get_abbrev_path(dest_restored_file)}".',
        )

        jobs.append(
            _PageJob(
                RestorePipeline(
                    title_work_dir,
                    Path(srce_file[0]),
                    Path(srce_upscayl_file[0]),
                    SCALE,
                    Path(dest_restored_file),
                    Path(dest_upscayled_restored_file),
                    Path(dest_svg_restored_file),
                    use_existing_work_files=use_existing_work_files,
                    debug_color_counts=debug_color_counts,
                ),
                title,
                volume,
                Path(dest_restored_file).stem,
            ),
        )

    summary = ", ".join(f"{state} {count}" for state, count in sorted(num_by_state.items()))
    logger.info(f'"{title}": {summary or "no pages"} - queued {len(jobs)}.')

    return jobs


_SMALL_RAM_DETECTED = psutil.virtual_memory().total < SMALL_RAM

# Each phase runs across all pages of a batch before the next phase starts. The third
# tuple element is the worker count for that phase: the memory-hungry phases (part 2
# smoothing, part 4 inpaint/overlay/resize) are throttled to few workers (1 on small-RAM
# machines) to avoid exhausting memory, while the lighter phases use the default pool
# size. This is why run_restore() builds a fresh ProcessPoolExecutor per phase rather
# than one shared pool. The fourth element caps the OpenMP threads each gmic subprocess
# in that phase may take; None leaves it to gmic, which takes every core it can see.
#
# The thread caps are deliberately left off. Six concurrent smooths ask for ninety six
# threads on sixteen cores, which looks like it should be costing something, but it is
# not: measured with scripts/bench_restore_phases.py on this machine (5700G, 16 cores,
# dual channel DDR4), smoothing ran at 27.3 pages/hour at OMP_NUM_THREADS=2, 29.7 at 4
# and 28.6 uncapped. An 8.8% spread across a 5.7x change in thread count, and not even
# monotonic - the step is limited by memory bandwidth, not by thread contention, and
# these 100 megapixel images will saturate two DDR4 channels whatever the threads do.
# Capping them to chase the 3.8% at omp=4 would be fitting one sample's noise.
#
# For the same reason the worker counts below are near their ceiling: six concurrent
# smooths return only about a quarter more throughput than one at a time. The way to
# make a long run faster is to keep these phases full, which is what batching pages
# across titles does, rather than to rearrange the threads inside them.
_PHASES: list[tuple[str, str, int | None, int | None]] = [
    ("part 1", "do_part1", None, None),
    ("part 2", "do_part2_memory_hungry", 1 if _SMALL_RAM_DETECTED else 6, None),
    ("part 3", "do_part3", None, None),
    ("part 4", "do_part4_memory_hungry", 1 if _SMALL_RAM_DETECTED else 4, None),
]


class _PhaseResult(NamedTuple):
    """What a worker sends back about the phase it just ran."""

    errors_occurred: bool
    failed_step: str | None
    step_seconds: dict[str, float]


def _run_restore_phase(
    proc: RestorePipeline, method_name: str, omp_threads: int | None
) -> _PhaseResult:
    """Run a single restore phase on a process, returning what happened.

    Runs in a worker process, so any mutation of ``proc`` here does NOT propagate back to
    the parent's copy. Everything the parent needs - whether it failed, where, and how
    long each step took - therefore comes back in the return value.

    Args:
        proc: The pipeline to run a phase of.
        method_name: The phase method to call.
        omp_threads: How many OpenMP threads the gmic subprocesses in this phase may use.
            None leaves it alone.

    Returns:
        The phase's outcome and timings.

    """
    if omp_threads is not None:
        os.environ["OMP_NUM_THREADS"] = str(omp_threads)

    getattr(proc, method_name)()

    return _PhaseResult(proc.errors_occurred, proc.failed_step, dict(proc.step_seconds))


def run_restore(restore_processes: list[RestorePipeline]) -> set[int]:
    """Run all restore phases across processes, skipping processes that fail.

    Args:
        restore_processes: The pipelines to run.

    Returns:
        The indexes of the pipelines that failed. The phases run in worker processes, so
        this is the only way the failures reach the caller.

    """
    logger.info(f"Starting restore for {len(restore_processes)} processes.")

    failed: set[int] = set()

    for phase_name, method_name, max_workers, omp_threads in _PHASES:
        num_submitted = 0
        with concurrent.futures.ProcessPoolExecutor(max_workers) as executor:
            futures: dict[concurrent.futures.Future[_PhaseResult], int] = {}
            for i, process in enumerate(restore_processes):
                if i in failed:
                    logger.warning(
                        f'Skipping {phase_name} for "{process.srce_upscale_file.name}"'
                        f" due to earlier failure.",
                    )
                    continue
                futures[executor.submit(_run_restore_phase, process, method_name, omp_threads)] = i
                num_submitted += 1

            # Consumed as they finish rather than after the pool drains, so a long phase
            # reports progress while it is still running instead of going quiet.
            for num_finished, future in enumerate(concurrent.futures.as_completed(futures), 1):
                i = futures[future]
                process = restore_processes[i]

                # noinspection PyBroadException
                try:
                    result = future.result()
                except Exception:  # noqa: BLE001
                    result = _PhaseResult(
                        errors_occurred=True, failed_step=phase_name, step_seconds={}
                    )
                    logger.exception(
                        f"Unexpected exception in {phase_name} for"
                        f' "{process.srce_upscale_file.name}".',
                    )

                # The worker mutated its own copy, so fold its timings back into ours.
                process.step_seconds.update(result.step_seconds)
                if result.errors_occurred:
                    process.errors_occurred = True
                    process.failed_step = result.failed_step
                    failed.add(i)
                    logger.error(
                        f'{phase_name} failed for "{process.srce_upscale_file.name}"'
                        f" at {result.failed_step}.",
                    )

                logger.info(
                    f"{phase_name}: {num_finished}/{num_submitted}"
                    f' - "{process.srce_upscale_file.name}".',
                )

    if failed:
        logger.error(f"{len(failed)} of {len(restore_processes)} processes had errors.")

    return failed


app = typer.Typer()


@app.command(help="Make restored files")
def main(  # noqa: PLR0913
    work_dir: Path = typer.Option(...),  # noqa: B008
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
    ledger_file: Annotated[
        Path | None,
        typer.Option("--ledger", help="Where to append the record of what was restored."),
    ] = None,
    batch_size: Annotated[
        int,
        typer.Option(help="How many pages go through the pipeline phases together."),
    ] = DEFAULT_BATCH_SIZE,
    use_existing_work_files: bool = typer.Option(
        default=False,
        help="Reuse existing intermediate work files instead of regenerating them (resume).",
    ),
    keep_work_files: bool = typer.Option(
        default=False,
        help="Keep intermediate work files instead of deleting them once a page is done.",
    ),
    force: bool = typer.Option(
        default=False,
        help="Restore pages even when they are already up to date with the current recipe.",
    ),
    debug_color_counts: bool = typer.Option(
        default=False,
        help="Write debug colour-count text files during colour removal (slow).",
    ),
) -> None:
    init_logging(APP_LOGGING_NAME, "batch-restore.log", log_level_str)

    comics_database, titles = get_comic_titles(volumes_str, title_str)

    work_dir.mkdir(parents=True, exist_ok=True)

    restore(
        comics_database,
        titles,
        work_dir,
        ledger_file or get_default_ledger_file(),
        batch_size,
        use_existing_work_files=use_existing_work_files,
        debug_color_counts=debug_color_counts,
        keep_work_files=keep_work_files,
        force=force,
    )


if __name__ == "__main__":
    app()
