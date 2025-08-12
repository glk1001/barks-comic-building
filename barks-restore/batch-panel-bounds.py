import concurrent.futures
import logging
import os
import sys
import time

from barks_fantagraphics.comics_cmd_args import CmdArgNames, CmdArgs
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_utils import get_abbrev_path
from comic_utils.comics_logging import setup_logging
from comic_utils.panel_bounding_box_processor import BoundingBoxProcessor


def panel_bounds(title_list: list[str]) -> None:
    start = time.time()

    num_page_files = 0
    for title in title_list:
        logging.info(f'Getting panel bounds for all pages in "{title}"...')

        title_work_dir = os.path.join(work_dir, title)
        os.makedirs(title_work_dir, exist_ok=True)

        bounding_box_processor = BoundingBoxProcessor(title_work_dir)

        comic = comics_database.get_comic_book(title)

        srce_files = comic.get_final_srce_story_files(RESTORABLE_PAGE_TYPES)
        dest_files = comic.get_srce_panel_segments_files(RESTORABLE_PAGE_TYPES)

        if not os.path.isdir(comic.get_srce_original_fixes_image_dir()):
            msg = (
                f"Could not find panel bounds directory "
                f'"{comic.get_srce_original_fixes_image_dir()}".'
            )
            raise FileNotFoundError(msg)
        # TODO: Put this in barks_fantagraphics
        srce_panels_bounds_override_dir = os.path.join(
            comic.get_srce_original_fixes_image_dir(), "bounded"
        )

        with concurrent.futures.ProcessPoolExecutor() as executor:
            for (srce_file, _), dest_file in zip(srce_files, dest_files):
                executor.submit(
                    get_page_panel_bounds,
                    bounding_box_processor,
                    srce_panels_bounds_override_dir,
                    srce_file,
                    dest_file,
                )

        num_page_files += len(srce_files)

    logging.info(
        f"\nTime taken to process all {num_page_files} files: {int(time.time() - start)}s."
    )


def get_page_panel_bounds(
    bounding_box_processor: BoundingBoxProcessor,
    srce_panels_bounds_override_dir: str,
    srce_file: str,
    dest_file: str,
) -> None:
    try:
        if not os.path.isfile(srce_file):
            msg = f'Could not find srce file: "{srce_file}".'
            raise FileNotFoundError(msg)
        if os.path.isfile(dest_file):
            logging.warning(f'Dest file exists - skipping: "{get_abbrev_path(dest_file)}".')
            return

        logging.info(
            f'Using Kumiko to get page panel bounds for "{get_abbrev_path(srce_file)}"'
            f' - saving to dest file "{get_abbrev_path(dest_file)}".'
        )

        segment_info = bounding_box_processor.get_panels_segment_info_from_kumiko(
            srce_file,
            srce_panels_bounds_override_dir,
        )

        bounding_box_processor.save_panels_segment_info(dest_file, segment_info)

    except Exception:
        logging.exception("Error: ")
        return


setup_logging(logging.INFO)

# TODO(glk): Some issue with type checking inspection?
# noinspection PyTypeChecker
cmd_args = CmdArgs("Panel Bounds", CmdArgNames.TITLE | CmdArgNames.VOLUME | CmdArgNames.WORK_DIR)
args_ok, error_msg = cmd_args.args_are_valid()
if not args_ok:
    logging.error(error_msg)
    sys.exit(1)

work_dir = os.path.join(cmd_args.get_work_dir())
os.makedirs(work_dir, exist_ok=True)

comics_database = cmd_args.get_comics_database()

panel_bounds(cmd_args.get_titles())
