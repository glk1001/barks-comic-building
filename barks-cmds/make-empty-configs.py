# ruff: noqa: ERA001
import json
import sys
from pathlib import Path

from barks_fantagraphics.comics_cmd_args import CmdArgNames, CmdArgs
from barks_fantagraphics.comics_utils import get_abbrev_path
from barks_fantagraphics.fanta_comics_info import FantaComicBookInfo, get_fanta_volume_str
from loguru import logger
from loguru_config import LoguruConfig

APP_LOGGING_NAME = "mcfg"

TOC_DIR = Path(
        "/home/greg/Prj/github/barks-compleat-digital/barks-compleat-reader/src/barks-fantagraphics/data")


def get_issue_titles(
        title_info_list: list[tuple[str, FantaComicBookInfo]],
) -> list[tuple[str, bool, bool]]:
    comic_issue_title_info_list = []
    for title_info in title_info_list:
        ttl = title_info[0]
        fanta_info = title_info[1]
        is_configured, _ = comics_database.is_story_title(ttl)
        comic_issue_title_info_list.append(
                (ttl, is_configured, fanta_info.comic_book_info.is_barks_title)
        )

    return comic_issue_title_info_list


def create_empty_config_file(ttl: str, is_barks_ttl: bool, first_page: int, last_page: int) -> None:
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


if __name__ == "__main__":
    cmd_args = CmdArgs("Make empty configs", CmdArgNames.VOLUME)
    args_ok, error_msg = cmd_args.args_are_valid()
    if not args_ok:
        logger.error(error_msg)
        sys.exit(1)

    # Global variable accessed by loguru-config.
    log_level = cmd_args.get_log_level()
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    comics_database = cmd_args.get_comics_database()
    volume = int(cmd_args.get_volume())

    toc_file = TOC_DIR / f"vol-{volume}-toc-gemini.json"
    toc_info = [] if not toc_file.is_file() else json.loads(toc_file.read_bytes())
    toc_dict = {} if not toc_info else {t["title"]: (t["page"], t_next["page"] - 1) for t, t_next in
                                        zip(toc_info, toc_info[1:])}

    titles_and_info = cmd_args.get_titles_and_info(configured_only=False)
    titles_config_info = get_issue_titles(titles_and_info)

    if len(titles_config_info) == 0:
        logger.error(f"There are no titles to configure for Fanta volume {volume}.")
    else:
        titles = []
        for title_config_info in titles_config_info:
            title = title_config_info[0]
            title_is_configured = title_config_info[1]
            is_barks_title = title_config_info[2]
            start_page, end_page = (0, 0) if not toc_dict else toc_dict[title]

            if title_is_configured:
                logger.info(f'Title: "{title}" is already configured - skipping.')
                continue

            titles.append((title, is_barks_title, start_page, end_page))

        logger.info("")
        for title, is_barks_title, start_page, end_page in titles:
            create_empty_config_file(title, is_barks_title, start_page, end_page)
