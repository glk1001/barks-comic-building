# ruff: noqa: T201
import json
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from barks_fantagraphics.comic_book import get_page_str
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_title_from_volume_page, get_volume_and_page
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from comic_utils.pil_image_utils import load_pil_image_for_reading
from intspan import intspan

from barks_comic_building.cli_setup import init_logging

APP_LOGGING_NAME = "ettl"

GIMP_EXE = ["run-gimp.sh"]

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


def _split_page_panel(option: str, page_panel: str) -> tuple[str, str]:
    page_num_str, sep, panel = page_panel.partition("-")
    if not sep or not page_num_str.isdecimal() or not panel.isdecimal() or int(panel) < 1:
        msg = f'{option} must be "<page>-<panel>", with the panel counted from 1: "{page_panel}".'
        raise typer.BadParameter(msg)
    return page_num_str, panel


def resolve_page_and_panel(
    comics_database: ComicsDatabase,
    volumes_str: str,
    title: str,
    page_panel: str,
    comic_page_panel: str,
) -> tuple[int, str, str, str]:
    """Work out which scan page and panel the options ask for.

    The page can be named three ways: ``--volume`` with ``--p-p`` (a page of that
    volume), ``--title`` with ``--p-p`` (a page of the title's volume, which must belong
    to the title), or ``--title`` with ``--cp-p`` (the title's nth body page).

    Args:
        comics_database: The database to look titles and volumes up in.
        volumes_str: The ``--volume`` option; a single volume, or empty.
        title: The ``--title`` option, or empty.
        page_panel: The ``--p-p`` option, "<volume page>-<panel>", or empty.
        comic_page_panel: The ``--cp-p`` option, "<comic page>-<panel>", or empty.

    Returns:
        The volume, the title, the scan page's name ("227") and the panel number.

    Raises:
        typer.BadParameter: If the options do not name exactly one page and panel.

    """
    if bool(volumes_str) == bool(title):
        msg = "Give exactly one of --volume and --title."
        raise typer.BadParameter(msg)
    if bool(page_panel) == bool(comic_page_panel):
        msg = "Give exactly one of --p-p and --cp-p."
        raise typer.BadParameter(msg)
    if volumes_str and comic_page_panel:
        msg = "Options --volume and --cp-p are mutually exclusive."
        raise typer.BadParameter(msg)

    if comic_page_panel:
        page_num_str, panel = _split_page_panel("--cp-p", comic_page_panel)
        try:
            volume, page = get_volume_and_page(comics_database, title, page_num_str)
        except RuntimeError as e:
            raise typer.BadParameter(str(e)) from e
        return volume, title, page, panel

    page_num_str, panel = _split_page_panel("--p-p", page_panel)
    page = get_page_str(int(page_num_str))

    if title:
        # Only the volume is wanted here: the page was given as a volume page.
        volume, _first_page = get_volume_and_page(comics_database, title, "")
    else:
        volumes = list(intspan(volumes_str))
        if len(volumes) != 1:
            msg = f'--volume must be a single volume: "{volumes_str}".'
            raise typer.BadParameter(msg)
        volume = volumes[0]

    page_title, _comic_page = get_title_from_volume_page(comics_database, volume, page)
    if not page_title:
        msg = f"Volume {volume} has no story on page {page}."
        raise typer.BadParameter(msg)
    if title and page_title != title:
        msg = f'Volume {volume} page {page} belongs to "{page_title}", not "{title}".'
        raise typer.BadParameter(msg)

    return volume, page_title, page, panel


app = typer.Typer()


@app.command(help="Edit comic title page")
def main(  # noqa: PLR0913
    volumes_str: VolumesArg = "",
    title: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
    panel_type: Annotated[str, typer.Option("--type", help="Panel type")] = "",
    page_panel: Annotated[str, typer.Option("--p-p", help="Page and panel")] = "",
    comic_page_panel: Annotated[str, typer.Option("--cp-p", help="Comic page and panel")] = "",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    if panel_type not in PANEL_TYPES:
        print(f'ERROR: Panel type "{panel_type}" is not in {list(PANEL_TYPES.keys())}.')
        sys.exit(1)

    comics_database = ComicsDatabase()
    volume, title, page, panel = resolve_page_and_panel(
        comics_database, volumes_str, title, page_panel, comic_page_panel
    )

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
