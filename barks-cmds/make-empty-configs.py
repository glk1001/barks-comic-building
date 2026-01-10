# ruff: noqa: ERA001
import itertools
import json
from pathlib import Path

import typer
from barks_fantagraphics.comics_consts import INTERNAL_DATA_DIR
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_issue_titles, get_titles_and_info
from barks_fantagraphics.comics_utils import get_abbrev_path
from barks_fantagraphics.fanta_comics_info import get_fanta_volume_str
from comic_utils.common_typer_options import LogLevelArg, VolumesArg
from intspan import intspan
from loguru import logger
from loguru_config import LoguruConfig

APP_LOGGING_NAME = "mcfg"

TOC_PAGE_OFFSET = 7
TOC_DIR = INTERNAL_DATA_DIR

app = typer.Typer()
log_level = ""


def create_empty_config_file(  # noqa: PLR0913
    comics_database: ComicsDatabase,
    volume: int,
    ttl: str,
    is_barks_ttl: bool,
    first_page: int,
    last_page: int,
) -> None:
    ini_file = comics_database.get_ini_file(ttl)
    # ini_file = os.path.join("/tmp", ttl + ".ini")
    if ini_file.exists():
        msg = f'Ini file "{ini_file}" already exists.'
        raise FileExistsError(msg)

    logger.info(f'Creating empty config file: "{get_abbrev_path(ini_file)}".')
    with ini_file.open("w") as f:
        f.write("[info]\n")
        if is_barks_ttl:
            f.write(f"title = {ttl}\n")
        else:
            f.write("title =\n")
        f.write(f"source_comic = {get_fanta_volume_str(volume)}\n")
        f.write("\n")
        f.write("[pages]\n")
        f.write("title_empty = TITLE\n")
        f.write(f"{first_page} - {last_page} = BODY\n")


@app.command(help="Make empty comic configs")
def main(
    volumes_str: VolumesArg = "",
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    # Global variable accessed by loguru-config.
    global log_level  # noqa: PLW0603
    log_level = log_level_str
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    volumes = list(intspan(volumes_str))
    assert volumes
    assert len(volumes) == 1
    volume = volumes[0]
    comics_database = ComicsDatabase()

    toc_file = TOC_DIR / f"vol-{volume}-toc-gemini.json"
    toc_info = [] if not toc_file.is_file() else json.loads(toc_file.read_bytes())
    toc_dict = (
        {}
        if not toc_info
        else {
            t["title"]: (t["page"] + TOC_PAGE_OFFSET, t_next["page"] + TOC_PAGE_OFFSET - 1)
            for t, t_next in itertools.pairwise(toc_info)
        }
    )

    titles_and_info = get_titles_and_info(comics_database, volumes, title="", configured_only=False)
    titles_config_info = get_issue_titles(comics_database, titles_and_info)

    if len(titles_config_info) == 0:
        logger.error(f"There are no titles to configure for Fanta volume {volume}.")
    else:
        titles = []
        for title_config_info in titles_config_info:
            title = title_config_info[0]
            is_barks_title = title_config_info[2].comic_book_info.is_barks_title
            title_is_configured = title_config_info[3]
            start_page, end_page = (0, 0) if not toc_dict else toc_dict[title]

            if title_is_configured:
                logger.info(f'Title: "{title}" is already configured - skipping.')
                continue

            titles.append((title, is_barks_title, start_page, end_page))

        logger.info("")
        for title, is_barks_title, start_page, end_page in titles:
            create_empty_config_file(
                comics_database, volume, title, is_barks_title, start_page, end_page
            )
