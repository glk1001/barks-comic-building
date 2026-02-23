# ruff: noqa: T201

import subprocess
import sys
from pathlib import Path

import typer
from barks_fantagraphics.comic_book import get_page_str
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.common_typer_options import LogLevelArg, PagesArg, VolumesArg
from intspan import intspan
from loguru_config import LoguruConfig

import barks_comic_building.log_setup as _log_setup

APP_LOGGING_NAME = "svpg"

_RESOURCES = Path(__file__).parent.parent / "resources"

VIEWER_EXE = ["/usr/bin/loupe"]


def open_viewer(image_file: Path) -> None:
    command = [*VIEWER_EXE, str(image_file)]

    _proc = subprocess.Popen(command)  # noqa: S603

    print(f'Image Viewer should now be showing image "{image_file}".')


app = typer.Typer()


@app.command(help="Open image viewer for Fanta volume page")
def main(
    volumes_str: VolumesArg = "",
    page_num_str: PagesArg = "",
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    _log_setup.log_level = log_level_str
    _log_setup.log_filename = "barks-cmds.log"
    _log_setup.APP_LOGGING_NAME = APP_LOGGING_NAME
    LoguruConfig.load(_RESOURCES / "log-config.yaml")

    volumes = list(intspan(volumes_str))
    assert volumes
    assert len(volumes) == 1
    volume = volumes[0]
    comics_database = ComicsDatabase()
    page = get_page_str(int(page_num_str))

    restored_dir = Path(comics_database.get_fantagraphics_restored_volume_image_dir(volume))
    restored_srce_file = restored_dir / (page + ".png")
    if not restored_srce_file.is_file():
        print(f'Error: Could not find restored file "{restored_srce_file}".')
        sys.exit(1)

    print(f"{volume}: {page}")

    open_viewer(restored_srce_file)


if __name__ == "__main__":
    app()
