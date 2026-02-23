# ruff: noqa: T201
import json
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from barks_fantagraphics.comic_book import get_page_str
from barks_fantagraphics.comics_consts import PageType
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_title_from_volume_page
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from comic_utils.pil_image_utils import load_pil_image_for_reading
from intspan import intspan
from loguru_config import LoguruConfig

import barks_comic_building.log_setup as _log_setup

APP_LOGGING_NAME = "ettl"

_RESOURCES = Path(__file__).parent.parent / "resources"

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


def get_source_file(comics_database: ComicsDatabase, volume: int, panel_typ: str, pge: str) -> Path:
    if panel_typ == "cl":
        upscayl_dir = Path(
            comics_database.get_fantagraphics_restored_upscayled_volume_image_dir(volume)
        )
        return upscayl_dir / (pge + ".png")

    restored_dir = Path(comics_database.get_fantagraphics_restored_volume_image_dir(volume))
    return restored_dir / (pge + ".png")


def get_target_file(ttl: str, panel_typ: str, pge: str, panl: str) -> Path:
    if panel_typ == "i":
        return TARGET_ROOT_DIR / PANEL_TYPES[panel_typ] / (ttl + ".png")

    target_dir = TARGET_ROOT_DIR / PANEL_TYPES[panel_typ] / ttl
    target_dir.mkdir(parents=True, exist_ok=True)

    return target_dir / f"{pge}-{panl}.png"


def write_cropped_image_file(
    srce_image_file: Path, segments_file: Path, target_image_file: Path, panel_typ: str, panel: str
) -> None:
    print(f'Source: "{srce_image_file}".')
    print(f'Segments: "{segments_file}".')

    if not segments_file.is_file():
        image = load_pil_image_for_reading(srce_image_file)
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

        image = load_pil_image_for_reading(srce_image_file)
        subimage = image.crop((left, bottom, right, upper))
        subimage.save(target_image_file, optimize=True, compress_level=9)

        print(f'Saved cropped image to "{target_image_file}".')


def open_gimp(image_file: Path) -> None:
    command = [*GIMP_EXE, str(image_file)]

    _proc = subprocess.Popen(command)  # noqa: S603

    print(f'Gimp should now be running with image "{image_file}".')


app = typer.Typer()


@app.command(help="Edit comic title page")
def main(  # noqa: C901, PLR0913, PLR0915
    volumes_str: VolumesArg = "",
    title: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
    panel_type: Annotated[str, typer.Option("--type", help="Panel type")] = "",
    page_panel: Annotated[str, typer.Option("--p-p", help="Page and panel")] = "",
    comic_page_panel: Annotated[str, typer.Option("--cp-p", help="Comic page and panel")] = "",
) -> None:
    _log_setup.log_level = log_level_str
    _log_setup.log_filename = "barks-cmds.log"
    _log_setup.APP_LOGGING_NAME = APP_LOGGING_NAME
    LoguruConfig.load(_RESOURCES / "log-config.yaml")

    if volumes_str and title:
        msg = "Options --volume and --title are mutually exclusive."
        raise typer.BadParameter(msg)
    if page_panel and comic_page_panel:
        msg = "Options --p-p and --cp-p are mutually exclusive."
        raise typer.BadParameter(msg)
    if volumes_str and comic_page_panel:
        msg = "Options --volume and --cp-p are mutually exclusive."
        raise typer.BadParameter(msg)

    if panel_type not in PANEL_TYPES:
        print(f'ERROR: Panel type "{panel_type}" is not in {list(PANEL_TYPES.keys())}.')
        sys.exit(1)

    comics_database = ComicsDatabase()

    if volumes_str:
        volumes = list(intspan(volumes_str))
        assert len(volumes) == 1
        volume = volumes[0]
        (page, panel) = page_panel.split("-")
        page = get_page_str(int(page))
        title, comic_page = get_title_from_volume_page(comics_database, volume, page)
        assert title
        assert comic_page != -1
    else:
        comic = comics_database.get_comic_book(title)
        volume = comic.get_fanta_volume()

        valid_page_list = [
            p.page_filenames for p in comic.page_images_in_order if p.page_type == PageType.BODY
        ]
        if page_panel:
            (page, panel) = page_panel.split("-")
        else:
            (comic_page, panel) = comic_page_panel.split("-")
            first_page = int(valid_page_list[0])
            page = first_page + int(comic_page) - 1

        page = get_page_str(int(page))
        if page not in valid_page_list:
            print(f'ERROR: Page "{page}" is not in {valid_page_list}.')
            sys.exit(1)

    srce_file = get_source_file(comics_database, volume, panel_type, page)
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

    write_cropped_image_file(srce_file, panel_segments_file, target_file, panel_type, panel)

    open_gimp(target_file)


if __name__ == "__main__":
    app()
