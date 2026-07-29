from __future__ import annotations

import contextlib
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import cv2 as cv
from barks_fantagraphics.comics_utils import get_clean_path
from comic_utils.pil_image_utils import get_image_size
from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Collection, Generator

from barks_comic_building.restore.image_io import (
    resize_image_file,
    svg_file_to_optimized_png,
    svg_file_to_png,
    write_cv_image_file,
)
from barks_comic_building.restore.inpaint import inpaint_image_file
from barks_comic_building.restore.overlay import overlay_inpainted_file_with_black_ink
from barks_comic_building.restore.page_state import (
    RECIPE_ID_KEY,
    RECIPE_KEY,
    RESTORE_DATE_KEY,
)
from barks_comic_building.restore.palette_snap import snap_image_file_to_srce_palette
from barks_comic_building.restore.remove_alias_artifacts import get_median_filter
from barks_comic_building.restore.remove_colors import (
    DEBUG_WRITE_COLOR_COUNTS,
    remove_colors_from_image,
)
from barks_comic_building.restore.restore_recipe import get_current_recipe
from barks_comic_building.restore.smooth_image import smooth_image_file
from barks_comic_building.restore.vtracer_to_svg import image_file_to_svg

# Default for whether existing intermediate work files are reused (resume) rather than
# regenerated. Can be overridden per pipeline via the constructor. Use with care.
USE_EXISTING_WORK_FILES = False


# The canonical step names. Kept separate from the log messages, which name the file
# being worked on: these are the keys the ledger records timings under, and a key that
# carried the page's filename would make every page its own step and leave the totals
# unable to answer where the time actually goes.
STEP_REMOVE_ARTIFACTS = "remove jpeg artifacts"
STEP_REMOVE_COLORS = "remove colors"
STEP_SMOOTH = "smooth"
STEP_GENERATE_SVG = "generate svg"
STEP_INPAINT = "inpaint"
STEP_SNAP_PALETTE = "snap palette"
STEP_OVERLAY = "overlay"
STEP_RESIZE = "resize restored file"


@contextlib.contextmanager
def _timed_step(pipeline: RestorePipeline, step_name: str, target: str) -> Generator[None]:
    """Run a pipeline step with timing, logging, and error handling.

    The elapsed time is kept on the pipeline as well as logged, so that the batch driver
    can hand it to the ledger rather than the run's only record of its own cost being a
    line buried in an append-only log. A step that fails is timed too - how long a page
    took to fail is worth as much as how long it took to succeed.

    Args:
        pipeline: The pipeline being run, which collects the timings.
        step_name: The canonical step name, used as the ledger key. One of the
            ``STEP_`` constants above, and never the name of a file.
        target: The file the step is producing, for the log message only.

    """
    start = time.time()
    # noinspection PyBroadException
    try:
        yield
    except Exception:  # noqa: BLE001
        pipeline.errors_occurred = True
        pipeline.failed_step = step_name
        pipeline.step_seconds[step_name] = time.time() - start
        logger.exception(f'Error in {step_name} "{target}": ')
    else:
        pipeline.step_seconds[step_name] = time.time() - start
        logger.info(f'Time taken for {step_name} "{target}": {int(time.time() - start)}s.')


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
        use_existing_work_files: bool = USE_EXISTING_WORK_FILES,
        debug_color_counts: bool = DEBUG_WRITE_COLOR_COUNTS,
        do_palette_snap: bool = True,
    ) -> None:
        self.work_dir = work_dir
        self.out_dir = dest_restored_file.parent
        self.srce_file = srce_file
        self.srce_upscale_file = srce_upscale_file
        self.scale = scale
        self.dest_restored_file = dest_restored_file
        self.dest_upscayled_restored_file = dest_upscayled_restored_file
        self.dest_svg_restored_file = dest_svg_restored_file
        self.use_existing_work_files = use_existing_work_files
        self.debug_color_counts = debug_color_counts
        self.do_palette_snap = do_palette_snap

        # Recorded into the restored page so that a later run can tell what it was made
        # with, and redo it when the tuning has moved on. Derived from the live step
        # constants, so it follows any of them being changed.
        self.recipe = get_current_recipe(scale, do_palette_snap=do_palette_snap)

        self.errors_occurred = False
        self.failed_step: str | None = None
        self.step_seconds: dict[str, float] = {}

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
        self.inpainted_file = work_dir / f"{self.srce_upscale_stem}-inpainted.png"
        self.palette_snapped_file = work_dir / f"{self.srce_upscale_stem}-palette-snapped.png"

        # The traced line art is rendered twice, at two sizes and in two forms, and the
        # two must not share a path. The 4x render is an rgba work file that the overlay
        # composites onto the colour layer; the 1x render is the inverted alpha mask that
        # ships beside the svg for the reader. They did share a path once, which made
        # part 4 overwrite its own input and quietly produce an inkless page whenever it
        # was re-run on its own.
        self.svg_png_4x_file = work_dir / f"{self.srce_upscale_stem}-svg-4x.png"
        self.png_of_svg_file = Path(str(self.dest_svg_restored_file) + ".png")

    @property
    def expected_output_files(self) -> list[Path]:
        """Return all intermediate and final output files produced by the pipeline."""
        files = [
            self.removed_artifacts_file,
            self.removed_colors_file,
            self.smoothed_removed_colors_file,
            self.dest_svg_restored_file,
            self.svg_png_4x_file,
            self.png_of_svg_file,
            self.inpainted_file,
        ]

        # Only expected when the snap actually runs. It is skipped when turned off, and
        # when there is no source page to take a palette from.
        if self.do_palette_snap and self.srce_file.is_file():
            files.append(self.palette_snapped_file)

        files += [self.dest_upscayled_restored_file, self.dest_restored_file]

        return files

    @property
    def work_files(self) -> list[Path]:
        """Return every intermediate this page writes into the work directory.

        Named explicitly rather than by globbing the work directory, because the work
        directory is shared by a whole title and cleaning up is a deletion - it should
        only ever remove files this page is known to have put there.

        Includes the three written by the step modules rather than by the pipeline
        itself, which would otherwise be left behind.
        """
        stem = self.srce_upscale_stem

        return [
            self.removed_artifacts_file,
            self.removed_colors_file,
            self.smoothed_removed_colors_file,
            self.inpainted_file,
            self.palette_snapped_file,
            self.svg_png_4x_file,
            self.work_dir / f"{stem}-posterized-pre-remove-colors.png",
            self.work_dir / f"{stem}-remove-mask.png",
            self.work_dir / f"{stem}-input-black-removed.png",
        ]

    @property
    def file_to_overlay(self) -> Path:
        """Return the colour layer the black ink is overlaid onto.

        The palette snapped file when there is one, otherwise the inpainted file it would
        have been made from - the snap is skipped when it is turned off or when there is
        no source file to take a palette from.
        """
        if self.do_palette_snap and self.palette_snapped_file.is_file():
            return self.palette_snapped_file
        return self.inpainted_file

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
            self._do_snap_palette()
        if not self.errors_occurred:
            self._do_overlay_inpaint_with_black_ink()
        if not self.errors_occurred:
            self._do_resize_restored_file()

    def _do_remove_jpg_artifacts(self) -> None:
        if self.use_existing_work_files and self.removed_artifacts_file.is_file():
            logger.warning(
                f"Removed artifacts file already exists - skipping:"
                f' "{self.removed_artifacts_file}".'
            )
            return

        logger.info(
            f'\nGenerating file with jpeg artifacts removed: "{self.removed_artifacts_file}"...'
        )
        with _timed_step(self, STEP_REMOVE_ARTIFACTS, self.removed_artifacts_file.name):
            upscale_image = cv.imread(str(self.srce_upscale_file))
            out_image = get_median_filter(upscale_image)  # ty:ignore[invalid-argument-type]
            write_cv_image_file(self.removed_artifacts_file, out_image)

    def _do_remove_colors(self) -> None:
        if self.use_existing_work_files and self.removed_colors_file.is_file():
            logger.warning(
                f'Removed colors file already exists - skipping: "{self.removed_colors_file}".'
            )
            return

        logger.info(f'\nGenerating color removed file "{self.removed_colors_file}"...')
        with _timed_step(self, STEP_REMOVE_COLORS, self.removed_colors_file.name):
            remove_colors_from_image(
                self.work_dir,
                self.srce_upscale_stem,
                self.removed_artifacts_file,
                self.removed_colors_file,
                debug_color_counts=self.debug_color_counts,
            )

    def _do_smooth_removed_colors(self) -> None:
        if self.use_existing_work_files and self.smoothed_removed_colors_file.is_file():
            logger.warning(
                f"Smoothed removed colors file already exists - skipping:"
                f' "{self.smoothed_removed_colors_file}".'
            )
            return

        logger.info(f'\nGenerating smoothed file "{self.smoothed_removed_colors_file}"...')
        with _timed_step(self, STEP_SMOOTH, self.smoothed_removed_colors_file.name):
            smooth_image_file(self.removed_colors_file, self.smoothed_removed_colors_file)

    def _do_generate_svg(self) -> None:
        if (
            self.use_existing_work_files
            and self.dest_svg_restored_file.is_file()
            and self.svg_png_4x_file.is_file()
        ):
            logger.warning(
                f'Svg file and its 4x render already exist - skipping: "{self.svg_png_4x_file}".'
            )
            return

        logger.info(f'\nGenerating svg file "{self.dest_svg_restored_file}"...')
        with _timed_step(self, STEP_GENERATE_SVG, self.dest_svg_restored_file.name):
            image_file_to_svg(self.smoothed_removed_colors_file, self.dest_svg_restored_file)

            logger.info(f'\nSaving svg file to same-sized png file "{self.svg_png_4x_file}"...')
            svg_file_to_png(self.dest_svg_restored_file, self.svg_png_4x_file)

    def _do_inpaint(self) -> None:
        if self.use_existing_work_files and self.inpainted_file.is_file():
            logger.warning(f'Inpainted file already exists - skipping: "{self.inpainted_file}".')
            return

        logger.info(f'\nInpainting upscayled file to "{self.inpainted_file}"...')
        with _timed_step(self, STEP_INPAINT, self.inpainted_file.name):
            inpaint_image_file(
                self.work_dir,
                self.srce_upscale_stem,
                self.srce_upscale_file,
                self.removed_colors_file,
                self.inpainted_file,
            )

    def _do_snap_palette(self) -> None:
        if not self.do_palette_snap:
            return
        if self.use_existing_work_files and self.palette_snapped_file.is_file():
            logger.warning(
                f'Palette snapped file already exists - skipping: "{self.palette_snapped_file}".'
            )
            return
        if not self.srce_file.is_file():
            logger.warning(
                f'No srce file to take a palette from - not snapping: "{self.srce_file}".'
            )
            return

        logger.info(f'\nSnapping inpainted file to "{self.palette_snapped_file}"...')
        with _timed_step(self, STEP_SNAP_PALETTE, self.palette_snapped_file.name):
            fraction = snap_image_file_to_srce_palette(
                self.srce_file, self.inpainted_file, self.palette_snapped_file
            )
            logger.info(f"Snapped {fraction:.1%} of pixels to the srce palette.")

    def _do_overlay_inpaint_with_black_ink(self) -> None:
        logger.info(
            f'\nOverlaying colour file "{self.file_to_overlay}"'
            f' with black ink file "{self.svg_png_4x_file}"...'
        )
        with _timed_step(self, STEP_OVERLAY, self.file_to_overlay.name):
            overlay_inpainted_file_with_black_ink(
                self.file_to_overlay, self.svg_png_4x_file, self.dest_upscayled_restored_file
            )

    def _do_resize_restored_file(self) -> None:
        logger.info(f'\nResizing restored file to "{self.dest_restored_file}"...')
        with _timed_step(self, STEP_RESIZE, self.dest_restored_file.name):
            srce_file = "N/A" if not self.srce_file.is_file() else get_clean_path(self.srce_file)

            # The recipe travels with the page, expanded as well as hashed, so that what
            # this page was made with can be read off the file itself rather than having
            # to be looked up somewhere that might not have survived alongside it.
            restored_file_metadata = {
                "Source file": f'"{srce_file}"',
                "Upscayl file": f'"{get_clean_path(self.srce_upscale_file)}"',
                "Upscayl scale": str(self.scale),
                RECIPE_ID_KEY: self.recipe.recipe_id,
                RECIPE_KEY: self.recipe.as_json(),
                RESTORE_DATE_KEY: datetime.now().astimezone().isoformat(timespec="seconds"),
            }

            resize_image_file(
                self.dest_upscayled_restored_file,
                self.scale,
                self.dest_restored_file,
                restored_file_metadata,
            )

            output_width, output_height = get_image_size(self.srce_file)
            logger.info(
                f"\nSaving svg file to {output_width} x {output_height}"
                f' optimized png file "{self.png_of_svg_file}"...'
            )
            svg_file_to_optimized_png(
                self.dest_svg_restored_file, output_width, output_height, self.png_of_svg_file
            )


def check_for_errors(
    restore_procs: list[RestorePipeline], failed_indexes: Collection[int] | None = None
) -> None:
    """Check all expected output files exist and log any errors.

    Args:
        restore_procs: The pipelines to check.
        failed_indexes: Indexes into ``restore_procs`` that the batch driver already saw
            fail. Needed because the phases run in worker processes, where a pipeline's
            ``errors_occurred`` is set on a copy that the parent never sees - without
            this the check would fall back to file existence alone. Omit when the
            pipelines were run in this process, as the single-page CLI does.

    """
    already_failed = set(failed_indexes or ())

    for i, proc in enumerate(restore_procs):
        if i in already_failed:
            proc.errors_occurred = True

        for file in proc.expected_output_files:
            if not file.is_file():
                logger.error(f'Could not find output artifact "{file}".')
                proc.errors_occurred = True

        if proc.errors_occurred:
            logger.error(f'Errors occurred while processing "{proc.srce_upscale_file}".')
