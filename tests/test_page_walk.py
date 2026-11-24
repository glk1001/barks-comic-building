"""Tests for the one walk over a title's pages that each stage has.

A run and the report of what a run would do used to each walk a title's pages for
themselves, with the same loop written out twice per stage. Nothing made the copies agree,
and the report exists to be believed. These tests hold the walk itself to account, and
then check the thing the walk is for: that what a run queues is exactly what the report
counts as waiting.

The comic here is a stand-in that hands back lists of files, which is all the walk asks
of the real one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from barks_fantagraphics.comic_book import ModifiedType
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from barks_comic_building.restore import (
    batch_restore_pipeline,
    batch_upscayl,
    restore_status,
    upscale_status,
)
from barks_comic_building.restore.page_state import (
    RECIPE_ID_KEY,
    PageState,
    get_ink_mask_file,
    walk_restore_pages,
)
from barks_comic_building.restore.restore_recipe import get_current_recipe
from barks_comic_building.restore.upscale_image import DEFAULT_UPSCALER, LIBRARY_SCALE
from barks_comic_building.restore.upscale_recipe import (
    get_current_recipe as get_current_upscale_recipe,
)
from barks_comic_building.restore.upscale_state import RECIPE_ID_KEY as UPSCALE_RECIPE_ID_KEY
from barks_comic_building.restore.upscale_state import (
    UPSCALE_DATE_KEY,
    UpscalePageState,
    walk_upscale_pages,
)

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.comics_consts import PageType
    from barks_fantagraphics.comics_database import ComicsDatabase

TITLE = "Lost in the Andes!"
VOLUME = 7

RESTORE_RECIPE_ID = get_current_recipe(4, do_palette_snap=True).recipe_id
UPSCALE_RECIPE = get_current_upscale_recipe(DEFAULT_UPSCALER, LIBRARY_SCALE)
UPSCALE_RECIPE_ID = UPSCALE_RECIPE.recipe_id
OLD_RECIPE_ID = "bbbbbbbbbbbb"


def write_png(path: Path, metadata: dict[str, str] | None = None) -> Path:
    """Write a tiny png, optionally carrying BARKS metadata."""
    info = PngInfo()
    for key, value in (metadata or {}).items():
        info.add_text(f"BARKS:{key}", value)

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2)).save(str(path), pnginfo=info)

    return path


class FakeComic:
    """A title made of files in a temporary directory."""

    def __init__(self, tmp_path: Path, pages: list[str]) -> None:
        self.root = tmp_path
        self.pages = pages
        self.fixes_pages: set[str] = set()
        self.hand_restored_pages: set[str] = set()

    def srce(self, page: str) -> Path:
        return self.root / "original" / f"{page}.jpg"

    def upscayl(self, page: str) -> Path:
        return self.root / "upscayled" / f"{page}.png"

    def restored(self, page: str) -> Path:
        return self.root / "restored" / f"{page}.png"

    def restored_4x(self, page: str) -> Path:
        return self.root / "restored-upscayled" / f"{page}.png"

    def svg(self, page: str) -> Path:
        return self.root / "restored-svg" / f"{page}.svg"

    # ---- what the walks ask for

    def get_final_srce_original_story_files(
        self, _page_types: list[PageType]
    ) -> list[tuple[Path, ModifiedType]]:
        return [(self.srce(page), ModifiedType.ORIGINAL) for page in self.pages]

    def get_final_srce_upscayled_story_files(
        self, _page_types: list[PageType]
    ) -> list[tuple[Path, ModifiedType]]:
        return [
            (
                self.upscayl(page),
                ModifiedType.MODIFIED if page in self.fixes_pages else ModifiedType.ORIGINAL,
            )
            for page in self.pages
        ]

    def get_srce_restored_story_files(self, _page_types: list[PageType]) -> list[Path]:
        return [self.restored(page) for page in self.pages]

    def get_srce_restored_upscayled_story_files(self, _page_types: list[PageType]) -> list[Path]:
        return [self.restored_4x(page) for page in self.pages]

    def get_srce_restored_svg_story_files(self, _page_types: list[PageType]) -> list[Path]:
        return [self.svg(page) for page in self.pages]

    def is_hand_restored(self, page_num: str) -> bool:
        return page_num in self.hand_restored_pages

    # ---- putting pages in the states the tests want

    def write_srce(self, page: str) -> None:
        write_png(self.srce(page))

    def write_upscayled(self, page: str, recipe_id: str = UPSCALE_RECIPE_ID) -> None:
        self.write_srce(page)
        write_png(
            self.upscayl(page),
            {UPSCALE_RECIPE_ID_KEY: recipe_id, UPSCALE_DATE_KEY: "2026-11-02T09:30:00+11:00"},
        )

    def write_restored(self, page: str, recipe_id: str = RESTORE_RECIPE_ID) -> None:
        self.write_upscayled(page)
        write_png(self.restored(page), {RECIPE_ID_KEY: recipe_id})
        write_png(self.restored_4x(page))
        self.svg(page).parent.mkdir(parents=True, exist_ok=True)
        self.svg(page).write_text("<svg/>")
        write_png(get_ink_mask_file(self.svg(page)))


class FakeDatabase:
    """As much of the comics database as a run asks for: one title."""

    def __init__(self, comic: FakeComic) -> None:
        self.comic = comic

    def get_comic_book(self, _title: str) -> FakeComic:
        return self.comic

    def get_fanta_volume_int(self, _title: str) -> int:
        return VOLUME


def as_database(comic: FakeComic) -> ComicsDatabase:
    return cast("ComicsDatabase", FakeDatabase(comic))


@pytest.fixture
def comic(tmp_path: Path) -> FakeComic:
    """Return a title with a page in every state a restore can find one in.

    110 is done, 111 was restored on an older recipe, 112 has never been restored, 113
    has no upscayled page to restore from, and 114 was restored by hand.
    """
    comic = FakeComic(tmp_path, ["110", "111", "112", "113", "114"])
    comic.write_restored("110")
    comic.write_restored("111", OLD_RECIPE_ID)
    comic.write_upscayled("112")
    comic.write_srce("113")
    comic.write_restored("114", OLD_RECIPE_ID)
    comic.hand_restored_pages.add("114")
    return comic


class TestTheRestoreWalk:
    def test_every_page_comes_back_in_order_with_its_state(self, comic: FakeComic) -> None:
        pages = list(walk_restore_pages(comic, RESTORE_RECIPE_ID))

        assert [(page.page, page.status.state) for page in pages] == [
            ("110", PageState.CURRENT),
            ("111", PageState.STALE),
            ("112", PageState.MISSING),
            ("113", PageState.NO_SRCE),
            ("114", PageState.HAND_RESTORED),
        ]

    def test_a_page_carries_its_own_files_and_nobody_elses(self, comic: FakeComic) -> None:
        page = list(walk_restore_pages(comic, RESTORE_RECIPE_ID))[1]

        assert page.srce_file == comic.srce("111")
        assert page.srce_upscayl_file == comic.upscayl("111")
        assert page.dest_restored_file == comic.restored("111")
        assert page.dest_upscayled_restored_file == comic.restored_4x("111")
        assert page.dest_svg_restored_file == comic.svg("111")

    def test_lists_of_different_lengths_are_an_error_and_not_a_short_walk(
        self, comic: FakeComic, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pairing pages off until the shorter list ran out would mismatch none and lose some."""
        monkeypatch.setattr(
            comic, "get_srce_restored_svg_story_files", lambda _types: [comic.svg("110")]
        )

        with pytest.raises(ValueError, match="zip"):
            list(walk_restore_pages(comic, RESTORE_RECIPE_ID))

    def test_the_run_queues_exactly_what_the_report_says_is_waiting(
        self, comic: FakeComic, tmp_path: Path
    ) -> None:
        database = as_database(comic)

        counts = restore_status.get_title_status(database, TITLE, RESTORE_RECIPE_ID)
        jobs = batch_restore_pipeline.get_title_jobs(
            database,
            TITLE,
            tmp_path / "work",
            get_current_recipe(4, do_palette_snap=True),
            use_existing_work_files=False,
            debug_color_counts=False,
            force=False,
        )

        assert [job.page for job in jobs] == ["111", "112"]
        assert len(jobs) == sum(n for state, n in counts.items() if state.needs_restoring)
        assert counts == {
            PageState.CURRENT: 1,
            PageState.STALE: 1,
            PageState.MISSING: 1,
            PageState.NO_SRCE: 1,
            PageState.HAND_RESTORED: 1,
        }

    def test_a_queued_page_is_given_its_own_files(self, comic: FakeComic, tmp_path: Path) -> None:
        jobs = batch_restore_pipeline.get_title_jobs(
            as_database(comic),
            TITLE,
            tmp_path / "work",
            get_current_recipe(4, do_palette_snap=True),
            use_existing_work_files=False,
            debug_color_counts=False,
            force=False,
        )

        job = jobs[0]
        assert (job.title, job.volume, job.page) == (TITLE, VOLUME, "111")
        assert job.pipeline.srce_upscale_file == comic.upscayl("111")
        assert job.pipeline.dest_restored_file == comic.restored("111")
        assert job.pipeline.dest_svg_restored_file == comic.svg("111")

    def test_forcing_requeues_a_current_page_but_never_a_hand_restored_one(
        self, comic: FakeComic, tmp_path: Path
    ) -> None:
        jobs = batch_restore_pipeline.get_title_jobs(
            as_database(comic),
            TITLE,
            tmp_path / "work",
            get_current_recipe(4, do_palette_snap=True),
            use_existing_work_files=False,
            debug_color_counts=False,
            force=True,
        )

        assert [job.page for job in jobs] == ["110", "111", "112"]


@pytest.fixture
def upscale_comic(tmp_path: Path) -> FakeComic:
    """Return a title with a page in every state an upscale can find one in.

    110 is done, 111 was upscayled on an older recipe, 112 has never been upscayled, 113
    has no scan, 114 is a hand-edited file standing in for the upscayled page, and 115
    belongs to a page that was restored by hand.
    """
    comic = FakeComic(tmp_path, ["110", "111", "112", "113", "114", "115"])
    comic.write_upscayled("110")
    comic.write_upscayled("111", OLD_RECIPE_ID)
    comic.write_srce("112")
    comic.write_srce("114")
    write_png(comic.upscayl("114"))
    comic.fixes_pages.add("114")
    comic.write_upscayled("115", OLD_RECIPE_ID)
    comic.hand_restored_pages.add("115")
    return comic


class TestTheUpscaleWalk:
    def test_every_page_comes_back_in_order_with_its_state(self, upscale_comic: FakeComic) -> None:
        pages = list(walk_upscale_pages(upscale_comic, UPSCALE_RECIPE_ID))

        assert [(page.page, page.status.state) for page in pages] == [
            ("110", UpscalePageState.CURRENT),
            ("111", UpscalePageState.STALE),
            ("112", UpscalePageState.MISSING),
            ("113", UpscalePageState.NO_SRCE),
            ("114", UpscalePageState.FIXES),
            ("115", UpscalePageState.HAND_RESTORED),
        ]

    def test_a_page_carries_its_own_files(self, upscale_comic: FakeComic) -> None:
        page = list(walk_upscale_pages(upscale_comic, UPSCALE_RECIPE_ID))[1]

        assert page.srce_file == upscale_comic.srce("111")
        assert page.dest_upscayl_file == upscale_comic.upscayl("111")

    def test_the_run_queues_exactly_what_the_report_says_is_waiting(
        self, upscale_comic: FakeComic
    ) -> None:
        database = as_database(upscale_comic)
        run_counts: dict[str, int] = {}

        counts = upscale_status.get_title_status(database, TITLE, UPSCALE_RECIPE_ID)
        jobs = batch_upscayl.get_title_jobs(
            database, TITLE, UPSCALE_RECIPE, run_counts, force=False
        )

        assert [job.page for job in jobs] == ["111", "112"]
        assert len(jobs) == sum(n for state, n in counts.items() if state.needs_upscayling)
        # The run keeps its own tally for its closing summary, and it is the same one.
        assert run_counts == dict(counts)

    def test_forcing_never_queues_a_page_a_run_would_destroy(
        self, upscale_comic: FakeComic
    ) -> None:
        jobs = batch_upscayl.get_title_jobs(
            as_database(upscale_comic), TITLE, UPSCALE_RECIPE, {}, force=True
        )

        assert [job.page for job in jobs] == ["110", "111", "112"]
        assert jobs[1].srce_file == upscale_comic.srce("111")
        assert jobs[1].dest_file == upscale_comic.upscayl("111")
