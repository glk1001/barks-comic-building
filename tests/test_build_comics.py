"""Tests for building one comic's pages, and for the batch that builds many.

Nothing here opens or writes an image: the image work is stubbed, and what is tested is
what the builder does around it - what it refuses before deleting the previous build,
how page failures are gathered and reported, and what exit code a batch ends with.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from barks_fantagraphics.comics_consts import PageType
from barks_fantagraphics.page_classes import (
    CleanPage,
    ComicDimensions,
    RequiredDimensions,
    SrceAndDestPages,
)
from barks_fantagraphics.panel_geometry import BoundingBox
from loguru import logger

from barks_comic_building.build import batch_build_comics, build_comics
from barks_comic_building.build.build_comics import (
    BuildError,
    ComicBookBuilder,
    find_missing_srce_files,
)

if TYPE_CHECKING:
    from barks_fantagraphics.comic_book import ComicBook
    from barks_fantagraphics.comics_database import ComicsDatabase


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


class FakeBuildComic:
    def __init__(self, tmp_path: Path) -> None:
        self.dest_dir = tmp_path / "dest"
        self.image_dir = self.dest_dir / "images"
        self.image_dir.mkdir(parents=True)

    def get_dest_dir(self) -> Path:
        return self.dest_dir

    def get_dest_image_dir(self) -> Path:
        return self.image_dir


class FakeImageBuilder:
    """Builds every page except the ones named, which fail as told."""

    def __init__(self, failures: dict[str, Exception]) -> None:
        self._failures = failures

    def get_dest_page_image(
        self, _srce_image: object, srce_page: CleanPage, _dest_page: CleanPage
    ) -> object:
        failure = self._failures.get(Path(srce_page.page_filename).name)
        if failure is not None:
            raise failure

        return object()


def make_builder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failures: dict[str, Exception] | None = None
) -> tuple[ComicBookBuilder, FakeBuildComic, SrceAndDestPages]:
    """Return a builder over two source pages on disk, with image work stubbed out."""
    comic = FakeBuildComic(tmp_path)
    srce_pages = []
    dest_pages = []
    for page_num, name in enumerate(("001.png", "002.png"), start=1):
        srce_file = tmp_path / name
        srce_file.touch()
        srce_pages.append(CleanPage(str(srce_file), PageType.COVER, page_num))
        dest_pages.append(CleanPage(str(comic.image_dir / name), PageType.COVER, page_num))
    pages = SrceAndDestPages(srce_pages, dest_pages)

    builder = ComicBookBuilder.__new__(ComicBookBuilder)
    monkeypatch.setattr(builder, "_comic", comic, raising=False)
    monkeypatch.setattr(builder, "_srce_and_dest_pages", pages, raising=False)
    monkeypatch.setattr(builder, "_image_builder", FakeImageBuilder(failures or {}), raising=False)
    monkeypatch.setattr(builder, "_page_errors", [], raising=False)
    monkeypatch.setattr(builder, "_save_dest_image", lambda *_args: None)
    monkeypatch.setattr(build_comics, "open_image_for_reading", lambda _path: object())

    return builder, comic, pages


class TestProcessingThePages:
    def test_a_missing_source_stops_the_build_before_anything_is_deleted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        builder, comic, pages = make_builder(tmp_path, monkeypatch)
        previous = comic.image_dir / "previous-build.jpg"
        previous.touch()
        Path(pages.srce_pages[1].page_filename).unlink()

        with pytest.raises(BuildError, match="1 source files are missing"):
            builder._process_pages()  # noqa: SLF001

        assert previous.exists()

    def test_a_build_that_can_start_clears_the_previous_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        builder, comic, _pages = make_builder(tmp_path, monkeypatch)
        previous = comic.image_dir / "previous-build.jpg"
        previous.touch()

        builder._process_pages()  # noqa: SLF001

        assert not previous.exists()

    def test_every_failing_page_is_named_in_one_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        failures: dict[str, Exception] = {
            "001.png": FileNotFoundError("no restored file"),
            "002.png": ValueError("too small"),
        }
        builder, _comic, _pages = make_builder(tmp_path, monkeypatch, failures)

        with pytest.raises(BuildError) as raised:
            builder._process_pages()  # noqa: SLF001

        message = str(raised.value)
        assert "2 of 2 pages failed" in message
        assert "no restored file" in message
        assert "too small" in message

    def test_one_failing_page_does_not_stop_the_others_being_tried(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        builder, _comic, _pages = make_builder(
            tmp_path, monkeypatch, {"001.png": FileNotFoundError("gone")}
        )

        with pytest.raises(BuildError, match="1 of 2 pages failed"):
            builder._process_pages()  # noqa: SLF001

    @pytest.mark.parametrize(
        ("failure", "has_traceback"),
        [(FileNotFoundError("gone"), False), (ZeroDivisionError("a bug"), True)],
    )
    def test_only_an_unexpected_failure_keeps_its_traceback(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        failure: Exception,
        has_traceback: bool,
    ) -> None:
        # A data problem already says what to fix; anything else is a bug.
        builder, _comic, pages = make_builder(tmp_path, monkeypatch, {"001.png": failure})
        records: list[bool] = []
        sink = logger.add(lambda msg: records.append(msg.record["exception"] is not None))

        try:
            builder._process_page(pages.srce_pages[0], pages.dest_pages[0])  # noqa: SLF001
        finally:
            logger.remove(sink)

        assert any(records) is has_traceback


class TestAComicWithNoPanels:
    """A collection of full-page images has no panel dimensions to check."""

    @staticmethod
    def _dimensions(
        monkeypatch: pytest.MonkeyPatch, page_type: PageType
    ) -> tuple[SrceAndDestPages, ComicDimensions, RequiredDimensions]:
        pages = SrceAndDestPages([CleanPage("001.png", page_type)], [])
        unset = (pages, ComicDimensions(), RequiredDimensions())
        monkeypatch.setattr(
            build_comics, "get_sorted_srce_and_dest_pages_with_dimensions", lambda *_a, **_k: unset
        )

        return ComicBookBuilder._get_srce_and_dest_pages_and_dimensions(  # noqa: SLF001
            cast("ComicBook", object())
        )

    def test_unset_dimensions_are_accepted_when_no_page_has_panels(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pages, srce_dim, _required_dim = self._dimensions(monkeypatch, PageType.COVER)

        assert srce_dim == ComicDimensions()

    def test_unset_dimensions_are_refused_for_a_page_with_panels(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(AssertionError):
            self._dimensions(monkeypatch, PageType.BODY)


class FailingBuilder:
    """Stands in for `ComicBookBuilder`, failing its build as the class is told to."""

    failure: Exception | None = None

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def build(self) -> None:
        if FailingBuilder.failure is not None:
            raise FailingBuilder.failure


class FakeTitledComic:
    title = "A Title"


class TestTheBatchExitCode:
    @pytest.mark.parametrize(
        ("failure", "exit_code"),
        [(None, 0), (BuildError("1 of 2 pages failed"), 1), (RuntimeError("a bug"), 1)],
    )
    def test_one_comics_outcome_is_its_exit_code(
        self, monkeypatch: pytest.MonkeyPatch, failure: Exception | None, exit_code: int
    ) -> None:
        monkeypatch.setattr(batch_build_comics, "ComicBookBuilder", FailingBuilder)
        FailingBuilder.failure = failure

        assert (
            batch_build_comics.process_comic_book(cast("ComicBook", FakeTitledComic())) == exit_code
        )

    def test_one_failed_comic_fails_the_batch_and_the_rest_still_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outcomes = iter([0, 1, 0])
        built: list[str] = []

        class Database:
            def get_comic_book(self, title: str) -> str:
                return title

        def process(comic: str) -> int:
            built.append(comic)
            return next(outcomes)

        monkeypatch.setattr(batch_build_comics, "process_comic_book", process)

        ret_code = batch_build_comics.process_comic_book_titles(
            cast("ComicsDatabase", Database()), ["A", "B", "C"]
        )

        assert ret_code == 1
        assert built == ["A", "B", "C"]
