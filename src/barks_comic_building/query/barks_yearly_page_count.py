# ruff: noqa: T201

from collections import defaultdict
from pathlib import Path

import typer
from barks_fantagraphics.barks_titles import (
    BARKS_TITLE_INFO,
    BARKS_TITLES,
    NON_COMIC_TITLES,
    ONE_PAGERS,
    Titles,
)
from barks_fantagraphics.comic_book import get_total_num_pages
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.common_typer_options import LogLevelArg
from loguru_config import LoguruConfig

import barks_comic_building.log_setup as _log_setup
from barks_comic_building.query.yearly_graph import create_yearly_plot

APP_LOGGING_NAME = "ycnt"

_RESOURCES = Path(__file__).parent.parent / "resources"

TEMP_PAGE_COUNTS = {
    Titles.DONALD_DUCK_FINDS_PIRATE_GOLD: 32,
    Titles.VICTORY_GARDEN_THE: 10,
    Titles.RABBITS_FOOT_THE: 10,
    Titles.LIFEGUARD_DAZE: 10,
    Titles.GOOD_DEEDS: 10,
    Titles.LIMBER_W_GUEST_RANCH_THE: 10,
    Titles.MIGHTY_TRAPPER_THE: 10,
    Titles.DONALD_DUCK_AND_THE_MUMMYS_RING: 28,
    Titles.DONALDS_GRANDMA_DUCK: 0,
    Titles.CAMP_COUNSELOR: 8,
    Titles.ATTIC_ANTICS: 10,
    Titles.GOOD_DEEDS_THE: 10,
    Titles.BLACK_WEDNESDAY: 10,
    Titles.WATCHFUL_PARENTS_THE: 10,
    Titles.WAX_MUSEUM_THE: 10,
    Titles.PAUL_BUNYAN_MACHINE_THE: 21,
    Titles.KNIGHTS_OF_THE_FLYING_SLEDS: 10,
    Titles.FUN_WHATS_THAT: 0,
    Titles.WITCHING_STICK_THE: 5,
    Titles.INVENTORS_CONTEST_THE: 4,
    Titles.GAB_MUFFER_THE: 0,
    Titles.STUBBORN_STORK_THE: 0,
    Titles.MILKTIME_MELODIES: 0,
    Titles.LOST_RABBIT_FOOT_THE: 0,
    Titles.OODLES_OF_OOMPH: 0,
    Titles.MASTER_GLASSER_THE: 10,
    Titles.ISLAND_IN_THE_SKY: 18,
    Titles.UNDER_THE_POLAR_ICE: 10,
    Titles.HOUND_OF_THE_WHISKERVILLES: 8,
    Titles.RIDING_THE_PONY_EXPRESS: 10,
    Titles.CAVE_OF_THE_WINDS: 0,
    Titles.MADBALL_PITCHER_THE: 0,
    Titles.MIXED_UP_MIXER: 0,
    Titles.WANT_TO_BUY_AN_ISLAND: 10,
    Titles.FROGGY_FARMER: 0,
    Titles.BEAR_TAMER_THE: 0,
    Titles.PIPELINE_TO_DANGER: 17,
    Titles.YOICKS_THE_FOX: 9,
    Titles.WAR_PAINT: 4,
    Titles.DOG_SITTER_THE: 10,
    Titles.MYSTERY_OF_THE_LOCH: 10,
    Titles.VILLAGE_BLACKSMITH_THE: 10,
    Titles.FRAIDY_FALCON_THE: 10,
    Titles.ALL_AT_SEA: 17,
    Titles.FISHY_WARDEN: 4,
    Titles.TWO_WAY_LUCK: 9,
    Titles.BALLOONATICS: 10,
    Titles.TURKEY_TROUBLE: 10,
    Titles.MISSILE_FIZZLE: 10,
    Titles.ROCKS_TO_RICHES: 10,
    Titles.SITTING_HIGH: 10,
    Titles.THATS_NO_FABLE: 18,
    Titles.CLOTHES_MAKE_THE_DUCK: 8,
    Titles.THAT_SMALL_FEELING: 4,
    Titles.MADCAP_MARINER_THE: 10,
    Titles.TERRIBLE_TOURIST: 10,
    Titles.LOST_FRONTIER: 10,
    Titles.YOU_CANT_WIN: 4,
    Titles.BILLIONS_IN_THE_HOLE: 16,
    Titles.BONGO_ON_THE_CONGO: 10,
    Titles.STRANGER_THAN_FICTION: 10,
    Titles.BOXED_IN: 10,
    Titles.CHUGWAGON_DERBY: 10,
    Titles.MYTHTIC_MYSTERY: 14,
    Titles.WILY_RIVAL: 4,
    Titles.DUCK_LUCK: 10,
    Titles.MR_PRIVATE_EYE: 10,
    Titles.HOUND_HOUNDER: 10,
    Titles.GOLDEN_NUGGET_BOAT_THE: 19,
    Titles.FAST_AWAY_CASTAWAY: 4,
    Titles.GIFT_LION: 4,
    Titles.JET_WITCH: 10,
    Titles.BOAT_BUSTER: 10,
    Titles.MIDAS_TOUCH_THE: 17,
    Titles.MONEY_BAG_GOAT: 6,
    Titles.DUCKBURGS_DAY_OF_PERIL: 4,
    Titles.NORTHEASTER_ON_CAPE_QUACK: 10,
    Titles.MOVIE_MAD: 10,
    Titles.TEN_CENT_VALENTINE: 10,
    Titles.CAVE_OF_ALI_BABA: 16,
    Titles.DEEP_DOWN_DOINGS: 9,
    Titles.GREAT_POP_UP_THE: 0,
    Titles.JUNGLE_BUNGLE: 10,
    Titles.MERRY_FERRY: 10,
    Titles.UNSAFE_SAFE_THE: 19,
    Titles.MUCH_LUCK_MCDUCK: 7,
    Titles.MADCAP_INVENTORS: 4,
    Titles.MEDALING_AROUND: 10,
    Titles.WAY_OUT_YONDER: 10,
    Titles.CANDY_KID_THE: 10,
    Titles.SPICY_TALE_A: 18,
    Titles.FINNY_FUN: 4,
    Titles.TRICKY_EXPERIMENT: 8,
    Titles.MASTER_WRECKER: 10,
    Titles.RAVEN_MAD: 10,
    Titles.STALWART_RANGER: 10,
    Titles.LOG_JOCKEY: 10,
    Titles.SNOW_DUSTER: 4,
    Titles.ODDBALL_ODYSSEY: 19,
    Titles.POSTHASTY_POSTMAN: 4,
    Titles.STATUS_SEEKER_THE: 20,
    Titles.MATTER_OF_FACTORY_A: 10,
    Titles.CHRISTMAS_CHEERS: 10,
    Titles.JINXED_JALOPY_RACE_THE: 10,
    Titles.FOR_OLD_DIMES_SAKE: 18,
    Titles.STONES_THROW_FROM_GHOST_TOWN_A: 10,
    Titles.SPARE_THAT_HAIR: 10,
    Titles.DUCKS_EYE_VIEW_OF_EUROPE_A: 10,
    Titles.CASE_OF_THE_STICKY_MONEY_THE: 20,
    Titles.GALL_OF_THE_WILD: 10,
    Titles.ZERO_HERO: 10,
    Titles.BEACH_BOY: 10,
    Titles.CROWN_OF_THE_MAYAS: 21,
    Titles.INVISIBLE_INTRUDER_THE: 6,
    Titles.ISLE_OF_GOLDEN_GEESE: 23,
    Titles.TRAVEL_TIGHTWAD_THE: 4,
    Titles.DUCKBURG_PET_PARADE_THE: 10,
    Titles.HELPERS_HELPING_HAND_A: 4,
    Titles.HAVE_GUN_WILL_DANCE: 10,
    Titles.LOST_BENEATH_THE_SEA: 22,
    Titles.LEMONADE_FLING_THE: 5,
    Titles.ONCE_UPON_A_CARNIVAL: 10,
    Titles.DOUBLE_MASQUERADE: 10,
    Titles.MAN_VERSUS_MACHINE: 4,
    Titles.THRIFTY_SPENDTHRIFT_THE: 20,
    Titles.FEUD_AND_FAR_BETWEEN: 10,
    Titles.BUBBLEWEIGHT_CHAMP: 10,
    Titles.JONAH_GYRO: 4,
    Titles.MANY_FACES_OF_MAGICA_DE_SPELL_THE: 22,
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

app = typer.Typer()


@app.command(help="Barks yearly page counts")
def main(log_level_str: LogLevelArg = "DEBUG") -> None:
    _log_setup.log_level = log_level_str
    _log_setup.log_filename = "barks-cmds.log"
    _log_setup.APP_LOGGING_NAME = APP_LOGGING_NAME
    LoguruConfig.load(_RESOURCES / "log-config.yaml")

    comics_database = ComicsDatabase()

    page_counts = defaultdict(int)
    for title_info in BARKS_TITLE_INFO:
        if title_info.title in NON_COMIC_TITLES:
            continue
        if title_info.title in ONE_PAGERS:
            num_pages = 1
        elif title_info.title in TEMP_PAGE_COUNTS:
            num_pages = TEMP_PAGE_COUNTS[title_info.title]
        else:
            title_str = BARKS_TITLES[title_info.title]
            # noinspection PyBroadException
            try:
                comic_book = comics_database.get_comic_book(title_str)
            except Exception:  # noqa: BLE001
                print(f"Titles.{title_info.title.name}: X,")
                continue

            num_pages = get_total_num_pages(comic_book)
            if num_pages <= 1:
                msg = f'For title "{title_str}", the page count is too small.'
                raise ValueError(msg)

        page_counts[title_info.submitted_year] += num_pages

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
