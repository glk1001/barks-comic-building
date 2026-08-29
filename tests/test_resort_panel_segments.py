"""Tests for the one-off re-sort of legacy panel segments files.

Files written before `barks-batch-panel-bounds` sorted panels hold kumiko's order. The
tool must move exactly the pages whose order differs from ours, honour the same overrides
the writer does, recompute `overall_bounds` only when no override pins it, and touch
nothing on a dry run.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from barks_comic_building.restore.resort_panel_segments import (
    get_resorted_segment_info,
    resort_segments_file,
)

if TYPE_CHECKING:
    from pathlib import Path

# Vol 10 p020 as kumiko emitted it (column-wise); reading order is 1,3,2,4.
KUMIKO_ORDER = [
    [222, 194, 965, 511],
    [222, 731, 994, 780],
    [1189, 194, 885, 648],
    [1218, 868, 856, 647],
]
READING_ORDER = [KUMIKO_ORDER[0], KUMIKO_ORDER[2], KUMIKO_ORDER[1], KUMIKO_ORDER[3]]
LEGACY: dict[str, Any] = {
    "filename": "020_orig.jpg",
    "size": [2216, 3056],
    "numbering": "ltr",
    "gutters": [0, 0],
    "license": None,
    "panels": KUMIKO_ORDER,
    "overall_bounds": [222, 194, 2073, 1514],
}


@pytest.fixture
def override_dir(tmp_path: Path) -> Path:
    d = tmp_path / "bounded"
    d.mkdir()
    return d


@pytest.fixture
def segments_file(tmp_path: Path) -> Path:
    f = tmp_path / "segments" / "020.json"
    f.parent.mkdir()
    f.write_text(json.dumps(LEGACY))
    return f


class TestGetResortedSegmentInfo:
    def test_a_file_already_in_order_is_left_alone(
        self, override_dir: Path, segments_file: Path
    ) -> None:
        info = {**LEGACY, "panels": READING_ORDER}
        assert get_resorted_segment_info(info, override_dir, segments_file) is None

    def test_reorders_and_reports_the_old_numbers(
        self, override_dir: Path, segments_file: Path
    ) -> None:
        result = get_resorted_segment_info(LEGACY, override_dir, segments_file)
        assert result is not None
        new_info, order = result
        assert new_info["panels"] == READING_ORDER
        assert order == [1, 3, 2, 4]
        assert new_info["overall_bounds"] == [222, 194, 2073, 1514]

    def test_recomputes_overall_bounds_unless_overridden(
        self, override_dir: Path, segments_file: Path
    ) -> None:
        info = {**LEGACY, "overall_bounds": [0, 0, 10, 10]}

        result = get_resorted_segment_info(info, override_dir, segments_file)
        assert result is not None
        assert result[0]["overall_bounds"] == [222, 194, 2073, 1514]

        (override_dir / "020-overall-bounds-only.jpg").touch()
        result = get_resorted_segment_info(info, override_dir, segments_file)
        assert result is not None
        assert result[0]["overall_bounds"] == [0, 0, 10, 10]

    def test_honours_a_panel_order_override(self, override_dir: Path, segments_file: Path) -> None:
        (override_dir / "020-panel-order.json").write_text("[4, 3, 2, 1]")

        result = get_resorted_segment_info(LEGACY, override_dir, segments_file)
        assert result is not None
        assert result[0]["panels"] == list(reversed(READING_ORDER))


class TestResortSegmentsFile:
    def test_dry_run_writes_nothing(self, override_dir: Path, segments_file: Path) -> None:
        assert resort_segments_file(segments_file, override_dir, dry_run=True)
        assert json.loads(segments_file.read_text()) == LEGACY

    def test_writes_the_new_order(self, override_dir: Path, segments_file: Path) -> None:
        assert resort_segments_file(segments_file, override_dir, dry_run=False)
        assert json.loads(segments_file.read_text())["panels"] == READING_ORDER

    def test_a_missing_file_is_skipped(self, override_dir: Path, tmp_path: Path) -> None:
        assert not resort_segments_file(tmp_path / "none.json", override_dir, dry_run=False)

    def test_a_linked_file_is_skipped(
        self, override_dir: Path, segments_file: Path, tmp_path: Path
    ) -> None:
        link = tmp_path / "link.json"
        link.symlink_to(segments_file)
        assert not resort_segments_file(link, override_dir, dry_run=False)
        assert json.loads(segments_file.read_text()) == LEGACY
