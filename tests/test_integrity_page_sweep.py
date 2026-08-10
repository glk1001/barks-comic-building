"""Tests that a title names every page it cannot resolve, not just the first.

`get_sorted_srce_and_dest_pages` resolves a whole title in one go and raises on the first
page it cannot find. The integrity check called it inside one try/except and recorded the
message, so a title missing several restored pages reported one of them and said nothing
about the others - and nothing about anything else either, because the page list it gave
up on is what every other per-page check reads.

Volume 4's pages 098 and 099 were the case that showed it. Both were missing from the
restored tree, both for the same reason, and the report only ever mentioned 098: fix that
one and 099 appears, as if it were a new problem rather than one that had been there all
along. So the pages are swept individually first, and the report says out loud when the
rest of the checks did not run.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from barks_fantagraphics.comics_consts import PageType
from barks_fantagraphics.page_classes import OriginalPage

from barks_comic_building.build.comics_integrity import ComicsIntegrityChecker, OutOfDateErrors
from barks_comic_building.build.utils import ZipOutOfDateErrors, ZipSymlinkOutOfDateErrors

if TYPE_CHECKING:
    import pytest
    from barks_fantagraphics.comic_book import ComicBook

RESTORED_DIR = Path("/fanta/restored/images")

# The page numbers a story runs over, and which of them have no restored file. Two missing
# rather than one, because one missing page cannot tell a sweep from a bail-out.
BODY_PAGES = ("096", "097", "098", "099", "100")
MISSING_PAGES = ("098", "099")


class FakeComic:
    """The two accessors the page sweep reaches for, over a story of BODY pages.

    Stands in for a `ComicBook`. `get_final_srce_story_file` is the real thing's contract:
    it returns the resolved path, or raises `FileNotFoundError` naming the page and its
    type - which is the message the report prints.
    """

    def __init__(self, missing: tuple[str, ...] = MISSING_PAGES) -> None:
        self._missing = missing
        self.page_images_in_order = [
            OriginalPage(page_num, PageType.BODY) for page_num in BODY_PAGES
        ]
        self.asked_for: list[str] = []

    def get_final_srce_story_file(self, page_num: str, page_type: PageType) -> tuple[Path, str]:
        self.asked_for.append(page_num)
        restored_file = RESTORED_DIR / f"{page_num}.png"
        if page_num in self._missing:
            msg = (
                f'Could not find restored source file "{restored_file}" of type "{page_type.name}"'
            )
            raise FileNotFoundError(msg)

        return restored_file, "ORIGINAL"


def as_comic(fake: FakeComic) -> ComicBook:
    """Present a `FakeComic` as the `ComicBook` the sweep is typed against."""
    return cast("ComicBook", fake)


def sweep(fake: FakeComic) -> list[str]:
    return ComicsIntegrityChecker.get_unresolvable_srce_file_errors(as_comic(fake))


def no_findings() -> OutOfDateErrors:
    return ComicsIntegrityChecker.make_out_of_date_errors("Santa's Stormy Visit")


class TestEveryUnresolvablePageIsNamed:
    def test_both_missing_pages_are_reported(self) -> None:
        messages = sweep(FakeComic())

        assert len(messages) == len(MISSING_PAGES)
        for page_num in MISSING_PAGES:
            assert any(f"{page_num}.png" in message for message in messages)

    def test_they_are_reported_in_page_order(self) -> None:
        """So the report reads down the story rather than in whatever order it found them."""
        messages = sweep(FakeComic())

        assert "098.png" in messages[0]
        assert "099.png" in messages[1]

    def test_the_message_still_names_the_page_type(self) -> None:
        """The sweep passes the resolver's own message through rather than rewording it."""
        messages = sweep(FakeComic())

        assert 'of type "BODY"' in messages[0]

    def test_the_sweep_does_not_stop_at_the_first_failure(self) -> None:
        """The property the old code lacked: every page is asked for, not just up to the bad one."""
        fake = FakeComic()

        sweep(fake)

        assert fake.asked_for == list(BODY_PAGES)

    def test_a_title_with_every_page_present_reports_nothing(self) -> None:
        assert sweep(FakeComic(missing=())) == []


class TestTheReportSaysWhenItStoppedEarly:
    def test_skipped_checks_are_announced(self, capsys: pytest.CaptureFixture[str]) -> None:
        errors = no_findings()
        errors.exception_errors.append("Could not find restored source file")
        errors.checks_skipped = True

        ComicsIntegrityChecker._print_dest_dir_findings(errors)  # noqa: SLF001

        assert "the page and dest dir checks were skipped" in capsys.readouterr().out

    def test_nothing_is_announced_when_the_checks_did_run(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An exception that did not stop the run must not claim the checks were skipped."""
        errors = no_findings()
        errors.exception_errors.append("the panel segments file could not be read")

        ComicsIntegrityChecker._print_dest_dir_findings(errors)  # noqa: SLF001

        assert "skipped" not in capsys.readouterr().out


class TestStoppingEarlyIsNotItselfAFinding:
    """`checks_skipped` explains other findings; it is never the only thing wrong.

    It always travels with the exception that caused it, so folding it into `is_error`
    would be redundant - and a title that stopped early with nothing recorded would be a
    bug in the sweep, not a finding to report.
    """

    def test_it_does_not_make_a_clean_title_an_error(self) -> None:
        errors = no_findings()
        errors.checks_skipped = True

        assert not errors.is_error

    def test_the_exception_it_travels_with_is_the_error(self) -> None:
        errors = no_findings()
        errors.exception_errors.append("Could not find restored source file")
        errors.checks_skipped = True

        assert errors.is_error
        assert errors.file_findings


class TestAnUnreadablePageListDegradesToOneMessage:
    def test_a_broken_page_list_is_reported_without_a_sweep(self) -> None:
        """Nothing to sweep if the list itself will not parse, so say the one thing there is.

        A page filename that is not a number is the real way this happens - the page list
        build ints it - and it stops the sweep before it has a single page to walk.
        """
        fake = FakeComic()
        fake.page_images_in_order = [OriginalPage("not-a-page", PageType.BODY)]

        messages = sweep(fake)

        assert len(messages) == 1
        assert "not-a-page" in messages[0]
        assert fake.asked_for == []


def test_the_findings_record_still_round_trips() -> None:
    """`checks_skipped` has a default, so the factory does not have to set it."""
    errors = no_findings()

    assert errors.checks_skipped is False
    assert isinstance(errors.zip_errors, ZipOutOfDateErrors)
    assert isinstance(errors.series_zip_symlink_errors, ZipSymlinkOutOfDateErrors)
