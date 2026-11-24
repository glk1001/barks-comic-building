"""Tests for which files `barks-fanta-story-files` marks as out of date.

The listing prints a built page above the files it was made from, each with its date, and
puts a `*` against a file newer than the thing made from it. It used to work that out by
comparing every row with the row above it, which is not the same question: the rows are
not all a chain. So a file in perfect order was marked whenever the row above it was a
stage that is not on disk, or a file it was never made from - the title page's inset
against the ini file's checkout time - and a page with nothing wrong looked stale.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from barks_fantagraphics.comic_book import ComicBook
from barks_fantagraphics.comics_consts import PageType
from barks_fantagraphics.pages import (
    TITLE_EMPTY_FILENAME,
    SrceDependency,
    get_sorted_srce_and_dest_pages,
)

from barks_comic_building.query.build_state import RESTORED_FLAG, UPSCAYLED_FLAG
from barks_comic_building.query.fantagraphics_story_files import (
    NOT_ON_DISK,
    OUT_OF_DATE_MARKER,
    get_listed_dependencies,
    get_out_of_date_files,
    print_story_files,
)
from tests.test_build_state_ladder import (
    ORIGINAL_TIME,
    PAGES,
    RESTORED_TIME,
    UPSCAYLED_TIME,
    Title,
)

DEST_TIME = 700.0


def stage(tmp_path: Path, tree: str, timestamp: float) -> SrceDependency:
    return SrceDependency(tmp_path / tree / "227.png", timestamp, independent=False)


def independent(tmp_path: Path, name: str, timestamp: float) -> SrceDependency:
    return SrceDependency(tmp_path / name, timestamp, independent=True)


def marked(
    tmp_path: Path,
    dependencies: list[SrceDependency],
    dest_timestamp: float = DEST_TIME,
    *,
    is_a_comic: bool = True,
) -> set[str]:
    """Return the marked files, each named by its tree or, for a loose file, its name."""
    out_of_date = get_out_of_date_files(
        dependencies,
        tmp_path / "dest" / "1-01.jpg",
        dest_timestamp,
        tmp_path / "title.ini",
        is_a_comic=is_a_comic,
    )

    return {
        file.name if file.parent == tmp_path else file.parent.name
        for file in out_of_date
        if isinstance(file, Path)
    }


def body_page(tmp_path: Path, **timestamps: float) -> list[SrceDependency]:
    """Return a body page's chain, latest stage first, with any stage's time overridden."""
    times = {
        "segments": 600.0,
        "restored": 500.0,
        "restored_4x": 400.0,
        "svg": 300.0,
        "upscayled": 200.0,
        "original": 100.0,
    } | timestamps

    return [stage(tmp_path, tree, timestamp) for tree, timestamp in times.items()]


def test_a_page_in_order_has_nothing_marked(tmp_path: Path) -> None:
    assert marked(tmp_path, body_page(tmp_path)) == set()


def test_a_stage_newer_than_the_one_made_from_it_is_marked(tmp_path: Path) -> None:
    assert marked(tmp_path, body_page(tmp_path, upscayled=450.0)) == {"upscayled"}


def test_a_source_newer_than_the_built_page_is_marked(tmp_path: Path) -> None:
    assert marked(tmp_path, body_page(tmp_path, segments=800.0)) == {"segments"}


def test_a_missing_stage_is_marked_and_the_one_after_it_is_not(tmp_path: Path) -> None:
    # The row after a missing stage used to be compared with the -1 that stands for it.
    assert marked(tmp_path, body_page(tmp_path, restored_4x=NOT_ON_DISK)) == {"restored_4x"}


def test_a_page_not_built_yet_marks_nothing_that_is_in_order(tmp_path: Path) -> None:
    # Restored and waiting for its build: there is no dest page for anything to outrun.
    assert marked(tmp_path, body_page(tmp_path), dest_timestamp=NOT_ON_DISK) == set()


def test_a_page_not_built_yet_still_has_its_own_chain_graded(tmp_path: Path) -> None:
    page = body_page(tmp_path, upscayled=450.0)

    assert marked(tmp_path, page, dest_timestamp=NOT_ON_DISK) == {"upscayled"}


class TestATitlePage:
    def title_page(self, tmp_path: Path, inset_time: float) -> list[SrceDependency]:
        # The ini file is git-tracked: its time is the last checkout's, long after the build.
        return [
            independent(tmp_path, "title.ini", 9000.0),
            independent(tmp_path, "inset.png", inset_time),
        ]

    def test_the_ini_files_checkout_time_marks_nothing(self, tmp_path: Path) -> None:
        assert marked(tmp_path, self.title_page(tmp_path, inset_time=650.0)) == set()

    def test_an_inset_older_than_the_ini_file_is_not_marked_for_it(self, tmp_path: Path) -> None:
        # What the row-above comparison got wrong: 650 is not newer than 9000.
        assert "inset.png" not in marked(tmp_path, self.title_page(tmp_path, inset_time=650.0))

    def test_an_inset_redrawn_since_the_build_is_marked(self, tmp_path: Path) -> None:
        assert marked(tmp_path, self.title_page(tmp_path, inset_time=800.0)) == {"inset.png"}

    def test_an_inset_is_not_marked_against_a_page_that_is_not_built(self, tmp_path: Path) -> None:
        page = self.title_page(tmp_path, inset_time=800.0)

        assert marked(tmp_path, page, dest_timestamp=NOT_ON_DISK) == set()


def test_a_bounds_fix_is_compared_with_the_page_and_not_with_the_row_above(
    tmp_path: Path,
) -> None:
    # Newer than the restored page listed after it, older than the built page: in order.
    page = body_page(tmp_path)
    page.insert(1, independent(tmp_path, "bounds.jpg", 650.0))

    assert marked(tmp_path, page) == set()


def test_a_page_of_a_title_that_is_not_a_comic_has_no_chain_to_mark(tmp_path: Path) -> None:
    page = body_page(tmp_path, upscayled=450.0)

    assert marked(tmp_path, page, is_a_comic=False) == set()


class TestListingAWholeTitle:
    """A real comic over a temporary directory, listed as the tool lists it."""

    @pytest.fixture
    def title(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Title:
        """Make a title page and two body pages, with nothing on disk but the ini file."""
        # Where a built comic's pages live is fixed by constants that point into the library.
        monkeypatch.setattr(ComicBook, "get_dest_image_dir", lambda _self: tmp_path / "built")

        return Title(
            tmp_path,
            [(TITLE_EMPTY_FILENAME, PageType.TITLE), *((page, PageType.BODY) for page in PAGES)],
        )

    @staticmethod
    def listed(title: Title, page: str) -> dict[Path, float]:
        """Return the files listed under a body page, and the time each is listed with."""
        srce_pages = get_sorted_srce_and_dest_pages(title.comic, get_full_paths=False).srce_pages
        srce_page = next(p for p in srce_pages if p.page_num == int(page))

        return {
            Path(str(dependency.file)): dependency.timestamp
            for dependency in get_listed_dependencies(title.comic, srce_page)
        }

    def test_a_restored_page_lists_what_the_pipeline_reports(self, title: Title) -> None:
        title.bring_to(RESTORED_FLAG)

        listed = self.listed(title, PAGES[0])

        assert listed[title.restored(PAGES[0])] == RESTORED_TIME
        assert listed[title.upscayled(PAGES[0])] == UPSCAYLED_TIME
        assert listed[title.original(PAGES[0])] == ORIGINAL_TIME

    def test_a_page_that_is_not_restored_yet_is_listed_as_missing(self, title: Title) -> None:
        title.bring_to(RESTORED_FLAG)
        title.restored(PAGES[1]).unlink()

        listed = self.listed(title, PAGES[1])

        assert next(iter(listed)) == title.restored(PAGES[1]), "the gap is the first row"
        assert listed[title.restored(PAGES[1])] == NOT_ON_DISK
        # The stages under the gap are listed as ever.
        assert listed[title.upscayled(PAGES[1])] == UPSCAYLED_TIME
        assert listed[title.original(PAGES[1])] == ORIGINAL_TIME

    def test_a_title_part_way_through_restoring_is_printed_to_its_last_page(
        self, title: Title, capsys: pytest.CaptureFixture[str]
    ) -> None:
        title.bring_to(RESTORED_FLAG)
        title.restored(PAGES[0]).unlink()

        print_story_files(title.comic, mods=False)
        listing = capsys.readouterr().out

        missing_row = f'FILE MISSING          :{OUT_OF_DATE_MARKER}"{title.restored(PAGES[0])}"'
        assert missing_row in listing
        # The page after the gap is reached: this is the row of its built file.
        assert f'{title.root / "built" / "2-02.jpg"}"' in listing

    def test_a_title_with_nothing_restored_is_printed(
        self, title: Title, capsys: pytest.CaptureFixture[str]
    ) -> None:
        title.bring_to(UPSCAYLED_FLAG)

        print_story_files(title.comic, mods=False)
        listing = capsys.readouterr().out

        for page in PAGES:
            assert f'FILE MISSING          :{OUT_OF_DATE_MARKER}"{title.restored(page)}"' in listing

    def test_a_missing_scan_of_a_page_that_is_not_restored_is_listed(self, tmp_path: Path) -> None:
        # A cover is built from its scan, so the scan is the file that is missing.
        title = Title(tmp_path, [("001", PageType.COVER)])
        srce_page = get_sorted_srce_and_dest_pages(title.comic, get_full_paths=False).srce_pages[0]

        dependencies = get_listed_dependencies(title.comic, srce_page)

        assert [(d.file, d.timestamp) for d in dependencies] == [
            (title.original("001"), NOT_ON_DISK)
        ]
