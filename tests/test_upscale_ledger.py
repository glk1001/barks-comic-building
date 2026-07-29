"""Tests for the record of what the upscale did.

The same properties the restore ledger has to hold, for the same reasons: a half written
last line must not cost the other thousands of records, the newest attempt at a page must
win over its earlier failures, and the timings an estimate is built from must not be
polluted by pages that failed.

The one addition is the error text. Upscayl fails in a way that matters here - it exits 0
after writing a black image, and the check rejects it - so a failed page has to keep the
reason, not just the outcome.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from barks_comic_building.restore.upscale_image import Upscaler
from barks_comic_building.restore.upscale_ledger import (
    LEDGER_SCHEMA,
    OUTCOME_FAILED,
    OUTCOME_OK,
    UpscaleLedgerWriter,
    read_upscale_ledger,
)
from barks_comic_building.restore.upscale_recipe import get_current_recipe

if TYPE_CHECKING:
    from pathlib import Path

SCALE = 4

# Named so the assertions read as "both of them" rather than as a bare literal.
TWO = 2


@pytest.fixture
def ledger_file(tmp_path: Path) -> Path:
    return tmp_path / "upscale-ledger.jsonl"


def write_pages(ledger_file: Path, pages: list[tuple[str, str, float]]) -> None:
    """Append one run's worth of page records: (page, outcome, total_seconds)."""
    recipe = get_current_recipe(Upscaler.WAIFU2X, SCALE)
    with UpscaleLedgerWriter(ledger_file, recipe) as writer:
        for page, outcome, seconds in pages:
            writer.write_page(
                title="Good Neighbors",
                volume=2,
                page=page,
                outcome=outcome,
                started="2026-07-29T12:00:00+10:00",
                total_seconds=seconds,
                error="wrote a black image" if outcome == OUTCOME_FAILED else None,
                srce_bytes=1000,
                dest_bytes=9000 if outcome == OUTCOME_OK else 0,
            )


class TestRoundTrip:
    def test_a_run_and_its_pages_come_back(self, ledger_file: Path) -> None:
        write_pages(ledger_file, [("067", OUTCOME_OK, 42.0)])

        ledger = read_upscale_ledger(ledger_file)

        assert len(ledger.runs) == 1
        assert len(ledger.pages) == 1
        assert ledger.pages[0].page == "067"
        assert ledger.pages[0].is_ok

    def test_the_recipe_expands_from_its_id(self, ledger_file: Path) -> None:
        """A ledger is self contained.

        A page names its recipe by id; the run record in the same file holds the settings.
        """
        write_pages(ledger_file, [("067", OUTCOME_OK, 42.0)])

        ledger = read_upscale_ledger(ledger_file)
        recipe = ledger.recipe_for(ledger.pages[0].recipe_id)

        assert recipe == get_current_recipe(Upscaler.WAIFU2X, SCALE)

    def test_a_failure_keeps_its_reason(self, ledger_file: Path) -> None:
        """Outcome alone cannot tell a rejected black image from a missing binary."""
        write_pages(ledger_file, [("067", OUTCOME_FAILED, 3.0)])

        page = read_upscale_ledger(ledger_file).pages[0]

        assert not page.is_ok
        assert page.error == "wrote a black image"

    def test_missing_ledger_reads_as_empty(self, tmp_path: Path) -> None:
        ledger = read_upscale_ledger(tmp_path / "not-there.jsonl")

        assert ledger.runs == {}
        assert ledger.pages == []


class TestSurvivingAKill:
    def test_a_truncated_last_line_costs_only_itself(self, ledger_file: Path) -> None:
        """A run killed mid-write must not take the rest of the ledger with it."""
        write_pages(ledger_file, [("067", OUTCOME_OK, 42.0), ("068", OUTCOME_OK, 44.0)])
        with ledger_file.open("a", encoding="utf-8") as f:
            f.write('{"type":"page","title":"Good Nei')

        assert len(read_upscale_ledger(ledger_file).pages) == TWO

    def test_records_from_a_newer_schema_are_refused(self, ledger_file: Path) -> None:
        """A newer record's fields cannot be known to this reader."""
        write_pages(ledger_file, [("067", OUTCOME_OK, 42.0)])
        with ledger_file.open("a", encoding="utf-8") as f:
            f.write(f'{{"type":"page","schema":{LEDGER_SCHEMA + 1},"title":"x","page":"1"}}\n')

        assert len(read_upscale_ledger(ledger_file).pages) == 1

    def test_two_runs_append_rather_than_replace(self, ledger_file: Path) -> None:
        write_pages(ledger_file, [("067", OUTCOME_OK, 42.0)])
        write_pages(ledger_file, [("068", OUTCOME_OK, 44.0)])

        ledger = read_upscale_ledger(ledger_file)

        assert len(ledger.runs) == TWO
        assert len(ledger.pages) == TWO

    def test_the_writer_refuses_to_be_used_unopened(self, ledger_file: Path) -> None:
        """Silently dropping a record is the one thing an append-only ledger must not do."""
        writer = UpscaleLedgerWriter(ledger_file, get_current_recipe(Upscaler.WAIFU2X, SCALE))

        with pytest.raises(RuntimeError, match="context manager"):
            writer.write_page(
                title="Good Neighbors",
                volume=2,
                page="067",
                outcome=OUTCOME_OK,
                started="2026-07-29T12:00:00+10:00",
                total_seconds=1.0,
            )


class TestLatestAttemptWins:
    def test_a_retry_supersedes_its_failure(self, ledger_file: Path) -> None:
        """Only the last attempt describes the file on disk now."""
        write_pages(ledger_file, [("067", OUTCOME_FAILED, 3.0)])
        write_pages(ledger_file, [("067", OUTCOME_OK, 42.0)])

        latest = read_upscale_ledger(ledger_file).latest_by_page()

        assert latest["Good Neighbors", "067"].is_ok


class TestTimingStats:
    def test_failed_pages_do_not_pollute_the_estimate(self, ledger_file: Path) -> None:
        """A page that died after three seconds is not evidence about what a page costs."""
        write_pages(
            ledger_file,
            [("067", OUTCOME_OK, 40.0), ("068", OUTCOME_OK, 44.0), ("069", OUTCOME_FAILED, 3.0)],
        )

        stats = read_upscale_ledger(ledger_file).timing_stats()

        assert stats is not None
        assert stats.count == TWO
        assert stats.mean_seconds == pytest.approx(42.0)

    def test_stats_can_be_restricted_to_one_recipe(self, ledger_file: Path) -> None:
        """The estimate that matches what the next page will cost."""
        write_pages(ledger_file, [("067", OUTCOME_OK, 42.0)])

        current = get_current_recipe(Upscaler.WAIFU2X, SCALE).recipe_id
        other = get_current_recipe(Upscaler.UPSCAYL, SCALE).recipe_id
        ledger = read_upscale_ledger(ledger_file)

        assert ledger.timing_stats(current) is not None
        assert ledger.timing_stats(other) is None

    def test_no_successful_pages_gives_no_stats(self, ledger_file: Path) -> None:
        write_pages(ledger_file, [("067", OUTCOME_FAILED, 3.0)])

        assert read_upscale_ledger(ledger_file).timing_stats() is None
