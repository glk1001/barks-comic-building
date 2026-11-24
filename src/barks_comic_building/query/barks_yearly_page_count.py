"""Plot how many story pages Barks submitted in each year."""
# ruff: noqa: T201

from collections import defaultdict

import typer
from barks_fantagraphics.barks_titles import ENUM_TO_STR_TITLE, Titles
from barks_fantagraphics.comic_book_info import (
    BARKS_TITLE_INFO,
    COVERS_SET,
    NON_COMIC_TITLES,
    ONE_PAGERS,
    SYNTHETIC_TITLES,
)
from barks_fantagraphics.comics_consts import PageType
from barks_fantagraphics.comics_database import ComicsDatabase, TitleNotFoundError
from comic_utils.common_typer_options import LogLevelArg

from barks_comic_building.cli_setup import init_logging
from barks_comic_building.query.yearly_graph import create_yearly_plot

APP_LOGGING_NAME = "ycnt"

# Story page counts for the titles that have no ini file yet, and only for those: a
# configured title is counted from its own page list, whatever this table says. It used to
# be read first, and went on answering for 118 titles long after they were configured -
# "Donald Duck Finds Pirate Gold" at 32 pages instead of 64. Drop an entry once its title
# is configured; until then a 0 means the count is not known.
# cspell:disable  # noqa: ERA001
UNCONFIGURED_PAGE_COUNTS = {
    Titles.ATTIC_ANTICS: 10,
    Titles.DUCKS_EYE_VIEW_OF_EUROPE_A: 10,
    Titles.GALL_OF_THE_WILD: 10,
    Titles.ZERO_HERO: 10,
    Titles.BEACH_BOY: 10,
    Titles.DUCKBURG_PET_PARADE_THE: 10,
    Titles.HAVE_GUN_WILL_DANCE: 10,
    Titles.ONCE_UPON_A_CARNIVAL: 10,
    Titles.DOUBLE_MASQUERADE: 10,
    Titles.FEUD_AND_FAR_BETWEEN: 10,
    Titles.BUBBLEWEIGHT_CHAMP: 10,
    Titles.CAPN_BLIGHTS_MYSTERY_SHIP: 10,
    Titles.LOONY_LUNAR_GOLD_RUSH_THE: 17,
    Titles.OLYMPIAN_TORCH_BEARER_THE: 10,
    Titles.RUG_RIDERS_IN_THE_SKY: 16,
    Titles.HOW_GREEN_WAS_MY_LETTUCE: 15,
    Titles.GREAT_WIG_MYSTERY_THE: 20,
    Titles.HERO_OF_THE_DIKE: 10,
    Titles.INTERPLANETARY_POSTMAN: 15,
    Titles.UNFRIENDLY_ENEMIES: 10,
    Titles.BILLION_DOLLAR_SAFARI_THE: 20,
    Titles.DELIVERY_DILEMMA: 10,
    Titles.INSTANT_HERCULES: 10,
    Titles.MCDUCK_OF_ARABIA: 24,
    Titles.MYSTERY_OF_THE_GHOST_TOWN_RAILROAD: 24,
    Titles.DUCK_OUT_OF_LUCK: 10,
    Titles.SWAMP_OF_NO_RETURN_THE: 24,
    Titles.MONKEY_BUSINESS: 10,
    Titles.GIANT_ROBOT_ROBBERS_THE: 20,
    Titles.NORTH_OF_THE_YUKON: 24,
    Titles.PHANTOM_OF_NOTRE_DUCK_THE: 24,
    Titles.SO_FAR_AND_NO_SAFARI: 24,
    Titles.QUEEN_OF_THE_WILD_DOG_PACK_THE: 24,
    Titles.HOUSE_OF_HAUNTS: 24,
    Titles.TREASURE_OF_MARCO_POLO: 24,
    Titles.BEAUTY_BUSINESS_THE: 10,
    Titles.MICRO_DUCKS_FROM_OUTER_SPACE: 24,
    Titles.NOT_SO_ANCIENT_MARINER_THE: 10,
    Titles.HEEDLESS_HORSEMAN_THE: 24,
    Titles.HALL_OF_THE_MERMAID_QUEEN: 24,
    Titles.DOOM_DIAMOND_THE: 24,
    Titles.CATTLE_KING_THE: 24,
    Titles.KING_SCROOGE_THE_FIRST: 21,
}
# cspell:enable  # noqa: ERA001

app = typer.Typer()


def get_story_page_count(comics_database: ComicsDatabase, title: Titles) -> int | None:
    """Return how many pages of story a title is.

    Story pages only, so every title is counted in the same unit: the title page, the
    front and back matter and the blanks of a built comic are not pages Barks drew.

    Args:
        comics_database: The database to look a configured title's pages up in.
        title: The title to count.

    Returns:
        The number of story pages, or None for a title with no count to give: one that
        is not a comic, a cover, a synthetic collection (its pages are other titles'
        pages, counted already), or an unconfigured title missing from
        `UNCONFIGURED_PAGE_COUNTS`.

    """
    if title in NON_COMIC_TITLES or title in SYNTHETIC_TITLES or title in COVERS_SET:
        return None
    if title in ONE_PAGERS:
        return 1

    try:
        comic_book = comics_database.get_comic_book(ENUM_TO_STR_TITLE[title])
    except TitleNotFoundError:
        return UNCONFIGURED_PAGE_COUNTS.get(title)

    return sum(1 for page in comic_book.page_images_in_order if page.page_type == PageType.BODY)


def sum_pages_by_year(comics_database: ComicsDatabase) -> tuple[dict[int, int], list[Titles]]:
    """Total the story pages Barks submitted in each year.

    Args:
        comics_database: The database to look configured titles up in.

    Returns:
        The page count for each submission year, and the stories that could not be
        counted because they are neither configured nor in `UNCONFIGURED_PAGE_COUNTS`.

    """
    page_counts: defaultdict[int, int] = defaultdict(int)
    uncounted: list[Titles] = []
    for title_info in BARKS_TITLE_INFO:
        title = title_info.title
        num_pages = get_story_page_count(comics_database, title)
        if num_pages is not None:
            page_counts[title_info.submitted_year] += num_pages
        elif not (title in NON_COMIC_TITLES or title in SYNTHETIC_TITLES or title in COVERS_SET):
            uncounted.append(title)

    return dict(page_counts), uncounted


@app.command(help="Barks yearly page counts")
def main(log_level_str: LogLevelArg = "DEBUG") -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    page_counts, uncounted = sum_pages_by_year(ComicsDatabase())

    for title in uncounted:
        print(f"Not counted - no ini file and no page count: Titles.{title.name}")

    for year in page_counts:
        print(f"{year}: {page_counts[year]}")

    years = sorted(page_counts)
    title = f"Yearly Page Count from {years[0]} to {years[-1]}"
    values_data = [page_counts[y] for y in years]

    print(f"Plotting {len(years)} data points...")

    create_yearly_plot(
        title,
        years=years,
        values=values_data,
        output_filename="/tmp/barks-yearly-page-counts.png",  # noqa: S108
        width_px=1000,
        height_px=732,
        dpi=100,  # A common DPI for screen resolutions
    )


if __name__ == "__main__":
    app()
