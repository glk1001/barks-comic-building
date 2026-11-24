"""Tests for how `barks-edit-page` turns its options into a page and a panel.

The justfile offers three ways to name a page: `edit-volume` (a volume and one of its
pages), `edit-title` (a title and a volume page) and `edit-comic` (a title and one of its
own pages). Only the first worked. `--cp-p` was checked for exclusivity and then never
read, so `edit-comic` always died splitting an empty `--p-p`; and `edit-title` handed its
volume page to a lookup that counts a story's body pages, so page 227 of a volume was
"not valid" for a ten-page story.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
import typer

from barks_comic_building.query import edit_page as ep

if TYPE_CHECKING:
    from barks_fantagraphics.comics_database import ComicsDatabase

TITLE = "Lost in the Andes!"
OTHER_TITLE = "The Golden Christmas Tree"
VOLUME = 7
# The story's body pages, as volume pages: its third page is volume page 229.
BODY_PAGES = ["227", "228", "229"]
OTHER_TITLE_PAGE = "100"

# Every lookup is stood in for below, so there is nothing for a real database to answer.
NO_DATABASE = cast("ComicsDatabase", None)


@pytest.fixture(autouse=True)
def lookups(monkeypatch: pytest.MonkeyPatch) -> None:
    def get_volume_and_page(_db: ComicsDatabase, title: str, page_num_str: str) -> tuple[int, str]:
        assert title == TITLE
        index = int(page_num_str) - 1 if page_num_str else 0
        if not 0 <= index < len(BODY_PAGES):
            msg = f'Page {page_num_str} not valid for "{title}".'
            raise RuntimeError(msg)
        return VOLUME, BODY_PAGES[index]

    def get_title_from_volume_page(_db: ComicsDatabase, volume: int, page: str) -> tuple[str, int]:
        assert volume == VOLUME
        if page in BODY_PAGES:
            return TITLE, BODY_PAGES.index(page) + 1
        if page == OTHER_TITLE_PAGE:
            return OTHER_TITLE, 1
        return "", -1

    monkeypatch.setattr(ep, "get_volume_and_page", get_volume_and_page)
    monkeypatch.setattr(ep, "get_title_from_volume_page", get_title_from_volume_page)


def resolve(
    volume: str = "", title: str = "", p_p: str = "", cp_p: str = ""
) -> tuple[int, str, str, str]:
    return ep.resolve_page_and_panel(NO_DATABASE, volume, title, p_p, cp_p)


def test_a_volume_and_a_volume_page_find_the_title() -> None:
    assert resolve(volume="7", p_p="228-2") == (VOLUME, TITLE, "228", "2")


def test_a_title_and_a_volume_page_name_that_volume_page() -> None:
    assert resolve(title=TITLE, p_p="229-4") == (VOLUME, TITLE, "229", "4")


def test_a_title_and_a_comic_page_name_the_nth_body_page_of_the_story() -> None:
    assert resolve(title=TITLE, cp_p="3-2") == (VOLUME, TITLE, "229", "2")


def test_a_volume_page_of_another_title_is_refused() -> None:
    with pytest.raises(typer.BadParameter, match=OTHER_TITLE):
        resolve(title=TITLE, p_p=f"{OTHER_TITLE_PAGE}-1")


def test_a_volume_page_with_no_story_is_refused() -> None:
    with pytest.raises(typer.BadParameter, match="no story"):
        resolve(volume="7", p_p="5-1")


def test_a_comic_page_past_the_end_of_the_story_is_refused() -> None:
    with pytest.raises(typer.BadParameter, match="not valid"):
        resolve(title=TITLE, cp_p="4-1")


@pytest.mark.parametrize(
    ("volume", "title", "p_p", "cp_p"),
    [
        ("7", TITLE, "228-2", ""),  # both a volume and a title
        ("", "", "228-2", ""),  # neither
        ("", TITLE, "228-2", "2-2"),  # both kinds of page
        ("", TITLE, "", ""),  # no page at all
        ("7", "", "", "2-2"),  # a comic page needs a title
        ("7-8", "", "228-2", ""),  # more than one volume
    ],
)
def test_options_that_do_not_name_one_page_are_refused(
    volume: str, title: str, p_p: str, cp_p: str
) -> None:
    with pytest.raises(typer.BadParameter):
        resolve(volume, title, p_p, cp_p)


# Panel 0 used to index the segments list at -1 and silently crop the last panel.
@pytest.mark.parametrize("page_panel", ["228", "228-", "-2", "228-0", "228-x", "a-2", "228-2-1"])
def test_a_malformed_page_and_panel_is_refused(page_panel: str) -> None:
    with pytest.raises(typer.BadParameter, match="<page>-<panel>"):
        resolve(volume="7", p_p=page_panel)
