import concurrent.futures
import sys
import time
from pathlib import Path

from barks_fantagraphics.comics_cmd_args import CmdArgNames, CmdArgs
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_utils import get_abbrev_path
from comic_utils.panel_bounding_box_processor import BoundingBoxProcessor
from loguru import logger
from loguru_config import LoguruConfig

APP_LOGGING_NAME = "bpan"


def panel_bounds(title_list: list[str]) -> None:
    start = time.time()

    num_page_files = 0
    for title in title_list:
        logger.info(f'Getting panel bounds for all pages in "{title}"...')

        title_work_dir = work_dir / title
        title_work_dir.mkdir(parents=True, exist_ok=True)

        bounding_box_processor = BoundingBoxProcessor(title_work_dir)

        comic = comics_database.get_comic_book(title)

        srce_files = comic.get_final_srce_story_files(RESTORABLE_PAGE_TYPES)
        dest_files = comic.get_srce_panel_segments_files(RESTORABLE_PAGE_TYPES)

        if not comic.get_srce_original_fixes_image_dir().is_dir():
            msg = (
                f"Could not find panel bounds directory "
                f'"{comic.get_srce_original_fixes_image_dir()}".'
            )
            raise FileNotFoundError(msg)
        # TODO(glk): Put this in barks_fantagraphics
        srce_panels_bounds_override_dir = comic.get_srce_original_fixes_image_dir() / "bounded"

        with concurrent.futures.ProcessPoolExecutor() as executor:
            for (srce_file, _), dest_file in zip(srce_files, dest_files, strict=True):
                executor.submit(
                    get_page_panel_bounds,
                    bounding_box_processor,
                    srce_panels_bounds_override_dir,
                    srce_file,
                    dest_file,
                )

        num_page_files += len(srce_files)

    logger.info(f"\nTime taken to process all {num_page_files} files: {int(time.time() - start)}s.")


def get_page_panel_bounds(
    bounding_box_processor: BoundingBoxProcessor,
    srce_panels_bounds_override_dir: Path,
    srce_file: Path,
    dest_file: Path,
) -> None:
    # noinspection PyBroadException
    try:
        if not srce_file.is_file():
            msg = f'Could not find srce file: "{srce_file}".'
            raise FileNotFoundError(msg)  # noqa: TRY301
        if dest_file.is_file():
            logger.warning(f'Dest file exists - skipping: "{get_abbrev_path(dest_file)}".')
            return

        logger.info(
            f'Using Kumiko to get page panel bounds for "{get_abbrev_path(srce_file)}"'
            f' - saving to dest file "{get_abbrev_path(dest_file)}".'
        )

        segment_info = bounding_box_processor.get_panels_segment_info_from_kumiko(
            srce_file,
            srce_panels_bounds_override_dir,
        )

        bounding_box_processor.save_panels_segment_info(dest_file, segment_info)

    except Exception:  # noqa: BLE001
        logger.exception("Error: ")
        return


if __name__ == "__main__":
    # TODO(glk): Some issue with type checking inspection?
    # noinspection PyTypeChecker
    cmd_args = CmdArgs(
        "Panel Bounds", CmdArgNames.TITLE | CmdArgNames.VOLUME | CmdArgNames.WORK_DIR
    )
    args_ok, error_msg = cmd_args.args_are_valid()
    if not args_ok:
        logger.error(error_msg)
        sys.exit(1)

    # Global variables accessed by loguru-config.
    log_level = cmd_args.get_log_level()
    log_filename = "batch-panel-bounds.log"
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    work_dir = cmd_args.get_work_dir()
    work_dir.mkdir(parents=True, exist_ok=True)

    comics_database = cmd_args.get_comics_database()

    panel_bounds(cmd_args.get_titles())
