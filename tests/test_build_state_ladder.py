"""Tests for the build-state ladder, run over a real comic with real file timestamps.

`get_chain_state` decides every flag `barks-fanta-info` prints, and until now no test ran
it: `test_restore_chain_state.py` grades hand-made dependency lists through a helper that
restates its per-page glue, and `test_collection_state.py` hands every rung a ready-made
`CLEAN_CHAIN`. The glue is where it has gone wrong. A stale keyword argument made every
title grade clean for days, and resolving each page's full path made a title grade clean
in the one state the upscayl rung is decided in - upscayled, and not yet restored.

So nothing here is a stand-in for the comic. A real `ComicBook` is pointed at a temporary
directory, and the page lists, the fixes rules and the dependency chain are the shipped
ones. Only where the built comic lives is redirected, because those paths are module
constants that point into the library.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

import pytest
from barks_fantagraphics.barks_titles import Titles
from barks_fantagraphics.comic_book import ComicBook, ComicBookDirs
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES, PageType
from barks_fantagraphics.fanta_comics_info import ALL_FANTA_COMIC_BOOK_INFO, FantaBook
from barks_fantagraphics.page_classes import OriginalPage
from barks_fantagraphics.pages import TITLE_EMPTY_FILENAME

from barks_comic_building.query import build_state as bs
from barks_comic_building.query import fantagraphics_info
from barks_comic_building.query.build_state import (
    BUILT_FLAG,
    CLEAN_CHAIN,
    CONFIGURED_FLAG,
    FAULT_FLAG,
    INSET_FLAG,
    PANELLED_FLAG,
    RESTORED_FLAG,
    UPSCAYLED_FLAG,
    get_build_blocker,
    get_build_state_flag,
    get_chain_state,
    get_title_state,
    has_fixes,
)

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.comics_database import ComicsDatabase

TITLE = "Lost in the Andes!"
VOLUME = 7
# Two body pages of volume 7 that are in no special-case list.
PAGES = ["050", "051"]

# When each stage of a page was made, in pipeline order. A stage made from the one before
# it is newer than it, so a chain in order has these increasing.
ORIGINAL_TIME = 1_700_000_100
UPSCAYLED_TIME = 1_700_000_200
SVG_TIME = 1_700_000_300
RESTORED_4X_TIME = 1_700_000_400
RESTORED_TIME = 1_700_000_500
SEGMENTS_TIME = 1_700_000_600
INSET_TIME = 1_700_000_650
BUILD_TIME = 1_700_000_700
# Later than everything above: something redone after the rest was finished.
REDONE_TIME = 1_700_000_900
# The ini file is git-tracked, so its time is the latest checkout's and newer than all.
CHECKOUT_TIME = 1_700_009_000


def write(path: Path, timestamp: float) -> Path:
    """Create a file dated `timestamp`, or re-date the one that is there."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    os.utime(path, (timestamp, timestamp))

    return path


def link(symlink: Path, target: Path, timestamp: float) -> None:
    symlink.parent.mkdir(parents=True, exist_ok=True)
    symlink.symlink_to(target)
    os.utime(symlink, (timestamp, timestamp), follow_symlinks=False)


class Title:
    """A real comic over a temporary directory, and the steps that bring it up the ladder."""

    def __init__(self, root: Path, page_types: list[tuple[str, PageType]]) -> None:
        self.root = root
        pages = [OriginalPage(filename, page_type) for filename, page_type in page_types]
        self.comic = ComicBook(
            ini_file=write(root / "ini" / f"{TITLE}.ini", CHECKOUT_TIME),
            title=TITLE,
            title_font_file=root / "fonts" / "title.ttf",
            title_font_size=155,
            title_color=(214, 48, 39),
            byline="by",
            issue_title="",
            author_font_size=90,
            srce_dir_num_page_files=len(pages),
            dirs=ComicBookDirs(
                srce_dir=root / "original",
                srce_upscayled_dir=root / "upscayled",
                srce_restored_dir=root / "restored",
                srce_restored_upscayled_dir=root / "restored-upscayled",
                srce_restored_svg_dir=root / "restored-svg",
                srce_restored_ocr_raw_dir=root / "ocr-raw",
                srce_restored_ocr_prelim_dir=root / "ocr-prelim",
                srce_restored_ocr_annotations_dir=root / "ocr-annotations",
                srce_fixes_dir=root / "fixes",
                srce_upscayled_fixes_dir=root / "upscayled-fixes",
                panel_segments_dir=root / "panel-segments",
            ),
            intro_inset_file=root / "insets" / f"{TITLE}.png",
            config_page_images=pages,
            page_images_in_order=pages,
            publication_date="April 1949",
            submitted_date="October 21, 1948",
            publication_text="",
            extra_pub_info="",
            fanta_book=FantaBook("Carl Barks Vol 07", "Fantagraphics", VOLUME, 2011, 240),
            fanta_info=ALL_FANTA_COMIC_BOOK_INFO[Titles.LOST_IN_THE_ANDES],
            solo_page_keys=frozenset(),
        )

    # ---- where things are

    def original(self, page: str) -> Path:
        return self.comic.get_srce_original_story_file(page)

    def upscayled(self, page: str) -> Path:
        return self.comic.get_srce_upscayled_story_file(page)

    def upscayled_fix(self, page: str) -> Path:
        return self.comic.get_srce_upscayled_fixes_story_file(page)

    def restored(self, page: str) -> Path:
        return self.comic.get_srce_restored_image_dir() / f"{page}.png"

    def segments(self, page: str) -> Path:
        return self.comic.get_srce_panel_segments_file(page)

    @property
    def inset(self) -> Path:
        return cast("Path", self.comic.intro_inset_file)

    @property
    def zip_file(self) -> Path:
        return self.root / "dest" / "comic.cbz"

    @property
    def metadata(self) -> Path:
        return self.root / "dest" / "comic-metadata.json"

    @property
    def series_symlink(self) -> Path:
        return self.root / "series" / "comic.cbz"

    @property
    def year_symlink(self) -> Path:
        return self.root / "year" / "comic.cbz"

    # ---- the steps of the workflow, each leaving its files dated as that step would

    def scan(self) -> None:
        for page in PAGES:
            write(self.original(page), ORIGINAL_TIME)

    def upscayl(self) -> None:
        for page in PAGES:
            write(self.upscayled(page), UPSCAYLED_TIME)

    def restore(self) -> None:
        for page in PAGES:
            write(self.comic.get_srce_restored_svg_story_file(page), SVG_TIME)
            write(self.comic.get_srce_restored_upscayled_story_file(page), RESTORED_4X_TIME)
            write(self.restored(page), RESTORED_TIME)

    def bound_panels(self) -> None:
        for page in PAGES:
            write(self.segments(page), SEGMENTS_TIME)

    def draw_inset(self) -> None:
        write(self.inset, INSET_TIME)

    def build(self) -> None:
        write(self.metadata, BUILD_TIME)
        write(self.zip_file, BUILD_TIME)
        link(self.series_symlink, self.zip_file, BUILD_TIME)
        link(self.year_symlink, self.zip_file, BUILD_TIME)

    def bring_to(self, flag: str) -> Title:
        """Run the workflow up to and including the step that earns `flag`."""
        steps = {
            CONFIGURED_FLAG: self.scan,
            UPSCAYLED_FLAG: self.upscayl,
            RESTORED_FLAG: self.restore,
            PANELLED_FLAG: self.bound_panels,
            INSET_FLAG: self.draw_inset,
            BUILT_FLAG: self.build,
        }
        for step_flag, step in steps.items():
            step()
            if step_flag == flag:
                break

        return self


@pytest.fixture
def title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Title:
    """Make a title page and two body pages, with nothing on disk but the ini file."""
    a_title = Title(
        tmp_path,
        [(TITLE_EMPTY_FILENAME, PageType.TITLE), *((page, PageType.BODY) for page in PAGES)],
    )

    # Where a built comic lives is fixed by module constants that point into the library.
    monkeypatch.setattr(ComicBook, "get_dest_comic_zip", lambda _self: a_title.zip_file)
    monkeypatch.setattr(ComicBook, "get_metadata_filepath", lambda _self: a_title.metadata)
    monkeypatch.setattr(
        ComicBook, "get_dest_series_comic_zip_symlink", lambda _self: a_title.series_symlink
    )
    monkeypatch.setattr(
        ComicBook, "get_dest_year_comic_zip_symlink", lambda _self: a_title.year_symlink
    )

    return a_title


class TestTheLadder:
    @pytest.mark.parametrize(
        "flag",
        [CONFIGURED_FLAG, UPSCAYLED_FLAG, RESTORED_FLAG, PANELLED_FLAG, INSET_FLAG, BUILT_FLAG],
    )
    def test_each_step_of_the_workflow_earns_its_flag(self, title: Title, flag: str) -> None:
        assert get_build_state_flag(title.bring_to(flag).comic) == flag

    def test_an_inset_drawn_before_the_panels_are_bounded_does_not_skip_a_rung(
        self, title: Title
    ) -> None:
        title.bring_to(RESTORED_FLAG).draw_inset()

        assert get_build_state_flag(title.comic) == RESTORED_FLAG

    def test_a_rescanned_page_takes_a_built_title_back_to_the_start(self, title: Title) -> None:
        # Strict: every later stage was made from an upscayl that is now out of date.
        title.bring_to(BUILT_FLAG)
        write(title.original(PAGES[0]), REDONE_TIME)

        assert get_build_state_flag(title.comic) == CONFIGURED_FLAG

    def test_a_redone_upscayl_takes_a_built_title_back_to_upscayled(self, title: Title) -> None:
        title.bring_to(BUILT_FLAG)
        write(title.upscayled(PAGES[0]), REDONE_TIME)

        assert get_build_state_flag(title.comic) == UPSCAYLED_FLAG

    def test_a_redone_restore_takes_a_built_title_back_to_restored(self, title: Title) -> None:
        title.bring_to(BUILT_FLAG)
        write(title.restored(PAGES[0]), REDONE_TIME)

        assert get_build_state_flag(title.comic) == RESTORED_FLAG

    def test_rebounded_panels_leave_a_title_waiting_only_for_its_build(self, title: Title) -> None:
        title.bring_to(BUILT_FLAG)
        write(title.segments(PAGES[0]), REDONE_TIME)

        assert get_build_state_flag(title.comic) == INSET_FLAG

    def test_a_redrawn_inset_leaves_a_title_waiting_only_for_its_build(self, title: Title) -> None:
        title.bring_to(BUILT_FLAG)
        write(title.inset, REDONE_TIME)

        assert get_build_state_flag(title.comic) == INSET_FLAG

    def test_a_checkout_that_bumps_the_ini_file_does_not_unbuild_a_title(
        self, title: Title
    ) -> None:
        # The fixture's ini file is already dated after everything else.
        assert title.comic.ini_file.stat().st_mtime > BUILD_TIME

        assert get_build_state_flag(title.bring_to(BUILT_FLAG).comic) == BUILT_FLAG


class TestTheChainOfAWholeTitle:
    def test_a_title_in_order_has_every_page_graded_and_none_stale(self, title: Title) -> None:
        chain = get_chain_state(title.bring_to(PANELLED_FLAG).comic)

        assert (chain.stale_upscayl_pages, chain.stale_restore_pages, chain.total_pages) == (
            0,
            0,
            len(PAGES),
        )

    def test_the_newest_source_is_the_last_thing_made(self, title: Title) -> None:
        chain = get_chain_state(title.bring_to(PANELLED_FLAG).comic)

        assert chain.max_srce is not None
        assert chain.max_srce.timestamp == SEGMENTS_TIME

    def test_the_inset_counts_as_a_source_though_it_is_in_no_chain(self, title: Title) -> None:
        chain = get_chain_state(title.bring_to(INSET_FLAG).comic)

        assert chain.max_srce is not None
        assert chain.max_srce.file == title.inset

    def test_stale_pages_are_counted_one_per_page_and_per_rung(self, title: Title) -> None:
        title.bring_to(PANELLED_FLAG)
        write(title.original(PAGES[0]), REDONE_TIME)
        write(title.original(PAGES[1]), REDONE_TIME)

        chain = get_chain_state(title.comic)

        assert (chain.stale_upscayl_pages, chain.stale_restore_pages) == (len(PAGES), 0)

    def test_a_title_with_no_restorable_page_has_nothing_to_grade(self, tmp_path: Path) -> None:
        covers = Title(tmp_path, [("050", PageType.COVER)])
        write(covers.original("050"), ORIGINAL_TIME)

        assert get_chain_state(covers.comic) is CLEAN_CHAIN


class TestATitleThatIsNotRestoredYet:
    """The state the upscayl rung is decided in, which used to grade clean whatever it held."""

    def test_its_upscayled_pages_are_still_graded(self, title: Title) -> None:
        chain = get_chain_state(title.bring_to(UPSCAYLED_FLAG).comic)

        assert (chain.stale_upscayl_pages, chain.total_pages) == (0, len(PAGES))

    def test_a_page_rescanned_since_the_upscayl_is_seen(self, title: Title) -> None:
        title.bring_to(UPSCAYLED_FLAG)
        write(title.original(PAGES[0]), REDONE_TIME)

        assert get_chain_state(title.comic).stale_upscayl_pages == 1
        assert get_build_state_flag(title.comic) == CONFIGURED_FLAG

    def test_a_rescanned_page_is_seen_on_a_title_only_partly_restored(self, title: Title) -> None:
        title.bring_to(RESTORED_FLAG)
        title.restored(PAGES[0]).unlink()
        write(title.original(PAGES[0]), REDONE_TIME)

        assert get_chain_state(title.comic).stale_upscayl_pages == 1
        assert get_build_state_flag(title.comic) == CONFIGURED_FLAG

    def test_the_missing_restore_is_still_the_reason_it_is_not_built(self, title: Title) -> None:
        # Existence before staleness: a page that is not there is the thing to say.
        title.bring_to(UPSCAYLED_FLAG)
        write(title.original(PAGES[0]), REDONE_TIME)

        assert get_build_blocker(title.comic) == "2 of its 2 pages are not restored"

    def test_a_page_with_no_scan_at_all_is_nothing_to_grade(self, title: Title) -> None:
        assert get_chain_state(title.comic).total_pages == 0


class TestAPageListThatWillNotResolve:
    def test_an_unreadable_comic_grades_clean_instead_of_raising(
        self, title: Title, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def unreadable(_comic: ComicBook, *, get_full_paths: bool) -> None:  # noqa: ARG001
            msg = "Processing front matter but page type is incorrect"
            raise ValueError(msg)

        monkeypatch.setattr(bs, "get_sorted_srce_and_dest_pages", unreadable)

        assert get_chain_state(title.bring_to(RESTORED_FLAG).comic) is CLEAN_CHAIN

    def test_a_call_made_with_the_wrong_arguments_is_a_bug_and_is_raised(
        self, title: Title, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # What a removed keyword argument looks like from here. Caught and logged at
        # debug, it made every title grade clean for days.
        def takes_other_arguments(_comic: ComicBook, *, check_timestamps: bool) -> None:
            raise AssertionError(check_timestamps)

        monkeypatch.setattr(bs, "get_sorted_srce_and_dest_pages", takes_other_arguments)

        with pytest.raises(TypeError, match="get_full_paths"):
            get_chain_state(title.bring_to(RESTORED_FLAG).comic)

    def test_a_type_error_from_inside_the_call_is_only_an_unreadable_comic(
        self, title: Title, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def unreadable(_comic: ComicBook, *, get_full_paths: bool) -> None:  # noqa: ARG001
            msg = "int() argument must be a string"
            raise TypeError(msg)

        monkeypatch.setattr(bs, "get_sorted_srce_and_dest_pages", unreadable)

        assert get_chain_state(title.bring_to(RESTORED_FLAG).comic) is CLEAN_CHAIN


class TestTheReasonATitleIsNotBuilt:
    def test_a_built_title_has_none(self, title: Title) -> None:
        assert get_build_blocker(title.bring_to(BUILT_FLAG).comic) is None

    def test_a_rescanned_page_is_named_first(self, title: Title) -> None:
        # In ladder order: the restore made from the stale upscayl comes second.
        title.bring_to(BUILT_FLAG)
        write(title.original(PAGES[0]), REDONE_TIME)

        assert get_build_blocker(title.comic) == (
            "1 of its 2 pages have an upscayled file older than its original scan"
        )

    def test_a_redone_upscayl_is_a_restore_to_run_again(self, title: Title) -> None:
        title.bring_to(BUILT_FLAG)
        write(title.upscayled(PAGES[0]), REDONE_TIME)

        assert get_build_blocker(title.comic) == (
            "1 of its 2 pages have restored art older than its upscayled source"
        )

    def test_a_redone_restore_is_panels_to_bound_again(self, title: Title) -> None:
        title.bring_to(BUILT_FLAG)
        write(title.restored(PAGES[0]), REDONE_TIME)

        assert get_build_blocker(title.comic) == (
            "1 of its 2 panel segments files are older than their restored page"
        )

    def test_rebounded_panels_make_the_build_stale(self, title: Title) -> None:
        title.bring_to(BUILT_FLAG)
        write(title.segments(PAGES[0]), REDONE_TIME)

        assert get_build_blocker(title.comic) == "the build is older than its source files"

    def test_a_zip_remade_since_does_not_stand_in_for_a_build(self, title: Title) -> None:
        # The metadata file is written by a build and by nothing else; a zip gets remade.
        title.bring_to(BUILT_FLAG)
        write(title.segments(PAGES[0]), REDONE_TIME)
        write(title.zip_file, REDONE_TIME + 1)

        assert get_build_blocker(title.comic) == "the build is older than its source files"

    def test_a_zip_older_than_the_sources_is_named(self, title: Title) -> None:
        title.bring_to(BUILT_FLAG)
        write(title.zip_file, SEGMENTS_TIME - 1)

        assert get_build_blocker(title.comic) == "the zip file is older than its source files"

    def test_a_symlink_older_than_its_zip_is_named(self, title: Title) -> None:
        title.bring_to(BUILT_FLAG)
        write(title.zip_file, REDONE_TIME)

        assert get_build_blocker(title.comic) == "the series symlink is older than the zip file"

    def test_a_missing_symlink_is_named(self, title: Title) -> None:
        title.bring_to(BUILT_FLAG)
        title.year_symlink.unlink()

        blocker = get_build_blocker(title.comic)

        assert blocker is not None
        assert blocker.startswith("there is no year symlink")


class TestFixes:
    def test_a_title_with_only_scans_has_none(self, title: Title) -> None:
        assert not has_fixes(title.bring_to(UPSCAYLED_FLAG).comic)

    def test_an_edited_scan_is_a_fix(self, title: Title) -> None:
        title.bring_to(UPSCAYLED_FLAG)
        write(title.comic.get_srce_original_fixes_story_file(PAGES[0]), ORIGINAL_TIME)

        assert has_fixes(title.comic)

    def test_an_upscayled_fix_in_place_of_the_upscayled_file_is_a_fix(self, title: Title) -> None:
        title.bring_to(UPSCAYLED_FLAG)
        title.upscayled(PAGES[0]).unlink()
        write(title.upscayled_fix(PAGES[0]), UPSCAYLED_TIME)

        assert has_fixes(title.comic)
        assert get_build_state_flag(title.comic) == UPSCAYLED_FLAG


class TestATitleWhoseFilesBreakAFileRule:
    """One such page used to leave a traceback where the volume's table should be."""

    @pytest.fixture
    def faulty(self, title: Title) -> Title:
        # A page may have an upscayled file or an upscayled fix, never both.
        title.bring_to(RESTORED_FLAG)
        write(title.upscayled_fix(PAGES[0]), UPSCAYLED_TIME)

        return title

    def test_the_fault_is_the_titles_state(self, faulty: Title) -> None:
        state = get_title_state(faulty.comic)

        assert state.flag == FAULT_FLAG
        assert state.fault is not None
        assert "Cannot have an upscayled file and a fixes file" in state.fault

    def test_a_title_in_order_has_its_rung_and_no_fault(self, title: Title) -> None:
        state = get_title_state(title.bring_to(RESTORED_FLAG).comic)

        assert (state.flag, state.has_fixes, state.fault) == (RESTORED_FLAG, False, None)

    def test_the_fault_is_the_reason_it_is_not_built(self, faulty: Title) -> None:
        blocker = get_build_blocker(faulty.comic)

        assert blocker is not None
        assert blocker.startswith("its files cannot be graded - Cannot have an upscayled file")

    def test_the_fault_is_seen_on_a_page_that_is_not_restored_yet(self, title: Title) -> None:
        title.bring_to(UPSCAYLED_FLAG)
        write(title.upscayled_fix(PAGES[0]), UPSCAYLED_TIME)

        assert get_title_state(title.comic).flag == FAULT_FLAG

    def test_a_bug_is_not_passed_off_as_a_fault(
        self, title: Title, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # NotImplementedError is a RuntimeError too, and is nothing to do with the files.
        def unfinished(_comic: ComicBook) -> str:
            raise NotImplementedError

        monkeypatch.setattr(bs, "get_build_state_flag", unfinished)

        with pytest.raises(NotImplementedError):
            get_title_state(title.comic)

    def test_the_info_report_gives_the_title_a_row_instead_of_raising(self, faulty: Title) -> None:
        class OneTitleDatabase:
            def get_comic_book(self, _title: str) -> ComicBook:
                return faulty.comic

        fanta_info = ALL_FANTA_COMIC_BOOK_INFO[Titles.LOST_IN_THE_ANDES]

        title_flags = fantagraphics_info.get_title_flags(
            cast("ComicsDatabase", OneTitleDatabase()),
            [bs.EMPTY_FLAG, bs.FIXES_FLAG],
            bs.BUILD_STATE_FLAGS,
            [(TITLE, "FC 223", fanta_info, True)],
        )

        assert title_flags[TITLE].build_state_flag == FAULT_FLAG
        assert "Cannot have an upscayled file and a fixes file" in title_flags[TITLE].fault


def test_the_pages_under_test_are_ordinary_restorable_pages() -> None:
    # A special-case page is given no restore stages at all, so it would grade nothing.
    assert PageType.BODY in RESTORABLE_PAGE_TYPES
    assert not any(ComicBook.is_fixes_special_case_added(VOLUME, page) for page in PAGES)
    assert not any(ComicBook.is_fixes_special_case(VOLUME, page) for page in PAGES)
