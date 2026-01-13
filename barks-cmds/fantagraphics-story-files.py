# ruff: noqa: T201
import zipfile
from pathlib import Path

import typer
from barks_fantagraphics import panel_bounding
from barks_fantagraphics.barks_titles import NON_COMIC_TITLES
from barks_fantagraphics.comic_book import ModifiedType
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_titles
from barks_fantagraphics.comics_utils import (
    get_abbrev_path,
    get_timestamp,
    get_timestamp_as_str,
)
from barks_fantagraphics.pages import get_restored_srce_dependencies, get_sorted_srce_and_dest_pages
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from intspan import intspan
from loguru_config import LoguruConfig

APP_LOGGING_NAME = "sfil"


def print_sources(indent: int, source_list: list[str]) -> None:
    if not source_list:
        print()
        return

    print(f'"{source_list[0]}"')
    for srce in source_list[1:]:
        print(" " * indent + f'"{srce}"')


def get_filepath_with_date(
    is_a_comic: bool, file: Path | zipfile.Path, timestamp: float, out_of_date_marker: str
) -> str:
    if not is_a_comic and (("upscayled" in str(file)) or ("svg" in str(file))):
        return ""

    missing_timestamp = "FILE MISSING          "  # same length as timestamp str

    if file.is_file():
        file_str = get_abbrev_path(file)
        file_timestamp = get_timestamp_as_str(timestamp, "-", date_time_sep=" ", hr_sep=":")
    else:
        file_str = file
        file_timestamp = missing_timestamp

    return f'{file_timestamp}:{out_of_date_marker}"{file_str}"'


app = typer.Typer()
log_level = ""


@app.command(help="Fantagraphics source files")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    mods: bool = False,
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    # Global variable accessed by loguru-config.
    global log_level  # noqa: PLW0603
    log_level = log_level_str
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    if volumes_str and title_str:
        msg = "Options --volume and --title are mutually exclusive."
        raise typer.BadParameter(msg)

    volumes = list(intspan(volumes_str))
    comics_database = ComicsDatabase()
    panel_bounding.warn_on_panels_bbox_height_less_than_av = False
    titles = get_titles(comics_database, volumes, title_str)

    for title in titles:
        comic_book = comics_database.get_comic_book(title)

        srce_and_dest_pages = get_sorted_srce_and_dest_pages(comic_book, get_full_paths=True)

        srce_pages = srce_and_dest_pages.srce_pages
        dest_pages = srce_and_dest_pages.dest_pages

        max_len_page_type = max([len(dp.page_type.name) for dp in dest_pages])
        is_a_comic_book = comic_book.get_title_enum() not in NON_COMIC_TITLES

        print()
        print(f'"{title}" source files:')

        for srce_page, dest_page in zip(srce_pages, dest_pages, strict=True):
            dest_page_num = Path(dest_page.page_filename).stem
            page_type_str = dest_page.page_type.name
            prev_timestamp = get_timestamp(Path(dest_page.page_filename))

            sources = [
                get_filepath_with_date(
                    is_a_comic_book, Path(dest_page.page_filename), prev_timestamp, " "
                )
            ]
            is_modded = False
            for dependency in get_restored_srce_dependencies(comic_book, srce_page):
                if dependency.mod_type != ModifiedType.ORIGINAL:
                    is_modded = True
                out_of_date_str = (
                    "*"
                    if (dependency.timestamp < 0) or (dependency.timestamp > prev_timestamp)
                    else " "
                )
                file_info = get_filepath_with_date(
                    is_a_comic_book, dependency.file, dependency.timestamp, out_of_date_str
                )
                if file_info:
                    sources.append(file_info)
                    prev_timestamp = dependency.timestamp

            if not mods or is_modded:
                print(
                    f"    {dest_page_num}"
                    f" ({dest_page.page_num:02}) - {page_type_str:{max_len_page_type}}: ",
                    end="",
                )
                print_sources(4 + 2 + 5 + 2 + 3 + max_len_page_type + 2, sources)

        print()


if __name__ == "__main__":
    app()
