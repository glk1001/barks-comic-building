"""Tests for deriving the censorship-fixes CSV's columns from a row's story and page.

The volume, image and printed page of a row all follow from the story and comic page GLK
writes down, so this tool fills them in. What it must not do is quietly overwrite a typed
cell that disagrees, since the typed value may be the right one - so a blank cell is
filled, and a contradiction stops the rewrite until someone has looked at it.
"""

from pathlib import Path

import pytest
from barks_fantagraphics.censorship_fixes import CENSORSHIP_FIXES_HEADER, CensorshipFixRow
from typer.testing import CliRunner

from barks_comic_building.build import censorship_csv
from barks_comic_building.build.censorship_csv import (
    StoryLocation,
    build_rows,
    find_disagreements,
    render_csv,
    row_sort_key,
)

FANTA_PAGE = CENSORSHIP_FIXES_HEADER.index("Fanta_page")
IMAGE = CENSORSHIP_FIXES_HEADER.index("Image")

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

    def test_every_cell_is_quoted_and_lines_end_in_a_newline(self) -> None:
        assert render_csv([row().as_cells()]).endswith(
            '"18","040","33","3","4","WDCS 194","error","[from]","[to]"\n'
        )


class TestTheCommand:
    """The real database, and a CSV of one row in a temporary file."""

    @staticmethod
    def run(csv_file: Path, *args: str) -> int:
        result = CliRunner().invoke(censorship_csv.app, ["--csv-file", str(csv_file), *args])
        return result.exit_code

    @pytest.fixture(autouse=True)
    def no_log_files(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(censorship_csv, "init_logging", lambda *_args: None)

    @pytest.fixture
    def csv_file(self, tmp_path: Path) -> Path:
        return tmp_path / "fixes.csv"

    def test_check_passes_a_correct_row(self, csv_file: Path) -> None:
        csv_file.write_text(render_csv([row().as_cells()]), encoding="utf-8", newline="")

        assert self.run(csv_file, "--check") == 0

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
