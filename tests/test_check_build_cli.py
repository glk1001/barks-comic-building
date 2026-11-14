"""Tests for `barks-check-build`'s option rules and the exit code it hands back.

Four combinations of options are refused before anything is checked, because each would
otherwise be dropped without a word - `--apply` with nothing to apply, a rename run
narrowed to a few titles. None of the four was tested, and a refusal that stops firing
looks, from the command line, exactly like a run that found nothing to do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from barks_comic_building.build import check_build_comics_integrity

if TYPE_CHECKING:
    from collections.abc import Callable

USAGE_ERROR = 2


class FakeChecker:
    """Records how the command built and ran the checker, and answers with a set code."""

    calls: list[dict[str, object]]
    exit_code = 0

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def check_comics_integrity(
        self, titles: list[str], *, fix_names: bool, apply_fixes: bool
    ) -> int:
        FakeChecker.calls.append(
            {"titles": titles, "fix_names": fix_names, "apply_fixes": apply_fixes}
        )
        return FakeChecker.exit_code

    def check_censorship_fixes_csv(self) -> int:
        FakeChecker.calls.append({"censorship_only": True})
        return FakeChecker.exit_code


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> Callable[..., tuple[int, str]]:
    """Run the command with no logging, no database and a recording checker."""
    FakeChecker.calls = []
    FakeChecker.exit_code = 0
    monkeypatch.setattr(check_build_comics_integrity, "init_logging", lambda *_args: None)
    monkeypatch.setattr(check_build_comics_integrity, "ComicsDatabase", object)
    monkeypatch.setattr(check_build_comics_integrity, "ComicsIntegrityChecker", FakeChecker)
    monkeypatch.setattr(
        check_build_comics_integrity,
        "get_comic_titles",
        lambda _volumes, title: (object(), [title or "Every Title In The Volume"]),
    )

    def invoke(*args: str) -> tuple[int, str]:
        result = CliRunner().invoke(check_build_comics_integrity.app, list(args))
        return result.exit_code, result.output

    return invoke


class TestOptionsThatCannotBeCombined:
    def test_apply_needs_fix_names(self, run: Callable[..., tuple[int, str]]) -> None:
        exit_code, output = run("--apply")

        assert exit_code == USAGE_ERROR
        assert "--fix-names" in output
        assert FakeChecker.calls == []

    def test_censorship_only_contradicts_skipping_the_censorship_check(
        self, run: Callable[..., tuple[int, str]]
    ) -> None:
        exit_code, _output = run("--censorship-only", "--no-check-censorship-csv")

        assert exit_code == USAGE_ERROR
        assert FakeChecker.calls == []

    @pytest.mark.parametrize("extra", [("--volume", "7"), ("--title", "A Title"), ("--fix-names",)])
    def test_censorship_only_takes_no_filter_and_no_fix(
        self, run: Callable[..., tuple[int, str]], extra: tuple[str, ...]
    ) -> None:
        exit_code, _output = run("--censorship-only", *extra)

        assert exit_code == USAGE_ERROR
        assert FakeChecker.calls == []

    @pytest.mark.parametrize("extra", [("--volume", "7"), ("--title", "A Title")])
    def test_fix_names_works_on_the_whole_tree(
        self, run: Callable[..., tuple[int, str]], extra: tuple[str, ...]
    ) -> None:
        exit_code, _output = run("--fix-names", *extra)

        assert exit_code == USAGE_ERROR
        assert FakeChecker.calls == []


class TestWhatTheCommandRuns:
    def test_no_filter_checks_every_title(self, run: Callable[..., tuple[int, str]]) -> None:
        exit_code, _output = run()

        assert exit_code == 0
        assert FakeChecker.calls == [{"titles": [], "fix_names": False, "apply_fixes": False}]

    def test_a_title_filter_is_passed_on(self, run: Callable[..., tuple[int, str]]) -> None:
        run("--title", "A Title")

        assert FakeChecker.calls[0]["titles"] == ["A Title"]

    def test_fix_names_and_apply_are_passed_on(self, run: Callable[..., tuple[int, str]]) -> None:
        run("--fix-names", "--apply")

        assert FakeChecker.calls == [{"titles": [], "fix_names": True, "apply_fixes": True}]

    def test_censorship_only_runs_just_that_check(
        self, run: Callable[..., tuple[int, str]]
    ) -> None:
        run("--censorship-only")

        assert FakeChecker.calls == [{"censorship_only": True}]


class TestTheExitCode:
    def test_findings_fail_the_command_with_a_banner(
        self, run: Callable[..., tuple[int, str]]
    ) -> None:
        FakeChecker.exit_code = 1

        exit_code, output = run()

        assert exit_code == 1
        assert "There were errors" in output

    def test_a_dry_run_fix_fails_without_the_error_banner(
        self, run: Callable[..., tuple[int, str]]
    ) -> None:
        # A stale tree on a dry run is not an error of the run's own: it has already said
        # what it would do.
        FakeChecker.exit_code = 1

        exit_code, output = run("--fix-names")

        assert exit_code == 1
        assert "There were errors" not in output
