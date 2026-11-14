"""Tests for the two build records written beside a comic: the summary and the page map.

`clean_summary.txt` is written at the very end of a build, after the zip and its links,
from some sixty fields of the comic. A wrong attribute or a format spec applied to the
wrong type fails only there - after everything expensive has succeeded - and the
integrity check then reports the comic as missing a file. Nothing exercised it at all.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest
from barks_build_comic_images.consts import DEST_SRCE_MAP_FILENAME, SUMMARY_FILENAME
from barks_fantagraphics.comic_book import ModifiedType
from barks_fantagraphics.comics_consts import PageType
from barks_fantagraphics.page_classes import (
    CleanPage,
    ComicDimensions,
    RequiredDimensions,
    SrceAndDestPages,
)
from barks_fantagraphics.panel_geometry import BoundingBox
from comic_utils.timing import Timing

from barks_comic_building.build.additional_file_writing import (
    write_srce_dest_map,
    write_summary_file,
)

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.comic_book import ComicBook

SRCE_DIM = ComicDimensions(
    min_panels_bbox_width=1000,
    max_panels_bbox_width=1200,
    min_panels_bbox_height=1400,
    max_panels_bbox_height=1600,
    av_panels_bbox_width=1100,
    av_panels_bbox_height=1500,
)
REQUIRED_DIM = RequiredDimensions(
    panels_bbox_width=1600, panels_bbox_height=2100, page_num_y_bottom=2300
)

# The page whose source is a fixes file rather than the volume's own scan.
MODIFIED_PAGE = "002"
MAX_DEST_TIMESTAMP = 1_700_000_000.0


class ConfigPage:
    def __init__(self, page_filenames: str, page_type: PageType) -> None:
        self.page_filenames = page_filenames
        self.page_type = page_type


class FakeDirs:
    def __init__(self, root: Path) -> None:
        self.srce_dir = root / "original" / "Volume 07"
        self.srce_upscayled_dir = root / "upscayled"
        self.srce_restored_dir = root / "restored"
        self.srce_fixes_dir = root / "fixes"
        self.srce_upscayled_fixes_dir = root / "upscayled-fixes"


class FakeComic:
    """Every accessor the two writers read, over files that exist under `tmp_path`."""

    def __init__(self, tmp_path: Path) -> None:
        self._root = tmp_path
        self.dirs = FakeDirs(tmp_path)
        self.ini_file = self._touch("A Fake Title.ini")
        self.title_font_file = self._touch("title.ttf")
        self.intro_inset_file = self._touch("inset.png")

        self.title = "A Fake Title"
        self.issue_title = "Walt Disney's Comics and Stories #100"
        self.series_name = "Donald Duck"
        self.number_in_series = 7
        self.chronological_number = 212
        self.submitted_date = "1948-09-01"
        self.submitted_year = 1948
        self.publication_date = "January 1949"
        self.publication_text = "First published in WDCS 100"
        self.title_font_size = 155
        self.author_font_size = 90
        self.config_page_images = [
            ConfigPage("001", PageType.COVER),
            ConfigPage("002-003", PageType.BODY),
        ]

        self.get_dest_dir().mkdir()
        self._touch("212 A Fake Title [WDCS 100].cbz")
        self._touch("series.cbz")
        self._touch("year.cbz")

    def _touch(self, name: str) -> Path:
        path = self._root / name
        path.touch()

        return path

    def get_ini_title(self) -> str:
        return "A Fake Title"

    def get_comic_title(self) -> str:
        return "A Fake Title"

    def get_dest_dir(self) -> Path:
        return self._root / "212 A Fake Title"

    def get_dest_rel_dirname(self) -> str:
        return "212 A Fake Title"

    def get_dest_comic_zip(self) -> Path:
        return self._root / "212 A Fake Title [WDCS 100].cbz"

    def get_dest_series_comic_zip_symlink(self) -> Path:
        return self._root / "series.cbz"

    def get_dest_year_comic_zip_symlink(self) -> Path:
        return self._root / "year.cbz"

    def get_final_srce_story_file(
        self, page_num_str: str, _page_type: PageType
    ) -> tuple[str, ModifiedType]:
        if page_num_str == MODIFIED_PAGE:
            return page_num_str, ModifiedType.MODIFIED

        return page_num_str, ModifiedType.ORIGINAL

    def get_final_srce_upscayled_story_file(
        self, page_num_str: str, _page_type: PageType
    ) -> tuple[str, ModifiedType]:
        return page_num_str, ModifiedType.ORIGINAL

    def get_final_srce_original_story_file(
        self, page_num_str: str, _page_type: PageType
    ) -> tuple[str, ModifiedType]:
        return page_num_str, ModifiedType.ORIGINAL


def clean_page(name: str, page_type: PageType, page_num: int) -> CleanPage:
    page = CleanPage(name, page_type, page_num)
    page.panels_bbox = BoundingBox(10, 20, 30, 40)

    return page


@pytest.fixture
def comic(tmp_path: Path) -> FakeComic:
    return FakeComic(tmp_path)


@pytest.fixture
def pages(tmp_path: Path) -> SrceAndDestPages:
    types = [PageType.COVER, PageType.BODY, PageType.BODY]

    return SrceAndDestPages(
        srce_pages=[
            clean_page(str(tmp_path / f"{i:03d}.png"), page_type, i)
            for i, page_type in enumerate(types, start=1)
        ],
        dest_pages=[
            clean_page(str(tmp_path / f"dest-{i:03d}.jpg"), page_type, i)
            for i, page_type in enumerate(types, start=1)
        ],
    )


def summary_fields(comic: FakeComic, pages: SrceAndDestPages) -> dict[str, str]:
    """Write the summary and return its "label = value" lines as a dict."""
    write_summary_file(
        cast("ComicBook", comic), SRCE_DIM, REQUIRED_DIM, pages, MAX_DEST_TIMESTAMP, Timing()
    )
    text = (comic.get_dest_dir() / SUMMARY_FILENAME).read_text()

    return {
        label.strip(): value.strip()
        for label, _, value in (line.partition(" = ") for line in text.splitlines())
        if value
    }


class TestTheSummaryFile:
    def test_it_is_written_into_the_dest_dir(
        self, comic: FakeComic, pages: SrceAndDestPages
    ) -> None:
        summary_fields(comic, pages)

        assert (comic.get_dest_dir() / SUMMARY_FILENAME).is_file()

    def test_it_records_the_titles_and_the_numbers(
        self, comic: FakeComic, pages: SrceAndDestPages
    ) -> None:
        fields = summary_fields(comic, pages)

        assert fields["title"] == '"A Fake Title"'
        assert fields["chronological number"] == "212"
        assert fields["series book num"] == "7"
        assert fields["submitted year"] == "1948"

    def test_it_records_the_dimensions_the_build_worked_to(
        self, comic: FakeComic, pages: SrceAndDestPages
    ) -> None:
        fields = summary_fields(comic, pages)

        assert fields["srce av panels bbox wid"] == "1100"
        assert fields["req panels bbox height"] == "2100"
        assert fields["calc panels bbox height"] == str(round(1500 * 1600 / 1100))

    def test_it_names_the_body_pages_built_from_a_fixes_file(
        self, comic: FakeComic, pages: SrceAndDestPages
    ) -> None:
        fields = summary_fields(comic, pages)

        # By the dest page's own number, not its place among the body pages.
        assert fields["modified body pages"] == "2"
        assert fields["has modified cover"] == "False"

    def test_a_modified_page_is_marked_in_the_page_list(
        self, comic: FakeComic, pages: SrceAndDestPages
    ) -> None:
        summary_fields(comic, pages)
        lines = (comic.get_dest_dir() / SUMMARY_FILENAME).read_text().splitlines()

        added = [line for line in lines if line.startswith("Added srce")]
        assert len(added) == len(pages.dest_pages)
        assert [("***M" in line) for line in added] == [False, True, False]

    def test_every_configured_page_range_is_listed(
        self, comic: FakeComic, pages: SrceAndDestPages
    ) -> None:
        summary_fields(comic, pages)
        text = (comic.get_dest_dir() / SUMMARY_FILENAME).read_text()

        assert "pages = 002-003" in text
        assert "page type = COVER" in text


class TestTheSrceDestMap:
    def test_each_dest_page_is_mapped_to_its_source(
        self, comic: FakeComic, pages: SrceAndDestPages
    ) -> None:
        write_srce_dest_map(cast("ComicBook", comic), SRCE_DIM, REQUIRED_DIM, pages)

        written = json.loads((comic.get_dest_dir() / DEST_SRCE_MAP_FILENAME).read_text())

        assert written["pages"]["dest-002.jpg"] == {"file": "002.png", "type": "BODY"}
        assert list(written["pages"]) == ["dest-001.jpg", "dest-002.jpg", "dest-003.jpg"]

    def test_the_directories_are_recorded_by_name(
        self, comic: FakeComic, pages: SrceAndDestPages
    ) -> None:
        write_srce_dest_map(cast("ComicBook", comic), SRCE_DIM, REQUIRED_DIM, pages)

        written = json.loads((comic.get_dest_dir() / DEST_SRCE_MAP_FILENAME).read_text())

        assert written["srce_dirname"] == "Volume 07"
        assert written["dest_dirname"] == "212 A Fake Title"
        assert written["dest_required_bbox_width"] == REQUIRED_DIM.panels_bbox_width
