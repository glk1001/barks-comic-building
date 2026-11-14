"""Tests for the checks a build makes before it deletes the previous build's files."""

from __future__ import annotations

from typing import TYPE_CHECKING

from barks_fantagraphics.comics_consts import PageType
from barks_fantagraphics.page_classes import CleanPage

from barks_comic_building.build.build_comics import find_missing_srce_files

if TYPE_CHECKING:
    from pathlib import Path


class TestFindingMissingSourceFiles:
    """A build that cannot succeed has to be refused while the old one is still whole."""

    def test_a_comic_with_every_source_present_has_none_missing(self, tmp_path: Path) -> None:
        present = tmp_path / "001.png"
        present.touch()

        assert find_missing_srce_files([CleanPage(str(present), PageType.BODY)]) == []

    def test_each_missing_source_is_named_once_in_order(self, tmp_path: Path) -> None:
        present = tmp_path / "001.png"
        present.touch()
        pages = [
            CleanPage(str(tmp_path / "003.png"), PageType.BODY),
            CleanPage(str(present), PageType.BODY),
            CleanPage(str(tmp_path / "002.png"), PageType.BODY),
            CleanPage(str(tmp_path / "003.png"), PageType.BACK_MATTER),
        ]

        assert find_missing_srce_files(pages) == [
            str(tmp_path / "002.png"),
            str(tmp_path / "003.png"),
        ]
