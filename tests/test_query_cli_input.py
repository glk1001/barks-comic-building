"""Tests for what the query tools say when they are given options they cannot use.

Most of them said it with a traceback: an `assert` on the volume list, `int("")` on a
page that was not given, a `KeyError` on a title, a `RuntimeError` from a filter. The
option at fault was somewhere in the traceback, or nowhere. They now raise
`typer.BadParameter`, which typer prints as a one-line usage error naming it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import typer
from barks_fantagraphics.barks_titles import ENUM_TO_STR_TITLE, Titles
from barks_fantagraphics.comic_book_info import COVERS, ONE_PAGERS
from typer.testing import CliRunner

from barks_comic_building.cli_setup import get_page_num, get_single_volume
from barks_comic_building.query import (
    fantagraphics_info,
    find_title_from_volume,
    make_empty_configs,
    one_pager_info,
    show_panel_bounds,
    show_volume_page,
)
from barks_comic_building.query.build_state import (
    BUILD_STATE_FLAGS,
    EMPTY_FLAG,
    FIXES_FLAG,
    PAYMENTS_FLAG,
    STORY_STATE_FLAGS,
    get_state_filter,
)
from barks_comic_building.query.make_empty_configs import TOC_PAGE_OFFSET, get_toc_page_ranges

if TYPE_CHECKING:
    from pathlib import Path

USAGE_ERROR = 2

NOT_A_TITLE = "0000 0000 0000"


@pytest.fixture(autouse=True)
def no_logging_and_no_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the tools from opening the log file or the comics library.

    Every case here must be turned away before the library is looked at, so a database
    that cannot be made proves it was.
    """

    def no_database(*_args: object, **_kwargs: object) -> None:
        msg = "The comics database was opened for input that should have been refused."
        raise AssertionError(msg)

    for module in (
        fantagraphics_info,
        find_title_from_volume,
        make_empty_configs,
        one_pager_info,
        show_panel_bounds,
        show_volume_page,
    ):
        monkeypatch.setattr(module, "init_logging", lambda *_args: None)
        monkeypatch.setattr(module, "ComicsDatabase", no_database)


def usage_error(app: typer.Typer, *args: str) -> str:
    """Run a tool, check it refused its options, and return what it said."""
    result = CliRunner().invoke(app, list(args))

    assert result.exit_code == USAGE_ERROR, result.output
    assert not isinstance(result.exception, AssertionError), result.exception

    # Typer wraps the message in a box, breaking it wherever the terminal is narrow.
    return " ".join(result.output.replace("│", " ").split())


class TestASingleVolume:
    def test_one_volume_is_that_volume(self) -> None:
        assert get_single_volume("7") == 7  # noqa: PLR2004

    @pytest.mark.parametrize("volumes", ["", "7-9", "7,9", "seven"], ids=str)
    def test_anything_else_is_refused_by_name(self, volumes: str) -> None:
        with pytest.raises(typer.BadParameter, match="--volume must be a single volume"):
            get_single_volume(volumes)


class TestAPageNumber:
    def test_a_number_is_that_page(self) -> None:
        assert get_page_num("--page", "227") == 227  # noqa: PLR2004

    @pytest.mark.parametrize("page", ["", "227-0", "-3", "p7", "7,8"], ids=str)
    def test_anything_else_is_refused_by_name(self, page: str) -> None:
        with pytest.raises(typer.BadParameter, match="--page must be a single page number"):
            get_page_num("--page", page)


class TestTheFixesFilter:
    def test_no_filter_keeps_titles_with_and_without_fixes(self) -> None:
        assert fantagraphics_info.get_fixes_filter("") == [EMPTY_FLAG, FIXES_FLAG]

    def test_titles_with_fixes_can_be_asked_for(self) -> None:
        assert fantagraphics_info.get_fixes_filter("F") == [FIXES_FLAG]

    def test_titles_without_fixes_can_be_asked_for(self) -> None:
        # There was no way to: the only value accepted was "F".
        assert fantagraphics_info.get_fixes_filter("none") == [EMPTY_FLAG]

    def test_anything_else_is_refused_with_the_values_it_takes(self) -> None:
        with pytest.raises(typer.BadParameter, match='must be "F" or "none": "X"'):
            fantagraphics_info.get_fixes_filter("X")


class TestTheStoryStateFilter:
    def test_a_story_has_every_state_but_payments(self) -> None:
        assert sorted([*STORY_STATE_FLAGS, PAYMENTS_FLAG]) == sorted(BUILD_STATE_FLAGS)
        assert PAYMENTS_FLAG not in STORY_STATE_FLAGS

    def test_the_payments_state_is_refused_for_stories(self) -> None:
        # It was accepted, and gave an empty table: no story is ever in it.
        message = usage_error(fantagraphics_info.app, "--volume", "7", "--built", "$")

        assert 'Not a valid state filter: "$"' in message

    def test_a_refused_state_names_the_ones_that_can_be_asked_for(self) -> None:
        with pytest.raises(typer.BadParameter, match=r"Valid states: X,C,U,R,P,I,B,!\."):
            get_state_filter("Q", STORY_STATE_FLAGS)


class TestTheInfoReportsOptions:
    def test_neither_a_volume_nor_a_title_is_refused(self) -> None:
        message = usage_error(fantagraphics_info.app)

        assert "One of the options --volume and --title is required." in message

    def test_a_volume_and_a_title_together_are_refused(self) -> None:
        message = usage_error(
            fantagraphics_info.app, "--volume", "7", "--title", "Lost in the Andes!"
        )

        assert "mutually exclusive" in message

    def test_a_volume_list_that_is_no_list_is_refused(self) -> None:
        assert "--volume is not a list of volumes" in usage_error(
            fantagraphics_info.app, "--volume", "seven"
        )

    def test_a_title_that_is_no_title_is_refused(self) -> None:
        message = usage_error(fantagraphics_info.app, "--title", NOT_A_TITLE)

        assert f'"{NOT_A_TITLE}" is not a title.' in message

    @pytest.mark.parametrize(
        "title",
        [ONE_PAGERS[0], COVERS[0], Titles.ALL_ONE_PAGERS],
        ids=["one-pager", "cover", "collection"],
    )
    def test_a_title_another_report_covers_is_sent_there(self, title: Titles) -> None:
        message = usage_error(fantagraphics_info.app, "--title", ENUM_TO_STR_TITLE[title])

        assert "Use barks-one-pager-info or barks-cover-info instead." in message

    def test_a_bad_fixes_filter_is_refused(self) -> None:
        assert "--fixes must be" in usage_error(
            fantagraphics_info.app, "--volume", "7", "--fixes", "X"
        )


class TestTheOtherToolsOptions:
    def test_the_one_pager_report_refuses_a_title_that_is_no_one_pager(self) -> None:
        message = usage_error(one_pager_info.app, "--title", "Lost in the Andes!")

        assert 'Title "Lost in the Andes!" is not a one-pager.' in message

    def test_the_panel_bounds_viewer_refuses_a_title_that_is_no_title(self) -> None:
        message = usage_error(show_panel_bounds.app, "--title", NOT_A_TITLE)

        assert f'"{NOT_A_TITLE}" is not a title.' in message

    def test_the_volume_page_viewer_refuses_a_missing_page(self) -> None:
        message = usage_error(show_volume_page.app, "--volume", "7")

        assert "--page must be a single page number" in message

    def test_the_volume_page_viewer_refuses_two_volumes(self) -> None:
        message = usage_error(show_volume_page.app, "--volume", "7-8", "--page", "5")

        assert "--volume must be a single volume" in message

    def test_the_title_finder_refuses_two_volumes(self) -> None:
        assert "--volume must be a single volume" in usage_error(
            find_title_from_volume.app, "7-8", "5"
        )

    def test_the_title_finder_refuses_a_page_that_is_no_number(self) -> None:
        assert "PAGE must be a single page number" in usage_error(
            find_title_from_volume.app, "7", "five"
        )

    def test_the_config_maker_refuses_a_missing_volume(self) -> None:
        assert "--volume must be a single volume" in usage_error(make_empty_configs.app)


class TestWhatTheTitleFinderSays:
    @pytest.fixture
    def found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Make every page of every volume page 3 of one story."""
        monkeypatch.setattr(find_title_from_volume, "ComicsDatabase", lambda: None)
        monkeypatch.setattr(
            find_title_from_volume,
            "get_title_from_volume_page",
            lambda _database, _volume, _page: ("Lost in the Andes!", 3),
        )

    @pytest.mark.usefixtures("found")
    def test_the_title_is_quoted_and_nothing_else_is(self) -> None:
        # It ended in a stray quote: `page 3"`.
        result = CliRunner().invoke(find_title_from_volume.app, ["7", "229"])

        assert result.output.strip() == (
            'For volume 7, page 229, found title "Lost in the Andes!", page 3.'
        )

    def test_it_logs_under_a_name_of_its_own(self) -> None:
        # It shared `barks-verify-title`'s, so the log could not tell the two apart.
        from barks_comic_building.query import verify_title  # noqa: PLC0415

        assert find_title_from_volume.APP_LOGGING_NAME != verify_title.APP_LOGGING_NAME


class TestATableOfContents:
    TOC = (
        {"page_offset": 0},
        {"title": "Duck Luck", "page": 7},
        {"title": "Sitting High", "page": 17},
        {"title": "END", "page": 27},
    )

    def test_a_story_runs_to_the_page_before_the_next_one(self) -> None:
        assert get_toc_page_ranges(list(self.TOC)) == {
            "Duck Luck": (7 + TOC_PAGE_OFFSET, 16 + TOC_PAGE_OFFSET),
            "Sitting High": (17 + TOC_PAGE_OFFSET, 26 + TOC_PAGE_OFFSET),
        }

    def test_the_end_entry_is_no_story(self) -> None:
        assert "END" not in get_toc_page_ranges(list(self.TOC))

    def test_no_table_of_contents_gives_no_ranges(self) -> None:
        assert get_toc_page_ranges([]) == {}
        assert get_toc_page_ranges([{"page_offset": 0}]) == {}

    def test_one_that_does_not_end_in_end_is_refused(self) -> None:
        # Its last story was silently left out, and looking it up raised `KeyError`.
        with pytest.raises(ValueError, match='must end in an "END" entry, not "Sitting High"'):
            get_toc_page_ranges(list(self.TOC[:-1]))


class TestMakingConfigsForATitleTheTocDoesNotHave:
    def test_the_title_is_named_and_no_ini_file_is_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json  # noqa: PLC0415
        from types import SimpleNamespace  # noqa: PLC0415

        volume = 27
        (tmp_path / f"vol-{volume}-toc-gemini.json").write_text(
            json.dumps(list(TestATableOfContents.TOC))
        )
        monkeypatch.setattr(make_empty_configs, "TOC_DIR", tmp_path)

        class Database:
            def get_ini_file(self, title: str) -> Path:
                return tmp_path / f"{title}.ini"

        def story(title: str) -> tuple[str, str, SimpleNamespace, bool]:
            info = SimpleNamespace(
                comic_book_info=SimpleNamespace(is_barks_title=True, title=Titles.DUCK_LUCK)
            )
            return title, "", info, False

        monkeypatch.setattr(make_empty_configs, "ComicsDatabase", Database)
        monkeypatch.setattr(make_empty_configs, "get_titles_and_info", lambda *_a, **_k: [])
        monkeypatch.setattr(
            make_empty_configs,
            "get_issue_titles",
            # The second is spelled as the title list spells it, and not as the TOC does.
            lambda *_args: [story("Duck Luck"), story("Sitting High!")],
        )

        message = usage_error(make_empty_configs.app, "--volume", str(volume))

        assert "These titles are not in the table of contents" in message
        assert '"Sitting High!"' in message
        assert '"Duck Luck"' not in message
        assert list(tmp_path.glob("*.ini")) == []
