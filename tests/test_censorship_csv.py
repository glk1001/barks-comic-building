"""Tests for deriving the censorship-fixes CSV's columns from a row's story and page.

The volume, image and printed page of a row all follow from the story and comic page GLK
writes down, so this tool fills them in. What it must not do is quietly overwrite a typed
cell that disagrees, since the typed value may be the right one - so a blank cell is
filled, and a contradiction stops the rewrite until someone has looked at it.
"""

from pathlib import Path
from typing import cast

import pytest
from barks_fantagraphics.censorship_fixes import CENSORSHIP_FIXES_HEADER, CensorshipFixRow
from barks_fantagraphics.comics_database import ComicsDatabase, TitleNotFoundError
from barks_fantagraphics.printed_pages import get_printed_page
from typer.testing import CliRunner

from barks_comic_building.build import censorship_csv
from barks_comic_building.build.censorship_csv import (
    CensorshipCsvError,
    StoryLocation,
    build_rows,
    find_disagreements,
    locate_story,
    render_csv,
    row_sort_key,
)
from barks_comic_building.build.comics_integrity import (
    CensorshipRowFacts,
    CensorshipRowFault,
    classify_censorship_row,
)

FANTA_PAGE = CENSORSHIP_FIXES_HEADER.index("Fanta_page")
IMAGE = CENSORSHIP_FIXES_HEADER.index("Image")
STORY = CENSORSHIP_FIXES_HEADER.index("Story")

SMOKE_WRITER = "WDCS 194"
COVER_STORY = "WDCS  95"
LOCATIONS = {
    SMOKE_WRITER: StoryLocation(
        "Smoke Writer in the Sky", 18, {"3": "040"}, frozenset({"empty_page"}), "31"
    ),
    COVER_STORY: StoryLocation("Gladstone Returns", 6, {"1": "134"}, frozenset({"213"}), "129"),
}


def row(
    *,
    story: str = SMOKE_WRITER,
    volume: int = 18,
    image: str = "040",
    fanta_page: str = "33",
    comic_page: str = "3",
) -> CensorshipFixRow:
    return CensorshipFixRow(
        volume, image, fanta_page, comic_page, "4", story, "error", "[from]", "[to]"
    )


class TestDerivingARow:
    def test_a_numbered_row_gets_its_image_and_printed_page(self) -> None:
        derived = build_rows([row(image="", fanta_page="")], LOCATIONS)[0]

        assert (derived[IMAGE], derived[FANTA_PAGE]) == ("040", "33")

    def test_a_cover_row_gets_its_printed_page_from_its_image(self) -> None:
        cover = row(story=COVER_STORY, volume=6, image="213", fanta_page="", comic_page="")

        assert build_rows([cover], LOCATIONS)[0][FANTA_PAGE] == "208"

    def test_a_page_the_story_does_not_have_derives_blank(self) -> None:
        derived = build_rows([row(comic_page="99")], LOCATIONS)[0]

        assert (derived[IMAGE], derived[FANTA_PAGE]) == ("", "")

    def test_a_whole_story_row_stays_blank(self) -> None:
        whole_story = row(image="", fanta_page="", comic_page="")

        derived = build_rows([whole_story], LOCATIONS)[0]

        assert (derived[IMAGE], derived[FANTA_PAGE]) == ("", "")


class TestFindingDisagreements:
    @staticmethod
    def disagreements(stored: CensorshipFixRow) -> list[censorship_csv.RowDisagreement]:
        return find_disagreements([stored], build_rows([stored], LOCATIONS), LOCATIONS)

    def test_a_correct_row_has_none(self) -> None:
        assert self.disagreements(row()) == []

    def test_the_printed_page_of_the_next_row_is_reported(self) -> None:
        bad = self.disagreements(row(fanta_page="154"))

        assert [(b.column, b.stored, b.derived) for b in bad] == [("Fanta_page", "154", "33")]

    def test_a_wrong_printed_page_on_a_cover_is_reported(self) -> None:
        cover = row(story=COVER_STORY, volume=6, image="213", fanta_page="0", comic_page="")

        bad = self.disagreements(cover)

        assert [(b.column, b.stored, b.derived) for b in bad] == [("Fanta_page", "0", "208")]

    def test_an_image_that_is_not_one_of_the_stories_covers_is_reported(self) -> None:
        cover = row(story=COVER_STORY, volume=6, image="999", fanta_page="", comic_page="")

        assert [b.column for b in self.disagreements(cover)] == ["Image"]


class TestWritingTheFile:
    def test_a_restored_folio_sorts_between_its_neighbours(self) -> None:
        def sort_key(fanta_page: str) -> tuple:
            return row_sort_key(
                [cell if i != FANTA_PAGE else fanta_page for i, cell in enumerate(row().as_cells())]
            )

        assert sort_key("188") < sort_key("188a") < sort_key("189")

    def test_stories_with_no_printed_page_do_not_interleave(self) -> None:
        # Two stories censored out of one volume. Every row keyed alike up to the comic
        # page, so page 1 of each came out before page 2 of either.
        rows = [
            row(story=story, image=image, fanta_page="", comic_page=comic_page).as_cells()
            for story, image, comic_page in (
                ("Story B", "120", "1"),
                ("Story A", "100", "1"),
                ("Story B", "121", "2"),
                ("Story A", "101", "2"),
            )
        ]

        in_order = sorted(rows, key=row_sort_key)

        assert [cells[STORY] for cells in in_order] == ["Story A", "Story A", "Story B", "Story B"]

    def test_every_cell_is_quoted_and_lines_end_in_a_newline(self) -> None:
        assert render_csv([row().as_cells()]).endswith(
            '"18","040","33","3","4","WDCS 194","error","[from]","[to]"\n'
        )


COVER_ROW = row(story=COVER_STORY, volume=6, image="213", fanta_page="208", comic_page="")


class TestLocatingAStory:
    def test_a_title_the_database_does_not_know_is_the_csvs_fault(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # It used to leave the command as an uncaught exception, not an exit code.
        def unknown(_database: object, story: str) -> str:
            msg = f'Could not find title "{story}".'
            raise TitleNotFoundError(msg, story)

        monkeypatch.setattr(censorship_csv, "resolve_censorship_story", unknown)

        with pytest.raises(CensorshipCsvError, match="Could not find title"):
            locate_story(cast("ComicsDatabase", object()), "No Such Story At All")


class TestTheCommand:
    """A CSV in a temporary file, and stories located from `LOCATIONS`.

    The command used to run against the real `ComicsDatabase`, so these passed or failed
    with the state of the library's ini files - and one row of the real "WDCS 194" was
    all they could say. What a story resolves to is `locate_story`'s business and is
    tested there; here it is given.
    """

    @staticmethod
    def run(csv_file: Path, *args: str) -> int:
        result = CliRunner().invoke(censorship_csv.app, ["--csv-file", str(csv_file), *args])
        return result.exit_code

    @pytest.fixture(autouse=True)
    def no_log_files(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(censorship_csv, "init_logging", lambda *_args: None)

    @pytest.fixture(autouse=True)
    def no_real_database(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def locate(_database: object, story: str) -> StoryLocation:
            if story not in LOCATIONS:
                msg = f'Could not find title "{story}".'
                raise CensorshipCsvError(msg)
            return LOCATIONS[story]

        monkeypatch.setattr(censorship_csv, "ComicsDatabase", lambda **_kwargs: object())
        monkeypatch.setattr(censorship_csv, "locate_story", locate)

    @pytest.fixture
    def csv_file(self, tmp_path: Path) -> Path:
        return tmp_path / "fixes.csv"

    def test_check_passes_a_correct_row(self, csv_file: Path) -> None:
        csv_file.write_text(render_csv([row().as_cells()]), encoding="utf-8", newline="")

        assert self.run(csv_file, "--check") == 0

    def test_an_unknown_story_fails_cleanly_and_writes_nothing(self, csv_file: Path) -> None:
        content = render_csv([row(story="No Such Story At All").as_cells()])
        csv_file.write_text(content, encoding="utf-8", newline="")

        result = CliRunner().invoke(censorship_csv.app, ["--csv-file", str(csv_file), "--check"])

        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit)
        assert csv_file.read_text(encoding="utf-8") == content

    def test_a_missing_csv_file_fails_cleanly(self, csv_file: Path) -> None:
        result = CliRunner().invoke(censorship_csv.app, ["--csv-file", str(csv_file), "--check"])

        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit)

    def test_a_contradiction_fails_and_writes_nothing(self, csv_file: Path) -> None:
        content = render_csv([row(fanta_page="154").as_cells()])
        csv_file.write_text(content, encoding="utf-8", newline="")

        assert self.run(csv_file) == 1
        assert csv_file.read_text(encoding="utf-8") == content

    def test_check_reports_a_blank_cell_without_filling_it(self, csv_file: Path) -> None:
        content = render_csv([row(fanta_page="").as_cells()])
        csv_file.write_text(content, encoding="utf-8", newline="")

        assert self.run(csv_file, "--check") == 1
        assert csv_file.read_text(encoding="utf-8") == content

    def test_a_blank_cell_is_filled_in(self, csv_file: Path) -> None:
        csv_file.write_text(
            render_csv([row(fanta_page="").as_cells()]), encoding="utf-8", newline=""
        )

        assert self.run(csv_file) == 0
        assert csv_file.read_text(encoding="utf-8") == render_csv([row().as_cells()])

    def test_check_fails_a_file_out_of_book_order_and_leaves_it(self, csv_file: Path) -> None:
        content = render_csv([row().as_cells(), COVER_ROW.as_cells()])
        csv_file.write_text(content, encoding="utf-8", newline="")

        assert self.run(csv_file, "--check") == 1
        assert csv_file.read_text(encoding="utf-8") == content

    def test_a_file_out_of_book_order_is_rewritten_in_order(self, csv_file: Path) -> None:
        csv_file.write_text(
            render_csv([row().as_cells(), COVER_ROW.as_cells()]), encoding="utf-8", newline=""
        )

        assert self.run(csv_file) == 0
        assert csv_file.read_text(encoding="utf-8") == render_csv(
            [COVER_ROW.as_cells(), row().as_cells()]
        )

    def test_a_correct_file_is_left_byte_for_byte(self, csv_file: Path) -> None:
        content = render_csv([COVER_ROW.as_cells(), row().as_cells()])
        csv_file.write_text(content, encoding="utf-8", newline="")

        assert self.run(csv_file) == 0
        assert csv_file.read_text(encoding="utf-8") == content


class TestTheTwoRowChecksAgree:
    """`barks-censorship-csv --check` and `barks-check-build` judge a row alike.

    The rules for whether a row agrees with its story are written twice: once here as
    cell-by-cell disagreements a rewrite can act on, once in the integrity check as a
    single classified fault. They are different shapes for different jobs, so they are
    not merged - but they had already drifted once, over a story that would not resolve,
    and nothing held them together. Every shape of row is put to both.
    """

    ROWS = (
        ("a correct row", row()),
        ("a wrong volume", row(volume=17)),
        ("a wrong image", row(image="041")),
        ("a blank image", row(image="")),
        ("a page the story does not have", row(image="", fanta_page="", comic_page="99")),
        ("a wrong printed page", row(fanta_page="154")),
        ("a blank printed page", row(fanta_page="")),
        ("a whole-story row", row(image="", fanta_page="", comic_page="")),
        (
            "a cover row",
            row(story=COVER_STORY, volume=6, image="213", fanta_page="208", comic_page=""),
        ),
        (
            "a cover row with an image that is no cover",
            row(story=COVER_STORY, volume=6, image="999", fanta_page="", comic_page=""),
        ),
        (
            "a cover row with a wrong printed page",
            row(story=COVER_STORY, volume=6, image="213", fanta_page="0", comic_page=""),
        ),
    )

    @staticmethod
    def integrity_fault(stored: CensorshipFixRow) -> CensorshipRowFault | None:
        """Judge the row as `check_censorship_fixes_rows` does, from the same location."""
        location = LOCATIONS[stored.story]

        return classify_censorship_row(
            CensorshipRowFacts(
                stored_volume=stored.volume,
                stored_image=stored.image,
                stored_comic_page=stored.comic_page,
                expected_volume=location.volume,
                expected_image=location.images.get(stored.comic_page),
                image_is_unnumbered_page=stored.image in location.unnumbered_images,
                stored_fanta_page=stored.fanta_page,
                expected_fanta_page=get_printed_page(stored.volume, stored.image) or "",
            )
        )

    @pytest.mark.parametrize(("shape", "stored"), ROWS, ids=[shape for shape, _ in ROWS])
    def test_a_row_is_faulted_by_both_or_by_neither(
        self, shape: str, stored: CensorshipFixRow
    ) -> None:
        disagreements = find_disagreements([stored], build_rows([stored], LOCATIONS), LOCATIONS)

        assert bool(disagreements) == (self.integrity_fault(stored) is not None), shape
