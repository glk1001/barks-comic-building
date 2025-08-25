# ruff: noqa: T201

import json
import subprocess
import sys
from pathlib import Path

from barks_fantagraphics.comics_cmd_args import CmdArgNames, CmdArgs, ExtraArg
from barks_fantagraphics.comics_consts import PageType
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.pil_image_utils import open_pil_image_for_reading
from loguru import logger
from loguru_config import LoguruConfig

GIMP_EXE = ["/usr/bin/flatpak", "run", "org.gimp.GIMP"]

# RESTORED_ROOT_DIR = /home/greg/Books/Carl Barks/Fantagraphics-restored
TARGET_ROOT_DIR = Path("/home/greg/Books/Carl Barks/Barks Panels Pngs")

PANEL_TYPES = {
    "i": "Insets",
    "cl": "Closeups",
    "f": "Favourites",
    "si": "Silhouettes",
    "sp": "Splash",
}
EXTRA_ARGS: list[ExtraArg] = [
    ExtraArg("--type", action="store", type=str, default=""),
    ExtraArg("--p-p", action="store", type=str, default=""),
]


def get_source_file(comics_db: ComicsDatabase, panel_typ: str, pge: str) -> Path:
    if panel_typ == "cl":
        upscayl_dir = Path(comics_db.get_fantagraphics_restored_upscayled_volume_image_dir(volume))
        return upscayl_dir / (pge + ".png")

    restored_dir = Path(comics_db.get_fantagraphics_restored_volume_image_dir(volume))
    return restored_dir / (pge + ".png")


def get_target_file(ttl: str, panel_typ: str, pge: str, panl: str) -> Path:
    if panel_typ == "i":
        return TARGET_ROOT_DIR / PANEL_TYPES[panel_typ] / (ttl + ".png")

    target_dir = TARGET_ROOT_DIR / PANEL_TYPES[panel_typ] / ttl
    target_dir.mkdir(parents=True, exist_ok=True)

    return target_dir / f"{pge}-{panl}.png"


def write_cropped_image_file(
    srce_image_file: Path, segments_file: Path, target_image_file: Path, panel_typ: str
) -> None:
    print(f'Source: "{srce_image_file}".')
    print(f'Segments: "{segments_file}".')

    if not panel_segments_file.is_file():
        image = open_pil_image_for_reading(str(srce_image_file))
        image.save(target_image_file, optimize=True, compress_level=9)
    else:
        with segments_file.open() as f:
            panel_segment_info = json.load(f)

        panel_box = panel_segment_info["panels"][int(panel) - 1]

        left = panel_box[0]
        bottom = panel_box[1]
        right = left + panel_box[2]
        upper = bottom + panel_box[3]
        if panel_typ == "cl":
            left *= 4
            bottom *= 4
            right *= 4
            upper *= 4

        print(f"Panel {panel}: {left}, {bottom}, {right}, {upper}")

        image = open_pil_image_for_reading(str(srce_image_file))
        subimage = image.crop((left, bottom, right, upper))
        subimage.save(target_image_file, optimize=True, compress_level=9)

        print(f'Saved cropped image to "{target_image_file}".')


def open_gimp(image_file: Path) -> None:
    command = [*GIMP_EXE, str(image_file)]

    _proc = subprocess.Popen(command)

    print(f'Gimp should now be running with image "{image_file}".')


if __name__ == "__main__":
    cmd_args = CmdArgs("Edit title", CmdArgNames.TITLE, extra_args=EXTRA_ARGS)
    args_ok, error_msg = cmd_args.args_are_valid()
    if not args_ok:
        logger.error(error_msg)
        sys.exit(1)

    # Global variable accessed by loguru-config.
    log_level = cmd_args.get_log_level()
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    comics_database = cmd_args.get_comics_database()
    panel_type = cmd_args.get_extra_arg("--type")
    page_panel = cmd_args.get_extra_arg("--p_p")
    (page, panel) = page_panel.split("-")
    title = cmd_args.get_title()

    comic = comics_database.get_comic_book(title)
    volume = comic.get_fanta_volume()
    valid_page_list = [
        p.page_filenames for p in comic.page_images_in_order if p.page_type == PageType.BODY
    ]

    if page not in valid_page_list:
        print(f'ERROR: Page "{page}" is not in {valid_page_list}.')
        sys.exit(1)
    if panel_type not in PANEL_TYPES:
        print(f'ERROR: Panel type "{panel_type}" is not in {list(PANEL_TYPES.keys())}.')
        sys.exit(1)

    srce_file = get_source_file(comics_database, panel_type, page)
    if not srce_file.is_file():
        print(f'ERROR: Could not find restored file "{srce_file}".')
        sys.exit(1)

    panel_segments_dir = Path(comics_database.get_fantagraphics_panel_segments_volume_dir(volume))
    panel_segments_file = panel_segments_dir / (page + ".json")
    if not panel_segments_file.is_file():
        print(f'WARN: Could not find segments file "{panel_segments_file}". Returning full page.')

    target_file = get_target_file(title, panel_type, page, panel)
    if target_file.is_file():
        print(f'ERROR: Target file already exists. Cannot overwrite: "{target_file}".')
        sys.exit(1)

    print(f'"{title}" [{volume}]: {page}, {panel}, {PANEL_TYPES[panel_type]}')

    write_cropped_image_file(srce_file, panel_segments_file, target_file, panel_type)

    open_gimp(target_file)
