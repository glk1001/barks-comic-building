"""Tests for the smaller restore tools telling the truth about what they did.

Each of these used to end the same way whatever had happened: a count of the pages it was
handed, reported as the pages it had done, and an exit code of 0.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image
from typer.testing import CliRunner

from barks_comic_building.restore import batch_restore_pipeline, batch_svg_to_png
from barks_comic_building.restore.batch_svg_to_png import SvgToPngOutcome, convert_svg_to_png
from barks_comic_building.restore.page_state import get_ink_mask_file
from barks_comic_building.restore.restore_pipeline import RestorePipeline
from barks_comic_building.restore.verify_volume_images import verify_volume_dir

if TYPE_CHECKING:
    from pathlib import Path


def write_page(path: Path) -> Path:
    Image.linear_gradient("L").convert("RGB").resize((16, 16)).save(str(path))
    return path


class TestSvgToPng:
    @pytest.fixture
    def rendered(self, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
        made: list[Path] = []

        def render(_svg_file: Path, _width: int, _height: int, png_file: Path) -> None:
            write_page(png_file)
            made.append(png_file)

        monkeypatch.setattr(batch_svg_to_png, "svg_file_to_optimized_png", render)

        return made

    def test_a_page_with_no_mask_is_converted(self, tmp_path: Path, rendered: list[Path]) -> None:
        srce = write_page(tmp_path / "010.png")
        svg = tmp_path / "010.svg"
        svg.write_text("<svg></svg>")

        assert convert_svg_to_png(srce, svg) is SvgToPngOutcome.CONVERTED
        assert rendered == [get_ink_mask_file(svg)]

    def test_a_page_that_has_its_mask_is_skipped_not_converted(
        self, tmp_path: Path, rendered: list[Path]
    ) -> None:
        srce = write_page(tmp_path / "010.png")
        svg = tmp_path / "010.svg"
        svg.write_text("<svg></svg>")
        write_page(get_ink_mask_file(svg))

        assert convert_svg_to_png(srce, svg) is SvgToPngOutcome.SKIPPED
        assert rendered == []

    def test_a_page_with_no_svg_has_failed(self, tmp_path: Path, rendered: list[Path]) -> None:
        srce = write_page(tmp_path / "010.png")

        assert convert_svg_to_png(srce, tmp_path / "010.svg") is SvgToPngOutcome.FAILED
        assert rendered == []


class TestVerifyVolumeDir:
    def test_a_damaged_file_is_counted_as_an_error(self, tmp_path: Path) -> None:
        write_page(tmp_path / "010.png")
        (tmp_path / "011.png").write_bytes(b"not a png")
        (tmp_path / "010.svg").write_text("<svg></svg>")
        (tmp_path / "notes.txt").write_text("not an image")
        (tmp_path / "bounded").mkdir()

        assert verify_volume_dir(tmp_path) == (2, 1)


class TestThePipelineStopsWhereItFailed:
    """The single-page tool calls every part in turn, whatever the last one did."""

    @pytest.fixture
    def pipeline(self, tmp_path: Path) -> RestorePipeline:
        for name in ("work", "restored", "svg"):
            (tmp_path / name).mkdir()
        upscayl_file = write_page(tmp_path / "110.png")

        return RestorePipeline(
            tmp_path / "work",
            tmp_path / "110.jpg",
            upscayl_file,
            4,
            tmp_path / "restored" / "110.png",
            tmp_path / "restored" / "110-4x.png",
            tmp_path / "svg" / "110.svg",
        )

    def test_a_part_after_a_failure_runs_nothing(self, pipeline: RestorePipeline) -> None:
        ran: list[str] = []
        pipeline.errors_occurred = True
        pipeline.failed_step = "smooth"

        pipeline._run_steps(lambda: ran.append("generate svg"))  # noqa: SLF001

        assert ran == []
        assert pipeline.failed_step == "smooth"

    def test_a_part_after_a_stop_runs_nothing(self, pipeline: RestorePipeline) -> None:
        ran: list[str] = []
        pipeline.stopped_early = True

        pipeline._run_steps(lambda: ran.append("generate svg"))  # noqa: SLF001

        assert ran == []

    def test_a_failure_part_way_through_a_part_ends_it(self, pipeline: RestorePipeline) -> None:
        ran: list[str] = []

        def fail() -> None:
            ran.append("inpaint")
            pipeline.errors_occurred = True

        pipeline._run_steps(fail, lambda: ran.append("overlay"))  # noqa: SLF001

        assert ran == ["inpaint"]

    @pytest.mark.parametrize("missing", ["restored", "svg"])
    def test_every_output_directory_is_checked_before_any_work(
        self, tmp_path: Path, missing: str
    ) -> None:
        """Only the first was, so a missing svg directory cost a quarter of an hour."""
        (tmp_path / "work").mkdir()
        for name in ("restored", "restored-4x", "svg"):
            if name != missing:
                (tmp_path / name).mkdir()

        with pytest.raises(FileNotFoundError, match="directory not found"):
            RestorePipeline(
                tmp_path / "work",
                tmp_path / "110.jpg",
                write_page(tmp_path / "110.png"),
                4,
                tmp_path / "restored" / "110.png",
                tmp_path / "restored-4x" / "110-4x.png",
                tmp_path / "svg" / "110.svg",
            )


class TestBatchRestoreArguments:
    @pytest.mark.parametrize("batch_size", ["0", "-1"])
    def test_a_batch_size_below_one_is_refused(self, tmp_path: Path, batch_size: str) -> None:
        """Zero was a traceback from `range`, and a negative size silently restored nothing."""
        result = CliRunner().invoke(
            batch_restore_pipeline.app,
            ["--work-dir", str(tmp_path), "--batch-size", batch_size],
        )

        assert result.exit_code == 2  # noqa: PLR2004
        assert "batch-size" in result.output
