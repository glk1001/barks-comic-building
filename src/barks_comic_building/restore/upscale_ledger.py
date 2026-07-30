"""An append-only record of what the upscale did, and how long it took.

The same record the restore keeps, one stage earlier, and for the same reason: upscaling
the library is thousands of pages of GPU work, and until now the only trace a finished
page left was the file itself. That cannot say what made it, how long it took, or which
pages failed - and Upscayl in particular fails in a way that matters here, exiting 0 after
writing a black image, so the record of what was rejected is worth keeping.

The ledger is one json object per line, appended as pages finish:

    {"type": "run",  ...}   once per invocation, carrying the full recipe
    {"type": "page", ...}   once per page, carrying its timing and outcome

Page records name their recipe by id only; the run records in the same file hold the
expanded settings, so a ledger is self contained. It lives beside the restore ledger
rather than in it, so that neither reader has to walk the other's records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import TYPE_CHECKING, Any

from loguru import logger

from barks_comic_building.restore.ledger_common import (
    OUTCOME_FAILED,
    OUTCOME_OK,
    RECORD_TYPE_PAGE,
    RECORD_TYPE_RUN,
    JsonlWriter,
    get_git_commit,
    get_host,
    new_run_id,
    now,
    read_records,
)
from barks_comic_building.restore.upscale_recipe import UpscaleRecipe

if TYPE_CHECKING:
    from typing import Self

__all__ = [
    "LEDGER_FILENAME",
    "OUTCOME_FAILED",
    "OUTCOME_OK",
    "UpscaleLedger",
    "UpscaleLedgerWriter",
    "get_default_upscale_ledger_file",
    "read_upscale_ledger",
]

# Bumped when the record shape changes. Readers use it to refuse records they predate.
LEDGER_SCHEMA = 1

LEDGER_FILENAME = "upscale-ledger.jsonl"


def get_default_upscale_ledger_file() -> Path:
    """Return where the upscale ledger lives unless told otherwise.

    A sibling of the Fantagraphics stage directories rather than inside one of them, so
    that the integrity checks that walk those trees do not see it, while the existing
    backup of the Barks root still picks it up.

    Returns:
        The default ledger path.

    """
    from barks_fantagraphics.comics_consts import BARKS_ROOT_DIR  # noqa: PLC0415

    return Path(BARKS_ROOT_DIR) / LEDGER_FILENAME


@dataclass(frozen=True, slots=True)
class UpscaleRunRecord:
    """One invocation of the upscale."""

    run_id: str
    started: str
    recipe_id: str
    recipe: UpscaleRecipe | None
    git_commit: str
    host: str


@dataclass(frozen=True, slots=True)
class UpscalePageRecord:
    """One page the upscale finished with, whether or not it worked."""

    run_id: str
    title: str
    volume: int
    page: str
    recipe_id: str
    outcome: str
    error: str | None
    started: str
    finished: str
    total_seconds: float
    srce_bytes: int
    dest_bytes: int

    @property
    def is_ok(self) -> bool:
        """Whether the page came out of the upscale intact."""
        return self.outcome == OUTCOME_OK


@dataclass(frozen=True, slots=True)
class UpscaleTimingStats:
    """How long pages have been taking."""

    count: int
    mean_seconds: float
    median_seconds: float


@dataclass
class UpscaleLedger:
    """A parsed upscale ledger."""

    runs: dict[str, UpscaleRunRecord] = field(default_factory=dict)
    pages: list[UpscalePageRecord] = field(default_factory=list)

    def recipe_for(self, recipe_id: str) -> UpscaleRecipe | None:
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

    def latest_by_page(self) -> dict[tuple[str, str], UpscalePageRecord]:
        """Return the most recent record for each page.

        A page can be upscayled more than once - after a failure, or after the recipe
        moved on - and only the last attempt describes the file on disk now.

        Returns:
            The newest record for each (title, page).

        """
        latest: dict[tuple[str, str], UpscalePageRecord] = {}
        for record in self.pages:
            latest[record.title, record.page] = record

        return latest

    def timing_stats(self, recipe_id: str | None = None) -> UpscaleTimingStats | None:
        """Return how long successful pages have been taking.

        Args:
            recipe_id: Only count pages made with this recipe. Pass None to count all of
                them. Restricting to the current recipe gives the estimate that matches
                what the next page will cost.

        Returns:
            The statistics, or None if no successful page qualifies.

        """
        totals = [
            record.total_seconds
            for record in self.pages
            if record.is_ok
            and record.total_seconds > 0
            and (recipe_id is None or record.recipe_id == recipe_id)
        ]
        if not totals:
            return None

        return UpscaleTimingStats(
            count=len(totals),
            mean_seconds=mean(totals),
            median_seconds=median(totals),
        )


class UpscaleLedgerWriter(JsonlWriter):
    """Appends run and page records to an upscale ledger."""

    def __init__(self, ledger_file: Path, recipe: UpscaleRecipe) -> None:
        """Open a ledger for appending and stamp a new run into it.

        Args:
            ledger_file: Where to append. Parent directories are created.
            recipe: The settings this run upscales with.

        """
        super().__init__(ledger_file)
        self.recipe = recipe
        self.started = now()
        self.run_id = new_run_id(self.started)

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
        error: str | None = None,
        srce_bytes: int = 0,
        dest_bytes: int = 0,
    ) -> None:
        """Append one page's outcome and timing.

        Args:
            title: The story the page belongs to.
            volume: Its Fantagraphics volume number.
            page: The page's file stem, as it is named in the volume.
            outcome: One of the ledger's ``OUTCOME_`` values.
            started: When the page started, as an iso timestamp.
            total_seconds: Wall clock for the page.
            error: Why it failed, when the outcome is a failure. Worth keeping in full:
                a rejected Upscayl page and a missing binary read identically from the
                outcome alone.
            srce_bytes: Size of the page the upscale was handed.
            dest_bytes: Size of the upscayled page, when there is one.

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
                "error": error,
                "started": started,
                "finished": now(),
                "total_seconds": round(total_seconds, 1),
                "srce_bytes": srce_bytes,
                "dest_bytes": dest_bytes,
            }
        )


def _parse_run(record: dict[str, Any]) -> UpscaleRunRecord:
    recipe_values = record.get("recipe")
    recipe = None
    if isinstance(recipe_values, dict):
        try:
            recipe = UpscaleRecipe.from_dict(recipe_values)
        except (ValueError, TypeError):
            # A run written by a version whose recipe had different fields. The id still
            # compares fine, so keep the run and leave the expansion unavailable.
            recipe = None

    return UpscaleRunRecord(
        run_id=record["run_id"],
        started=record.get("started", ""),
        recipe_id=record.get("recipe_id", ""),
        recipe=recipe,
        git_commit=record.get("git_commit", ""),
        host=record.get("host", ""),
    )


def _parse_page(record: dict[str, Any]) -> UpscalePageRecord:
    return UpscalePageRecord(
        run_id=record.get("run_id", ""),
        title=record["title"],
        volume=int(record.get("volume", 0)),
        page=str(record["page"]),
        recipe_id=record.get("recipe_id", ""),
        outcome=record.get("outcome", OUTCOME_OK),
        error=record.get("error"),
        started=record.get("started", ""),
        finished=record.get("finished", ""),
        total_seconds=float(record.get("total_seconds", 0.0)),
        srce_bytes=int(record.get("srce_bytes", 0)),
        dest_bytes=int(record.get("dest_bytes", 0)),
    )


def read_upscale_ledger(ledger_file: Path | None = None) -> UpscaleLedger:
    """Read an upscale ledger back.

    Args:
        ledger_file: The ledger to read. Defaults to `get_default_upscale_ledger_file()`.

    Returns:
        The parsed ledger. Empty if the file does not exist.

    """
    path = ledger_file or get_default_upscale_ledger_file()

    ledger = UpscaleLedger()
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
