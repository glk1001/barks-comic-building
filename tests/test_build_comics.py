"""Tests for the checks a build makes before it deletes the previous build's files."""

from __future__ import annotations

from typing import TYPE_CHECKING

from barks_fantagraphics.comics_consts import PageType
from barks_fantagraphics.page_classes import CleanPage
from barks_fantagraphics.panel_geometry import BoundingBox

from barks_comic_building.build import build_comics
from barks_comic_building.build.build_comics import ComicBookBuilder, find_missing_srce_files

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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


class TestTheJpegComments:
    def test_each_panels_bbox_is_written_under_its_own_label(self) -> None:
        # The dest box used to be written under the source label.
        srce_page = CleanPage("/srce/001.png", PageType.BODY)
        srce_page.panels_bbox = BoundingBox(1, 2, 3, 4)
        dest_page = CleanPage("/dest/001.jpg", PageType.BODY)
        dest_page.panels_bbox = BoundingBox(5, 6, 7, 8)

        comments = ComicBookBuilder._get_dest_jpg_comments(srce_page, dest_page)  # noqa: SLF001

        assert any(line.endswith("Srce panels bbox: 1, 2, 3, 4") for line in comments)
        assert any(line.endswith("Dest panels bbox: 5, 6, 7, 8") for line in comments)


class TestTheSummaryIsTheBuildersToWrite:
    """The integrity check requires the summary, so `build` writes it, not its caller."""

    def test_build_writes_the_summary_last(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ran: list[str] = []
        builder = ComicBookBuilder.__new__(ComicBookBuilder)
        for step in (
            "_init_pages",
            "_create_comic_book",
            "_log_comic_book_params",
            "_zip_and_symlink_comic_book",
        ):
            monkeypatch.setattr(builder, step, lambda step=step: ran.append(step))
        for getter in (
            "get_srce_dim",
            "get_required_dim",
            "get_srce_and_dest_pages",
            "get_max_dest_page_timestamp",
        ):
            monkeypatch.setattr(builder, getter, lambda: None)
        monkeypatch.setattr(builder, "_comic", None, raising=False)
        monkeypatch.setattr(
            build_comics, "write_summary_file", lambda *_args: ran.append("summary")
        )

        builder.build()

        assert ran[-2:] == ["_zip_and_symlink_comic_book", "summary"]
