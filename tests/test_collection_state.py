"""Tests for the build state of the two synthetic collections and their members.

The failure that matters is silent and one-directional: `is_built` gates on the
restore and panel-bounds rungs, which glob `RESTORABLE_PAGE_TYPES`. An all-`COVER`
title such as "All Covers" has no page in those types, so those globs come back
empty - and `all_files_exist([])` is False. A fully built collection then reports
as never built, and nothing in the report says why. So the no-restorable-pages
branch gets its own tests, in both directions.
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest
from barks_fantagraphics.barks_covers import BARKS_COVERS
from barks_fantagraphics.barks_titles import Titles
from barks_fantagraphics.comic_book_info import COVERS, ONE_PAGERS, is_one_pager_located

from barks_comic_building.query.build_state import (
    BUILD_STATE_FLAGS,
    CLEAN_CHAIN,
    CONFIGURED_FLAG,
    NOT_CONFIGURED_FLAG,
    all_files_exist,
    get_build_blocker,
    get_staged_link_stem,
    get_state_filter,
    has_restorable_pages,
    is_built,
)
from barks_comic_building.query.cover_info import (
    COVER_STATE_FLAGS,
    get_cover_problems,
    get_cover_row,
    get_short_issue_title,
    has_incomplete_submitted_date,
    has_issue_problem,
)
from barks_comic_building.query.fantagraphics_info import is_story_title
from barks_comic_building.query.one_pager_info import (
    ONE_PAGER_STATE_FLAGS,
    get_one_pager_problems,
)

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.comic_book import ComicBook


def touch(path: Path) -> Path:
    """Create an empty file, making its parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()

    return path


class FakeComic:
    """The files `is_built` decides a comic's state from.

    Stands in for a `ComicBook`: only the accessors `build_state` actually calls are
    implemented, so a test can build an all-`COVER` collection (no restorable pages)
    without a comics database or a real ini file.
    """

    def __init__(self, tmp_path: Path, *, restorable: bool) -> None:
        self.ini_file = tmp_path / "collection.ini"
        self._restored = [tmp_path / "restored" / "500.png"] if restorable else []
        self._segments = [tmp_path / "segments" / "500.json"] if restorable else []
        self._srce = [tmp_path / "fixes" / "500.jpg"]
        self._zip = tmp_path / "dest" / "collection.cbz"
        self._metadata = tmp_path / "dest" / "comic-metadata.json"
        self._series_symlink = tmp_path / "series" / "collection.cbz"
        self._year_symlink = tmp_path / "year" / "collection.cbz"

    def get_ini_title(self) -> str:
        return "Fake Collection"

    def get_srce_restored_story_files(self, _page_types: list[object]) -> list[Path]:
        return self._restored

    def get_srce_panel_segments_files(self, _page_types: list[object]) -> list[Path]:
        return self._segments

    def get_final_srce_story_files(self, _page_types: list[object]) -> list[tuple[Path, None]]:
        return [(f, None) for f in self._srce]

    def get_dest_comic_zip(self) -> Path:
        return self._zip

    def get_metadata_filepath(self) -> Path:
        return self._metadata

    def get_dest_series_comic_zip_symlink(self) -> Path:
        return self._series_symlink

    def get_dest_year_comic_zip_symlink(self) -> Path:
        return self._year_symlink

    def stage_sources(self) -> None:
        for f in self._srce:
            touch(f)

    def restore_pages(self) -> None:
        for f in self._restored:
            touch(f)

    def write_panel_segments(self) -> None:
        for f in self._segments:
            touch(f)

    def build_dest(self) -> None:
        touch(self._zip)
        # Written by every build and by nothing else, which is what makes it the thing
        # the build state is dated by.
        touch(self._metadata)
        self._series_symlink.parent.mkdir(parents=True, exist_ok=True)
        self._series_symlink.symlink_to(self._zip)
        self._year_symlink.parent.mkdir(parents=True, exist_ok=True)
        self._year_symlink.symlink_to(self._zip)


def as_comic(fake: FakeComic) -> ComicBook:
    """Present a `FakeComic` as the `ComicBook` the predicates are typed against."""
    return cast("ComicBook", fake)


@pytest.fixture
def covers_collection(tmp_path: Path) -> FakeComic:
    """Make an all-COVER collection: no page of it ever gets restored or panel-bounded."""
    return FakeComic(tmp_path, restorable=False)


class TestAllFilesExist:
    def test_empty_list_is_not_satisfied(self) -> None:
        # This is what makes the no-restorable-pages branch necessary.
        assert not all_files_exist([])


class TestHasRestorablePages:
    def test_all_cover_collection_has_none(self, covers_collection: FakeComic) -> None:
        assert not has_restorable_pages(as_comic(covers_collection))

    def test_ordinary_title_has_some(self, tmp_path: Path) -> None:
        assert has_restorable_pages(as_comic(FakeComic(tmp_path, restorable=True)))


class TestAllCoverCollectionIsBuilt:
    def test_unstaged_and_unbuilt_is_not_built(self, covers_collection: FakeComic) -> None:
        assert not is_built(as_comic(covers_collection))

    def test_staged_but_not_built_is_not_built(self, covers_collection: FakeComic) -> None:
        covers_collection.stage_sources()

        assert not is_built(as_comic(covers_collection))

    def test_built_without_staged_sources_is_not_built(self, covers_collection: FakeComic) -> None:
        covers_collection.build_dest()

        assert not is_built(as_comic(covers_collection))

    def test_staged_and_built_is_built(self, covers_collection: FakeComic) -> None:
        covers_collection.stage_sources()
        covers_collection.build_dest()

        assert is_built(as_comic(covers_collection))

    def test_zip_older_than_its_sources_is_not_built(self, covers_collection: FakeComic) -> None:
        covers_collection.stage_sources()
        covers_collection.build_dest()
        zip_file = covers_collection.get_dest_comic_zip()
        srce_timestamp = covers_collection.get_final_srce_story_files([])[0][0].stat().st_mtime
        os.utime(zip_file, (srce_timestamp - 100, srce_timestamp - 100))

        assert not is_built(as_comic(covers_collection))

    def test_missing_year_symlink_is_not_built(self, covers_collection: FakeComic) -> None:
        # The year symlink used to be checked against its own presence but timed
        # against the series symlink, so this case needs its own test.
        covers_collection.stage_sources()
        covers_collection.build_dest()
        covers_collection.get_dest_year_comic_zip_symlink().unlink()

        assert not is_built(as_comic(covers_collection))

    def test_missing_series_symlink_is_not_built(self, covers_collection: FakeComic) -> None:
        covers_collection.stage_sources()
        covers_collection.build_dest()
        covers_collection.get_dest_series_comic_zip_symlink().unlink()

        assert not is_built(as_comic(covers_collection))


class TestBuildBlocker:
    """A "NOT built" report has to be able to say which step is outstanding.

    The zip existing while the state reads NOT built is the confusing case - the
    blocker is what tells you it is the pages, not the archive.
    """

    def test_built_collection_has_no_blocker(self, covers_collection: FakeComic) -> None:
        covers_collection.stage_sources()
        covers_collection.build_dest()

        assert get_build_blocker(as_comic(covers_collection)) is None

    def test_unstaged_pages_are_named_as_the_blocker(self, covers_collection: FakeComic) -> None:
        assert get_build_blocker(as_comic(covers_collection)) == "1 of its 1 pages are not staged"

    def test_missing_zip_is_named_as_the_blocker(self, covers_collection: FakeComic) -> None:
        covers_collection.stage_sources()

        blocker = get_build_blocker(as_comic(covers_collection))

        assert blocker is not None
        assert blocker.startswith("there is no zip file")

    def test_a_build_older_than_its_sources_is_named_as_the_blocker(
        self, covers_collection: FakeComic
    ) -> None:
        # The zip and both symlinks are present and current; only the file a build
        # writes says when the build actually ran.
        covers_collection.stage_sources()
        covers_collection.build_dest()
        srce_timestamp = covers_collection.get_final_srce_story_files([])[0][0].stat().st_mtime
        metadata_file = covers_collection.get_metadata_filepath()
        os.utime(metadata_file, (srce_timestamp - 100, srce_timestamp - 100))

        assert get_build_blocker(as_comic(covers_collection)) == (
            "the build is older than its staged source images"
        )

    def test_a_build_with_no_metadata_file_is_named_as_the_blocker(
        self, covers_collection: FakeComic
    ) -> None:
        covers_collection.stage_sources()
        covers_collection.build_dest()
        covers_collection.get_metadata_filepath().unlink()

        blocker = get_build_blocker(as_comic(covers_collection))

        assert blocker is not None
        assert blocker.startswith("there is no build metadata file")

    def test_unrestored_pages_are_named_as_the_blocker(self, tmp_path: Path) -> None:
        comic = FakeComic(tmp_path, restorable=True)
        comic.stage_sources()
        comic.build_dest()

        assert (
            get_build_blocker(as_comic(comic), CLEAN_CHAIN) == "1 of its 1 pages are not restored"
        )

    def test_missing_panel_segments_are_named_as_the_blocker(self, tmp_path: Path) -> None:
        comic = FakeComic(tmp_path, restorable=True)
        comic.stage_sources()
        comic.restore_pages()
        comic.build_dest()

        assert (
            get_build_blocker(as_comic(comic), CLEAN_CHAIN)
            == "1 of its 1 pages have no panel segments file"
        )

    def test_a_zip_that_exists_still_blocks_on_its_pages(self, tmp_path: Path) -> None:
        # The case that prompted the message: the .cbz is right there on disk, but
        # the collection is still not built because its pages are not all restored.
        comic = FakeComic(tmp_path, restorable=True)
        comic.stage_sources()
        comic.build_dest()

        assert comic.get_dest_comic_zip().is_file()
        blocker = get_build_blocker(as_comic(comic), CLEAN_CHAIN)
        assert blocker is not None
        assert "zip" not in blocker

    def test_is_built_is_the_blockers_verdict(self, tmp_path: Path) -> None:
        # The two must never disagree, so is_built is defined in terms of the blocker.
        comic = FakeComic(tmp_path, restorable=True)
        for step in (comic.stage_sources, comic.restore_pages, comic.write_panel_segments):
            assert is_built(as_comic(comic), CLEAN_CHAIN) is (
                get_build_blocker(as_comic(comic), CLEAN_CHAIN) is None
            )
            step()
        comic.build_dest()

        assert is_built(as_comic(comic), CLEAN_CHAIN)
        assert get_build_blocker(as_comic(comic), CLEAN_CHAIN) is None


class TestCoverIssueProblem:
    """A cover whose issue data is incomplete gets its Issue cell flagged.

    The warning has to be a cell style, not a row style: every cover with a bad
    issue today is also unlocated, so a row-level warning would be invisible under
    the not-done colour.
    """

    def test_a_fully_identified_cover_is_not_flagged(self) -> None:
        cover = next(c for c in BARKS_COVERS if c.issue_name is not None)

        assert not has_issue_problem(cover)

    def test_a_cover_with_no_issues_member_is_flagged(self) -> None:
        cover = next(c for c in BARKS_COVERS if c.issue_name is None)

        assert has_issue_problem(cover)

    def test_every_flagged_cover_falls_back_to_its_series_name(self) -> None:
        # The flag and the fallback have to agree: whatever is flagged is exactly
        # what get_short_issue_title could not name properly.
        for cover in BARKS_COVERS:
            if cover.issue_name is None:
                assert has_issue_problem(cover)
                assert get_short_issue_title(cover).startswith(
                    " ".join(w.capitalize() for w in cover.series_name.split())
                )

    def test_the_flag_reaches_the_row(self) -> None:
        # Built per cover rather than via get_cover_rows so the check needs no
        # ComicsDatabase - the row itself is what carries the flag to the table.
        rows = [get_cover_row(cover, None) for cover in BARKS_COVERS]
        flagged = [r for r in rows if r.has_issue_problem]

        assert len(flagged) == sum(1 for c in BARKS_COVERS if has_issue_problem(c))
        assert flagged, "expected at least one cover with incomplete issue data"

    def test_an_unnumbered_or_undated_cover_is_flagged(self) -> None:
        # None exist yet, so build them from a real record to prove the rule holds
        # when such a cover is first authored.
        good = next(c for c in BARKS_COVERS if not has_issue_problem(c))

        assert has_issue_problem(replace(good, issue_number=-1))
        assert has_issue_problem(replace(good, issue_month=-1))
        assert has_issue_problem(replace(good, issue_year=-1))
        assert not has_issue_problem(good)


class TestProblemCodes:
    """The Problem column exists because the ladder stops at its first unmet rung.

    A one-pager with no payment value reports `C` however much of its restore work
    is done, so anything actionable has to be reported independently of the ladder
    or it stays invisible.
    """

    @staticmethod
    def _links(tmp_path: Path, names: list[str]) -> list[tuple[Path, Path]]:
        source = touch(tmp_path / "srce.jpg")
        return [(tmp_path / "staged" / name, source) for name in names]

    def test_missing_staged_artifacts_are_counted(self, tmp_path: Path) -> None:
        links = self._links(tmp_path, ["500.jpg", "500.png", "500.svg"])

        problems = get_one_pager_problems(ONE_PAGERS[0], links)

        assert "link(3)" in problems

    def test_a_copied_artifact_is_reported_separately(self, tmp_path: Path) -> None:
        links = self._links(tmp_path, ["500.jpg", "500.png"])
        touch(links[0][0])  # a real file, not a symlink
        links[1][0].parent.mkdir(parents=True, exist_ok=True)
        links[1][0].symlink_to(links[1][1])

        problems = get_one_pager_problems(ONE_PAGERS[0], links)

        assert "copy(1)" in problems
        assert not any(p.startswith("link") for p in problems)

    def test_a_stage_that_has_not_been_run_is_not_a_link_problem(self, tmp_path: Path) -> None:
        # Nothing to link: the one-pager's own volume has no such artifact either, so
        # this is outstanding work, which the State ladder reports, not a fault.
        absent_source = tmp_path / "never-made.svg"

        problems = get_one_pager_problems(ONE_PAGERS[0], [(tmp_path / "500.svg", absent_source)])

        assert not any(p.startswith("link") for p in problems)

    def test_an_artifact_produced_in_the_collection_is_not_a_copy(self, tmp_path: Path) -> None:
        # Running the pipeline on the collection itself (barks-batch-upscayl --title
        # "All One-Pagers") writes a real file for a stage the one-pager's own volume
        # never had. There is no upstream file to have diverged from, so it is normal
        # output, not an anomaly - every one of the 44 real files on disk is this case.
        absent_source = tmp_path / "never-made.png"
        link = touch(tmp_path / "staged" / "500.png")

        problems = get_one_pager_problems(ONE_PAGERS[0], [(link, absent_source)])

        assert not any(p.startswith("copy") for p in problems)

    def test_fully_symlinked_staging_reports_neither(self, tmp_path: Path) -> None:
        links = self._links(tmp_path, ["500.jpg", "500.png"])
        for link, source in links:
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(source)

        problems = get_one_pager_problems(ONE_PAGERS[0], links)

        assert not any(p.startswith(("link", "copy")) for p in problems)

    def test_an_unlocated_one_pager_reports_no_staging_or_page_problem(self) -> None:
        # Its `X` state already says the location table is the thing to fill in, so
        # repeating that as problem codes would be noise on all 27 unlocated rows.
        unlocated = next(t for t in ONE_PAGERS if not is_one_pager_located(t))

        problems = get_one_pager_problems(unlocated, None)

        assert not any(p.startswith(("link", "copy")) for p in problems)
        assert "page" not in problems

    def test_covers_do_not_report_copied_staging(self, tmp_path: Path) -> None:
        # `barks-stage-covers --copy` is a supported mode, so a real file is fine.
        cover = next(c for c in BARKS_COVERS if not has_incomplete_submitted_date(c))
        source = touch(tmp_path / "srce.jpg")
        link = touch(tmp_path / "staged" / "500.jpg")

        assert get_cover_problems(cover, [(link, source)]) == []

    def test_a_cover_missing_its_staged_jpg_reports_link(self, tmp_path: Path) -> None:
        cover = next(c for c in BARKS_COVERS if not has_incomplete_submitted_date(c))
        source = touch(tmp_path / "srce.jpg")

        problems = get_cover_problems(cover, [(tmp_path / "staged" / "500.jpg", source)])

        assert problems == ["link"]

    def test_a_cover_missing_only_its_upscayled_png_is_clean(self, tmp_path: Path) -> None:
        # Every located cover is in this state and builds fine, so it is not a problem.
        cover = next(c for c in BARKS_COVERS if not has_incomplete_submitted_date(c))
        source = touch(tmp_path / "srce.jpg")
        jpg = touch(tmp_path / "staged" / "500.jpg")

        problems = get_cover_problems(cover, [(jpg, source), (tmp_path / "up" / "500.png", source)])

        assert problems == []

    def test_an_incomplete_submitted_date_is_reported(self) -> None:
        cover = next(c for c in BARKS_COVERS if not has_incomplete_submitted_date(c))

        assert has_incomplete_submitted_date(replace(cover, submitted_day=-1))
        assert has_incomplete_submitted_date(replace(cover, submitted_month=-1))
        assert has_incomplete_submitted_date(replace(cover, submitted_year=-1))
        assert not has_incomplete_submitted_date(cover)


class TestStagedLinkStem:
    def test_no_links_gives_no_stem(self) -> None:
        assert get_staged_link_stem(None) == ""
        assert get_staged_link_stem([]) == ""

    def test_the_shared_collection_page_is_returned(self, tmp_path: Path) -> None:
        source = tmp_path / "srce.jpg"
        links = [(tmp_path / name, source) for name in ("500.jpg", "500.png", "500.json")]

        assert get_staged_link_stem(links) == "500"

    def test_a_double_suffix_link_does_not_leak_into_the_stem(self, tmp_path: Path) -> None:
        # Path.stem would give "500.svg" here, which is why the first dot is used.
        source = tmp_path / "srce.svg"
        links = [(tmp_path / "500.svg.png", source)]

        assert get_staged_link_stem(links) == "500"


class TestStateFilter:
    def test_empty_arg_keeps_every_flag(self) -> None:
        assert get_state_filter("", COVER_STATE_FLAGS) == COVER_STATE_FLAGS

    def test_comma_separated_arg_is_split(self) -> None:
        assert get_state_filter("X,C", COVER_STATE_FLAGS) == [NOT_CONFIGURED_FLAG, CONFIGURED_FLAG]

    def test_flag_the_report_cannot_produce_is_rejected(self) -> None:
        # 'R' is a valid one-pager state but meaningless for covers.
        with pytest.raises(RuntimeError, match="Not a valid state filter"):
            get_state_filter("R", COVER_STATE_FLAGS)


class TestReportLadders:
    def test_cover_ladder_is_a_subset_of_the_shared_flags(self) -> None:
        assert set(COVER_STATE_FLAGS).issubset(set(BUILD_STATE_FLAGS))

    def test_one_pager_ladder_is_a_subset_of_the_shared_flags(self) -> None:
        assert set(ONE_PAGER_STATE_FLAGS).issubset(set(BUILD_STATE_FLAGS))

    def test_both_ladders_start_at_missing(self) -> None:
        assert COVER_STATE_FLAGS[0] == NOT_CONFIGURED_FLAG
        assert ONE_PAGER_STATE_FLAGS[0] == NOT_CONFIGURED_FLAG


class TestIsStoryTitle:
    def test_one_pager_is_not_a_story(self) -> None:
        assert not is_story_title(ONE_PAGERS[0])

    def test_cover_is_not_a_story(self) -> None:
        assert not is_story_title(COVERS[0])

    def test_collections_are_not_stories(self) -> None:
        assert not is_story_title(Titles.ALL_ONE_PAGERS)
        assert not is_story_title(Titles.ALL_COVERS)

    def test_a_real_story_is_a_story(self) -> None:
        assert is_story_title(Titles.DONALD_DUCK_FINDS_PIRATE_GOLD)
