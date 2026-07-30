"""Tests for the two findings that no existence or timestamp check could reach.

Both are cases where every file involved is present and the timestamps along the chain
are perfectly consistent, so the report used to describe a clean page:

- A restorable page built from a file *outside* the restored tree. The synthetic
  collections fall back to the staged original scan when a page has not been restored
  yet, so the restored slot resolves to a real, up-to-date file - just the wrong one.
  The only trace is which tree it came from.
- Panel segments older than the hand-drawn bounds override they were computed from. The
  override was an independent dependency, so it raised the source maximum - which dates
  the zip and the info files, but never the one artifact actually derived from it.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from barks_fantagraphics.pages import SrceDependency

from barks_comic_building.build.comics_integrity import (
    has_restored_file_in_chain,
    panel_segments_are_stale,
)

if TYPE_CHECKING:
    from pathlib import Path

OLD = 1_700_000_000.0
NEW = 1_800_000_000.0


def touch_at(path: Path, timestamp: float) -> Path:
    """Create a file with an exact mtime, so the comparison is not clock-dependent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    os.utime(path, (timestamp, timestamp))
    return path


def dependency(file: Path) -> SrceDependency:
    """Make a chain member for `file`. Only its path matters to the helper under test."""
    return SrceDependency(file, OLD, independent=False)


class TestARestorablePagesSource:
    @pytest.fixture
    def restored_dir(self, tmp_path: Path) -> Path:
        restored = tmp_path / "Fantagraphics-restored" / "vol" / "images"
        restored.mkdir(parents=True)
        return restored

    def test_a_page_built_from_its_restored_file_is_fine(self, restored_dir: Path) -> None:
        chain = [dependency(restored_dir / "501.png")]

        assert has_restored_file_in_chain(chain, restored_dir)

    def test_a_page_built_from_the_staged_scan_is_caught(
        self, restored_dir: Path, tmp_path: Path
    ) -> None:
        # What the collections' fallback produces: the fixes tree's scan standing in for
        # a restored file that was never made.
        fixes_scan = tmp_path / "Fantagraphics-fixes-and-additions" / "vol" / "images" / "501.jpg"
        chain = [dependency(fixes_scan)]

        assert not has_restored_file_in_chain(chain, restored_dir)

    def test_the_restored_upscayled_tree_does_not_count(
        self, restored_dir: Path, tmp_path: Path
    ) -> None:
        # A sibling tree, not a subdirectory - so a page with its 4x output but no
        # source-size restored file is still caught.
        upscayled = tmp_path / "Fantagraphics-restored-upscayled" / "vol" / "images" / "501.png"
        chain = [dependency(upscayled)]

        assert not has_restored_file_in_chain(chain, restored_dir)

    def test_an_empty_chain_has_no_restored_file(self, restored_dir: Path) -> None:
        assert not has_restored_file_in_chain([], restored_dir)


class TestPanelSegmentsAgainstABoundsOverride:
    @pytest.fixture
    def segments(self, tmp_path: Path) -> Path:
        return tmp_path / "panel-segments" / "vol" / "117.json"

    @pytest.fixture
    def bounds(self, tmp_path: Path) -> Path:
        return tmp_path / "fixes" / "vol" / "images" / "bounded" / "117.jpg"

    def test_segments_newer_than_the_override_are_fine(self, segments: Path, bounds: Path) -> None:
        touch_at(bounds, OLD)
        touch_at(segments, NEW)

        assert not panel_segments_are_stale(segments, bounds)

    def test_segments_older_than_the_override_are_stale(self, segments: Path, bounds: Path) -> None:
        # The override was hand-edited after the segments were last computed from it.
        touch_at(segments, OLD)
        touch_at(bounds, NEW)

        assert panel_segments_are_stale(segments, bounds)

    def test_equal_timestamps_are_not_stale(self, segments: Path, bounds: Path) -> None:
        # Matches the chain walk, which also treats equal mtime values as up to date.
        touch_at(segments, OLD)
        touch_at(bounds, OLD)

        assert not panel_segments_are_stale(segments, bounds)

    def test_a_page_with_no_override_is_never_stale_this_way(self, segments: Path) -> None:
        touch_at(segments, OLD)

        assert not panel_segments_are_stale(segments, None)

    def test_missing_segments_are_left_to_the_chain(self, segments: Path, bounds: Path) -> None:
        # The chain reports an absent stage with its own sentinel; reporting it a second
        # way here would only pad the report.
        touch_at(bounds, NEW)

        assert not segments.is_file()
        assert not panel_segments_are_stale(segments, bounds)
