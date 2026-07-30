"""Tests for the info files written beside a built comic's pages.

Two things here fail in ways a build would not notice.

`get_page_counts` buckets every page by type and then asserts its own buckets add up to
the total. A page type that belongs to no bucket therefore does not produce a wrong count
- it raises, mid-build, after the pages are already written. The partition is checked
here against every member of `PageType`, so adding a type without giving it a bucket
fails in a test rather than in a build. (The `# TODO(glk)` about paintings in that
function is exactly this worry.)

The page numbering written into `metadata.txt` is what the reader displays. It is a
different scheme from the page numbers burnt into the images - front matter is numbered
by position and never skipped - and the two being different is deliberate, so a test that
just checked they agreed would be wrong. What matters is that the body restarts at 1 at
the first non-front-matter page, and that double-page spreads alternate left and right.
"""

from __future__ import annotations

import configparser
import json
import os
from typing import TYPE_CHECKING, cast

import pytest
from barks_build_comic_images.consts import (
    DEST_PANELS_BBOXES_FILENAME,
    DOUBLE_PAGES,
    DOUBLE_PAGES_SECTION,
    METADATA_FILENAME,
    PAGE_NUMBERS_SECTION,
)
from barks_fantagraphics.barks_titles import Titles
from barks_fantagraphics.comic_book_info import SYNTHETIC_TITLES
from barks_fantagraphics.comics_consts import PageType
from barks_fantagraphics.page_classes import CleanPage, ComicDimensions, RequiredDimensions
from barks_fantagraphics.panel_geometry import BoundingBox

from barks_comic_building.build.additional_file_writing import (
    get_page_counts,
    write_dest_panels_bboxes,
    write_json_metadata,
    write_metadata_file,
    write_readme_file,
)
from barks_comic_building.build.comics_integrity import ComicsIntegrityChecker, HashErrors

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.comic_book import ComicBook

# Which bucket of `get_page_counts` each page type belongs to. Written out rather than
# derived, so that this is an independent statement of the partition rather than a
# restatement of the implementation.
BUCKET_FOR_PAGE_TYPE = {
    PageType.FRONT: "front",
    PageType.TITLE: "title",
    PageType.COVER: "cover",
    PageType.SPLASH: "splash",
    PageType.FRONT_NO_PANELS: "front_matter",
    PageType.FRONT_MATTER: "front_matter",
    PageType.PAINTING: "painting",
    PageType.PAINTING_NO_BORDER: "painting",
    PageType.BACK_PAINTING: "painting",
    PageType.BACK_PAINTING_NO_BORDER: "painting",
    PageType.BODY: "story",
    PageType.BACK_MATTER: "back_matter",
    PageType.BACK_NO_PANELS: "back_matter",
    PageType.BACK_NO_PANELS_DOUBLE: "back_matter",
    PageType.BLANK_PAGE: "blank",
}

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

BBOX = (10, 20, 30, 40)

SUBMITTED_YEAR = 1948

# An mtime far in the future, for the touched-but-unedited case.
FUTURE = 2_000_000_000.0


class FakeDirs:
    """The one source directory the metadata writers record."""

    def __init__(self, tmp_path: Path) -> None:
        self.srce_dir = tmp_path / "srce"


class FakeComic:
    """The accessors the info-file writers read.

    Stands in for a `ComicBook`: enough to write `metadata.txt`, the json metadata and
    the dest bboxes, with no comics database and a real ini file on disk only because its
    hash goes into the json.
    """

    def __init__(self, tmp_path: Path, title_enum: Titles = Titles.ALL_COVERS) -> None:
        self.dest_dir = tmp_path / "dest"
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        self.ini_file = tmp_path / "A Fake Title.ini"
        self.ini_file.write_text("[info]\ntitle = A Fake Title\n")
        self.dirs = FakeDirs(tmp_path)
        self._title_enum = title_enum

        self.title = "A Fake Title"
        self.issue_title = "Walt Disney's Comics and Stories #100"
        self.series_name = "Donald Duck"
        self.number_in_series = 7
        self.publication_date = "January 1949"
        self.submitted_date = "1948-09-01"
        self.submitted_year = SUBMITTED_YEAR

    def get_dest_dir(self) -> Path:
        return self.dest_dir

    def get_metadata_filepath(self) -> Path:
        return self.dest_dir / "comic-metadata.json"

    def get_title_enum(self) -> Titles:
        return self._title_enum

    def get_ini_title(self) -> str:
        return "A Fake Title"

    def get_comic_title(self) -> str:
        return "A Fake Title"


def as_comic(fake: FakeComic) -> ComicBook:
    """Present a `FakeComic` as the `ComicBook` the writers are typed against."""
    return cast("ComicBook", fake)


def page(page_type: PageType, name: str = "001.jpg", *, arabic: bool = False) -> CleanPage:
    """Make a dest page of one type, with a known panels bbox.

    Args:
        page_type: The page's type.
        name: The dest filename.
        arabic: Whether front matter is numbered in arabic rather than roman numerals.

    Returns:
        The page.

    """
    clean_page = CleanPage(name, page_type, use_arabic_page_num=arabic)
    # `BoundingBox` is frozen, so the whole box is replaced rather than mutated.
    clean_page.panels_bbox = BoundingBox(*BBOX)

    return clean_page


@pytest.fixture
def comic(tmp_path: Path) -> FakeComic:
    return FakeComic(tmp_path)


def read_metadata(comic: FakeComic) -> configparser.ConfigParser:
    """Read back the written `metadata.txt`."""
    parser = configparser.ConfigParser()
    parser.read(comic.get_dest_dir() / METADATA_FILENAME)

    return parser


class TestThePageCountsPartitionEveryType:
    """Every page type must land in exactly one bucket.

    `get_page_counts` asserts its buckets sum to the total, so a type belonging to no
    bucket raises mid-build rather than producing a wrong number.
    """

    def test_every_page_type_is_accounted_for(self) -> None:
        # A tripwire for a new `PageType`: it has to be given a bucket, and the mapping
        # below has to say which.
        assert set(BUCKET_FOR_PAGE_TYPE) == set(PageType)

    @pytest.mark.parametrize("page_type", list(PageType))
    def test_one_page_lands_in_exactly_one_bucket(
        self, comic: FakeComic, page_type: PageType
    ) -> None:
        counts = get_page_counts(as_comic(comic), [page(page_type)])

        expected = BUCKET_FOR_PAGE_TYPE[page_type]
        assert counts[expected] == 1
        assert counts["total"] == 1
        assert sum(v for k, v in counts.items() if k != "total") == 1

    def test_one_page_of_every_type_sums_to_the_total(self, comic: FakeComic) -> None:
        pages = [page(page_type) for page_type in PageType]

        counts = get_page_counts(as_comic(comic), pages)

        assert counts["total"] == len(list(PageType))

    def test_an_empty_comic_counts_nothing(self, comic: FakeComic) -> None:
        counts = get_page_counts(as_comic(comic), [])

        assert counts["total"] == 0


class TestTheAllCoversCollectionIsAllowedItsShape:
    """The synthetic collections break two rules an ordinary comic must keep."""

    def test_many_covers_are_allowed_for_a_synthetic_title(self, comic: FakeComic) -> None:
        # An ordinary comic has at most one cover; "All Covers" is nothing but covers.
        assert Titles.ALL_COVERS in SYNTHETIC_TITLES
        covers = [page(PageType.COVER, f"{i:03d}.jpg") for i in range(5)]

        counts = get_page_counts(as_comic(comic), covers)

        assert counts["cover"] == len(covers)

    def test_no_title_page_is_allowed_for_a_synthetic_title(self, comic: FakeComic) -> None:
        counts = get_page_counts(as_comic(comic), [page(PageType.COVER)])

        assert counts["title"] == 0


class TestTheWrittenPageNumbers:
    def test_the_body_restarts_at_one_after_the_front_matter(self, comic: FakeComic) -> None:
        pages = [
            page(PageType.FRONT, "001.jpg"),
            page(PageType.TITLE, "002.jpg"),
            page(PageType.BODY, "003.jpg"),
            page(PageType.BODY, "004.jpg"),
        ]

        write_metadata_file(as_comic(comic), pages)

        numbers = read_metadata(comic)[PAGE_NUMBERS_SECTION]
        assert numbers["3"] == "1"
        assert numbers["4"] == "2"

    def test_a_comic_with_no_front_matter_starts_its_body_at_one(self, comic: FakeComic) -> None:
        pages = [page(PageType.BODY, "001.jpg"), page(PageType.BODY, "002.jpg")]

        write_metadata_file(as_comic(comic), pages)

        numbers = read_metadata(comic)[PAGE_NUMBERS_SECTION]
        assert numbers["1"] == "1"
        assert numbers["2"] == "2"

    def test_front_matter_is_numbered_by_position_and_never_skipped(self, comic: FakeComic) -> None:
        # Unlike the numbers burnt into the images, this scheme numbers the front cover
        # too and blanks nothing - the two are deliberately different.
        pages = [
            page(PageType.FRONT, "001.jpg"),
            page(PageType.TITLE, "002.jpg"),
            page(PageType.BODY, "003.jpg"),
        ]

        write_metadata_file(as_comic(comic), pages)

        numbers = read_metadata(comic)[PAGE_NUMBERS_SECTION]
        assert set(numbers) == {"1", "2", "3"}

    def test_arabic_front_matter_survives_more_pages_than_there_are_numerals(
        self, comic: FakeComic
    ) -> None:
        # Roman numerals only run to "x" here, so a collection with a long front matter
        # has to be numbered as an ordinary book or the numbering raises.
        pages = [page(PageType.FRONT_MATTER, f"{i:03d}.jpg", arabic=True) for i in range(12)]
        pages.append(page(PageType.BODY, "013.jpg"))

        write_metadata_file(as_comic(comic), pages)

        numbers = read_metadata(comic)[PAGE_NUMBERS_SECTION]
        assert numbers["12"] == "12"
        assert numbers["13"] == "1"


class TestTheWrittenDoublePages:
    def test_consecutive_body_pages_pair_left_then_right(self, comic: FakeComic) -> None:
        pages = [page(PageType.BODY, f"{i:03d}.jpg") for i in range(1, 5)]

        write_metadata_file(as_comic(comic), pages)

        doubles = read_metadata(comic)[DOUBLE_PAGES_SECTION]
        # The first is a left page spreading onto the next; the second is the right of
        # that pair, and the alternation continues.
        assert doubles["1"] == "1,2"
        assert doubles["2"] == "1,2"
        assert doubles["3"] == "3,4"
        assert doubles["4"] == "3,4"

    def test_a_page_type_outside_the_spread_set_gets_no_entry(self, comic: FakeComic) -> None:
        assert PageType.TITLE not in DOUBLE_PAGES
        pages = [page(PageType.TITLE, "001.jpg"), page(PageType.BODY, "002.jpg")]

        write_metadata_file(as_comic(comic), pages)

        assert "1" not in read_metadata(comic)[DOUBLE_PAGES_SECTION]

    def test_a_blank_page_joins_the_same_alternation(self, comic: FakeComic) -> None:
        assert PageType.BLANK_PAGE in DOUBLE_PAGES
        pages = [page(PageType.BODY, "001.jpg"), page(PageType.BLANK_PAGE, "002.jpg")]

        write_metadata_file(as_comic(comic), pages)

        doubles = read_metadata(comic)[DOUBLE_PAGES_SECTION]
        assert doubles["2"] == "1,2"


class TestTheJsonMetadata:
    def test_the_written_json_round_trips(self, comic: FakeComic) -> None:
        write_json_metadata(as_comic(comic), SRCE_DIM, REQUIRED_DIM, [page(PageType.BODY)])

        metadata = json.loads(comic.get_metadata_filepath().read_text())

        assert metadata["title"] == "A Fake Title"
        assert metadata["series_name"] == "Donald Duck"
        assert metadata["submitted_year"] == SUBMITTED_YEAR

    def test_the_required_dimensions_are_written_as_a_triple(self, comic: FakeComic) -> None:
        write_json_metadata(as_comic(comic), SRCE_DIM, REQUIRED_DIM, [page(PageType.BODY)])

        metadata = json.loads(comic.get_metadata_filepath().read_text())

        assert metadata["required_dim"] == [
            REQUIRED_DIM.panels_bbox_width,
            REQUIRED_DIM.panels_bbox_height,
            REQUIRED_DIM.page_num_y_bottom,
        ]

    def test_the_page_counts_are_nested_in_the_json(self, comic: FakeComic) -> None:
        pages = [page(PageType.BODY, "001.jpg"), page(PageType.COVER, "002.jpg")]

        write_json_metadata(as_comic(comic), SRCE_DIM, REQUIRED_DIM, pages)

        metadata = json.loads(comic.get_metadata_filepath().read_text())

        assert metadata["page_counts"]["story"] == 1
        assert metadata["page_counts"]["total"] == len(pages)

    def test_the_ini_hash_is_recorded(self, comic: FakeComic) -> None:
        # This is what `check_hashes` compares against to notice an edited ini.
        write_json_metadata(as_comic(comic), SRCE_DIM, REQUIRED_DIM, [page(PageType.BODY)])

        metadata = json.loads(comic.get_metadata_filepath().read_text())

        assert metadata["ini_hash"]

    def test_editing_the_ini_changes_the_recorded_hash(self, comic: FakeComic) -> None:
        write_json_metadata(as_comic(comic), SRCE_DIM, REQUIRED_DIM, [page(PageType.BODY)])
        before = json.loads(comic.get_metadata_filepath().read_text())["ini_hash"]

        comic.ini_file.write_text("[info]\ntitle = A Fake Title\nextra = 1\n")
        write_json_metadata(as_comic(comic), SRCE_DIM, REQUIRED_DIM, [page(PageType.BODY)])
        after = json.loads(comic.get_metadata_filepath().read_text())["ini_hash"]

        assert before != after


class TestTheDestPanelBboxes:
    def test_the_bboxes_are_keyed_by_dest_basename(self, comic: FakeComic) -> None:
        pages = [page(PageType.BODY, "/somewhere/dest/images/007.jpg")]

        write_dest_panels_bboxes(as_comic(comic), pages)

        written = json.loads((comic.get_dest_dir() / DEST_PANELS_BBOXES_FILENAME).read_text())

        assert set(written) == {"007.jpg"}

    def test_each_bbox_is_written_as_four_numbers(self, comic: FakeComic) -> None:
        write_dest_panels_bboxes(as_comic(comic), [page(PageType.BODY)])

        written = json.loads((comic.get_dest_dir() / DEST_PANELS_BBOXES_FILENAME).read_text())

        assert written["001.jpg"] == list(BBOX)


class TestTheIniIsCheckedByHashNotByTimestamp:
    """Where the ini's staleness signal actually lives.

    The integrity check deliberately ignores the ini's mtime - it is git-tracked, so a
    checkout rewrites it without changing a byte. This is the check that replaces it, and
    it is exact: the hash recorded at build time versus the hash now.
    """

    def test_an_unedited_ini_matches_what_was_built(self, comic: FakeComic) -> None:
        write_json_metadata(as_comic(comic), SRCE_DIM, REQUIRED_DIM, [page(PageType.BODY)])

        errors = HashErrors()

        assert ComicsIntegrityChecker.check_hashes(as_comic(comic), errors) == 0

    def test_a_touched_but_unedited_ini_still_matches(self, comic: FakeComic) -> None:
        # The 2982-findings case: the mtime moves, the content does not. A hash notices
        # the difference; a timestamp comparison cannot.
        write_json_metadata(as_comic(comic), SRCE_DIM, REQUIRED_DIM, [page(PageType.BODY)])
        os.utime(comic.ini_file, (FUTURE, FUTURE))

        errors = HashErrors()

        assert ComicsIntegrityChecker.check_hashes(as_comic(comic), errors) == 0

    def test_an_edited_ini_is_caught(self, comic: FakeComic) -> None:
        write_json_metadata(as_comic(comic), SRCE_DIM, REQUIRED_DIM, [page(PageType.BODY)])
        comic.ini_file.write_text("[info]\ntitle = A Fake Title\npages = 1-10\n")

        errors = HashErrors()

        assert ComicsIntegrityChecker.check_hashes(as_comic(comic), errors) == 1
        assert errors.file_to_hash == comic.ini_file

    def test_an_unbuilt_comic_is_reported_as_unbuilt(self, comic: FakeComic) -> None:
        errors = HashErrors()

        assert ComicsIntegrityChecker.check_hashes(as_comic(comic), errors) == 1
        assert errors.metadata_file == comic.get_metadata_filepath()

    def test_metadata_with_no_recorded_hash_is_reported_not_skipped(self, comic: FakeComic) -> None:
        # This used to return 0 with a log warning. Now that the ini's timestamp is
        # deliberately ignored, the hash is its only check - so a comic built before the
        # hash was recorded would otherwise have its ini verified by nothing at all.
        comic.get_metadata_filepath().write_text(json.dumps({"title": "A Fake Title"}))

        errors = HashErrors()

        assert ComicsIntegrityChecker.check_hashes(as_comic(comic), errors) == 1
        assert errors.metadata_missing_hash == comic.get_metadata_filepath()


class TestTheReadme:
    def test_the_readme_names_the_three_titles_and_the_archived_ini(self, comic: FakeComic) -> None:
        write_readme_file(as_comic(comic))

        text = (comic.get_dest_dir() / "readme.txt").read_text()

        assert "A Fake Title" in text
        assert comic.ini_file.name in text
