"""What the cover and one-pager reports have in common: their rows, table and footer.

`barks-cover-info` and `barks-one-pager-info` each report on the titles of one synthetic
collection, a row a title and a last line saying whether the collection itself is built.
The two were written as copies of each other - the same volume and state filters, the
same five trailing columns, the same footer word for word - so a change to one had to be
remembered in the other. What differs between them is each report's own: its leading
columns and how it finds a row's fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from rich.console import Console
from rich.table import Table
from rich.text import Text

from barks_comic_building.query.build_state import (
    BUILT_STYLE,
    NOT_DONE_STYLE,
    PROBLEM_STYLE,
    get_build_blocker,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from barks_fantagraphics.comics_database import ComicsDatabase

# The columns every collection report ends with, after the report's own, and whether
# each is right-justified.
SHARED_COLUMNS = (
    ("Vol", True),
    ("Jpgs", True),
    ("Link", True),
    ("State", False),
    ("Problem", False),
)


class CollectionRow(Protocol):
    """What a row of either report has, whatever else it carries.

    Attributes:
        volume: The Fantagraphics volume the title is in, or None when it is not located.
        page: Its page in that volume.
        link: The staged page it is built from, or empty.
        state_flag: How far along its report's ladder it is.
        problems: Everything found wrong with its files.

    """

    @property
    def volume(self) -> int | None: ...
    @property
    def page(self) -> str: ...
    @property
    def link(self) -> str: ...
    @property
    def state_flag(self) -> str: ...
    @property
    def problems(self) -> list[str]: ...


def filter_rows[RowT: CollectionRow](
    rows: Iterable[RowT], volumes: list[int], state_filter: list[str]
) -> list[RowT]:
    """Keep the rows the `--volume` and `--state` options ask for.

    Args:
        rows: Every row of the report.
        volumes: Keep only the rows in these volumes; empty keeps every volume.
        state_filter: Keep only the rows whose state flag is one of these.

    Returns:
        The rows that pass both, in the order given.

    """
    return [
        row
        for row in rows
        if (not volumes or row.volume in volumes) and row.state_flag in state_filter
    ]


def get_collection_state_text(
    comics_database: ComicsDatabase, collection_title: str
) -> tuple[str, str]:
    """Get the bottom-line text saying whether a collection is built.

    Args:
        comics_database: The comics database.
        collection_title: The collection's title: "All Covers" or "All One-Pagers".

    Returns:
        The message and the rich style to print it in.

    """
    comic = comics_database.get_comic_book(collection_title)
    blocker = get_build_blocker(comic)
    if blocker is None:
        return f'"{collection_title}" is built.', BUILT_STYLE

    return f'"{collection_title}" is NOT built - {blocker}.', NOT_DONE_STYLE


def get_report_table[RowT: CollectionRow](
    leading_columns: Sequence[str],
    rows: Iterable[tuple[Sequence[str | Text], RowT]],
    done_flag: str,
) -> Table:
    """Return a collection report's table.

    Args:
        leading_columns: The report's own columns, which come first.
        rows: Each row's cells for those columns, with the row itself for the rest.
        done_flag: The state a finished title is in. A row in any other state is
            printed in the not-done colour.

    Returns:
        The table: the report's columns, then `SHARED_COLUMNS`.

    """
    table = Table()
    for column in leading_columns:
        table.add_column(column)
    for column, right_justified in SHARED_COLUMNS:
        table.add_column(column, justify="right" if right_justified else "left")

    for leading_cells, row in rows:
        table.add_row(
            *leading_cells,
            "" if row.volume is None else str(row.volume),
            row.page,
            row.link,
            row.state_flag,
            Text(",".join(row.problems), style=PROBLEM_STYLE),
            style=NOT_DONE_STYLE if row.state_flag != done_flag else None,
        )

    return table


def print_collection_report(
    table: Table, comics_database: ComicsDatabase, collection_title: str
) -> None:
    """Print a collection report: its table, then whether the collection is built.

    Args:
        table: The report's table, from `get_report_table`.
        comics_database: The comics database, to grade the collection with.
        collection_title: The collection's title.

    """
    console = Console()
    console.print(table)

    collection_text, collection_style = get_collection_state_text(comics_database, collection_title)
    console.print(collection_text, style=collection_style)
