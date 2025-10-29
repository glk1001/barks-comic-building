# ruff: noqa: T201

import subprocess
import sys
from pathlib import Path

from barks_fantagraphics.comics_cmd_args import CmdArgNames, CmdArgs
from barks_fantagraphics.comics_consts import PageType
from loguru import logger
from loguru_config import LoguruConfig

APP_LOGGING_NAME = "sttl"

VIEWER_EXE = ["/usr/bin/eog"]


def open_viewer(image_file: Path) -> None:
    command = [*VIEWER_EXE, str(image_file)]

    _proc = subprocess.Popen(command)  # noqa: S603

    print(f'Image Viewer should now be showing image "{image_file}".')


if __name__ == "__main__":
    cmd_args = CmdArgs("Show title in viewer", CmdArgNames.TITLE)
    args_ok, error_msg = cmd_args.args_are_valid()
    if not args_ok:
        logger.error(error_msg)
        sys.exit(1)

    # Global variable accessed by loguru-config.
    log_level = cmd_args.get_log_level()
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    comics_database = cmd_args.get_comics_database()
    title = cmd_args.get_title()

    comic = comics_database.get_comic_book(title)
    volume = comic.get_fanta_volume()
    valid_page_list = [
        p.page_filenames for p in comic.page_images_in_order if p.page_type == PageType.BODY
    ]

    first_page = valid_page_list[0]
    restored_dir = Path(comics_database.get_fantagraphics_restored_volume_image_dir(volume))
    restored_srce_file = restored_dir / (first_page + ".png")
    if not restored_srce_file.is_file():
        print(f'Error: Could not find restored file "{restored_srce_file}".')
        sys.exit(1)

    print(f'"{title}" [{volume}]: {first_page}')

    open_viewer(restored_srce_file)
