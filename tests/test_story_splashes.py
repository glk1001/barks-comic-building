"""Tests for barks-fanta-story-splashes: which pages of a story it calls a splash.

The rule itself is `barks_fantagraphics.splash_pages`, tested where it lives. What is
tested here is that this tool asks it: the tool used to have a rule of its own, which
needed two panels of different sizes to see a splash and so never saw a page that is a
single panel, and which skipped page 1.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from barks_fantagraphics.barks_tags_data import SPLASH_EXCEPTIONS
from barks_fantagraphics.barks_titles import Titles
from barks_fantagraphics.comic_book import ComicBook
from barks_fantagraphics.comic_book_info import NON_COMIC_TITLES
from barks_fantagraphics.comics_consts import PageType
from barks_fantagraphics.pages import TITLE_EMPTY_FILENAME
from barks_fantagraphics.splash_pages import SPLASH_MIN_FRACTION

from barks_comic_building.query.fantagraphics_story_splashes import (
    StorySplashes,
    get_story_splashes,
    has_story_pages,
)
from tests.test_build_state_ladder import Title

if TYPE_CHECKING:
    from pathlib import Path

PAGES = ["050", "051", "052"]

PAGE_WIDTH = 1000
PAGE_HEIGHT = 1500
OVERALL_BOUNDS = [0, 0, PAGE_WIDTH - 1, PAGE_HEIGHT - 1]

# Panels as [x, y, width, height].
EIGHT_PANELS = [[x, y, 500, 375] for y in range(0, PAGE_HEIGHT, 375) for x in (0, 500)]
ONE_PANEL = [[0, 0, PAGE_WIDTH, PAGE_HEIGHT]]
HALF_PAGE_PANEL_AND_FOUR = [
    [0, 0, PAGE_WIDTH, 750],
    *([x, y, 500, 375] for y in (750, 1125) for x in (0, 500)),
]


@pytest.fixture
def story(tmp_path: Path) -> Title:
    """Make a title page and three body pages, every one an ordinary eight-panel page."""
    a_story = Title(
        tmp_path,
        [(TITLE_EMPTY_FILENAME, PageType.TITLE), *((page, PageType.BODY) for page in PAGES)],
    )
    for page in PAGES:
        set_panels(a_story, page, EIGHT_PANELS)

    return a_story


def set_panels(story: Title, page: str, panels: list[list[int]]) -> None:
    segments_file = story.segments(page)
    segments_file.parent.mkdir(parents=True, exist_ok=True)
    segments_file.write_text(json.dumps({"overall_bounds": OVERALL_BOUNDS, "panels": panels}))


def test_a_story_of_ordinary_pages_has_no_splash(story: Title) -> None:
    assert get_story_splashes(story.comic) == StorySplashes()


def test_a_page_that_is_one_panel_is_a_splash(story: Title) -> None:
    set_panels(story, PAGES[1], ONE_PANEL)

    assert get_story_splashes(story.comic).splashes == [PAGES[1]]


def test_a_half_page_panel_is_a_splash(story: Title) -> None:
    set_panels(story, PAGES[2], HALF_PAGE_PANEL_AND_FOUR)

    assert get_story_splashes(story.comic).splashes == [PAGES[2]]


def test_the_first_page_is_judged_like_any_other(story: Title) -> None:
    set_panels(story, PAGES[0], HALF_PAGE_PANEL_AND_FOUR)

    assert get_story_splashes(story.comic).splashes == [PAGES[0]]


def test_the_line_is_the_shared_rules_and_not_one_of_this_tools(story: Title) -> None:
    just_over = [[0, 0, PAGE_WIDTH, int(PAGE_HEIGHT * SPLASH_MIN_FRACTION) + 1]]
    just_under = [[0, 0, PAGE_WIDTH, int(PAGE_HEIGHT * SPLASH_MIN_FRACTION) - 1]]
    set_panels(story, PAGES[1], [*just_over, *EIGHT_PANELS[6:]])
    set_panels(story, PAGES[2], [*just_under, *EIGHT_PANELS[6:]])

    assert get_story_splashes(story.comic).splashes == [PAGES[1]]


class TestExceptions:
    """`SPLASH_EXCEPTIONS` is written in the story's own page numbers, as the reader's are."""

    @pytest.fixture(autouse=True)
    def two_splashes(self, story: Title) -> None:
        """Make the story's first and third pages splashes."""
        set_panels(story, PAGES[0], HALF_PAGE_PANEL_AND_FOUR)
        set_panels(story, PAGES[2], ONE_PANEL)

    def test_an_exempt_page_is_left_out_and_said_to_be(
        self, story: Title, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Page 1 of the story is the volume's page 050.
        monkeypatch.setitem(SPLASH_EXCEPTIONS, Titles.LOST_IN_THE_ANDES, ["1"])

        found = get_story_splashes(story.comic)

        assert found.splashes == [PAGES[2]]
        assert found.exempt == [PAGES[0]]

    def test_an_exception_with_no_pages_leaves_the_whole_title_out(
        self, story: Title, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(SPLASH_EXCEPTIONS, Titles.LOST_IN_THE_ANDES, [])

        found = get_story_splashes(story.comic)

        assert found.splashes == []
        assert found.exempt == [PAGES[0], PAGES[2]]

    def test_an_exception_for_a_page_that_is_no_splash_exempts_nothing(
        self, story: Title, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(SPLASH_EXCEPTIONS, Titles.LOST_IN_THE_ANDES, ["2"])

        found = get_story_splashes(story.comic)

        assert found.splashes == [PAGES[0], PAGES[2]]
        assert found.exempt == []


def test_the_story_under_test_has_no_exception_of_its_own() -> None:
    # Or the tests above would be measuring the real exception and not their own.
    assert Titles.LOST_IN_THE_ANDES not in SPLASH_EXCEPTIONS


def test_a_page_with_no_panel_segments_is_reported_and_the_rest_are_judged(
    story: Title,
) -> None:
    story.segments(PAGES[0]).unlink()
    set_panels(story, PAGES[1], ONE_PANEL)

    found = get_story_splashes(story.comic)

    assert found.not_panelled == [PAGES[0]]
    assert found.splashes == [PAGES[1]]


def test_a_story_with_a_page_still_to_restore_is_judged(story: Title) -> None:
    # Nothing but the panel segments is on disk: no scan, no restored page.
    set_panels(story, PAGES[1], ONE_PANEL)

    assert get_story_splashes(story.comic).splashes == [PAGES[1]]


def test_a_page_with_no_panels_is_no_splash(story: Title) -> None:
    set_panels(story, PAGES[1], [])

    assert get_story_splashes(story.comic) == StorySplashes()


def test_a_story_has_pages_to_judge(story: Title) -> None:
    assert has_story_pages(story.comic)


@pytest.mark.parametrize(
    "title",
    [Titles.ALL_ONE_PAGERS, Titles.ALL_COVERS, next(iter(NON_COMIC_TITLES))],
    ids=["one-pager collection", "cover collection", "article"],
)
def test_a_collection_or_an_article_has_none(
    story: Title, monkeypatch: pytest.MonkeyPatch, title: Titles
) -> None:
    monkeypatch.setattr(ComicBook, "get_title_enum", lambda _self: title)

    assert not has_story_pages(story.comic)
