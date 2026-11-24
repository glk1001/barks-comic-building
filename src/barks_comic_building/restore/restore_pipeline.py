from __future__ import annotations

import contextlib
import json
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

import cv2 as cv
from barks_fantagraphics.comics_database import get_fanta_title_for_volume
from barks_fantagraphics.comics_utils import get_clean_path
from barks_fantagraphics.fanta_comics_info import HAND_RESTORED_PAGES
from comic_utils.pil_image_utils import get_image_size
from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

from barks_comic_building.restore.image_checks import (
    MAX_THUMBNAIL_DEVIATION,
    find_content_fault,
    find_structural_fault,
)
from barks_comic_building.restore.image_io import (
    is_complete_png,
    is_complete_svg,
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
    get_ink_mask_file,
    get_upscayl_input_stamp,
)
from barks_comic_building.restore.palette_snap import snap_image_file_to_srce_palette
from barks_comic_building.restore.remove_alias_artifacts import get_median_filter
from barks_comic_building.restore.remove_colors import (
    DEBUG_WRITE_COLOR_COUNTS,
    remove_colors_from_image,
)
from barks_comic_building.restore.restore_recipe import get_current_recipe
from barks_comic_building.restore.run_stop import read_stop_mode
from barks_comic_building.restore.smooth_image import smooth_image_file
from barks_comic_building.restore.vtracer_to_svg import image_file_to_svg

# Default for whether existing intermediate work files are reused (resume) rather than
# regenerated. Can be overridden per pipeline via the constructor. Use with care.
USE_EXISTING_WORK_FILES = False


# The declared hand-restored pages, resolved from (volume, page) to the (volume directory
# name, page stem) pair a destination path can be tested against. Resolved once, at import,
# because the volume titles never change during a run.
_HAND_RESTORED_PAGE_KEYS: frozenset[tuple[str, str]] = frozenset(
    (get_fanta_title_for_volume(volume), page_num) for volume, page_num in HAND_RESTORED_PAGES
)


def is_hand_restored_page(dest_file: Path) -> bool:
    """Return whether a destination path is one of the declared hand-restored pages.

    Answered from the path alone - the volume directory two levels up, and the page stem -
    rather than from anything the caller passes in. That is what makes it a second guard
    rather than the same knowledge handed down a level: `single_restore_pipeline` has only
    bare paths off the command line and could not answer honestly if it were asked.

    The resolved parent is tested as well as the given one, since a page can be reached
    through a symlinked volume directory - the staged collections are built that way - and
    the volume's name only appears once the links have been followed.

    Args:
        dest_file: A path the restore is about to write.

    Returns:
        True if that path is a page whose restoration was made by hand.

    """
    for image_dir in (dest_file.parent, dest_file.parent.resolve()):
        if (image_dir.parent.name, dest_file.stem) in _HAND_RESTORED_PAGE_KEYS:
            return True

    return False


# The canonical step names. Kept separate from the log messages, which name the file
# being worked on: these are the keys the ledger records timings under, and a key that
# carried the page's filename would make every page its own step and leave the totals
# unable to answer where the time actually goes.
STEP_PREPARE_WORK_FILES = "prepare work files"
STEP_REMOVE_ARTIFACTS = "remove jpeg artifacts"
STEP_REMOVE_COLORS = "remove colors"
STEP_SMOOTH = "smooth"
STEP_GENERATE_SVG = "generate svg"
STEP_INPAINT = "inpaint"
STEP_SNAP_PALETTE = "snap palette"
STEP_OVERLAY = "overlay"
STEP_RESIZE = "resize restored file"

# There was a retry here, and then a ladder of reduced scales beneath it, on the strength of
# volume 4's 098 and 099 coming back as blank pages. They were never blank: the inpaint had
# written values a shade over 255, gmic had answered by writing 16 bit pngs, and the check
# below was reading those as solid black. Both are gone now that the inpaint clamps its
# output - see `_GMIC_CLAMP_TO_8_BIT` in `inpaint`. Retrying a step whose output was
# misjudged only ever spent time, and shrinking the page to satisfy the misreading cost
# real quality: the fill it produced at 1/8 was visibly crude.


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
        stop_file: Path | None = None,
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

        # Where a request to stop the run would be written. Read between steps rather
        # than during one, so a step always finishes what it is writing. None means this
        # pipeline is not part of a run that can be stopped, as when it is driven
        # directly by the single-page CLI.
        self.stop_file = stop_file

        self.errors_occurred = False
        self.failed_step: str | None = None
        self.step_seconds: dict[str, float] = {}

        # Set when the pipeline gave up part way through a phase because a stop was
        # asked for. Not a failure: the page is unfinished but everything it wrote is
        # intact, and the next run picks it up.
        self.stopped_early = False

        if not self.work_dir.is_dir():
            msg = f'Work directory not found: "{self.work_dir}".'
            raise FileNotFoundError(msg)
        if not self.out_dir.is_dir():
            msg = f'Restored directory not found: "{self.out_dir}".'
            raise FileNotFoundError(msg)
        if not self.srce_upscale_file.is_file():
            msg = f'Upscayl file not found: "{self.srce_upscale_file}".'
            raise FileNotFoundError(msg)

        # Which upscale of the page this is, read once here so that every phase works
        # from the same answer. It goes into the restored page, where a later run uses it
        # to tell that the input has been redone since, and into the stamp beside the
        # work files, where a resumed run uses it to tell whose input they were made from.
        self.input_stamp = get_upscayl_input_stamp(self.srce_upscale_file)
        input_stat = self.srce_upscale_file.stat()
        self.work_stamp: dict[str, Any] = {
            "recipe_id": self.recipe.recipe_id,
            "input": self.input_stamp,
            # A hand-edited input carries no upscale to name, and the work files are
            # gone within the hour anyway, so the file itself is pinned down as well.
            # Erring towards a mismatch here only costs redoing some intermediates.
            "input_mtime_ns": input_stat.st_mtime_ns,
            "input_size": input_stat.st_size,
        }

        self.png_of_svg_file = get_ink_mask_file(self.dest_svg_restored_file)

        # Collection titles carry pages whose outputs are symlinks to another volume's,
        # and writing to one of those paths follows the link: that volume's page would be
        # replaced from a different source image, and neither end would say so. Refused
        # here as well as in the page state, because there is no caller for whom it is
        # right, and this is the last point before the writing starts.
        for dest_file in (
            self.dest_restored_file,
            self.dest_upscayled_restored_file,
            self.dest_svg_restored_file,
            self.png_of_svg_file,
        ):
            if dest_file.is_symlink():
                msg = (
                    f'Refusing to restore onto a symlink: "{dest_file}"'
                    f' points at "{dest_file.resolve()}", which belongs to another volume.'
                )
                raise ValueError(msg)

            # Likewise refused here as well as in the page state. A page whose restoration
            # was made by hand carries no recipe of ours, so it reads as stale on every
            # run, and there is no re-run that could make it again.
            if is_hand_restored_page(dest_file):
                msg = (
                    f'Refusing to restore over a hand-restored page: "{dest_file}".'
                    " That page was made by hand and cannot be remade."
                )
                raise ValueError(msg)

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

        # Says what the work files beside it were made with. See `_prepare_work_files`.
        self.work_stamp_file = work_dir / f"{self.srce_upscale_stem}-work-stamp.json"

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
        itself, which would otherwise be left behind, and the stamp that says what the
        rest were made with.
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
            self.work_stamp_file,
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

    def _run_steps(self, *steps: Callable[[], None]) -> None:
        """Run steps in order, giving up early on an error or a stop request.

        The stop is looked for between steps and never during one, so whatever a worker
        is in the middle of always finishes. That is what keeps a stopped run resumable:
        every intermediate left on disk is a whole file, not a truncated one.
        """
        for step in steps:
            step()

            if self.errors_occurred:
                return

            if read_stop_mode(self.stop_file).stops_pages_that_have_started:
                self.stopped_early = True
                # The step that just ran is the last one the timer recorded.
                last_step = next(reversed(self.step_seconds), "the current step")
                logger.warning(
                    f'Stop requested - "{self.srce_upscale_file.name}" stopping after {last_step}.',
                )
                return

    def _read_work_stamp(self) -> dict[str, Any] | None:
        """Return the stamp left beside this page's work files, or None if it is no use."""
        try:
            stamp = json.loads(self.work_stamp_file.read_text())
        except (OSError, ValueError):
            return None

        return stamp if isinstance(stamp, dict) else None

    def _prepare_work_files(self) -> None:
        """Throw away work files that are not this run's to carry on from.

        A page that fails or is stopped keeps its intermediates so the next run can
        resume from them, and they can sit there a long time. Reused only because they
        exist, a smoothed mask from before the smoothing was tuned again, or an inpaint of
        the page as it was before being upscayled again, went straight into a page that
        was then stamped with today's recipe and read as CURRENT from then on.

        So each page leaves a stamp beside its work files saying what they were made
        with and from. Unless that matches this run exactly, and reuse was asked for,
        everything is deleted and the page starts clean. That is done whether or not
        this run is a resume, because the next one may be: a plain run that is killed
        half way would otherwise leave its new stamp vouching for older files it had
        not yet got round to overwriting.

        Runs first, as a step, so that not being able to write the stamp fails the page
        rather than letting it go on to make work files nothing vouches for.
        """
        if self.use_existing_work_files and self._read_work_stamp() == self.work_stamp:
            return

        try:
            leftovers = [file for file in self.work_files if file.is_file()]
            if leftovers and self.use_existing_work_files:
                logger.warning(
                    f"Discarding {len(leftovers)} work file(s) made with another recipe"
                    f' or from another input: "{self.srce_upscale_stem}-*".'
                )
            for file in leftovers:
                file.unlink(missing_ok=True)

            self.work_stamp_file.write_text(json.dumps(self.work_stamp, sort_keys=True))
        except OSError:
            self.errors_occurred = True
            self.failed_step = STEP_PREPARE_WORK_FILES
            logger.exception(f'Error in {STEP_PREPARE_WORK_FILES} "{self.work_stamp_file.name}": ')

    def _can_reuse(self, *files: Path) -> bool:
        """Return whether a step may skip its work and use what is already on disk.

        Whose files they are is `_prepare_work_files`' question. This one is whether
        they are whole: a worker killed part way through a write leaves a file that
        exists and is no good, and only a stop asked for between steps is guaranteed
        not to.
        """
        if not self.use_existing_work_files:
            return False

        return all(
            is_complete_svg(file) if file.suffix == ".svg" else is_complete_png(file)
            for file in files
        )

    def do_part1(self) -> None:
        self._run_steps(
            self._prepare_work_files, self._do_remove_jpg_artifacts, self._do_remove_colors
        )

    def do_part2_memory_hungry(self) -> None:
        self._run_steps(self._do_smooth_removed_colors)

    def do_part3(self) -> None:
        self._run_steps(self._do_generate_svg)

    def do_part4_memory_hungry(self) -> None:
        self._run_steps(
            self._do_inpaint,
            self._do_snap_palette,
            self._do_overlay_inpaint_with_black_ink,
            self._do_resize_restored_file,
        )

    def _do_remove_jpg_artifacts(self) -> None:
        if self._can_reuse(self.removed_artifacts_file):
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
        if self._can_reuse(self.removed_colors_file):
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
        if self._can_reuse(self.smoothed_removed_colors_file):
            logger.warning(
                f"Smoothed removed colors file already exists - skipping:"
                f' "{self.smoothed_removed_colors_file}".'
            )
            return

        logger.info(f'\nGenerating smoothed file "{self.smoothed_removed_colors_file}"...')
        with _timed_step(self, STEP_SMOOTH, self.smoothed_removed_colors_file.name):
            smooth_image_file(self.removed_colors_file, self.smoothed_removed_colors_file)

    def _do_generate_svg(self) -> None:
        if self._can_reuse(self.dest_svg_restored_file, self.svg_png_4x_file):
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
        if self._can_reuse(self.inpainted_file):
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
            self._verify_inpaint()

    def _verify_inpaint(self) -> None:
        """Refuse an inpaint that came back as a blank page.

        Kept because a blank fill is a real failure mode - volume 3's 251, 254, 257 and 259
        were genuinely blank - and catching it here names the step that produced it instead
        of leaving the overlay to fail on its input two steps later.

        Not retried. The pages that looked blank for a day were being misread, not badly
        filled, and there has never been a case of the inpaint failing once and succeeding
        on a repeat.

        The output is only checked for being blank, not for resembling the page it came
        from. The inpaint lifts every ink pixel out and fills it, which on the page measured
        here already moves the thumbnail 22.9 of the 25 that `MAX_THUMBNAIL_DEVIATION`
        allows, and an ink-heavier page moves it further - a content check here would fail
        good pages. The overlay puts the ink back, which is why the same threshold is honest
        one step later.
        """
        self._verify_output(
            self.inpainted_file,
            expected_size=get_image_size(self.srce_upscale_file),
            expected_mode="RGB",
        )

    def _do_snap_palette(self) -> None:
        if not self.do_palette_snap:
            return
        if self._can_reuse(self.palette_snapped_file):
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

    def _verify_output(
        self,
        out_file: Path,
        *,
        expected_size: tuple[int, int] | None = None,
        expected_mode: str | None = None,
        srce_file: Path | None = None,
        max_deviation: float = MAX_THUMBNAIL_DEVIATION,
    ) -> None:
        """Check what was just written, and refuse to leave a bad page on disk.

        The bad output is deleted rather than kept, because a corrupt page that stays put
        reads as CURRENT on the next run once it has been stamped, and would never be
        looked at again. Deleted, it comes back as MISSING and the next run redoes it.

        Args:
            out_file: The file the step has just written.
            expected_size: The (width, height) it should have, or None not to check.
            expected_mode: The PIL mode it should have, or None not to check.
            srce_file: What it was made from, to compare it against, or None to run only
                the structural checks.
            max_deviation: How far from `srce_file` it is allowed to be.

        Raises:
            RuntimeError: If the output is unreadable, the wrong shape, one flat colour,
                or does not resemble what it was made from.

        """
        fault = find_structural_fault(
            out_file, expected_size=expected_size, expected_mode=expected_mode
        )
        if fault is None and srce_file is not None:
            fault = find_content_fault(out_file, srce_file, max_deviation)

        if fault is None:
            return

        out_file.unlink(missing_ok=True)
        msg = f'Bad restore output "{out_file.name}", deleted: {fault}.'
        raise RuntimeError(msg)

    def _do_overlay_inpaint_with_black_ink(self) -> None:
        logger.info(
            f'\nOverlaying colour file "{self.file_to_overlay}"'
            f' with black ink file "{self.svg_png_4x_file}"...'
        )
        with _timed_step(self, STEP_OVERLAY, self.file_to_overlay.name):
            overlay_inpainted_file_with_black_ink(
                self.file_to_overlay, self.svg_png_4x_file, self.dest_upscayled_restored_file
            )

            # Checked before the resize rather than at the end of the run, because the
            # resize reads this file: a blacked-out overlay would otherwise be quietly
            # copied down into the restored page as well.
            self._verify_output(
                self.dest_upscayled_restored_file,
                expected_size=get_image_size(self.srce_upscale_file),
                expected_mode="RGB",
                srce_file=self.srce_upscale_file,
            )

    def _do_resize_restored_file(self) -> None:
        logger.info(f'\nResizing restored file to "{self.dest_restored_file}"...')
        with _timed_step(self, STEP_RESIZE, self.dest_restored_file.name):
            upscayled_width, upscayled_height = get_image_size(self.dest_upscayled_restored_file)
            output_size = (upscayled_width // self.scale, upscayled_height // self.scale)

            # The ink mask goes first, because the restored page is the one that carries
            # the recipe and a page is taken as finished once it does. Written after it,
            # a mask that failed left a page that said it was done and had no mask.
            #
            # Sized from the page it sits beside rather than from the original scan,
            # which a page added by hand does not have.
            logger.info(
                f"\nSaving svg file to {output_size[0]} x {output_size[1]}"
                f' optimized png file "{self.png_of_svg_file}"...'
            )
            svg_file_to_optimized_png(
                self.dest_svg_restored_file, *output_size, self.png_of_svg_file
            )

            # Structural checks only, and no mode check: the traced ink is written as a
            # palette png, and it looks nothing like the colour page it came from, so a
            # deviation threshold that suited the other two outputs would fire on every
            # page.
            self._verify_output(self.png_of_svg_file, expected_size=output_size)

            srce_file = "N/A" if not self.srce_file.is_file() else get_clean_path(self.srce_file)

            # The recipe travels with the page, expanded as well as hashed, so that what
            # this page was made with can be read off the file itself rather than having
            # to be looked up somewhere that might not have survived alongside it.
            restored_file_metadata = {
                "Source file": f'"{srce_file}"',
                "Upscayl file": f'"{get_clean_path(self.srce_upscale_file)}"',
                "Upscayl scale": str(self.scale),
                **self.input_stamp,
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

            # This is the page the build reads, and the only one carrying a recipe, so a
            # bad one here is the one that would go unnoticed longest.
            self._verify_output(
                self.dest_restored_file,
                expected_size=output_size,
                expected_mode="RGB",
                srce_file=self.dest_upscayled_restored_file,
            )


def check_for_errors(restore_procs: list[RestorePipeline]) -> None:
    """Check all expected output files exist and log any errors.

    A pipeline that failed is expected to say so itself, through ``errors_occurred``.
    The phases of a batch run in worker processes, where that is set on a copy the parent
    never sees, so the batch driver copies it back onto its own pipelines as each result
    arrives - rather than passing the failures here by index, which went wrong as soon as
    the list being checked was not the whole batch.

    Args:
        restore_procs: The pipelines to check.

    """
    for proc in restore_procs:
        for file in proc.expected_output_files:
            if not file.is_file():
                logger.error(f'Could not find output artifact "{file}".')
                proc.errors_occurred = True

        if proc.errors_occurred:
            logger.error(f'Errors occurred while processing "{proc.srce_upscale_file}".')
