"""Tests for the integrity checker's read of a panel segments file.

The panel index is the public panel number - the censorship CSV, the OCR groups and the
search index all name panels by it - so the file must hold the panels in *our* reading
order, and the geometry must add up. `check_panel_segments_file` is the I/O shell around
the pure validator in `comic_utils.panel_segmentation`; these tests cover the shell: what
counts as a fault at this level, how the overrides reach the validator, and that the
opt-in image-size check only runs when asked.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from PIL import Image

from barks_comic_building.build.comics_integrity import check_panel_segments_file

if TYPE_CHECKING:
    from pathlib import Path

# Vol 10 p020 in reading order (kumiko had emitted it column-wise).
PANELS = [[222, 194, 965, 511], [1189, 194, 885, 648], [222, 731, 994, 780], [1218, 868, 856, 647]]
VALID: dict[str, Any] = {
    "filename": "020_orig.jpg",
    "size": [2216, 3056],
    "numbering": "ltr",
    "gutters": [0, 0],
    "license": None,
    "panels": PANELS,
    "overall_bounds": [222, 194, 2073, 1514],
}


@pytest.fixture
def segments_file(tmp_path: Path) -> Path:
    return tmp_path / "020.json"


def check(segments_file: Path, **kwargs: Any) -> tuple[str, ...]:  # noqa: ANN401
    kwargs.setdefault("has_overall_bounds_override", False)
    kwargs.setdefault("panel_order_file", None)
    kwargs.setdefault("restored_image", None)
    return check_panel_segments_file(segments_file, **kwargs)


class TestWhatCountsAsAFault:
    def test_a_valid_file_has_none(self, segments_file: Path) -> None:
        segments_file.write_text(json.dumps(VALID))
        assert check(segments_file) == ()

    def test_a_missing_file_is_not_this_checks_business(self, segments_file: Path) -> None:
        assert check(segments_file) == ()

    def test_malformed_json(self, segments_file: Path) -> None:
        segments_file.write_text("{not json")
        (fault,) = check(segments_file)
        assert "JSON" in fault

    def test_json_that_is_not_an_object(self, segments_file: Path) -> None:
        segments_file.write_text("[1, 2]")
        (fault,) = check(segments_file)
        assert "not an object" in fault

    def test_panels_out_of_reading_order(self, segments_file: Path) -> None:
        segments_file.write_text(
            json.dumps({**VALID, "panels": [PANELS[0], PANELS[2], PANELS[1], PANELS[3]]})
        )
        (fault,) = check(segments_file)
        assert fault.startswith("Panels are not in reading order - by their current numbers")
        assert "[1, 3, 2, 4]" in fault


class TestOverridesReachTheValidator:
    def test_a_matching_panel_order_override(self, tmp_path: Path, segments_file: Path) -> None:
        segments_file.write_text(
            json.dumps({**VALID, "panels": [PANELS[0], PANELS[2], PANELS[1], PANELS[3]]})
        )
        order_file = tmp_path / "020-panel-order.json"
        order_file.write_text("[1, 3, 2, 4]")

        assert check(segments_file, panel_order_file=order_file) == ()

    def test_an_unreadable_panel_order_override(self, tmp_path: Path, segments_file: Path) -> None:
        segments_file.write_text(json.dumps(VALID))
        order_file = tmp_path / "020-panel-order.json"
        order_file.write_text('["a"]')

        (fault,) = check(segments_file, panel_order_file=order_file)
        assert fault.startswith("Bad panel order override")

    def test_overall_bounds_override_allows_a_mismatch(self, segments_file: Path) -> None:
        segments_file.write_text(json.dumps({**VALID, "overall_bounds": [200, 190, 2100, 1600]}))

        assert check(segments_file) != ()
        assert check(segments_file, has_overall_bounds_override=True) == ()


class TestTheImageSizeCheckIsOptIn:
    @pytest.fixture
    def restored_image(self, tmp_path: Path) -> Path:
        image = tmp_path / "020.png"
        Image.new("RGB", (2216, 3000)).save(image)  # 56 px shorter than the json says
        return image

    def test_runs_when_an_image_is_given(self, segments_file: Path, restored_image: Path) -> None:
        segments_file.write_text(json.dumps(VALID))
        (fault,) = check(segments_file, restored_image=restored_image)
        assert fault == "Page size does not match the image: image 2216x3000, size 2216x3056."

    def test_skipped_without_one(self, segments_file: Path) -> None:
        segments_file.write_text(json.dumps(VALID))
        assert check(segments_file) == ()
