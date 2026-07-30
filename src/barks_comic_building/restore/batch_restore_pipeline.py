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
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
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
    OUTCOME_COPIED,
    OUTCOME_FAILED,
    OUTCOME_OK,
    OUTCOME_PRESENT,
    OUTCOME_STOPPED,
    LedgerWriter,
    get_default_ledger_file,
    read_ledger,
)
from barks_comic_building.restore.restore_pipeline import RestorePipeline, check_for_errors
from barks_comic_building.restore.restore_recipe import RestoreRecipe, get_current_recipe
from barks_comic_building.restore.run_stop import (
    StopMode,
    clear_stop,
    get_stop_file,
    parse_duration,
    read_stop_mode,
    request_stop,
)

APP_LOGGING_NAME = "bres"


SCALE = 4
SMALL_RAM = 16 * 1024 * 1024 * 1024

# How many pages go through the phases together. Large enough that the throttled phases
# run full rounds, small enough that the work directory stays a few tens of gigabytes and
# that an interrupted run loses at most this much unfinished work.
DEFAULT_BATCH_SIZE = 64


class _NonComicPage(NamedTuple):
    """A non-comic page a run dealt with, and what it did about it.

    The outcome is either copied, for a page this run wrote, or present, for one that was
    already there and left alone.
    """

    title: str
    volume: int
    page: str
    dest_file: Path
    started: str
    seconds: float
    outcome: str


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
    stop_after_seconds: float | None = None,
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
        stop_after_seconds: Ask the run to stop cleanly once it has been going this
            long. None lets it run to the end.
        use_existing_work_files: Reuse surviving intermediates rather than regenerating.
        debug_color_counts: Write the slow colour-count debug files.
        keep_work_files: Leave intermediates behind instead of cleaning up after a page.
        force: Restore pages that are already current.

    """
    start = time.time()

    # A request left over from the last run would otherwise stop this one before it had
    # done anything, which would look exactly like the run refusing to start.
    if clear_stop(work_dir):
        logger.warning("Cleared a stop request left over from an earlier run.")

    stop_file = get_stop_file(work_dir)
    deadline: float | None = None
    if stop_after_seconds:
        deadline = start + stop_after_seconds
        logger.info(
            f"Will stop cleanly after {format_duration(stop_after_seconds)}"
            f" - pages under way at that point will still be finished.",
        )
    logger.info(f'To stop sooner: "just restore-stop", or touch "{stop_file}".')

    recipe = get_current_recipe(SCALE, do_palette_snap=True)
    logger.info(f"Restore recipe {recipe.recipe_id}: {recipe.as_json()}")

    jobs: list[_PageJob] = []
    non_comic: list[_NonComicPage] = []
    for title in title_list:
        if is_non_comic_title(title):
            non_comic += copy_title(comics_database, title)
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

    if not jobs and not non_comic:
        logger.info(
            f"Nothing to do across {len(title_list)} title(s)"
            f" - every page is already up to date with this recipe.",
        )
        return

    if jobs:
        _log_run_estimate(jobs, ledger_file, recipe)

    workers = {phase[0]: phase[2] or os.process_cpu_count() or 0 for phase in _PHASES}
    with LedgerWriter(ledger_file, recipe, workers) as ledger:
        _write_non_comic_records(ledger, non_comic)

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
                deadline,
                keep_work_files=keep_work_files,
            )

            stop_mode = read_stop_mode(stop_file)
            if stop_mode is not StopMode.NONE:
                logger.warning(
                    f"\nStopping after {num_done} of {len(jobs)} page(s): {stop_mode.describe}."
                    f"\nRe-run the same command to carry on"
                    f" - finished pages are skipped, and part-finished ones"
                    f" resume with --use-existing-work-files.",
                )
                break

    num_copied = sum(1 for page in non_comic if page.outcome == OUTCOME_COPIED)
    elapsed = format_duration(time.time() - start)

    # A run that stopped early got through only some of what it queued, and saying it
    # restored all of them - in a fraction of the time that would have taken - would be
    # the most misleading line in the log.
    if num_done < len(jobs):
        logger.info(
            f"\nStopped after {elapsed}, having worked on {num_done} of {len(jobs)}"
            f" queued page(s) and copied {num_copied}.",
        )
    else:
        logger.info(
            f"\nTime taken to restore {len(jobs)} page(s) and copy {num_copied}: {elapsed}.",
        )


def _write_non_comic_records(ledger: LedgerWriter, non_comic: list[_NonComicPage]) -> None:
    """Record the non-comic pages, whether this run wrote them or found them.

    Args:
        ledger: Where to record them.
        non_comic: The pages `copy_title` reported.

    """
    for page in non_comic:
        ledger.write_page(
            title=page.title,
            volume=page.volume,
            page=page.page,
            outcome=page.outcome,
            started=page.started,
            total_seconds=page.seconds,
            step_seconds={},
            dest_bytes=page.dest_file.stat().st_size if page.dest_file.is_file() else 0,
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
    deadline: float | None,
    *,
    keep_work_files: bool,
) -> int:
    """Run one batch through all phases, then record and clean up after it.

    Returns:
        How many pages of the batch were attempted. Pages the stop reached before they
        had begun do not count, since nothing was done to them.

    """
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    batch_start_time = time.time()

    pipelines = [job.pipeline for job in batch]
    result = run_restore(pipelines, deadline)
    check_for_errors(
        [p for i, p in enumerate(pipelines) if i not in result.unfinished | result.untouched],
        result.failed,
    )

    num_attempted = len(batch) - len(result.untouched)

    # A page's share of the batch's wall clock, which is the figure that multiplies out
    # to a useful estimate. Summing its step times would give the cpu cost of the page
    # instead, several times larger than the wall clock because the phases run many pages
    # at once - a per-page mean built from that would overstate a run by a factor of five.
    # The per-step breakdown is kept alongside it for anyone asking where the time went.
    seconds_each = (time.time() - batch_start_time) / max(num_attempted, 1)

    for i, job in enumerate(batch):
        if i in result.untouched:
            # Never begun, so there is nothing to say about it and nothing to tidy. It
            # is simply still to do, which the page state will work out on its own.
            continue

        if i in result.unfinished:
            outcome = OUTCOME_STOPPED
        elif i in result.failed or job.pipeline.errors_occurred:
            outcome = OUTCOME_FAILED
        else:
            outcome = OUTCOME_OK

        ledger.write_page(
            title=job.title,
            volume=job.volume,
            page=job.page,
            outcome=outcome,
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

        # Only a page that finished has intermediates worth nothing. A stopped one keeps
        # its own so that the next run can carry on from where it left off.
        if outcome == OUTCOME_OK and not keep_work_files:
            _clean_up_work_files(job.pipeline)

    num_done = num_done_before + num_attempted
    _log_progress(num_done, num_jobs, run_start)

    return num_attempted


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


def copy_title(comics_database: ComicsDatabase, title_str: str) -> list[_NonComicPage]:
    """Copy a non-comic title's pages through unrestored.

    Reports the pages rather than a count of them, so that they can be written to the
    ledger. A copied page is as finished as a restored one, and leaving it out meant a run
    that only copied left no trace at all - not even that it happened.

    Pages already there are reported too, as present rather than copied. They cost
    nothing to record and they make the ledger account for every page of the title, so
    that a title with no records is a title nothing looked at rather than a title whose
    pages all happened to exist.

    Args:
        comics_database: The comics database.
        title_str: The title to copy.

    Returns:
        One entry per page, saying what was done about it.

    """
    logger.info(f'Copying non-comic title "{title_str}".')

    comic = comics_database.get_comic_book(title_str)
    volume = comics_database.get_fanta_volume_int(title_str)
    srce_files = comic.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES)
    dest_restored_files = comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES)

    pages: list[_NonComicPage] = []
    for srce_file, dest_file in zip(srce_files, dest_restored_files, strict=True):
        started = datetime.now().astimezone().isoformat(timespec="seconds")
        page_start = time.time()

        if Path(dest_file).is_file():
            logger.debug(f'Dest file exists - leaving alone: "{get_abbrev_path(dest_file)}".')
            outcome = OUTCOME_PRESENT
        else:
            logger.info(
                f'Copying "{get_abbrev_path(srce_file[0])}" to "{get_abbrev_path(dest_file)}".',
            )
            copy_file_to_png(srce_file[0], dest_file)
            outcome = OUTCOME_COPIED

        pages.append(
            _NonComicPage(
                title=title_str,
                volume=volume,
                page=Path(dest_file).stem,
                dest_file=Path(dest_file),
                started=started,
                seconds=time.time() - page_start,
                outcome=outcome,
            )
        )

    return pages


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
                    # The run's work directory, not this title's, so every page of the
                    # run looks at the same request.
                    stop_file=get_stop_file(work_dir),
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


class _PhaseOutcome(StrEnum):
    """What became of a page in a phase."""

    RAN = "ran"
    """It ran the phase through, for good or ill."""

    SKIPPED = "skipped"
    """A stop was already in force when its turn came, so it was never begun.

    Queued work, in other words. A page skipped in the first phase has had nothing done
    to it at all; one skipped later has earlier phases behind it and work files to show
    for them."""

    STOPPED = "stopped"
    """It began the phase and gave up between steps because a stop was asked for."""


class _PhaseResult(NamedTuple):
    """What a worker sends back about the phase it just ran."""

    errors_occurred: bool
    failed_step: str | None
    step_seconds: dict[str, float]
    outcome: _PhaseOutcome


def _run_restore_phase(
    proc: RestorePipeline, method_name: str, omp_threads: int | None, *, is_first_phase: bool
) -> _PhaseResult:
    """Run a single restore phase on a process, returning what happened.

    Runs in a worker process, so any mutation of ``proc`` here does NOT propagate back to
    the parent's copy. Everything the parent needs - whether it failed, where, how long
    each step took, and whether a stop cut it short - therefore comes back in the return
    value.

    Every page of a batch is submitted to the pool up front, so most of them sit queued
    behind the handful actually running. Reading the stop here, as each one starts, is
    what lets those queued pages fall through untouched the moment a stop is asked for,
    rather than the whole batch having to be seen through.

    Args:
        proc: The pipeline to run a phase of.
        method_name: The phase method to call.
        omp_threads: How many OpenMP threads the gmic subprocesses in this phase may use.
            None leaves it alone.
        is_first_phase: Whether this is the phase that starts a page off. Only pages that
            have not started yet are dropped by the gentler stop; one already under way
            is seen through to the end so that it comes out finished.

    Returns:
        The phase's outcome and timings.

    """
    stop_mode = read_stop_mode(proc.stop_file)
    if stop_mode.stops_pages_that_have_started or (
        stop_mode is not StopMode.NONE and is_first_phase
    ):
        return _PhaseResult(
            errors_occurred=False,
            failed_step=None,
            step_seconds={},
            outcome=_PhaseOutcome.SKIPPED,
        )

    if omp_threads is not None:
        os.environ["OMP_NUM_THREADS"] = str(omp_threads)

    getattr(proc, method_name)()

    return _PhaseResult(
        proc.errors_occurred,
        proc.failed_step,
        dict(proc.step_seconds),
        _PhaseOutcome.STOPPED if proc.stopped_early else _PhaseOutcome.RAN,
    )


@dataclass
class RunResult:
    """Which pages of a batch ended up where."""

    failed: set[int] = field(default_factory=set)
    """Pages that hit an error. The phases run in worker processes, so this is the only
    way their failures reach the caller."""

    unfinished: set[int] = field(default_factory=set)
    """Pages left part way through because the run was asked to stop, having done at
    least some work. Their intermediates are whole files and are kept for the next run."""

    untouched: set[int] = field(default_factory=set)
    """Pages the stop reached before they had begun. Nothing was written for them, so
    there is nothing to record and nothing to clean up."""

    started: set[int] = field(default_factory=set)
    """Pages that have run at least one phase. What tells a page the stop found waiting
    in the queue from one it found part way through."""

    def is_settled(self, index: int) -> bool:
        """Whether this page is done with, one way or another, and needs no more phases."""
        return index in self.failed or index in self.unfinished or index in self.untouched


def _record_phase_result(
    result: _PhaseResult, index: int, process: RestorePipeline, phase_name: str, run: RunResult
) -> None:
    """Fold one page's phase result back into the parent's picture of the batch."""
    # The worker mutated its own copy, so its timings only exist in what it sent back.
    process.step_seconds.update(result.step_seconds)

    if result.outcome is _PhaseOutcome.SKIPPED:
        # Whether there is anything to keep depends on how far it had got before the
        # stop arrived, which is what `started` remembers.
        (run.unfinished if index in run.started else run.untouched).add(index)
        return

    run.started.add(index)

    if result.outcome is _PhaseOutcome.STOPPED:
        process.stopped_early = True
        run.unfinished.add(index)

    if result.errors_occurred:
        process.errors_occurred = True
        process.failed_step = result.failed_step
        run.failed.add(index)
        logger.error(
            f'{phase_name} failed for "{process.srce_upscale_file.name}" at {result.failed_step}.',
        )


def _run_phase(
    phase: tuple[str, str, int | None, int | None],
    restore_processes: list[RestorePipeline],
    run: RunResult,
    deadline: float | None,
    *,
    is_first_phase: bool,
) -> float | None:
    """Put every page still in play through one phase.

    Returns:
        The deadline still to watch for, or None once it has passed and the stop it
        asked for has been made.

    """
    phase_name, method_name, max_workers, omp_threads = phase

    with concurrent.futures.ProcessPoolExecutor(max_workers) as executor:
        futures: dict[concurrent.futures.Future[_PhaseResult], int] = {}
        for i, process in enumerate(restore_processes):
            if run.is_settled(i):
                continue
            futures[
                executor.submit(
                    _run_restore_phase,
                    process,
                    method_name,
                    omp_threads,
                    is_first_phase=is_first_phase,
                )
            ] = i

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
                    errors_occurred=True,
                    failed_step=phase_name,
                    step_seconds={},
                    outcome=_PhaseOutcome.RAN,
                )
                logger.exception(
                    f'Unexpected exception in {phase_name} for "{process.srce_upscale_file.name}".',
                )

            _record_phase_result(result, i, process, phase_name, run)

            logger.info(
                f"{phase_name}: {num_finished}/{len(futures)}"
                f' - "{process.srce_upscale_file.name}".',
            )

            if deadline is not None and time.time() > deadline:
                deadline = None
                if process.stop_file is not None:
                    request_stop(process.stop_file.parent)
                    logger.warning(
                        "Reached the --stop-after time. Pages already started will"
                        " finish; nothing new will begin.",
                    )

    return deadline


def run_restore(
    restore_processes: list[RestorePipeline], deadline: float | None = None
) -> RunResult:
    """Run all restore phases across processes, skipping processes that fail.

    Args:
        restore_processes: The pipelines to run.
        deadline: When to ask the run to stop of its own accord, as a `time.time()`
            value. Checked as pages come back, so a bounded run ends on the same path as
            one stopped by hand rather than on a second mechanism of its own.

    Returns:
        Which pages failed, which were left unfinished, and which were never begun.

    """
    logger.info(f"Starting restore for {len(restore_processes)} processes.")

    run = RunResult()

    for phase_index, phase in enumerate(_PHASES):
        deadline = _run_phase(
            phase,
            restore_processes,
            run,
            deadline,
            is_first_phase=phase_index == 0,
        )

    if run.failed:
        logger.error(f"{len(run.failed)} of {len(restore_processes)} processes had errors.")
    if run.unfinished or run.untouched:
        logger.warning(
            f"Stopped: {len(run.unfinished)} page(s) left part way through,"
            f" {len(run.untouched)} not begun.",
        )

    return run


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
    stop_after: Annotated[
        str | None,
        typer.Option(
            "--stop-after",
            help="Stop cleanly once the run has been going this long, e.g. 8h, 90m, 1h30m.",
        ),
    ] = None,
    debug_color_counts: bool = typer.Option(
        default=False,
        help="Write debug colour-count text files during colour removal (slow).",
    ),
) -> None:
    init_logging(APP_LOGGING_NAME, "batch-restore.log", log_level_str)

    try:
        stop_after_seconds = parse_duration(stop_after) if stop_after else None
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    comics_database, titles = get_comic_titles(volumes_str, title_str)

    work_dir.mkdir(parents=True, exist_ok=True)

    restore(
        comics_database,
        titles,
        work_dir,
        ledger_file or get_default_ledger_file(),
        batch_size,
        stop_after_seconds,
        use_existing_work_files=use_existing_work_files,
        debug_color_counts=debug_color_counts,
        keep_work_files=keep_work_files,
        force=force,
    )


if __name__ == "__main__":
    app()
