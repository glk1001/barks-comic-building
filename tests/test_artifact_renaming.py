"""Tests for the artifact rename ordering - where the correctness argument lives.

`order_moves` reorders a set of renames so none ever clobbers a live path. Because
the move map is injective with distinct sources, every component of its graph is a
simple path or a simple cycle; paths unroll from the free end, cycles need one temp.
Getting that wrong would silently destroy built comics, so it is tested directly and
also property-tested by replaying the returned steps against an in-memory model of
the filesystem.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from barks_comic_building.build.artifact_renaming import (
    TEMP_SUFFIX,
    RenameConflictError,
    RenameStep,
    dest_dir_key,
    order_moves,
    temp_path_for,
    zip_key,
)

DIR = Path("/comics/Chronological")
OTHER_DIR = Path("/comics/Elsewhere")

# Breaking one cycle costs exactly two temp steps: out to the temp, and back again.
STEPS_PER_CYCLE_BREAK = 2


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

    def test_chain_unrolls_from_the_free_end(self) -> None:
        # a->b->c with c free: c must be vacated... it already is, so b->c goes first.
        moves = {p("a"): p("b"), p("b"): p("c")}
        occupied = {p("a"), p("b")}
        steps = order_moves(moves, occupied)

        assert steps == [RenameStep(p("b"), p("c")), RenameStep(p("a"), p("b"))]
        assert replay(steps, occupied) == {p("b"), p("c")}

    def test_descending_chain(self) -> None:
        # The shape your renumbering actually produces: everything shifts down one.
        moves = {p("002"): p("001"), p("003"): p("002"), p("004"): p("003")}
        occupied = {p("002"), p("003"), p("004")}
        steps = order_moves(moves, occupied)

        assert steps[0] == RenameStep(p("002"), p("001"))
        assert replay(steps, occupied) == {p("001"), p("002"), p("003")}

    def test_ascending_chain(self) -> None:
        # Everything shifts up one: the far end must move first.
        moves = {p("001"): p("002"), p("002"): p("003"), p("003"): p("004")}
        occupied = {p("001"), p("002"), p("003")}
        steps = order_moves(moves, occupied)

        assert steps[0] == RenameStep(p("003"), p("004"))
        assert replay(steps, occupied) == {p("002"), p("003"), p("004")}

    def test_two_cycle_uses_one_temp(self) -> None:
        moves = {p("a"): p("b"), p("b"): p("a")}
        occupied = {p("a"), p("b")}
        steps = order_moves(moves, occupied)

        assert sum(1 for s in steps if s.is_temp) == STEPS_PER_CYCLE_BREAK
        assert replay(steps, occupied) == {p("a"), p("b")}

    def test_three_cycle_uses_one_temp(self) -> None:
        moves = {p("a"): p("b"), p("b"): p("c"), p("c"): p("a")}
        occupied = {p("a"), p("b"), p("c")}
        steps = order_moves(moves, occupied)

        assert sum(1 for s in steps if s.is_temp) == STEPS_PER_CYCLE_BREAK
        assert replay(steps, occupied) == {p("a"), p("b"), p("c")}

    def test_chain_feeding_a_cycle(self) -> None:
        # d->a joins a 3-cycle a->b->c->a. The chain cannot move until the cycle
        # breaks, so this only works if the cycle is handled first.
        moves = {p("a"): p("b"), p("b"): p("c"), p("c"): p("a"), p("d"): p("e")}
        occupied = {p("a"), p("b"), p("c"), p("d")}
        steps = order_moves(moves, occupied)

        assert replay(steps, occupied) == {p("a"), p("b"), p("c"), p("e")}

    def test_disjoint_components(self) -> None:
        moves = {p("a"): p("b"), p("x"): p("y"), p("m"): p("n"), p("n"): p("o")}
        occupied = {p("a"), p("x"), p("m"), p("n")}
        steps = order_moves(moves, occupied)

        assert replay(steps, occupied) == {p("b"), p("y"), p("n"), p("o")}

    def test_move_onto_an_untouched_occupant_is_rejected(self) -> None:
        # "b" exists and is not itself being moved, so nothing can ever vacate it.
        with pytest.raises(RenameConflictError, match="not being moved"):
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
        moves = {p(f"{i:03d}"): p(f"{i + 2:03d}") for i in range(1, 40)}
        occupied = set(moves)

        assert order_moves(moves, occupied) == order_moves(moves, occupied)

    @pytest.mark.parametrize("seed", range(25))
    def test_random_permutation_never_clobbers(self, seed: int) -> None:
        """Any permutation must replay safely and land exactly on the targets."""
        rng = random.Random(seed)
        names = [p(f"{i:03d}") for i in range(rng.randint(2, 30))]
        shuffled = names[:]
        rng.shuffle(shuffled)

        moves = {src: dst for src, dst in zip(names, shuffled, strict=True) if src != dst}
        occupied = set(names)

        # replay() asserts no step ever clobbers or moves a missing source.
        assert replay(order_moves(moves, occupied), occupied) == set(names)

    def test_temp_path_encodes_its_destination(self) -> None:
        # This is what makes an interrupted run recoverable without a journal.
        tmp = temp_path_for(p("212 Foo Bar.cbz"))

        assert tmp.parent == p("212 Foo Bar.cbz").parent
        assert tmp.name.endswith(TEMP_SUFFIX)
        assert tmp.name[: -len(TEMP_SUFFIX)] == "212 Foo Bar.cbz"


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
