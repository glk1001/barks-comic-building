"""Tests for the source trees' recursive unexpected-files sweep.

The six source trees (original, upscayled, restored, restored-upscayled, restored-svg,
panel-segments) hold nothing but volume directories of numbered page files, and the
sweep is what catches everything else: a copied volume directory, an `OLD/` backup
tree, a `144.png.corrupt-bak` beside the real page, or a `112-u.png` no pipeline reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from barks_comic_building.build.comics_integrity import (
    ORIGINAL_TREE,
    PANEL_SEGMENTS_TREE,
    RESTORED_SVG_TREE,
    RESTORED_TREE,
    RESTORED_UPSCAYLED_TREE,
    UPSCAYLED_TREE,
    ComicsIntegrityChecker,
    SourceTreeSpec,
    is_expected_page_file,
)

PAGE_FILE_CASES = [
    ("001.jpg", ORIGINAL_TREE, True),
    ("250.jpg", ORIGINAL_TREE, True),
    ("001.png", ORIGINAL_TREE, False),
    ("001.png", UPSCAYLED_TREE, True),
    ("001.png", RESTORED_TREE, True),
    ("001.png", RESTORED_UPSCAYLED_TREE, True),
    ("010.svg", RESTORED_SVG_TREE, True),
    # The svg tree's rendered pngs carry the compound extension, and only that: a bare
    # `.png` in the svg tree is a stray, not a page.
    ("010.svg.png", RESTORED_SVG_TREE, True),
    ("010.png", RESTORED_SVG_TREE, False),
    ("010.json", PANEL_SEGMENTS_TREE, True),
    # The real strays this sweep was added to catch.
    ("112-u.png", UPSCAYLED_TREE, False),
    ("144.png.corrupt-bak", RESTORED_TREE, False),
    ("ComicInfo.xml", ORIGINAL_TREE, False),
    ("notes.txt", RESTORED_TREE, False),
    # A numeric stem alone is not enough - the extension must match the tree.
    ("001.jpg", RESTORED_TREE, False),
    ("001", PANEL_SEGMENTS_TREE, False),
]


class TestIsExpectedPageFile:
    @pytest.mark.parametrize(("name", "spec", "expected"), PAGE_FILE_CASES)
    def test_page_file_pattern(self, name: str, spec: SourceTreeSpec, expected: bool) -> None:
        assert is_expected_page_file(name, spec.page_file_exts) is expected


class TestCheckPageFilesInDir:
    @staticmethod
    def sweep(dir_path: Path) -> int:
        return ComicsIntegrityChecker.check_page_files_in_dir(
            "restored", dir_path, RESTORED_TREE.page_file_exts
        )

    def test_a_directory_of_pages_is_clean(self, tmp_path: Path) -> None:
        for page in ("001.png", "002.png"):
            (tmp_path / page).touch()

        assert self.sweep(tmp_path) == 0

    def test_a_stray_file_is_reported(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        (tmp_path / "001.png").touch()
        (tmp_path / "144.png.corrupt-bak").touch()

        assert self.sweep(tmp_path) == 1
        assert "144.png.corrupt-bak" in capsys.readouterr().out

    def test_a_stray_subdirectory_is_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        (tmp_path / "OLD").mkdir()

        assert self.sweep(tmp_path) == 1
        assert "OLD" in capsys.readouterr().out

    def test_a_missing_directory_is_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        assert self.sweep(tmp_path / "not-there") == 1
        assert "missing" in capsys.readouterr().out
