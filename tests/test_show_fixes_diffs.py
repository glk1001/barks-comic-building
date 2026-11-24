"""Tests for `barks-show-fixes-diffs`: what it compares, counts and leaves behind.

Three things were wrong, and each made the tool quietly say less than it had found. Diffs
between a scan and its original-size fix were written to disk and then left out of the
count, so a title whose only fixes were of that kind was never reported as having any. A
third, "restored" stage compared a restored page with the file the build uses for it,
which is the same file, so it could not find a diff - but it could raise, on the first
page not restored yet, and end the run for every later title in the volume. And the
downscaled copy of an upscayled fix was written to one fixed name in /tmp, so two runs at
once compared one's scan with the other's fix.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from barks_fantagraphics.comic_book import ModifiedType
from PIL import Image, ImageDraw

from barks_comic_building.query import show_fixes_diffs as sfd

if TYPE_CHECKING:
    import pytest
    from barks_fantagraphics.comics_database import ComicsDatabase

TITLE = "Lost in the Andes!"
PAGE_SIZE = (240, 320)
UPSCALE = 4


def write_page(path: Path, *, edited: bool, scale: int = 1) -> Path:
    """Write a white page with a grey border, and a black square on it if `edited`."""
    width, height = PAGE_SIZE[0] * scale, PAGE_SIZE[1] * scale
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (10 * scale, 10 * scale, width - 10 * scale, height - 10 * scale), outline="grey"
    )
    if edited:
        draw.rectangle((60 * scale, 60 * scale, 120 * scale, 120 * scale), fill="black")

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)

    return path


class FakeComic:
    """A two-page title: page 050 may have an original fix, page 051 an upscayled one."""

    def __init__(self, root: Path, *, original_fix: bool, upscayled_fix: bool) -> None:
        self.scans = [
            write_page(root / "original" / "050.png", edited=False),
            write_page(root / "original" / "051.png", edited=False),
        ]
        self.original_fixes = list(self.scans)
        self.upscayled = [root / "upscayled" / "050.png", root / "upscayled" / "051.png"]
        self.upscayled_fixes = list(self.upscayled)
        self.restored_files_asked_for = False

        if original_fix:
            self.original_fixes[0] = write_page(root / "fixes" / "050.png", edited=True)
        if upscayled_fix:
            self.upscayled_fixes[1] = write_page(
                root / "upscayled-fixes" / "051.png", edited=True, scale=UPSCALE
            )

    def _with_mods(self, files: list[Path], plain: list[Path]) -> list[tuple[Path, ModifiedType]]:
        return [
            (file, ModifiedType.ORIGINAL if file == original else ModifiedType.MODIFIED)
            for file, original in zip(files, plain, strict=True)
        ]

    def get_srce_original_story_files(self, _page_types: list[object]) -> list[Path]:
        return self.scans

    def get_final_srce_original_story_files(
        self, _page_types: list[object]
    ) -> list[tuple[Path, ModifiedType]]:
        return self._with_mods(self.original_fixes, self.scans)

    def get_srce_upscayled_story_files(self, _page_types: list[object]) -> list[Path]:
        return self.upscayled

    def get_final_srce_upscayled_story_files(
        self, _page_types: list[object]
    ) -> list[tuple[Path, ModifiedType]]:
        return self._with_mods(self.upscayled_fixes, self.upscayled)

    def get_final_srce_story_files(self, _page_types: list[object]) -> list[object]:
        # What the removed "restored" stage called, and what raised on an unrestored page.
        self.restored_files_asked_for = True
        msg = "Could not find restored source file"
        raise FileNotFoundError(msg)


class FakeDatabase:
    def __init__(self, comic: FakeComic) -> None:
        self.comic = comic

    def get_comic_book(self, _title: str) -> FakeComic:
        return self.comic


def show_diffs(comic: FakeComic, out_dir: Path) -> tuple[Path, int]:
    return sfd.show_diffs_for_title(cast("ComicsDatabase", FakeDatabase(comic)), TITLE, out_dir)


def test_a_title_with_no_fixes_has_no_diffs_and_writes_nothing(tmp_path: Path) -> None:
    comic = FakeComic(tmp_path / "comic", original_fix=False, upscayled_fix=False)

    title_dir, num_diffs = show_diffs(comic, tmp_path / "out")

    assert num_diffs == 0
    assert not title_dir.exists()


def test_the_diffs_of_an_original_size_fix_are_counted(tmp_path: Path) -> None:
    comic = FakeComic(tmp_path / "comic", original_fix=True, upscayled_fix=False)

    title_dir, num_diffs = show_diffs(comic, tmp_path / "out")

    assert num_diffs > 0
    assert sorted(file.name for file in (title_dir / "orig").iterdir()) == [
        "050-1-srce.png",
        "050-2-fixes.png",
    ]


def test_the_diffs_of_an_upscayled_fix_are_counted(tmp_path: Path) -> None:
    comic = FakeComic(tmp_path / "comic", original_fix=False, upscayled_fix=True)

    title_dir, num_diffs = show_diffs(comic, tmp_path / "out")

    assert num_diffs > 0
    assert sorted(file.name for file in (title_dir / "upscayl").iterdir()) == [
        "051-1-srce.png",
        "051-2-fixes.png",
    ]


def test_both_kinds_of_fix_add_up(tmp_path: Path) -> None:
    only_original = show_diffs(
        FakeComic(tmp_path / "a", original_fix=True, upscayled_fix=False), tmp_path / "out-a"
    )[1]
    only_upscayled = show_diffs(
        FakeComic(tmp_path / "b", original_fix=False, upscayled_fix=True), tmp_path / "out-b"
    )[1]
    both = show_diffs(
        FakeComic(tmp_path / "c", original_fix=True, upscayled_fix=True), tmp_path / "out-c"
    )[1]

    assert both == only_original + only_upscayled


def test_a_title_that_is_not_restored_yet_does_not_end_the_run(tmp_path: Path) -> None:
    comic = FakeComic(tmp_path / "comic", original_fix=True, upscayled_fix=False)

    show_diffs(comic, tmp_path / "out")

    assert not comic.restored_files_asked_for


def test_the_downscaled_fix_is_a_scratch_file_of_this_run_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch_files: list[Path] = []
    real_downscale_jpg = sfd.downscale_jpg

    def downscale_jpg(width: int, height: int, srce_file: Path, dest_file: Path) -> None:
        scratch_files.append(dest_file)
        real_downscale_jpg(width, height, srce_file, dest_file)

    monkeypatch.setattr(sfd, "downscale_jpg", downscale_jpg)

    show_diffs(
        FakeComic(tmp_path / "a", original_fix=False, upscayled_fix=True), tmp_path / "out-a"
    )
    show_diffs(
        FakeComic(tmp_path / "b", original_fix=False, upscayled_fix=True), tmp_path / "out-b"
    )

    first, second = scratch_files
    assert first != second
    assert first.parent != Path("/tmp")  # noqa: S108
    assert not first.exists()
    assert not second.exists()
