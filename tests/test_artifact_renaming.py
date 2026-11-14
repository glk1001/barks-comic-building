"""Tests for the artifact rename safety rule and the keys artifacts are matched on.

`order_moves` refuses any rename that would land on a path that exists, and returns the
rest in a fixed order. There is nothing to order: an artifact's name carries its own
title, so one artifact's destination is never another's source - the last test in this
file pins that premise against the key functions. Getting the rule wrong would silently
destroy built comics, so every accepted set of steps is also replayed against an
in-memory model of the filesystem.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from barks_comic_building.build.artifact_renaming import (
    RenameConflictError,
    RenameStep,
    dest_dir_key,
    order_moves,
    zip_key,
)

DIR = Path("/comics/Chronological")
OTHER_DIR = Path("/comics/Elsewhere")


def p(name: str) -> Path:
    """Return a path in the standard test directory."""
    return DIR / name


def replay(steps: list[RenameStep], occupied: set[Path]) -> set[Path]:
    """Replay steps against an in-memory model, asserting nothing is ever clobbered.

    Args:
        steps: The ordered renames.
        occupied: The paths present before the first step.

    Returns:
        The set of paths present after the last step.

    """
    state = set(occupied)
    for step in steps:
        assert step.src in state, f'Step renames a missing source: "{step.src}".'
        assert step.dst not in state, f'Step clobbers an occupied path: "{step.dst}".'
        state.remove(step.src)
        state.add(step.dst)
    return state


class TestOrderMoves:
    def test_no_moves_gives_no_steps(self) -> None:
        assert order_moves({}, set()) == []

    def test_single_move_into_free_space(self) -> None:
        moves = {p("a"): p("b")}
        steps = order_moves(moves, {p("a")})

        assert steps == [RenameStep(p("a"), p("b"))]
        assert replay(steps, {p("a")}) == {p("b")}

    def test_disjoint_moves_all_go(self) -> None:
        moves = {p("002 B"): p("003 B"), p("001 A"): p("002 A")}
        occupied = {p("001 A"), p("002 B")}
        steps = order_moves(moves, occupied)

        assert replay(steps, occupied) == {p("002 A"), p("003 B")}

    def test_a_move_onto_another_moves_source_is_rejected(self) -> None:
        # A chain. Real artifact names cannot form one, so it is refused rather than
        # unrolled - the machinery that unrolled it guarded a state that never arises.
        with pytest.raises(RenameConflictError, match="already exists"):
            order_moves({p("a"): p("b"), p("b"): p("c")}, {p("a"), p("b")})

    def test_a_swap_is_rejected(self) -> None:
        with pytest.raises(RenameConflictError, match="already exists"):
            order_moves({p("a"): p("b"), p("b"): p("a")}, {p("a"), p("b")})

    def test_move_onto_an_untouched_occupant_is_rejected(self) -> None:
        # "b" exists and is not itself being moved, so nothing can ever vacate it.
        with pytest.raises(RenameConflictError, match="already exists"):
            order_moves({p("a"): p("b")}, {p("a"), p("b")})

    def test_duplicate_destinations_are_rejected(self) -> None:
        with pytest.raises(RenameConflictError, match="share a destination"):
            order_moves({p("a"): p("c"), p("b"): p("c")}, {p("a"), p("b")})

    def test_cross_directory_move_is_rejected(self) -> None:
        # Guards atomicity: a rename across filesystems would fail with EXDEV.
        with pytest.raises(RenameConflictError, match="Cross-directory"):
            order_moves({p("a"): OTHER_DIR / "a"}, {p("a")})

    def test_ordering_is_deterministic(self) -> None:
        # A dry run and the subsequent apply must print identically.
        moves = {p(f"{i:03d} Title {i}"): p(f"{i + 2:03d} Title {i}") for i in range(1, 40)}
        occupied = set(moves)

        steps = order_moves(moves, occupied)

        assert steps == order_moves(dict(reversed(moves.items())), occupied)
        assert [step.src for step in steps] == sorted(moves)

    def test_a_whole_renumbering_never_lands_on_a_live_path(self) -> None:
        # Every title shifts down one - the shape inserting a title produces. Each
        # destination carries its own title, so none is another title's source.
        moves = {p(f"{i:03d} Title {i}"): p(f"{i - 1:03d} Title {i}") for i in range(2, 40)}
        occupied = set(moves)

        assert replay(order_moves(moves, occupied), occupied) == set(moves.values())


class TestMatchKeys:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("212 Trouble Indemnity", "Trouble Indemnity"),
            ("001 Donald Duck Finds Pirate Gold", "Donald Duck Finds Pirate Gold"),
            ("123 You Can't Guess!", "You Can't Guess!"),
            ("456 Ten-Dollar Dither", "Ten-Dollar Dither"),
            ("007 Don Ault - Life Among the Ducks", "Don Ault - Life Among the Ducks"),
            ("042 A Spicy Tale", "A Spicy Tale"),
        ],
    )
    def test_dest_dir_key(self, name: str, expected: str) -> None:
        assert dest_dir_key(name) == expected

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("212 Trouble Indemnity [WDCS 168].cbz", "Trouble Indemnity"),
            ("001 Donald Duck Finds Pirate Gold [FC 9].cbz", "Donald Duck Finds Pirate Gold"),
            ("123 You Can't Guess! [CP 2].cbz", "You Can't Guess!"),
            ("443 George Lucas - An Appreciation [EX 1].cbz", "George Lucas - An Appreciation"),
            # A title containing a bracket: only the final " [" starts the issue.
            ("050 Some [Bracketed] Title [US 12].cbz", "Some [Bracketed] Title"),
        ],
    )
    def test_zip_key(self, name: str, expected: str) -> None:
        assert zip_key(name) == expected

    @pytest.mark.parametrize(
        "name",
        [
            "no number here",
            "12 too few digits",
            "1234 too many digits",
            ".hidden",
            "",
        ],
    )
    def test_unnumbered_names_have_no_key(self, name: str) -> None:
        assert dest_dir_key(name) is None
        assert zip_key(name) is None

    def test_keys_agree_across_artifact_kinds(self) -> None:
        # The dest dir and the zip must resolve to the same key, or a title would be
        # reported as an orphan in one namespace and missing in the other.
        assert dest_dir_key("212 Trouble Indemnity") == zip_key(
            "212 Trouble Indemnity [WDCS 168].cbz"
        )
