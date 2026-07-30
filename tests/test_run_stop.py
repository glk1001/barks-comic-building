"""Tests for asking a long restore run to stop.

A stop is only worth having if it is trustworthy in both directions. It has to be seen -
by the parent and by every worker process, which is why it lives on the filesystem rather
than in a variable - and it has to not be seen when nobody asked, because a stop wrongly
believed in would silently end a run that should have carried on for days.

The escalation matters too: asking twice is how you say "sooner", so a second ask must
never leave the request where it was.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from barks_comic_building.restore.run_stop import (
    StopMode,
    clear_stop,
    get_stop_file,
    parse_duration,
    read_stop_mode,
    request_stop,
)

if TYPE_CHECKING:
    from pathlib import Path

HOUR = 3600
MINUTE = 60


class TestNoRequest:
    def test_nothing_asked_for_reads_as_none(self, tmp_path: Path) -> None:
        assert read_stop_mode(get_stop_file(tmp_path)) is StopMode.NONE

    def test_no_stop_file_at_all_reads_as_none(self) -> None:
        """A pipeline outside a stoppable run, as the single-page CLI builds."""
        assert read_stop_mode(None) is StopMode.NONE

    def test_a_missing_work_dir_reads_as_none(self, tmp_path: Path) -> None:
        assert read_stop_mode(get_stop_file(tmp_path / "not-there")) is StopMode.NONE


class TestRequesting:
    def test_the_default_ask_lets_started_pages_finish(self, tmp_path: Path) -> None:
        assert request_stop(tmp_path) is StopMode.PAGES
        assert read_stop_mode(get_stop_file(tmp_path)) is StopMode.PAGES

    def test_asking_for_step_directly(self, tmp_path: Path) -> None:
        assert request_stop(tmp_path, StopMode.STEP) is StopMode.STEP

    def test_asking_twice_escalates(self, tmp_path: Path) -> None:
        """Asking again is how you say sooner, without having to recall a flag."""
        request_stop(tmp_path)

        assert request_stop(tmp_path) is StopMode.STEP
        assert read_stop_mode(get_stop_file(tmp_path)) is StopMode.STEP

    def test_escalation_does_not_go_backwards(self, tmp_path: Path) -> None:
        """Once it is at STEP, a gentler ask must not relax it."""
        request_stop(tmp_path, StopMode.STEP)

        assert request_stop(tmp_path, StopMode.PAGES) is StopMode.STEP

    def test_requesting_none_is_refused(self, tmp_path: Path) -> None:
        """It would write a file that reads as a stop but is not one."""
        with pytest.raises(ValueError, match="clear_stop"):
            request_stop(tmp_path, StopMode.NONE)

    def test_the_file_says_what_it_means(self, tmp_path: Path) -> None:
        """Somebody will read this file before they read the code."""
        request_stop(tmp_path)
        text = get_stop_file(tmp_path).read_text()

        assert text.splitlines()[0] == StopMode.PAGES
        assert "requested" in text
        assert "no new pages" in text

    def test_the_work_dir_is_made_if_needed(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "not-yet"

        request_stop(work_dir)

        assert read_stop_mode(get_stop_file(work_dir)) is StopMode.PAGES


class TestClearing:
    def test_clearing_withdraws_the_request(self, tmp_path: Path) -> None:
        request_stop(tmp_path)

        assert clear_stop(tmp_path) is True
        assert read_stop_mode(get_stop_file(tmp_path)) is StopMode.NONE

    def test_clearing_nothing_says_so(self, tmp_path: Path) -> None:
        assert clear_stop(tmp_path) is False

    def test_a_run_starts_from_a_clean_slate(self, tmp_path: Path) -> None:
        """A request left behind by the last run must not stop the next one.

        That failure would look exactly like the run refusing to start, with days of
        work quietly not happening.
        """
        request_stop(tmp_path, StopMode.STEP)
        clear_stop(tmp_path)
        request_stop(tmp_path)

        assert read_stop_mode(get_stop_file(tmp_path)) is StopMode.PAGES


class TestDamagedRequests:
    def test_an_unreadable_request_is_still_a_stop(self, tmp_path: Path) -> None:
        """Somebody clearly asked. Reading rubbish as "carry on" ignores them."""
        get_stop_file(tmp_path).write_text("\x00\x01 not a mode")

        assert read_stop_mode(get_stop_file(tmp_path)) is StopMode.PAGES

    def test_an_empty_request_is_still_a_stop(self, tmp_path: Path) -> None:
        """What a bare `touch` of the file leaves."""
        get_stop_file(tmp_path).touch()

        assert read_stop_mode(get_stop_file(tmp_path)) is StopMode.PAGES

    def test_trailing_whitespace_and_case_are_forgiven(self, tmp_path: Path) -> None:
        get_stop_file(tmp_path).write_text("  STEP  \nrequested whenever\n")

        assert read_stop_mode(get_stop_file(tmp_path)) is StopMode.STEP


class TestWhoGetsCutShort:
    @pytest.mark.parametrize(
        ("mode", "expected"),
        [(StopMode.NONE, False), (StopMode.PAGES, False), (StopMode.STEP, True)],
    )
    def test_only_step_interrupts_a_page_under_way(self, mode: StopMode, *, expected: bool) -> None:
        """The whole point of the gentler mode is that a started page still finishes."""
        assert mode.stops_pages_that_have_started is expected


class TestParseDuration:
    @pytest.mark.parametrize(
        ("text", "seconds"),
        [
            ("8h", 8 * HOUR),
            ("90m", 90 * MINUTE),
            ("1h30m", HOUR + 30 * MINUTE),
            ("45s", 45),
            ("2h15m30s", 2 * HOUR + 15 * MINUTE + 30),
            ("  8h  ", 8 * HOUR),
            ("8H", 8 * HOUR),
            ("1h 30m", HOUR + 30 * MINUTE),
        ],
    )
    def test_durations_that_should_parse(self, text: str, seconds: float) -> None:
        assert parse_duration(text) == seconds

    @pytest.mark.parametrize("text", ["", "   ", "8", "8x", "hours", "1h1h", "8h junk", "-8h"])
    def test_durations_that_should_not(self, text: str) -> None:
        """Anything not fully understood is refused rather than partly honoured.

        A misread duration would stop a run at the wrong time and never say why.
        """
        with pytest.raises(ValueError, match=r"(?i)duration"):
            parse_duration(text)
