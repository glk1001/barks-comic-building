"""Derive the volume/image/page columns of the censorship-fixes CSV.

The CSV, which ships in `barks_fantagraphics/data`, is hand-maintained: GLK adds a row
naming a story, a page and panel, and the before/after text, and classifies each row as
an error or a censorship fix. Everything else - the Fantagraphics volume, the scan image
stem and the printed book page - is derived here, and the rows are sorted into book
order.

`barks-check-build` reports a row that disagrees with its story as well. This tool is
what fills a blank cell in and puts the file in order; its `--check` also reports those.

The tool is idempotent, so it can be re-run after rows are added, and it writes nothing
when nothing has changed.
"""

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from barks_fantagraphics.censorship_fixes import (
    CENSORSHIP_FIXES_CSV,
    CENSORSHIP_FIXES_HEADER,
    CensorshipFixesError,
    CensorshipFixRow,
    censorship_story_pages,
    read_censorship_fixes,
    resolve_censorship_story,
)
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.printed_pages import get_printed_page
from comic_utils.common_typer_options import LogLevelArg
from rich import box
from rich.console import Console
from rich.table import Table

from barks_comic_building.cli_setup import init_logging

APP_LOGGING_NAME = "cscsv"


_console = Console()


class CensorshipCsvError(Exception):
    """A row could not be resolved to a volume, image or printed page."""


@dataclass(frozen=True, slots=True)
class StoryLocation:
    """Where a story sits in its Fantagraphics volume.

    Attributes:
        title: The canonical DB title.
        volume: The Fantagraphics volume number.
        images: Comic page number to scan image stem, for BODY pages only.
        unnumbered_images: Stems of the story's pages that carry no comic page number -
            its cover and the like.
        printed_page: The story's first printed book page, or None if the story was not
            printed in the volume at all.

    """

    title: str
    volume: int
    images: dict[str, str]
    unnumbered_images: frozenset[str]
    printed_page: str | None


def locate_story(comics_database: ComicsDatabase, story: str) -> StoryLocation:
    """Resolve one CSV story name to its volume, page images and printed start page.

    Args:
        comics_database: The comics database.
        story: The `Story` cell as written in the CSV.

    Returns:
        The story's location in its Fantagraphics volume.

    Raises:
        CensorshipCsvError: If the story cannot be resolved or has no BODY pages.

    """
    try:
        title = resolve_censorship_story(comics_database, story)
        pages = censorship_story_pages(comics_database, title)
    except CensorshipFixesError as e:
        raise CensorshipCsvError(str(e)) from e

    if not pages.body_images:
        msg = f'No BODY pages found for "{title}".'
        raise CensorshipCsvError(msg)

    first_image = pages.body_images[min(pages.body_images, key=int)]

    return StoryLocation(
        title,
        pages.volume,
        pages.body_images,
        pages.unnumbered_images,
        get_printed_page(pages.volume, first_image),
    )


def read_fix_records(file: Path) -> list[CensorshipFixRow]:
    """Read the censorship-fixes CSV.

    Args:
        file: The CSV file.

    Returns:
        The rows as stored.

    Raises:
        CensorshipCsvError: If the file cannot be read.

    """
    try:
        return read_censorship_fixes(file)
    except CensorshipFixesError as e:
        raise CensorshipCsvError(str(e)) from e


def build_rows(
    stored_rows: list[CensorshipFixRow], locations: dict[str, StoryLocation]
) -> list[list[str]]:
    """Rebuild the derived columns of every row.

    A row with no comic page is a fix to a page that has none - a cover, or a splash. Its
    image cannot be derived from anything, so it is the author's to give and is carried
    through; `find_disagreements` is what checks it really is one of that story's
    unnumbered pages. Its printed page follows from the image, once the image is one of
    those pages. A whole-story row has neither, and any other row's cell is left as typed,
    since the image it would be derived from is already reported as wrong.

    Args:
        stored_rows: The rows read from the CSV.
        locations: Story name to resolved location, from `locate_story`.

    Returns:
        One output row per stored row, in `CENSORSHIP_FIXES_HEADER` order and in the
        stored order, so a row can be compared with the one it came from.

    A row naming a page its story does not have derives to blank cells, which
    `find_disagreements` reports as an unfixable disagreement; raising here would stop
    every other row being checked over one typo.

    """
    rows = []
    for row in stored_rows:
        location = locations[row.story]
        if row.comic_page:
            image = location.images.get(row.comic_page, "")
            fanta_page = get_printed_page(location.volume, image) or ""
        elif row.image in location.unnumbered_images:
            image = row.image
            fanta_page = get_printed_page(location.volume, image) or ""
        else:
            image, fanta_page = row.image, row.fanta_page

        rows.append(
            [
                str(location.volume),
                image,
                fanta_page,
                row.comic_page,
                row.panel,
                row.story,
                row.error_type,
                row.change_from,
                row.change_to,
            ]
        )

    return rows


# The columns this tool works out from Story and Comic_page. Everything else in a row is
# authored by hand, so only these can disagree with the story they claim to describe.
DERIVED_COLUMNS = ("Volume", "Image", "Fanta_page")


@dataclass(frozen=True, slots=True)
class RowDisagreement:
    """One derived cell that does not match what the story and page say it should be.

    Attributes:
        line: The row's line in the CSV, counting the header as line 1.
        story: The row's story, for finding it by eye.
        comic_page: The row's page within that story.
        column: Which derived column disagrees.
        stored: The value in the file.
        derived: The value the comics database and the printed-page table give.
        fixable: Whether re-running the tool would settle it. A blank cell with a value
            to fill it with is fixable; a row naming a page its story does not have is
            not, since there is nothing to derive and only the author can say what the
            row meant.

    """

    line: int
    story: str
    comic_page: str
    column: str
    stored: str
    derived: str
    fixable: bool = True


def find_disagreements(
    stored_rows: list[CensorshipFixRow],
    derived_rows: list[list[str]],
    locations: dict[str, StoryLocation],
) -> list[RowDisagreement]:
    """Find every derived cell that disagrees with the row's own story and page.

    A hand-edited Volume, Image or Fanta_page is otherwise invisible: a plain run would
    quietly overwrite it, so nothing would ever say the row had been wrong.

    Args:
        stored_rows: The rows as read from the file.
        derived_rows: The rebuilt rows, in the same order.
        locations: Story name to resolved location, from `locate_story`.

    Returns:
        One entry per disagreeing cell, in file order.

    """
    image_index = CENSORSHIP_FIXES_HEADER.index("Image")

    disagreements = []
    for line, (stored, derived) in enumerate(zip(stored_rows, derived_rows, strict=True), start=2):
        # A row naming a page its story does not have derives a blank image, and a blank
        # stored image would otherwise agree with it - so the typo would be reported by
        # nothing. There is no value to fill the cell with, so the author has to settle it.
        no_such_page = bool(stored.comic_page) and not derived[image_index]
        if no_such_page:
            numbered = sorted(locations[stored.story].images, key=int)
            disagreements.append(
                RowDisagreement(
                    line=line,
                    story=stored.story,
                    comic_page=stored.comic_page,
                    column="Image",
                    stored=stored.image,
                    derived=f"that story has pages {numbered[0]}-{numbered[-1]}",
                    fixable=False,
                )
            )

        # An unnumbered row's image is carried through rather than derived, so comparing
        # it with itself proves nothing. Check it names a page the story actually has.
        if stored.image and not stored.comic_page:
            unnumbered = locations[stored.story].unnumbered_images
            if stored.image not in unnumbered:
                disagreements.append(
                    RowDisagreement(
                        line=line,
                        story=stored.story,
                        comic_page=stored.comic_page,
                        column="Image",
                        stored=stored.image,
                        derived=f"one of {sorted(unnumbered - {'empty_page'})}",
                    )
                )

        stored_cells = stored.as_cells()
        for column in DERIVED_COLUMNS:
            index = CENSORSHIP_FIXES_HEADER.index(column)
            if no_such_page and index == image_index:
                # Already reported above, and with something to act on.
                continue
            if stored_cells[index] != derived[index]:
                disagreements.append(
                    RowDisagreement(
                        line=line,
                        story=stored.story,
                        comic_page=stored.comic_page,
                        column=column,
                        stored=stored_cells[index],
                        derived=derived[index],
                    )
                )

    return disagreements


def print_disagreements(disagreements: list[RowDisagreement]) -> None:
    """Print the derived cells that disagree with their row's story and page.

    Args:
        disagreements: The disagreements, from `find_disagreements`.

    """
    table = Table(
        title="Derived columns that disagree with the row's story and page",
        box=box.ROUNDED,
        header_style="bold red",
        title_style="bold red",
    )
    table.add_column("Line", justify="right")
    table.add_column("Story")
    table.add_column("Comic page", justify="right")
    table.add_column("Column")
    table.add_column("In file")
    table.add_column("Should be")

    for bad in disagreements:
        table.add_row(
            str(bad.line),
            bad.story,
            bad.comic_page,
            bad.column,
            f"[red]{bad.stored or '(blank)'}[/]",
            f"[green]{bad.derived or '(blank)'}[/]",
        )

    _console.print()
    _console.print(table)


def row_sort_key(row: list[str]) -> tuple:
    """Order one output row by where its fix sits in the printed books.

    Volume first, then the printed page, so stories come out in book order and a page's
    panels in reading order. `Fanta_page` is the right key rather than `Image`: a
    restored page can be spliced in out of sequence (`The Bill Collectors` page 3 is
    image 227, folio "188a"), and the folio sorts into place where the image stem would
    not. A row with no printed page at all - a story censored out of its volume - leads
    its volume, since it stands for the whole story rather than a page of it.

    Args:
        row: One output row, in `CENSORSHIP_FIXES_HEADER` order.

    Returns:
        A sort key.

    """

    def cell(name: str) -> str:
        return row[CENSORSHIP_FIXES_HEADER.index(name)]

    def panel_key(panel: str) -> tuple[tuple[int, str], ...]:
        # Every panel written so far is a number or a comma-separated pair of them, but
        # sorting is no place to insist on that: a range or a word orders on its leading
        # digits, and on the text itself after that, rather than raising from inside
        # `sorted` with nothing to say which row was at fault.
        parts = [p.strip() for p in panel.split(",")]
        return tuple(((int(m[0]) if (m := re.match(r"\d+", p)) else 0), p) for p in parts if p)

    fanta_page = cell("Fanta_page")
    folio = re.fullmatch(r"(\d+)([a-z]*)", fanta_page)
    page_key = (int(folio[1]), folio[2]) if folio else (0, "")

    comic_page = cell("Comic_page")

    return (
        int(cell("Volume")),
        bool(fanta_page),
        page_key,
        int(comic_page) if comic_page.isdigit() else 0,
        panel_key(cell("Panel")),
    )


def render_csv(rows: list[list[str]]) -> str:
    """Render the nine-column CSV, quoting every field as the original does.

    Args:
        rows: The data rows, in `CENSORSHIP_FIXES_HEADER` order.

    Returns:
        The complete file content.

    """
    out = io.StringIO(newline="")
    # The file this replaces is LF-terminated; csv.writer defaults to CRLF.
    writer = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(CENSORSHIP_FIXES_HEADER)
    writer.writerows(rows)
    return out.getvalue()


def print_story_summary(rows: list[CensorshipFixRow], locations: dict[str, StoryLocation]) -> None:
    """Print how every distinct story in the CSV was resolved.

    Args:
        rows: The rows read from the CSV.
        locations: Story name to resolved location, from `locate_story`.

    """
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.story] = counts.get(row.story, 0) + 1

    table = Table(
        title="Censorship CSV story resolution",
        box=box.ROUNDED,
        header_style="bold cyan",
        title_style="bold magenta",
    )
    table.add_column("Story")
    table.add_column("Rows", justify="right")
    table.add_column("DB title")
    table.add_column("Vol", justify="right")
    table.add_column("Images")
    table.add_column("Printed pg", justify="right")

    for story, count in counts.items():
        location = locations[story]
        stems = sorted(location.images.values(), key=int)
        printed = location.printed_page or "-"
        table.add_row(
            story,
            str(count),
            location.title if location.title != story else "",
            str(location.volume),
            f"{stems[0]}-{stems[-1]}",
            printed,
        )

    _console.print()
    _console.print(table)


app = typer.Typer()


@app.command(help="Derive the volume/image/page columns of the censorship-fixes CSV")
def main(
    csv_file: Annotated[
        Path, typer.Option("--csv-file", help="The censorship fixes CSV to rewrite.")
    ] = CENSORSHIP_FIXES_CSV,
    check: Annotated[
        bool, typer.Option("--check", help="Resolve and report only; write nothing.")
    ] = False,
    log_level_str: LogLevelArg = "ERROR",
) -> None:
    """Rewrite the censorship-fixes CSV with its derived columns filled in."""
    init_logging(APP_LOGGING_NAME, "censorship-csv.log", log_level_str)

    comics_database = ComicsDatabase(for_building_comics=False)

    stored_rows = read_fix_records(csv_file)
    # Once per distinct story, not once per row: each call loads the story's ini file and
    # walks its pages, and the CSV runs several rows to the story.
    locations = {
        story: locate_story(comics_database, story)
        for story in dict.fromkeys(row.story for row in stored_rows)
    }
    rows = build_rows(stored_rows, locations)

    print_story_summary(stored_rows, locations)

    disagreements = find_disagreements(stored_rows, rows, locations)
    if disagreements:
        print_disagreements(disagreements)

    sorted_rows = sorted(rows, key=row_sort_key)
    # The derived rows either side of the sort, not the stored ones: comparing with what
    # is in the file makes every blank cell awaiting a fill look like a row out of place.
    out_of_order = rows != sorted_rows

    # A blank cell is the tool's to fill in. A cell someone typed is not: the value it
    # disagrees with may be the right one, as it was for Turkey Raffle, where the page
    # was wrong and the image was right. Neither is a blank cell with nothing to fill it.
    conflicts = [bad for bad in disagreements if bad.stored or not bad.fixable]

    _console.print(f"[dim]{len(rows)} rows resolved.[/]")
    if conflicts:
        _console.print(
            f"[red]{len(conflicts)} cell(s) contradict their row's story and page."
            f" Nothing will be rewritten until they are settled.[/]"
        )
        raise typer.Exit(code=1)

    fills = len(disagreements)
    if check:
        if fills:
            _console.print(f"[yellow]{fills} blank cell(s) would be filled in.[/]")
        if out_of_order:
            _console.print("[yellow]The file is not in book order.[/]")
        if fills or out_of_order:
            _console.print("[dim]Re-run without --check to rewrite it.[/]")
            raise typer.Exit(code=1)
        _console.print("[dim]Every derived column agrees, and the file is in order.[/]")
        return

    content = render_csv(sorted_rows)
    if content == csv_file.read_text(encoding="utf-8", newline=""):
        # Nothing derived has changed, so leave the backup alone - re-running the tool
        # must never overwrite a backup that still holds real earlier content.
        _console.print(f"[dim]{csv_file} is already up to date - nothing written.[/]")
        return

    # No backup file: the CSV is tracked in barks-compleat-reader, so git is the
    # history, and an untracked .bak beside it inside `data/` would be clutter.
    csv_file.write_text(content, encoding="utf-8", newline="")
    _console.print(f"[dim]Wrote {len(rows)} rows to[/] [cyan]{csv_file}[/]")


if __name__ == "__main__":
    app()
