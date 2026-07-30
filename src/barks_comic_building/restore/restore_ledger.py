"""An append-only record of what the restore pipeline did, and how long it took.

Restoring the whole library is hundreds of hours of work spread over weeks, and until now
the only trace a finished page left was the file itself. That is enough to answer "does
this page exist" and nothing else - not what it was made with, not how long it took, not
which pages failed and where.

The ledger is one json object per line, appended as pages finish:

    {"type": "run",  ...}   once per invocation, carrying the full recipe
    {"type": "page", ...}   once per page, carrying its timings and outcome

Page records name their recipe by id only; the run records in the same file hold the
expanded settings, so a ledger is self contained. Reading one back needs nothing but the
standard library, and `read_ledger` is here so that a tool does not have to know the
line format at all.

Only the parent process writes, on the completion of a page whose phases ran in a worker,
so there is no interleaving to guard against. Lines are flushed as they are written and a
truncated last line is skipped on read, so a ledger stays usable after a hard kill.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import TYPE_CHECKING, Any

from loguru import logger

from barks_comic_building.restore.ledger_common import (
    OUTCOME_COPIED,
    OUTCOME_FAILED,
    OUTCOME_OK,
    OUTCOME_PRESENT,
    OUTCOME_STOPPED,
    RECORD_TYPE_PAGE,
    RECORD_TYPE_RUN,
    JsonlWriter,
    get_git_commit,
    get_host,
    new_run_id,
    now,
    read_records,
)
from barks_comic_building.restore.restore_recipe import RestoreRecipe

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Self

__all__ = [
    "OUTCOME_COPIED",
    "OUTCOME_FAILED",
    "OUTCOME_OK",
    "OUTCOME_PRESENT",
    "OUTCOME_STOPPED",
    "RECORD_TYPE_PAGE",
    "RECORD_TYPE_RUN",
    "Ledger",
    "LedgerWriter",
    "PageRecord",
    "RunRecord",
    "TimingStats",
    "get_default_ledger_file",
    "read_ledger",
    "summarise_step_seconds",
]

# Bumped when the record shape changes. Readers use it to refuse records they predate.
LEDGER_SCHEMA = 1

LEDGER_FILENAME = "restore-ledger.jsonl"


def get_default_ledger_file() -> Path:
    """Return where the ledger lives unless told otherwise.

    A sibling of the Fantagraphics stage directories rather than inside one of them, so
    that the integrity checks that walk those trees do not see it, while the existing
    backup of the Barks root still picks it up.

    Returns:
        The default ledger path.

    """
    from barks_fantagraphics.comics_consts import BARKS_ROOT_DIR  # noqa: PLC0415

    return Path(BARKS_ROOT_DIR) / LEDGER_FILENAME


@dataclass(frozen=True, slots=True)
class RunRecord:
    """One invocation of the restore pipeline."""

    run_id: str
    started: str
    recipe_id: str
    recipe: RestoreRecipe | None
    git_commit: str
    host: str
    workers: dict[str, int]


@dataclass(frozen=True, slots=True)
class PageRecord:
    """One page the pipeline finished with, whether or not it worked."""

    run_id: str
    title: str
    volume: int
    page: str
    recipe_id: str
    outcome: str
    failed_step: str | None
    started: str
    finished: str
    total_seconds: float
    step_seconds: dict[str, float]
    dest_bytes: int
    upscaler: str

    @property
    def is_ok(self) -> bool:
        """Whether the page is in good order, whatever this run did or did not do to it.

        A page that was already there counts: it is not a failure, and listing it as one
        would bury the real failures under every page a re-run walked past.
        """
        return self.outcome in (OUTCOME_OK, OUTCOME_COPIED, OUTCOME_PRESENT)


@dataclass(frozen=True, slots=True)
class TimingStats:
    """How long pages have been taking."""

    count: int
    mean_seconds: float
    median_seconds: float
    step_mean_seconds: dict[str, float]


@dataclass
class Ledger:
    """A parsed ledger."""

    runs: dict[str, RunRecord] = field(default_factory=dict)
    pages: list[PageRecord] = field(default_factory=list)

    def recipe_for(self, recipe_id: str) -> RestoreRecipe | None:
        """Return the expanded settings behind a recipe id.

        Args:
            recipe_id: The id carried by a page record.

        Returns:
            The recipe, or None if no run record in this ledger used it.

        """
        for run in self.runs.values():
            if run.recipe_id == recipe_id and run.recipe is not None:
                return run.recipe

        return None

    def latest_by_page(self) -> dict[tuple[str, str], PageRecord]:
        """Return the most recent record for each page.

        A page can be restored more than once - after a failure, or after the recipe
        moved on - and only the last attempt describes the file on disk now.

        Returns:
            The newest record for each (title, page).

        """
        latest: dict[tuple[str, str], PageRecord] = {}
        for record in self.pages:
            latest[record.title, record.page] = record

        return latest

    def _is_measured(self, record: PageRecord, recipe_id: str | None) -> bool:
        """Whether a record is evidence of what a restored page costs.

        Restored pages only. A copied page is recorded as done, and reads as fine through
        ``is_ok``, but it is a file copy taking a fraction of a second where a restore
        takes minutes - counting it would drag the mean down and shorten every estimate
        built from it.

        Args:
            record: The page record to weigh up.
            recipe_id: Restrict to this recipe, or None for any.

        Returns:
            Whether it should count.

        """
        return (
            record.outcome == OUTCOME_OK
            and record.total_seconds > 0
            and (recipe_id is None or record.recipe_id == recipe_id)
        )

    def timing_stats(self, recipe_id: str | None = None) -> TimingStats | None:
        """Return how long restored pages have been taking.

        Args:
            recipe_id: Only count pages made with this recipe. Pass None to count all of
                them. Restricting to the current recipe gives the estimate that matches
                what the next page will cost.

        Returns:
            The statistics, or None if no restored page qualifies.

        """
        totals = [
            record.total_seconds for record in self.pages if self._is_measured(record, recipe_id)
        ]
        if not totals:
            return None

        # The same pages the totals above were taken from. Counting a page's steps but not
        # its total would put the two figures on different sets, and the step table
        # reports itself as being over `count` pages.
        step_totals: dict[str, list[float]] = {}
        for record in self.pages:
            if not self._is_measured(record, recipe_id):
                continue
            for step, seconds in record.step_seconds.items():
                step_totals.setdefault(step, []).append(seconds)

        return TimingStats(
            count=len(totals),
            mean_seconds=mean(totals),
            median_seconds=median(totals),
            step_mean_seconds={step: mean(values) for step, values in step_totals.items()},
        )


class LedgerWriter(JsonlWriter):
    """Appends run and page records to a ledger file.

    Used as a context manager so the run record is written on entry and the handle is
    closed on the way out, whatever the run did.
    """

    def __init__(self, ledger_file: Path, recipe: RestoreRecipe, workers: dict[str, int]) -> None:
        """Open a ledger for appending and stamp a new run into it.

        Args:
            ledger_file: Where to append. Parent directories are created.
            recipe: The settings this run restores with.
            workers: The per-phase worker counts, recorded so that a timing read back
                later can be understood in the light of how contended it was.

        """
        super().__init__(ledger_file)
        self.recipe = recipe
        self.started = now()
        self.run_id = new_run_id(self.started)

        self._workers = workers

    def __enter__(self) -> Self:
        """Open the ledger file and append this run's record."""
        super().__enter__()

        self.write(
            {
                "type": RECORD_TYPE_RUN,
                "schema": LEDGER_SCHEMA,
                "run_id": self.run_id,
                "started": self.started,
                "recipe_id": self.recipe.recipe_id,
                "recipe": self.recipe.as_dict(),
                "git_commit": get_git_commit(),
                "host": get_host(),
                "workers": self._workers,
            }
        )

        return self

    def write_page(  # noqa: PLR0913
        self,
        title: str,
        volume: int,
        page: str,
        outcome: str,
        started: str,
        total_seconds: float,
        step_seconds: dict[str, float],
        failed_step: str | None = None,
        dest_bytes: int = 0,
        upscaler: str = "",
    ) -> None:
        """Append one page's outcome and timings.

        Args:
            title: The story the page belongs to.
            volume: Its Fantagraphics volume number.
            page: The page's file stem, as it is named in the volume.
            outcome: One of the module's ``OUTCOME_`` values.
            started: When the page started, as an iso timestamp.
            total_seconds: Wall clock for the whole page.
            step_seconds: Wall clock per pipeline step.
            failed_step: The step that failed, when the outcome is a failure.
            dest_bytes: Size of the restored page, when there is one.
            upscaler: Which upscaler produced this page's input, read from that file's
                metadata. Upstream provenance rather than part of the restore recipe,
                since it describes the input the restore was handed.

        """
        self.write(
            {
                "type": RECORD_TYPE_PAGE,
                "schema": LEDGER_SCHEMA,
                "run_id": self.run_id,
                "title": title,
                "volume": volume,
                "page": page,
                "recipe_id": self.recipe.recipe_id,
                "outcome": outcome,
                "failed_step": failed_step,
                "started": started,
                "finished": now(),
                "total_seconds": round(total_seconds, 1),
                "step_seconds": {k: round(v, 1) for k, v in step_seconds.items()},
                "dest_bytes": dest_bytes,
                "upscaler": upscaler,
            }
        )


def _parse_run(record: dict[str, Any]) -> RunRecord:
    recipe_values = record.get("recipe")
    recipe = None
    if isinstance(recipe_values, dict):
        try:
            recipe = RestoreRecipe.from_dict(recipe_values)
        except (ValueError, TypeError):
            # A run written by a version whose recipe had different fields. The id still
            # compares fine, so keep the run and leave the expansion unavailable.
            recipe = None

    return RunRecord(
        run_id=record["run_id"],
        started=record.get("started", ""),
        recipe_id=record.get("recipe_id", ""),
        recipe=recipe,
        git_commit=record.get("git_commit", ""),
        host=record.get("host", ""),
        workers=record.get("workers", {}),
    )


def _parse_page(record: dict[str, Any]) -> PageRecord:
    return PageRecord(
        run_id=record.get("run_id", ""),
        title=record["title"],
        volume=int(record.get("volume", 0)),
        page=str(record["page"]),
        recipe_id=record.get("recipe_id", ""),
        outcome=record.get("outcome", OUTCOME_OK),
        failed_step=record.get("failed_step"),
        started=record.get("started", ""),
        finished=record.get("finished", ""),
        total_seconds=float(record.get("total_seconds", 0.0)),
        step_seconds={k: float(v) for k, v in record.get("step_seconds", {}).items()},
        dest_bytes=int(record.get("dest_bytes", 0)),
        upscaler=record.get("upscaler", ""),
    )


def read_ledger(ledger_file: Path | None = None) -> Ledger:
    """Read a ledger back.

    Malformed lines are skipped rather than raising - a ledger that survived a hard kill
    mid-write has to stay readable, and one bad line should not cost the other thousands.

    Args:
        ledger_file: The ledger to read. Defaults to `get_default_ledger_file()`.

    Returns:
        The parsed ledger. Empty if the file does not exist.

    """
    path = ledger_file or get_default_ledger_file()

    ledger = Ledger()
    for record in read_records(path, LEDGER_SCHEMA):
        try:
            if record.get("type") == RECORD_TYPE_RUN:
                run = _parse_run(record)
                ledger.runs[run.run_id] = run
            elif record.get("type") == RECORD_TYPE_PAGE:
                ledger.pages.append(_parse_page(record))
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug(f'Skipping unreadable record in "{path}": {exc}.')

    return ledger


def summarise_step_seconds(records: Iterable[PageRecord]) -> dict[str, float]:
    """Return the total seconds spent in each step across some page records.

    Args:
        records: The page records to add up.

    Returns:
        Total seconds per step name, largest first.

    """
    totals: dict[str, float] = {}
    for record in records:
        for step, seconds in record.step_seconds.items():
            totals[step] = totals.get(step, 0.0) + seconds

    return dict(sorted(totals.items(), key=lambda kv: -kv[1]))
