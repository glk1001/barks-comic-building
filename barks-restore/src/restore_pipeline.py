from __future__ import annotations

import time
from typing import TYPE_CHECKING

import cv2 as cv
from barks_fantagraphics.comics_utils import get_clean_path
from loguru import logger

from .image_io import resize_image_file, svg_file_to_png, write_cv_image_file
from .inpaint import inpaint_image_file
from .overlay import overlay_inpainted_file_with_black_ink
from .remove_alias_artifacts import get_median_filter
from .remove_colors import remove_colors_from_image
from .smooth_image import smooth_image_file
from .vtracer_to_svg import image_file_to_svg

if TYPE_CHECKING:
    from pathlib import Path

USE_EXISTING_WORK_FILES = False  # Use with care


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
        self.png_of_svg_file = self.dest_svg_restored_file.with_suffix(".png")
        self.inpainted_file = work_dir / f"{self.srce_upscale_stem}-inpainted.png"

    def do_part1(self) -> None:
        self.do_remove_jpg_artifacts()
        self.do_remove_colors()

    def do_part2_memory_hungry(self) -> None:
        self.do_smooth_removed_colors()

    def do_part3(self) -> None:
        self.do_generate_svg()

    def do_part4_memory_hungry(self) -> None:
        self.do_inpaint()
        self.do_overlay_inpaint_with_black_ink()
        self.do_resize_restored_file()

    def do_remove_jpg_artifacts(self) -> None:
        if USE_EXISTING_WORK_FILES and self.removed_artifacts_file.is_file():
            logger.warning(
                f"Removed artifacts file already exists - skipping:"
                f' "{self.removed_artifacts_file}".'
            )
            return

        try:
            start = time.time()
            logger.info(
                f'\nGenerating file with jpeg artifacts removed: "{self.removed_artifacts_file}"...'
            )

            upscale_image = cv.imread(str(self.srce_upscale_file))
            out_image = get_median_filter(upscale_image)
            write_cv_image_file(self.removed_artifacts_file, out_image)

            logger.info(
                f"Time taken to remove jpeg artifacts for"
                f' "{self.removed_artifacts_file.name}":'
                f" {int(time.time() - start)}s."
            )
        except Exception:  # noqa: BLE001
            self.errors_occurred = True
            logger.exception("Error removing jpg artifacts: ")

    def do_remove_colors(self) -> None:
        if USE_EXISTING_WORK_FILES and self.removed_colors_file.is_file():
            logger.warning(
                f'Removed colors file already exists - skipping: "{self.removed_colors_file}".'
            )
            return

        try:
            start = time.time()
            logger.info(f'\nGenerating color removed file "{self.removed_colors_file}"...')

            remove_colors_from_image(
                self.work_dir,
                self.srce_upscale_stem,
                self.removed_artifacts_file,
                self.removed_colors_file,
            )

            logger.info(
                f'Time taken to remove colors for "{self.removed_colors_file.name}":'
                f" {int(time.time() - start)}s."
            )
        except Exception:  # noqa: BLE001
            self.errors_occurred = True
            logger.exception("Error removing colors: ")

    def do_smooth_removed_colors(self) -> None:
        if USE_EXISTING_WORK_FILES and self.smoothed_removed_colors_file.is_file():
            logger.warning(
                f"Smoothed removed colors file already exists - skipping:"
                f' "{self.smoothed_removed_colors_file}".'
            )
            return

        try:
            start = time.time()
            logger.info(f'\nGenerating smoothed file "{self.smoothed_removed_colors_file}"...')

            smooth_image_file(self.removed_colors_file, self.smoothed_removed_colors_file)

            logger.info(
                f'Time taken to smooth "{self.smoothed_removed_colors_file.name}":'
                f" {int(time.time() - start)}s."
            )
        except Exception:  # noqa: BLE001
            logger.exception("Error smoothing removed colors: ")

    def do_generate_svg(self) -> None:
        try:
            start = time.time()
            logger.info(f'\nGenerating svg file "{self.dest_svg_restored_file}"...')

            image_file_to_svg(self.smoothed_removed_colors_file, self.dest_svg_restored_file)

            logger.info(
                f'Time taken to generate svg "{self.dest_svg_restored_file.name}":'
                f" {int(time.time() - start)}s."
            )

            logger.info(f'\nSaving svg file to png file "{self.png_of_svg_file}"...')
            svg_file_to_png(self.dest_svg_restored_file, self.png_of_svg_file)
        except Exception:  # noqa: BLE001
            self.errors_occurred = True
            logger.exception("Error generating svg: ")

    def do_inpaint(self) -> None:
        if USE_EXISTING_WORK_FILES and self.inpainted_file.is_file():
            logger.warning(f'Inpainted file already exists - skipping: "{self.inpainted_file}".')
            return

        try:
            start = time.time()
            logger.info(f'\nInpainting upscayled file to "{self.inpainted_file}"...')

            inpaint_image_file(
                self.work_dir,
                self.srce_upscale_stem,
                self.srce_upscale_file,
                self.removed_colors_file,
                self.inpainted_file,
            )

            logger.info(
                f'Time taken to inpaint "{self.inpainted_file.name}": {int(time.time() - start)}s.'
            )
        except Exception:  # noqa: BLE001
            self.errors_occurred = True
            logger.exception("Error inpainting: ")

    def do_overlay_inpaint_with_black_ink(self) -> None:
        try:
            start = time.time()
            logger.info(
                f'\nOverlaying inpainted file "{self.inpainted_file}"'
                f' with black ink file "{self.png_of_svg_file}"...'
            )

            overlay_inpainted_file_with_black_ink(
                self.inpainted_file, self.png_of_svg_file, self.dest_upscayled_restored_file
            )

            logger.info(
                f'Time taken to overlay inpainted file "{self.inpainted_file.name}":'
                f" {int(time.time() - start)}s."
            )
        except Exception:  # noqa: BLE001
            self.errors_occurred = True
            logger.exception("Error overlaying inpainted file: ")

    def do_resize_restored_file(self) -> None:
        try:
            logger.info(f'\nResizing restored file to "{self.dest_restored_file}"...')

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
        except Exception:  # noqa: BLE001
            self.errors_occurred = True
            logger.exception("Error resizing file: ")


def check_file_exists(proc: RestorePipeline, file: Path) -> None:
    if not file.is_file():
        logger.error(f'Could not find output artifact "{file}".')
        proc.errors_occurred = True


def check_for_errors(restore_procs: list[RestorePipeline]) -> None:
    for proc in restore_procs:
        check_file_exists(proc, proc.removed_artifacts_file)
        check_file_exists(proc, proc.removed_colors_file)
        check_file_exists(proc, proc.smoothed_removed_colors_file)
        check_file_exists(proc, proc.dest_svg_restored_file)
        check_file_exists(proc, proc.png_of_svg_file)
        check_file_exists(proc, proc.inpainted_file)
        check_file_exists(proc, proc.dest_upscayled_restored_file)
        check_file_exists(proc, proc.dest_restored_file)

        if proc.errors_occurred:
            logger.error(f'Errors occurred while processing "{proc.srce_upscale_file}".')
