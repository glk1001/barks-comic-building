"""Tests for showing a one-pager's panel bounds.

A one-pager has no `.ini` of its own - it is a member of the `All One-Pagers` collection
- so `get_comic_book` cannot open it. `barks-show-panel-bounds` asked for one anyway and
died with `TitleNotFoundError: Could not find title "Dogged Determination". Did you mean
"Foxy Relations"?`, which reads like a misspelling rather than a whole class of title the
lookup cannot reach. The resolution step above it already knew better:
`get_title_from_volume_page` checks `ONE_PAGER_LOCATIONS` first and had returned the
right title.

That made the tool unusable for exactly the pages the integrity report sends you to,
since a one-pager's pages are only ever checked through the collection.

Two things about the fix are decisions rather than mechanism, and are what this file
pins. The page is reached through the collection, never through the home volume's trees
directly - `Art Appreciation` has no restored png and no segments file under volume 28 at
all, only under the collection, so the direct route would fail on it. And the page is
*labelled* with its volume page, because that is what the `bounded` override and the
`barks-batch-panel-bounds` re-run are keyed by; the collection page number is only how
the file was reached.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar, cast

import pytest
from barks_fantagraphics.barks_titles import Titles
from PIL import Image

from barks_comic_building.query import show_panel_bounds as spb

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.comics_database import ComicsDatabase

# Every path under test reaches the database only through functions this file stands in
# for, so there is nothing for a real one to answer.
NO_DATABASE = cast("ComicsDatabase", None)

ONE_PAGER = Titles.DOGGED_DETERMINATION
VOLUME = 20
VOLUME_PAGE = 95
COLLECTION_PAGE = "593"

PAGE_SIZE = (400, 600)
PANELS = [[10, 10, 180, 280], [210, 10, 180, 280], [10, 310, 380, 280]]
OVERALL_BOUNDS = [10, 10, 389, 589]


def write_page_png(path: Path) -> Path:
    """Write a page png that passes `validate_page_bw_image` - white ground, black ink."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", PAGE_SIZE, (255, 255, 255, 255))
    image.paste((0, 0, 0, 255), (50, 50, 150, 150))
    image.save(path)

    return path


def write_segments(path: Path) -> Path:
    """Write a panel segments json matching `PAGE_SIZE`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"size": list(PAGE_SIZE), "panels": PANELS, "overall_bounds": OVERALL_BOUNDS})
    )

    return path


class Staged:
    """One one-pager's staged candidates, as `stage_one_pagers` hands them over.

    Only the two the viewer reads are filled in - the svg's png rendering and the panel
    segments - each as the `(collection slot, home volume file)` pair the stager returns.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.collection = tmp_path / "collection"
        self.volume = tmp_path / f"volume-{VOLUME}"

        self.png_link = self.collection / f"{COLLECTION_PAGE}.svg.png"
        self.png_source = self.volume / f"{VOLUME_PAGE:03d}.svg.png"
        self.segments_link = self.collection / f"{COLLECTION_PAGE}.json"
        self.segments_source = self.volume / f"{VOLUME_PAGE:03d}.json"

    def stage_from_the_volume(self) -> None:
        """Set up the ordinary shape: the volume holds the files, the collection links them."""
        write_page_png(self.png_source)
        write_segments(self.segments_source)
        self.png_link.parent.mkdir(parents=True, exist_ok=True)
        self.png_link.symlink_to(self.png_source)
        self.segments_link.symlink_to(self.segments_source)

    def own_it_in_the_collection(self) -> None:
        """Set up `Art Appreciation`: only the collection has this page.

        Its volume never restored it, so the home-volume route would find nothing at all.
        """
        write_page_png(self.png_link)
        write_segments(self.segments_link)

    @property
    def links(self) -> list[tuple[Path, Path]]:
        return [
            (self.png_link, self.png_source),
            (self.segments_link, self.segments_source),
        ]

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Stand in for the stager and the location table."""
        monkeypatch.setattr(spb, "get_staged_links_by_title", lambda _db: {ONE_PAGER: self.links})
        monkeypatch.setattr(
            spb, "get_one_pager_fanta_vol_and_page", lambda _title: (VOLUME, VOLUME_PAGE)
        )


@pytest.fixture
def staged(tmp_path: Path) -> Staged:
    return Staged(tmp_path)


class TestWhichFileIsThePagesOwn:
    def test_the_volumes_file_wins_when_it_has_one(self, staged: Staged) -> None:
        staged.stage_from_the_volume()

        assert spb.page_home_file(staged.png_link, staged.png_source) == staged.png_source

    def test_the_collection_is_home_when_the_volume_has_nothing(self, staged: Staged) -> None:
        # The two read the same bytes through a link, so this is about which path a
        # message names - and it should name where the work is done.
        staged.own_it_in_the_collection()

        assert spb.page_home_file(staged.png_link, staged.png_source) == staged.png_link


class TestWhereThePageLives:
    def test_a_located_one_pager_names_its_volume_and_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            spb, "get_one_pager_fanta_vol_and_page", lambda _title: (VOLUME, VOLUME_PAGE)
        )

        assert spb.one_pager_where(ONE_PAGER) == "Vol 20, page 095"

    def test_an_unlocated_one_pager_says_so_instead_of_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(spb, "get_one_pager_fanta_vol_and_page", lambda _title: (None, None))

        assert spb.one_pager_where(ONE_PAGER) == "no authored location"


class TestBuildingTheOnePagersPage:
    def test_a_staged_one_pager_yields_its_single_page(
        self, staged: Staged, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        staged.stage_from_the_volume()
        staged.install(monkeypatch)

        pages = spb.one_pager_page_images(NO_DATABASE, ONE_PAGER)

        assert len(pages) == 1
        label, image = pages[0]
        assert label == "095", "the volume page, not the collection page"
        assert image.size == PAGE_SIZE

    def test_a_collection_owned_one_pager_still_yields_its_page(
        self, staged: Staged, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The case the home-volume route would have failed on: nothing under the volume.
        staged.own_it_in_the_collection()
        staged.install(monkeypatch)

        assert not staged.png_source.exists()
        assert len(spb.one_pager_page_images(NO_DATABASE, ONE_PAGER)) == 1

    def test_an_unstaged_one_pager_reports_rather_than_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A location that is still a placeholder stages nothing, and a KeyError out of
        # here would say nothing about why.
        monkeypatch.setattr(spb, "get_staged_links_by_title", lambda _db: {})

        assert spb.one_pager_page_images(NO_DATABASE, ONE_PAGER) == []


class FakeViewer:
    """Records what the viewer was asked to show, instead of opening a window."""

    last: ClassVar[dict[str, Any]] = {}

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        FakeViewer.last = kwargs

    def run(self) -> None:
        return


class TestWhichBuilderIsUsed:
    def test_a_one_pager_does_not_go_through_get_comic_book(
        self, staged: Staged, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        staged.stage_from_the_volume()
        staged.install(monkeypatch)
        monkeypatch.setattr(spb, "KivyPageViewer", FakeViewer)

        def fail(*_args: object, **_kwargs: object) -> None:
            pytest.fail("a one-pager must not be opened as a comic book")

        monkeypatch.setattr(spb, "_build_page_images", fail)

        spb.show_panel_bounds(NO_DATABASE, "Dogged Determination", "095")

        assert FakeViewer.last["start_page"] == 1
        assert "Vol 20, page 095" in FakeViewer.last["window_title"]

    def test_an_ordinary_title_still_takes_the_comic_book_route(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        page = Image.new("RGBA", PAGE_SIZE)
        monkeypatch.setattr(spb, "_build_page_images", lambda _db, _title: [("011", page)])
        monkeypatch.setattr(spb, "KivyPageViewer", FakeViewer)

        def fail(*_args: object, **_kwargs: object) -> None:
            pytest.fail("an ordinary story must not go through the collection")

        monkeypatch.setattr(spb, "one_pager_page_images", fail)

        spb.show_panel_bounds(NO_DATABASE, "Frozen Gold", "011")

        # No location suffix: an ordinary story is not staged from anywhere.
        assert FakeViewer.last["window_title"] == "Panel bounds — Frozen Gold"
