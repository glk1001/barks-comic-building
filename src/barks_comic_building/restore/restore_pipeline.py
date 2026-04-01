from __future__ import annotations

import contextlib
import time
from pathlib import Path
from typing import TYPE_CHECKING

import cv2 as cv
from barks_fantagraphics.comics_utils import get_clean_path
from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Generator

from barks_comic_building.restore.image_io import (
    resize_image_file,
    svg_file_to_png,
    write_cv_image_file,
)
from barks_comic_building.restore.inpaint import inpaint_image_file
from barks_comic_building.restore.overlay import overlay_inpainted_file_with_black_ink
from barks_comic_building.restore.remove_alias_artifacts import get_median_filter
from barks_comic_building.restore.remove_colors import remove_colors_from_image
from barks_comic_building.restore.smooth_image import smooth_image_file
from barks_comic_building.restore.vtracer_to_svg import image_file_to_svg

USE_EXISTING_WORK_FILES = False  # Use with care


@contextlib.contextmanager
def _timed_step(pipeline: RestorePipeline, step_name: str) -> Generator[None]:
    """Run a pipeline step with timing, logging, and error handling."""
    start = time.time()
    # noinspection PyBroadException
    try:
        yield
    except Exception:  # noqa: BLE001
        pipeline.errors_occurred = True
        logger.exception(f"Error in {step_name}: ")
    else:
        logger.info(f"Time taken for {step_name}: {int(time.time() - start)}s.")


# noinspection PyBroadException
class RestorePipeline:
    def __init__(  # noqa: PLR0913
        self,
        work_dir: Path,
        srce_file: Path,
        srce_upscale_file: Path,
        scale: int,
        dest_restored_file: Path,
        dest_upscayled_restored_file: Path,
        dest_svg_restored_file: Path,
    ) -> None:
        self.work_dir = work_dir
        self.out_dir = dest_restored_file.parent
        self.srce_file = srce_file
        self.srce_upscale_file = srce_upscale_file
        self.scale = scale
        self.dest_restored_file = dest_restored_file
        self.dest_upscayled_restored_file = dest_upscayled_restored_file
        self.dest_svg_restored_file = dest_svg_restored_file

        self.errors_occurred = False

        if not self.work_dir.is_dir():
            msg = f'Work directory not found: "{self.work_dir}".'
            raise FileNotFoundError(msg)
        if not self.out_dir.is_dir():
            msg = f'Restored directory not found: "{self.out_dir}".'
            raise FileNotFoundError(msg)
        if not self.srce_upscale_file.is_file():
            msg = f'Upscayl file not found: "{self.srce_upscale_file}".'
            raise FileNotFoundError(msg)

        self.srce_upscale_stem = f"{self.srce_upscale_file.stem}-upscayled"

        self.removed_artifacts_file = work_dir / f"{self.srce_upscale_stem}-median-filtered.png"
        self.removed_colors_file = work_dir / f"{self.srce_upscale_stem}-color-removed.png"
        self.smoothed_removed_colors_file = (
            work_dir / f"{self.srce_upscale_stem}-color-removed-smoothed.png"
        )
        self.png_of_svg_file = Path(str(self.dest_svg_restored_file) + ".png")
        self.inpainted_file = work_dir / f"{self.srce_upscale_stem}-inpainted.png"

    @property
    def expected_output_files(self) -> list[Path]:
        """Return all intermediate and final output files produced by the pipeline."""
        return [
            self.removed_artifacts_file,
            self.removed_colors_file,
            self.smoothed_removed_colors_file,
            self.dest_svg_restored_file,
            self.png_of_svg_file,
            self.inpainted_file,
            self.dest_upscayled_restored_file,
            self.dest_restored_file,
        ]

    def do_part1(self) -> None:
        self._do_remove_jpg_artifacts()
        if not self.errors_occurred:
            self._do_remove_colors()

    def do_part2_memory_hungry(self) -> None:
        self._do_smooth_removed_colors()

    def do_part3(self) -> None:
        self._do_generate_svg()

    def do_part4_memory_hungry(self) -> None:
        self._do_inpaint()
        if not self.errors_occurred:
            self._do_overlay_inpaint_with_black_ink()
        if not self.errors_occurred:
            self._do_resize_restored_file()

    def _do_remove_jpg_artifacts(self) -> None:
        if USE_EXISTING_WORK_FILES and self.removed_artifacts_file.is_file():
            logger.warning(
                f"Removed artifacts file already exists - skipping:"
                f' "{self.removed_artifacts_file}".'
            )
            return

        logger.info(
            f'\nGenerating file with jpeg artifacts removed: "{self.removed_artifacts_file}"...'
        )
        with _timed_step(self, f'remove jpeg artifacts for "{self.removed_artifacts_file.name}"'):
            upscale_image = cv.imread(str(self.srce_upscale_file))
            out_image = get_median_filter(upscale_image)  # ty:ignore[invalid-argument-type]
            write_cv_image_file(self.removed_artifacts_file, out_image)

    def _do_remove_colors(self) -> None:
        if USE_EXISTING_WORK_FILES and self.removed_colors_file.is_file():
            logger.warning(
                f'Removed colors file already exists - skipping: "{self.removed_colors_file}".'
            )
            return

        logger.info(f'\nGenerating color removed file "{self.removed_colors_file}"...')
        with _timed_step(self, f'remove colors for "{self.removed_colors_file.name}"'):
            remove_colors_from_image(
                self.work_dir,
                self.srce_upscale_stem,
                self.removed_artifacts_file,
                self.removed_colors_file,
            )

    def _do_smooth_removed_colors(self) -> None:
        if USE_EXISTING_WORK_FILES and self.smoothed_removed_colors_file.is_file():
            logger.warning(
                f"Smoothed removed colors file already exists - skipping:"
                f' "{self.smoothed_removed_colors_file}".'
            )
            return

        logger.info(f'\nGenerating smoothed file "{self.smoothed_removed_colors_file}"...')
        with _timed_step(self, f'smooth "{self.smoothed_removed_colors_file.name}"'):
            smooth_image_file(self.removed_colors_file, self.smoothed_removed_colors_file)

    def _do_generate_svg(self) -> None:
        logger.info(f'\nGenerating svg file "{self.dest_svg_restored_file}"...')
        with _timed_step(self, f'generate svg "{self.dest_svg_restored_file.name}"'):
            image_file_to_svg(self.smoothed_removed_colors_file, self.dest_svg_restored_file)

            logger.info(f'\nSaving svg file to png file "{self.png_of_svg_file}"...')
            svg_file_to_png(self.dest_svg_restored_file, self.png_of_svg_file)

    def _do_inpaint(self) -> None:
        if USE_EXISTING_WORK_FILES and self.inpainted_file.is_file():
            logger.warning(f'Inpainted file already exists - skipping: "{self.inpainted_file}".')
            return

        logger.info(f'\nInpainting upscayled file to "{self.inpainted_file}"...')
        with _timed_step(self, f'inpaint "{self.inpainted_file.name}"'):
            inpaint_image_file(
                self.work_dir,
                self.srce_upscale_stem,
                self.srce_upscale_file,
                self.removed_colors_file,
                self.inpainted_file,
            )

    def _do_overlay_inpaint_with_black_ink(self) -> None:
        logger.info(
            f'\nOverlaying inpainted file "{self.inpainted_file}"'
            f' with black ink file "{self.png_of_svg_file}"...'
        )
        with _timed_step(self, f'overlay inpainted file "{self.inpainted_file.name}"'):
            overlay_inpainted_file_with_black_ink(
                self.inpainted_file, self.png_of_svg_file, self.dest_upscayled_restored_file
            )

    def _do_resize_restored_file(self) -> None:
        logger.info(f'\nResizing restored file to "{self.dest_restored_file}"...')
        with _timed_step(self, f'resize restored file "{self.dest_restored_file.name}"'):
            srce_file = "N/A" if not self.srce_file.is_file() else get_clean_path(self.srce_file)

            # TODO(glk): Save other params used in process.
            restored_file_metadata = {
                "Source file": f'"{srce_file}"',
                "Upscayl file": f'"{get_clean_path(self.srce_upscale_file)}"',
                "Upscayl scale": str(self.scale),
            }

            resize_image_file(
                self.dest_upscayled_restored_file,
                self.scale,
                self.dest_restored_file,
                restored_file_metadata,
            )


def check_for_errors(restore_procs: list[RestorePipeline]) -> None:
    """Check all expected output files exist and log any errors."""
    for proc in restore_procs:
        for file in proc.expected_output_files:
            if not file.is_file():
                logger.error(f'Could not find output artifact "{file}".')
                proc.errors_occurred = True

        if proc.errors_occurred:
            logger.error(f'Errors occurred while processing "{proc.srce_upscale_file}".')
