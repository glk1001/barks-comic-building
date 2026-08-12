"""Tests for grading a page's restore chain against its own inputs.

The fault these exist for is silent and one-directional. Every stage of the pipeline is
made *from* the one before it, but the build ladder used to compare only two adjacent
links - the panel segments against the restored page, and the zip against the panel
segments. A re-upscayl that nothing downstream was re-run over left the middle of the
chain inverted with both of those comparisons still passing, so four titles reported as
built while their zip, their pages and their restored art all predated the upscayled
files they were made from.

The other direction matters just as much. A check that fires on everything is as useless
as one that fires on nothing, and the first cut of this did fire on everything: it
counted a stage that was simply *absent* as an inversion, which condemned every title
whose pages legitimately have no upscayled or svg stage behind them at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from barks_fantagraphics.pages import SrceDependency

from barks_comic_building.query.build_state import (
    on_disk_chain,
    stale_chain_rungs,
)

if TYPE_CHECKING:
    from pathlib import Path

# `get_restored_srce_dependencies` returns the chain latest stage first, and each entry
# carries its own timestamp, so a test can state a whole page's history as a list.
SEGMENTS = "segments"
RESTORED = "restored"
RESTORED_UPSCAYLED = "restored-upscayled"
RESTORED_SVG = "restored-svg"
UPSCAYLED = "upscayled"
ORIGINAL = "original"

# Which rung remakes each tree. The real map comes from the comic's own directory
# accessors; here the trees are named directly so the test says what it means.
PANELS_RUNG = "panels"
RESTORE_RUNG = "restore"
UPSCAYL_RUNG = "upscayl"

# The scan trees are deliberately absent, as they are from the real map: an inverted
# pair always blames its *shallower* file, and the scan is the tail of the chain, so it
# is the one stage that can never be the thing needing remade.
RUNG_BY_TREE = {
    SEGMENTS: PANELS_RUNG,
    RESTORED: RESTORE_RUNG,
    RESTORED_UPSCAYLED: RESTORE_RUNG,
    RESTORED_SVG: RESTORE_RUNG,
    UPSCAYLED: UPSCAYL_RUNG,
}

ALL_TREES = [*RUNG_BY_TREE, ORIGINAL]

MISSING = -1.0


@pytest.fixture
def trees(tmp_path: Path) -> dict[str, Path]:
    """One directory per stage of the pipeline, laid out as the comics root is."""
    return {name: tmp_path / name for name in ALL_TREES}


@pytest.fixture
def rung_by_dir(trees: dict[str, Path]) -> dict[Path, str]:
    return {trees[name]: rung for name, rung in RUNG_BY_TREE.items()}


def chain(trees: dict[str, Path], *stages: tuple[str, float]) -> list[SrceDependency]:
    """Build a page's dependency chain from `(tree, timestamp)` pairs, latest first."""
    return [
        SrceDependency(trees[tree] / "500.png", timestamp, independent=False)
        for tree, timestamp in stages
    ]


def rungs(
    dependencies: list[SrceDependency],
    rung_by_dir: dict[Path, str],
) -> frozenset[str]:
    """Grade one page the way `get_chain_state` does, and return only its verdict."""
    found, _max_srce = stale_chain_rungs(on_disk_chain(dependencies), rung_by_dir, None)

    return found


class TestAChainInOrder:
    def test_timestamps_decreasing_down_the_chain_are_clean(
        self, trees: dict[str, Path], rung_by_dir: dict[Path, str]
    ) -> None:
        # Every stage newer than the one it was made from: the ordinary, correct case.
        page = chain(
            trees,
            (SEGMENTS, 600),
            (RESTORED, 500),
            (RESTORED_UPSCAYLED, 400),
            (RESTORED_SVG, 300),
            (UPSCAYLED, 200),
            (ORIGINAL, 100),
        )

        assert rungs(page, rung_by_dir) == frozenset()

    def test_an_artifact_exactly_as_old_as_its_input_is_not_stale(
        self, trees: dict[str, Path], rung_by_dir: dict[Path, str]
    ) -> None:
        # Matches `is_stale`, so the two cannot disagree on the boundary case.
        page = chain(trees, (RESTORED, 100), (UPSCAYLED, 100), (ORIGINAL, 100))

        assert rungs(page, rung_by_dir) == frozenset()


class TestTheReportedFault:
    """The four volume 6 titles: re-upscayled, with nothing downstream re-run."""

    def test_an_upscayl_newer_than_the_restore_blames_the_restore(
        self, trees: dict[str, Path], rung_by_dir: dict[Path, str]
    ) -> None:
        # The older file of the inverted pair is what needs remaking, so a restore that
        # predates its upscayl is a restore to re-run, not an upscayl.
        page = chain(
            trees,
            (SEGMENTS, 600),
            (RESTORED, 300),
            (RESTORED_UPSCAYLED, 290),
            (RESTORED_SVG, 280),
            (UPSCAYLED, 900),
            (ORIGINAL, 100),
        )

        assert rungs(page, rung_by_dir) == frozenset({RESTORE_RUNG})

    def test_a_rescanned_original_blames_the_upscayl(
        self, trees: dict[str, Path], rung_by_dir: dict[Path, str]
    ) -> None:
        page = chain(trees, (RESTORED, 500), (UPSCAYLED, 400), (ORIGINAL, 900))

        assert rungs(page, rung_by_dir) == frozenset({UPSCAYL_RUNG})

    def test_stale_segments_are_left_to_the_panel_bounds_rung(
        self, trees: dict[str, Path], rung_by_dir: dict[Path, str]
    ) -> None:
        # `has_panel_bounds` already owns this comparison. Counting it here as well
        # would demote a title twice over for one fault.
        page = chain(trees, (SEGMENTS, 100), (RESTORED, 500), (UPSCAYLED, 400))

        assert rungs(page, rung_by_dir) == frozenset({PANELS_RUNG})

    def test_an_unrecognised_tree_is_blamed_on_the_restore(
        self, trees: dict[str, Path], rung_by_dir: dict[Path, str]
    ) -> None:
        # A collection whose restored page is missing falls back to its staged scan,
        # which resolves to a real, present file in a tree the map does not know. Calling
        # that a restore is the actionable answer - it is the restore that never ran.
        page = chain(trees, (ORIGINAL, 300), (UPSCAYLED, 900))

        assert rungs(page, rung_by_dir) == frozenset({RESTORE_RUNG})


class TestAMissingStageIsNotAStaleOne:
    """Absence is the existence rungs' finding, and theirs alone.

    `walk_srce_dependency_chain` reports its missing-stage sentinel as an inversion,
    which is what the integrity report wants. Passed straight through, it condemned
    every title built from pages that never had those stages.
    """

    def test_a_page_with_no_intermediate_stages_is_clean(
        self, trees: dict[str, Path], rung_by_dir: dict[Path, str]
    ) -> None:
        # A hand-restored or added-fixes page: restored art, and the scan behind it.
        page = chain(
            trees,
            (SEGMENTS, 600),
            (RESTORED, 500),
            (RESTORED_UPSCAYLED, MISSING),
            (RESTORED_SVG, MISSING),
            (UPSCAYLED, MISSING),
            (ORIGINAL, 100),
        )

        assert rungs(page, rung_by_dir) == frozenset()

    def test_a_real_inversion_is_still_found_around_a_missing_stage(
        self, trees: dict[str, Path], rung_by_dir: dict[Path, str]
    ) -> None:
        # Skipping the absent stages must not skip the comparison across them.
        page = chain(
            trees,
            (RESTORED, 300),
            (RESTORED_UPSCAYLED, MISSING),
            (RESTORED_SVG, MISSING),
            (UPSCAYLED, 900),
            (ORIGINAL, 100),
        )

        assert rungs(page, rung_by_dir) == frozenset({RESTORE_RUNG})

    def test_a_page_with_nothing_on_disk_grades_nothing(
        self, trees: dict[str, Path], rung_by_dir: dict[Path, str]
    ) -> None:
        page = chain(trees, (RESTORED, MISSING), (UPSCAYLED, MISSING))

        assert on_disk_chain(page) == []
        assert rungs(page, rung_by_dir) == frozenset()


class TestIndependentDependencies:
    def test_they_are_kept_out_of_the_chain(
        self, trees: dict[str, Path], rung_by_dir: dict[Path, str]
    ) -> None:
        # A hand-drawn bounds override is not a stage: nothing is derived from it, so
        # putting it in the chain would make the restored page compare against it and
        # mask the real fault. It is graded by `panel_segments_are_stale` instead.
        page = chain(trees, (SEGMENTS, 600), (RESTORED, 500), (UPSCAYLED, 400))
        override = SrceDependency(trees[SEGMENTS] / "bounds.json", 9999, independent=True)

        assert rungs([page[0], override, *page[1:]], rung_by_dir) == frozenset()


class TestTheNewestSourceIsCollected:
    def test_the_maximum_names_the_file_it_came_from(
        self, trees: dict[str, Path], rung_by_dir: dict[Path, str]
    ) -> None:
        # The build is dated against this, so it has to be able to name the file - that
        # is what `MaxTimestamp` bundles together.
        newest = 900.0
        page = chain(trees, (SEGMENTS, 600), (RESTORED, 300), (UPSCAYLED, newest))

        _rungs, max_srce = stale_chain_rungs(on_disk_chain(page), rung_by_dir, None)

        assert max_srce is not None
        assert max_srce.timestamp == newest
        assert max_srce.file == trees[UPSCAYLED] / "500.png"

    def test_a_missing_stage_is_never_the_newest_input(
        self, trees: dict[str, Path], rung_by_dir: dict[Path, str]
    ) -> None:
        # The sentinel is lower than every real timestamp, so folding it in unguarded
        # would be harmless - but naming an absent file as the newest input would not.
        newest = 500.0
        page = chain(trees, (RESTORED, newest), (UPSCAYLED, MISSING), (ORIGINAL, 100))

        _rungs, max_srce = stale_chain_rungs(on_disk_chain(page), rung_by_dir, None)

        assert max_srce is not None
        assert max_srce.timestamp == newest
        assert max_srce.file == trees[RESTORED] / "500.png"
