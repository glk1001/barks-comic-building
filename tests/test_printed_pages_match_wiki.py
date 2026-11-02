"""Tests that the printed-page table still agrees with the barks-wiki contents table.

`barks_fantagraphics.printed_pages` began as the INDUCKS printed pages in barks-wiki's
generated `ccbdl-contents.md`, and is now maintained on its own. These tests are what stop
the two drifting apart. They need the sibling repo, and skip with a reason without it.

The contents table has rows the printed-page table should not reproduce: a story's second
appearance or excerpt in a volume's back matter is printed somewhere other than the images
its `DB body` column names, and two gags are printed in a different volume from the one the
database files them in. `EXPLAINED_ROWS` lists them all, so a new mismatch fails rather
than joining them unnoticed - and an entry that stops being a mismatch fails too.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest
from barks_fantagraphics.censorship_fixes import censorship_story_pages
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.printed_pages import get_printed_page

CONTENTS_FILE: Final = (
    Path(__file__).parents[2] / "barks-wiki" / "okf" / "reference" / "data" / "ccbdl-contents.md"
)

# Vol | Pg | Type | Title | Pp | INDUCKS code | DB title | DB body | delta
CONTENTS_COLUMNS: Final = 9

# The `(volume, Pg)` of each contents row whose printed page is not on its `DB body` image.
EXPLAINED_ROWS: Final[frozenset[tuple[int, str]]] = frozenset(
    {
        (2, "229"),  # "Kite Weather": a second appearance, in the back matter.
        (3, "231a"),  # An excerpt of "The Firebug".
        (8, "25"),  # "Fractious Fun": printed in volume 8, filed in volume 7.
        (8, "26"),  # "King-Size Cone": printed in volume 8, filed in volume 7.
        (12, "48"),  # The restored excerpt of "Back to the Klondike".
        (13, "1a"),  # An excerpt of "Trick or Treat".
        (15, "233"),  # "Donald Duck Tells About Kites": a second appearance, in the back matter.
        (20, "120a"),  # An excerpt of "High Rider".
        (25, "200"),  # "Peril of the Black Forest": a second appearance, in the back matter.
        (25, "201"),  # "Whale of a Good Deed": a second appearance, in the back matter.
        (25, "203"),  # "Let Sleeping Bones Lie": a second appearance, in the back matter.
        (26, "183"),  # "That's No Fable!": a second appearance, in the back matter.
    }
)

# Its page 3 is the restored page, so pages after it are not `first page + n - 1`. Each of
# its pages is still right on its own, which the table's unit tests pin.
STORIES_NOT_PRINTED_IN_RUNS: Final = frozenset({"The Bill Collectors"})

MIN_EXPECTED_ROWS: Final = 600
MIN_EXPECTED_STORY_PAGES: Final = 5000


@dataclass(frozen=True, slots=True)
class ContentsRow:
    """One contents-table row that the wiki matched to a page in the database."""

    volume: int
    printed_page: str
    db_title: str
    db_body: str


def _read_contents_rows() -> list[ContentsRow]:
    if not CONTENTS_FILE.is_file():
        pytest.skip(f'The barks-wiki contents table is not at "{CONTENTS_FILE}".')

    rows = []
    for line in CONTENTS_FILE.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == CONTENTS_COLUMNS and cells[0].isdigit() and cells[7].isdigit():
            rows.append(ContentsRow(int(cells[0]), cells[1], cells[6], cells[7]))

    return rows


@pytest.fixture(scope="module")
def contents_rows() -> list[ContentsRow]:
    return _read_contents_rows()


def test_the_contents_table_was_really_read(contents_rows: list[ContentsRow]) -> None:
    # Otherwise a change to the table's layout would pass every test below by reading nothing.
    assert len(contents_rows) >= MIN_EXPECTED_ROWS


def test_every_contents_row_gives_the_printed_page(contents_rows: list[ContentsRow]) -> None:
    disagreements = [
        (row, get_printed_page(row.volume, row.db_body))
        for row in contents_rows
        if (row.volume, row.printed_page) not in EXPLAINED_ROWS
        and get_printed_page(row.volume, row.db_body) != row.printed_page
    ]

    assert disagreements == []


def test_every_explained_row_is_still_a_real_row_and_still_differs(
    contents_rows: list[ContentsRow],
) -> None:
    rows = {(row.volume, row.printed_page): row for row in contents_rows}

    assert set(rows) >= EXPLAINED_ROWS
    assert [
        key
        for key in EXPLAINED_ROWS
        if get_printed_page(key[0], rows[key].db_body) == rows[key].printed_page
    ] == []


def test_every_page_of_every_story_is_in_step_with_its_first(
    contents_rows: list[ContentsRow],
) -> None:
    # The contents table only gives each story's first page. A step inside a story, or a
    # story whose images are not contiguous, shows up on a later page.
    comics_database = ComicsDatabase(for_building_comics=False)
    first_pages = {
        (row.volume, row.db_title, int(row.db_body)): row.printed_page
        for row in contents_rows
        if (row.volume, row.printed_page) not in EXPLAINED_ROWS
    }

    compared = 0
    disagreements = []
    for title in comics_database.get_all_story_titles():
        if title in STORIES_NOT_PRINTED_IN_RUNS:
            continue

        pages = censorship_story_pages(comics_database, title)
        if not pages.body_images:
            continue

        first_image = pages.body_images[min(pages.body_images, key=int)]
        first_page = first_pages.get((pages.volume, title, int(first_image)))
        if first_page is None:
            continue

        for comic_page, image in pages.body_images.items():
            compared += 1
            expected = str(int(first_page) + int(comic_page) - 1)
            if get_printed_page(pages.volume, image) != expected:
                disagreements.append((title, comic_page, image, expected))

    assert compared >= MIN_EXPECTED_STORY_PAGES
    assert disagreements == []


def test_explained_rows_are_written_the_way_the_table_writes_them() -> None:
    # Pg is the only key, and a folio such as "231a" is easy to mistype as a number.
    assert all(re.fullmatch(r"\d+[a-z]?", page) for _volume, page in EXPLAINED_ROWS)
