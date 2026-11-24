"""Tests for the rows, table and footer the cover and one-pager reports share."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from rich.console import Console

from barks_comic_building.query import collection_report, cover_info, one_pager_info
from barks_comic_building.query.build_state import BUILT_STYLE, NOT_DONE_STYLE
from barks_comic_building.query.collection_report import (
    filter_rows,
    get_collection_state_text,
    get_report_table,
)

if TYPE_CHECKING:
    import pytest
    from barks_fantagraphics.comics_database import ComicsDatabase
    from rich.table import Table

DONE = "R"
NOT_DONE = "C"


@dataclass
class Row:
    name: str
    volume: int | None
    state_flag: str = DONE
    page: str = "227"
    link: str = "501"
    problems: list[str] = field(default_factory=list)


class OneCollectionDatabase:
    def get_comic_book(self, title: str) -> str:
        return title


def rendered(table: Table) -> str:
    console = Console(width=120, record=True, force_terminal=False)
    console.print(table)
    return console.export_text()


class TestFilteringRows:
    ROWS = (Row("a", 7), Row("b", 8, NOT_DONE), Row("c", None), Row("d", 7, NOT_DONE))

    def names(self, volumes: list[int], states: list[str]) -> list[str]:
        return [row.name for row in filter_rows(self.ROWS, volumes, states)]

    def test_no_volumes_keeps_every_volume_and_the_unlocated(self) -> None:
        assert self.names([], [DONE, NOT_DONE]) == ["a", "b", "c", "d"]

    def test_volumes_keep_only_their_rows(self) -> None:
        assert self.names([7], [DONE, NOT_DONE]) == ["a", "d"]

    def test_states_keep_only_their_rows(self) -> None:
        assert self.names([], [NOT_DONE]) == ["b", "d"]

    def test_both_filters_apply_together(self) -> None:
        assert self.names([7], [NOT_DONE]) == ["d"]


class TestTheTable:
    def test_the_reports_own_columns_come_before_the_shared_ones(self) -> None:
        table = get_report_table(["Title", "Kind"], [], DONE)

        assert [column.header for column in table.columns] == [
            "Title",
            "Kind",
            "Vol",
            "Jpgs",
            "Link",
            "State",
            "Problem",
        ]

    def test_a_row_is_its_own_cells_then_the_shared_ones(self) -> None:
        row = Row("a", 7, problems=["no scan", "stale link"])

        text = rendered(get_report_table(["Title"], [(["A Title"], row)], DONE))

        cells = [cell.strip() for cell in text.splitlines()[3].strip("│").split("│")]
        assert cells == ["A Title", "7", "227", "501", DONE, "no scan,stale link"]

    def test_an_unlocated_row_has_no_volume(self) -> None:
        text = rendered(get_report_table(["Title"], [(["A Title"], Row("a", None))], DONE))

        assert [cell.strip() for cell in text.splitlines()[3].strip("│").split("│")][1] == ""

    def test_only_a_row_that_is_not_done_is_in_the_not_done_colour(self) -> None:
        table = get_report_table(
            ["Title"],
            [(["Done"], Row("a", 7)), (["Not done"], Row("b", 7, NOT_DONE))],
            DONE,
        )

        assert [row.style for row in table.rows] == [None, NOT_DONE_STYLE]


class TestTheFooter:
    def footer(self, monkeypatch: pytest.MonkeyPatch, blocker: str | None) -> tuple[str, str]:
        monkeypatch.setattr(collection_report, "get_build_blocker", lambda _comic: blocker)

        return get_collection_state_text(
            cast("ComicsDatabase", OneCollectionDatabase()), "All Covers"
        )

    def test_a_built_collection_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self.footer(monkeypatch, None) == ('"All Covers" is built.', BUILT_STYLE)

    def test_one_that_is_not_built_says_why(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self.footer(monkeypatch, "there is no zip file") == (
            '"All Covers" is NOT built - there is no zip file.',
            NOT_DONE_STYLE,
        )


def test_neither_report_keeps_a_footer_of_its_own() -> None:
    # Each had a copy, word for word but for the collection's name.
    assert not hasattr(cover_info, "get_collection_state_text")
    assert not hasattr(one_pager_info, "get_collection_state_text")
