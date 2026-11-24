"""Tests for which surviving work files a resumed restore is allowed to carry on from.

A page that fails or is stopped keeps its intermediates so the next run need not repeat
them, and the only test for reusing one used to be that it existed. That let three kinds
of file into a finished page: one made before the tuning changed, one made from the page
as it was before being upscayled again, and one a killed worker never finished writing.
All three ended up under a page stamped with the recipe in force, which then read as
CURRENT and was never looked at again.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from barks_comic_building.restore import restore_pipeline
from barks_comic_building.restore.page_state import (
    INPUT_DATE_KEY,
    INPUT_RECIPE_ID_KEY,
    RECIPE_ID_KEY,
    PageState,
    get_page_status,
)
from barks_comic_building.restore.restore_pipeline import (
    STEP_PREPARE_WORK_FILES,
    STEP_RESIZE,
    RestorePipeline,
)
from barks_comic_building.restore.upscale_state import RECIPE_ID_KEY as UPSCALE_RECIPE_ID_KEY
from barks_comic_building.restore.upscale_state import UPSCALE_DATE_KEY

if TYPE_CHECKING:
    from pathlib import Path

SCALE = 4
PAGE_SIZE = 16
UPSCALE_RECIPE_ID = "cccccccccccc"
FIRST_UPSCALE = "2026-07-29T18:00:00+10:00"
SECOND_UPSCALE = "2026-11-02T09:30:00+11:00"


def write_page(path: Path, size: int, upscale_date: str | None = None) -> Path:
    """Write a png that is not one flat colour, optionally stamped as an upscale."""
    info = PngInfo()
    if upscale_date:
        info.add_text(f"BARKS:{UPSCALE_RECIPE_ID_KEY}", UPSCALE_RECIPE_ID)
        info.add_text(f"BARKS:{UPSCALE_DATE_KEY}", upscale_date)

    Image.linear_gradient("L").convert("RGB").resize((size, size)).save(str(path), pnginfo=info)

    return path


def make_pipeline(
    tmp_path: Path,
    page: str = "110",
    *,
    use_existing_work_files: bool = True,
    upscale_date: str | None = FIRST_UPSCALE,
) -> RestorePipeline:
    """Build a pipeline for one page over whatever is already in `tmp_path`."""
    work_dir = tmp_path / "work"
    out_dir = tmp_path / "restored"
    svg_dir = tmp_path / "svg"
    for directory in (work_dir, out_dir, svg_dir):
        directory.mkdir(exist_ok=True)

    upscayl_file = tmp_path / f"{page}.png"
    if not upscayl_file.is_file():
        write_page(upscayl_file, PAGE_SIZE * SCALE, upscale_date)

    return RestorePipeline(
        work_dir,
        tmp_path / f"{page}.jpg",
        upscayl_file,
        SCALE,
        out_dir / f"{page}.png",
        out_dir / f"{page}-4x.png",
        svg_dir / f"{page}.svg",
        use_existing_work_files=use_existing_work_files,
    )


def leave_work_files(pipeline: RestorePipeline) -> list[Path]:
    """Leave a page's intermediates behind as a finished part 1 would, stamp included."""
    pipeline._prepare_work_files()  # noqa: SLF001
    files = [file for file in pipeline.work_files if file != pipeline.work_stamp_file]
    for file in files:
        if file.suffix == ".png":
            write_page(file, PAGE_SIZE)
        else:
            file.write_text("colour counts")

    return files


class TestWhoseWorkFilesTheyAre:
    def test_a_resume_under_the_same_recipe_and_input_keeps_them(self, tmp_path: Path) -> None:
        files = leave_work_files(make_pipeline(tmp_path))

        make_pipeline(tmp_path)._prepare_work_files()  # noqa: SLF001

        assert all(file.is_file() for file in files)

    def test_a_changed_recipe_discards_them(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        files = leave_work_files(make_pipeline(tmp_path))

        monkeypatch.setattr("barks_comic_building.restore.restore_recipe.SMOOTH_THRESHOLD", 1)
        resumed = make_pipeline(tmp_path)
        resumed._prepare_work_files()  # noqa: SLF001

        assert [file for file in files if file.is_file()] == []
        assert not resumed.errors_occurred

    def test_an_input_upscayled_again_discards_them(self, tmp_path: Path) -> None:
        first = make_pipeline(tmp_path)
        files = leave_work_files(first)
        input_stat = first.srce_upscale_file.stat()

        # The same bytes on disk for the same length of time, so only what the page
        # says about itself has changed.
        write_page(first.srce_upscale_file, PAGE_SIZE * SCALE, SECOND_UPSCALE)
        os.utime(first.srce_upscale_file, ns=(input_stat.st_atime_ns, input_stat.st_mtime_ns))
        make_pipeline(tmp_path)._prepare_work_files()  # noqa: SLF001

        assert [file for file in files if file.is_file()] == []

    def test_a_hand_edited_input_that_changed_discards_them(self, tmp_path: Path) -> None:
        """An input with no upscale to name is pinned down by the file itself."""
        first = make_pipeline(tmp_path, upscale_date=None)
        files = leave_work_files(first)

        input_stat = first.srce_upscale_file.stat()
        os.utime(
            first.srce_upscale_file,
            ns=(input_stat.st_atime_ns, input_stat.st_mtime_ns + 1_000_000_000),
        )
        make_pipeline(tmp_path)._prepare_work_files()  # noqa: SLF001

        assert [file for file in files if file.is_file()] == []

    def test_work_files_with_no_stamp_are_discarded(self, tmp_path: Path) -> None:
        """What every failed page in a work directory looks like before this existed."""
        pipeline = make_pipeline(tmp_path)
        files = leave_work_files(pipeline)
        pipeline.work_stamp_file.unlink()

        make_pipeline(tmp_path)._prepare_work_files()  # noqa: SLF001

        assert [file for file in files if file.is_file()] == []

    def test_an_unreadable_stamp_vouches_for_nothing(self, tmp_path: Path) -> None:
        pipeline = make_pipeline(tmp_path)
        files = leave_work_files(pipeline)
        pipeline.work_stamp_file.write_text('{"recipe_id": "')

        make_pipeline(tmp_path)._prepare_work_files()  # noqa: SLF001

        assert [file for file in files if file.is_file()] == []

    def test_a_plain_run_starts_clean_and_leaves_a_stamp(self, tmp_path: Path) -> None:
        """Or a kill half way would leave its new stamp vouching for the older files."""
        files = leave_work_files(make_pipeline(tmp_path))

        plain = make_pipeline(tmp_path, use_existing_work_files=False)
        plain._prepare_work_files()  # noqa: SLF001

        assert [file for file in files if file.is_file()] == []
        assert plain._read_work_stamp() == plain.work_stamp  # noqa: SLF001

    def test_another_page_s_work_files_are_left_alone(self, tmp_path: Path) -> None:
        other_page = make_pipeline(tmp_path, "111")
        files = leave_work_files(other_page)

        make_pipeline(tmp_path, "110", use_existing_work_files=False)._prepare_work_files()  # noqa: SLF001

        assert all(file.is_file() for file in files)
        assert other_page.work_stamp_file.is_file()

    def test_a_stamp_that_cannot_be_written_fails_the_page(self, tmp_path: Path) -> None:
        pipeline = make_pipeline(tmp_path)
        pipeline.work_stamp_file.mkdir()

        pipeline.do_part1()

        assert pipeline.errors_occurred
        assert pipeline.failed_step == STEP_PREPARE_WORK_FILES
        assert not pipeline.removed_artifacts_file.exists()


class TestWhetherTheyAreWhole:
    def test_a_whole_png_can_be_reused(self, tmp_path: Path) -> None:
        pipeline = make_pipeline(tmp_path)
        write_page(pipeline.inpainted_file, PAGE_SIZE)

        assert pipeline._can_reuse(pipeline.inpainted_file)  # noqa: SLF001

    def test_a_png_cut_short_by_a_kill_cannot(self, tmp_path: Path) -> None:
        pipeline = make_pipeline(tmp_path)
        whole = write_page(pipeline.inpainted_file, PAGE_SIZE).read_bytes()
        pipeline.inpainted_file.write_bytes(whole[: len(whole) // 2])

        assert not pipeline._can_reuse(pipeline.inpainted_file)  # noqa: SLF001

    def test_a_missing_file_cannot(self, tmp_path: Path) -> None:
        pipeline = make_pipeline(tmp_path)

        assert not pipeline._can_reuse(pipeline.inpainted_file)  # noqa: SLF001

    def test_nothing_is_reused_unless_asked(self, tmp_path: Path) -> None:
        pipeline = make_pipeline(tmp_path, use_existing_work_files=False)
        write_page(pipeline.inpainted_file, PAGE_SIZE)

        assert not pipeline._can_reuse(pipeline.inpainted_file)  # noqa: SLF001

    @pytest.mark.parametrize(
        ("svg_text", "expected"),
        [
            ('<svg><path d="M0 0"/>\n</svg>\n', True),
            ('<svg><path d="M0 0"/>\n<path d="M0', False),
            ("", False),
        ],
    )
    def test_the_svg_and_its_render_must_both_be_whole(
        self, tmp_path: Path, svg_text: str, *, expected: bool
    ) -> None:
        pipeline = make_pipeline(tmp_path)
        write_page(pipeline.svg_png_4x_file, PAGE_SIZE)
        pipeline.dest_svg_restored_file.write_text(svg_text)

        reusable = pipeline._can_reuse(  # noqa: SLF001
            pipeline.dest_svg_restored_file, pipeline.svg_png_4x_file
        )

        assert reusable is expected


class TestTheLastStep:
    """The mask is written before the page that says the restore is finished."""

    @pytest.fixture
    def pipeline(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RestorePipeline:
        pipeline = make_pipeline(tmp_path)
        write_page(pipeline.dest_upscayled_restored_file, PAGE_SIZE * SCALE)
        pipeline.dest_svg_restored_file.write_text("<svg></svg>")

        def resize(in_file: Path, scale: int, out_file: Path, metadata: dict[str, str]) -> None:
            info = PngInfo()
            for key, value in metadata.items():
                info.add_text(f"BARKS:{key}", value)
            with Image.open(in_file) as image:
                size = (image.width // scale, image.height // scale)
                image.resize(size).save(str(out_file), pnginfo=info)

        def render(_svg_file: Path, width: int, _height: int, png_file: Path) -> None:
            write_page(png_file, width)

        monkeypatch.setattr(restore_pipeline, "resize_image_file", resize)
        monkeypatch.setattr(restore_pipeline, "svg_file_to_optimized_png", render)

        return pipeline

    def status(self, pipeline: RestorePipeline) -> PageState:
        return get_page_status(
            pipeline.srce_upscale_file,
            pipeline.dest_restored_file,
            pipeline.dest_upscayled_restored_file,
            pipeline.dest_svg_restored_file,
            pipeline.recipe.recipe_id,
            is_hand_restored=False,
        ).state

    def test_a_finished_page_is_current_and_names_its_input(
        self, pipeline: RestorePipeline
    ) -> None:
        pipeline._do_resize_restored_file()  # noqa: SLF001

        assert not pipeline.errors_occurred
        assert self.status(pipeline) is PageState.CURRENT
        with Image.open(pipeline.dest_restored_file) as image:
            assert image.info[f"BARKS:{RECIPE_ID_KEY}"] == pipeline.recipe.recipe_id
            assert image.info[f"BARKS:{INPUT_RECIPE_ID_KEY}"] == UPSCALE_RECIPE_ID
            assert image.info[f"BARKS:{INPUT_DATE_KEY}"] == FIRST_UPSCALE

    def test_a_page_with_no_original_scan_still_gets_its_mask(
        self, pipeline: RestorePipeline
    ) -> None:
        """The mask used to be sized from the scan, which a page added by hand lacks."""
        assert not pipeline.srce_file.exists()

        pipeline._do_resize_restored_file()  # noqa: SLF001

        assert not pipeline.errors_occurred
        with Image.open(pipeline.png_of_svg_file) as mask:
            assert mask.size == (PAGE_SIZE, PAGE_SIZE)

    def test_a_failed_mask_leaves_no_page_claiming_to_be_finished(
        self, pipeline: RestorePipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def render(*_args: object) -> None:
            msg = "oxipng failed"
            raise RuntimeError(msg)

        monkeypatch.setattr(restore_pipeline, "svg_file_to_optimized_png", render)

        pipeline._do_resize_restored_file()  # noqa: SLF001

        assert pipeline.errors_occurred
        assert pipeline.failed_step == STEP_RESIZE
        assert not pipeline.dest_restored_file.exists()
        assert self.status(pipeline) is PageState.INCOMPLETE

    def test_a_page_whose_input_is_then_upscayled_again_is_stale(
        self, pipeline: RestorePipeline
    ) -> None:
        pipeline._do_resize_restored_file()  # noqa: SLF001

        write_page(pipeline.srce_upscale_file, PAGE_SIZE * SCALE, SECOND_UPSCALE)

        assert self.status(pipeline) is PageState.STALE
