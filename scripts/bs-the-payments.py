# ruff: noqa: T201

import os.path
import re
from collections import OrderedDict
from dataclasses import dataclass

from barks_fantagraphics.barks_titles import BARKS_TITLE_DICT, BARKS_TITLES, Titles
from bs4 import BeautifulSoup
from comic_utils.comic_consts import MONTH_AS_LONG_STR

KYLING_TITLE_MAP = {
    "Pirate Gold": Titles.DONALD_DUCK_FINDS_PIRATE_GOLD,
    "Victory Garden": Titles.VICTORY_GARDEN_THE,
    "The Lucky Rabbit's Foot": Titles.RABBITS_FOOT_THE,
    "The Lifeguard": Titles.LIFEGUARD_DAZE,
    "Dude Ranch": Titles.LIMBER_W_GUEST_RANCH_THE,
    "The Mummy's Ring": Titles.DONALD_DUCK_AND_THE_MUMMYS_RING,
    "The Falcon": Titles.FARRAGUT_THE_FALCON,
    "Putty War": Titles.PURLOINED_PUTTY_THE,
    "Tight Wire Artist": Titles.HIGH_WIRE_DAREDEVILS,
    "The Coin Incident": Titles.TEN_CENTS_WORTH_OF_TROUBLE,
    "Seaside Home": Titles.DONALDS_BAY_LOT,
    "Trade Rats": Titles.THIEVERY_AFOOT,
    "Skate Race": Titles.LONG_RACE_TO_PUMPKINBURG_THE,
    "Cow Puncher": Titles.WEBFOOTED_WRANGLER,
    "The Sleepwalker": Titles.ICEBOX_ROBBER_THE,
    "The Woodpecker": Titles.PECKING_ORDER,
    "Grand Canyon Incident": Titles.TAMING_THE_RAPIDS,
    "Wild Horse Taming": Titles.DAYS_AT_THE_LAZY_K,
    "The Radar Tracker": Titles.EYES_IN_THE_DARK,
    "The Three Detectives": Titles.THUG_BUSTERS,
    "Water Ski Race (1)": Titles.GREAT_SKI_RACE_THE,
    "Best Christmas": Titles.DONALD_DUCKS_BEST_CHRISTMAS,
    "Dollar Bill Fight": Titles.TEN_DOLLAR_DITHER,
    "Seals are so Smart!": Titles.SEALS_ARE_SO_SMART,
    "Temper Control Resolution": Titles.DONALD_TAMES_HIS_TEMPER,
    "The Parrot from Singapore": Titles.SINGAPORE_JOE,
    "Master Ice-Fisher": Titles.MASTER_ICE_FISHER,
    "The Jet Engines": Titles.JET_RESCUE,
    "The Monster Kite": Titles.DONALDS_MONSTER_KITE,
    "Biceps Competition": Titles.BICEPS_BLUES,
    "The Posh Dog": Titles.SMUGSNORKLE_SQUATTIE_THE,
    "Dishonest Swimmers": Titles.SWIMMING_SWINDLERS,
    "Hookey Players": Titles.PLAYIN_HOOKEY,
    "The Bill Collector": Titles.BILL_COLLECTORS_THE,
    "Turkey Trouble (1)": Titles.TURKEY_RAFFLE,
    "The Stray Cat": Titles.CANTANKEROUS_CAT_THE,
    "Donald Duck's Atom Bomb": Titles.DONALD_DUCKS_ATOM_BOMB,
    "Giant Garden Bugs": Titles.GOING_BUGGY,
    "Jammed Safe": Titles.JAM_ROBBERS,
    "Picnic Spoilers": Titles.PICNIC_TRICKS,
    "Bee Spree": Titles.DONALDS_POSY_PATCH,
    "The Fake Gold Mine Map": Titles.DONALD_MINES_HIS_OWN_BUSINESS,
    "Master Magician": Titles.MAGICAL_MISERY,
    "Vacation Interruptus": Titles.VACATION_MISERY,
    "Adventure down Under": Titles.ADVENTURE_DOWN_UNDER,
    "The String Trio": Titles.MASTERS_OF_MELODY_THE,
    "Volunteer Fireman": Titles.FIREMAN_DONALD,
    "Turkey Shoot": Titles.TERRIBLE_TURKEY_THE,
    "Wintertime Wagers": Titles.WINTERTIME_WAGER,
    "The Watchman Watchers": Titles.WATCHING_THE_WATCHMAN,
    "Telegram Messengers": Titles.WIRED,
    "Monkey Party": Titles.GOING_APE,
    "The Juvenile Professor": Titles.SPOIL_THE_ROD,
    "Rocket Race": Titles.ROCKET_RACE_TO_THE_MOON,
    "Coast Patrolman": Titles.DONALD_OF_THE_COAST_GUARD,
    "The Fund-Raisers": Titles.GLADSTONE_RETURNS,
    "The Strange Golf Game": Titles.LINKS_HIJINKS,
    "Pearl Hunt": Titles.PEARLS_OF_WISDOM,
    "Fox Hunt": Titles.FOXY_RELATIONS,
    "Radio Quiz Show": Titles.CRAZY_QUIZ_SHOW_THE,
    "The Truant Officer": Titles.TRUANT_OFFICER_DONALD,
    "Nightmares": Titles.DONALD_DUCKS_WORST_NIGHTMARE,
    "Painted Horses": Titles.PIZEN_SPRING_DUDE_RANCH,
    "The Maharajah's Lost Ruby": Titles.RIVAL_BEACHCOMBERS,
    "Lost in the Andes": Titles.LOST_IN_THE_ANDES,
    "Race to the South Seas": Titles.RACE_TO_THE_SOUTH_SEAS,
    "The Ping-Pong Method": Titles.SUNKEN_YACHT_THE,
    "The Echo Experts": Titles.MANAGING_THE_ECHO_SYSTEM,
    "Pets Galore": Titles.PLENTY_OF_PETS,
    "The Frog Jumping Competition": Titles.GREAT_DUCKBURG_FROG_JUMPING_CONTEST_THE,
    "The Witching Stick (1)": Titles.DOWSING_DUCKS,
    "Goldilocks": Titles.GOLDILOCKS_GAMBIT_THE,
    "Old Love Letters": Titles.DONALDS_LOVE_LETTERS,
    "Rip van Winkle": Titles.RIP_VAN_DONALD,
    "Medicine Mission": Titles.SERUM_TO_CODFISH_COVE,
    "The Wildflower Club Picnic": Titles.WILD_ABOUT_FLOWERS,
    "Ancient Persia": Titles.IN_ANCIENT_PERSIA,
    "You Can't Guess": Titles.YOU_CANT_GUESS,
    "Troublesome Money Manager": Titles.BILLIONS_TO_SNEEZE_AT,
    "Rescue Operation St. Bernard": Titles.OPERATION_ST_BERNARD,
    "Money Crib Cyclone": Titles.FINANCIAL_FABLE_A,
    "April Foolers": Titles.APRIL_FOOLERS_THE,
    "Swimming Pool Trouble": Titles.POOL_SHARKS,
    "Rare Coins": Titles.TROUBLE_WITH_DIMES_THE,
    "Interchanged Golfers": Titles.GLADSTONES_LUCK,
    "Grandma and Daisy": Titles.ATTIC_ANTICS,
    "Woodchucks vs Boonehead": Titles.TEN_STAR_GENERALS,
    "School Evaders": Titles.TRUANT_NEPHEWS_THE,
    "The Anti Beagle Boys Cannon": Titles.TERROR_OF_THE_BEAGLE_BOYS,
    "The Frozen Money Bin": Titles.BIG_BIN_ON_KILLMOTOR_HILL_THE,
    "Turkey Raffle": Titles.GLADSTONES_USUAL_VERY_GOOD_YEAR,
    "A Songwriter's Troubles": Titles.SCREAMING_COWBOY_THE,
    "Statues Galore": Titles.STATUESQUE_SPENDTHRIFTS,
    "The Racing Pigeon": Titles.ROCKET_WING_SAVES_THE_DAY,
    "Gladstone's Dark Secret": Titles.GLADSTONES_TERRIBLE_SECRET,
    "The Think Boxes": Titles.THINK_BOX_BOLLIX_THE,
    "Houseboat Vacation": Titles.HOUSEBOAT_HOLIDAY,
    "Gemstones in the Desert": Titles.GEMSTONE_HUNTERS,
    "Money Spree": Titles.SPENDING_MONEY,
    "The Hypnotizer Gun": Titles.HYPNO_GUN_THE,
    "Thanksgiving Blackmail": Titles.CHARITABLE_CHORE_A,
    "Free Turkey Dinner": Titles.TURKEY_WITH_ALL_THE_SCHEMINGS,
    "Valentine Letter": Titles.MY_LUCKY_VALENTINE,
    "Flipism": Titles.FLIP_DECISION,
    "Easter Parade": Titles.EASTER_ELECTION_THE,
    "Gyro's Trained Worms": Titles.WORM_WEARY,
    "Clubhouse for Sale": Titles.MUCH_ADO_ABOUT_QUACKLY_HALL,
    "The Rainbow Heirs": Titles.SOME_HEIR_OVER_THE_RAINBOW,
    "Climbing Old Demontooth": Titles.MONEY_STAIRS_THE,
    "The Money Bin Tank": Titles.ROUND_MONEY_BIN_THE,
    "Bee Trouble": Titles.BEE_BUMBLES,
    "The Swamp Gas Monster": Titles.WISPY_WILLIE,
    "The Hawaiian Hideaway": Titles.MENEHUNE_MYSTERY_THE,
    "The Christmas Camel": Titles.HAMMY_CAMEL_THE,
    "Donald's Fix-it Shop": Titles.FIX_UP_MIX_UP,
    "The Stationmaster Turkeys": Titles.TURKEY_TROT_AT_ONE_WHISTLE,
    "The Swami's Pearls": Titles.RAFFLE_REVERSAL,
    "The New Flour": Titles.FLOUR_FOLLIES,
    "Helter Skelter Musician": Titles.PRICE_OF_FAME_THE,
    "Midget Racers": Titles.MIDGETS_MADNESS,
    "Salmon Fishing Contest": Titles.SALMON_DERBY,
    "Foiled House Wreckers": Titles.OUTFOXED_FOX,
    "The Chipmunk Mascot": Titles.CHELTENHAMS_CHOICE,
    "Riverboat Runaway": Titles.TRAVELLING_TRUANTS,
    "Ant Attack": Titles.RANTS_ABOUT_ANTS,
    "The Pigeon Carrier": Titles.MILLION_DOLLAR_PIGEON,
    "Super-Waxed Money Bin": Titles.TOO_SAFE_SAFE,
    "The Election Campaign": Titles.CAMPAIGN_OF_NOTE_A,
    "Christmas Submarine Trip": Titles.SEARCH_FOR_THE_CUSPIDORIA,
    "New Year's Resolutions": Titles.NEW_YEARS_REVOLUTIONS,
    "Donald Tells About Kites": Titles.DONALD_DUCK_TELLS_ABOUT_KITES,
    "The Mail Ice Boat": Titles.ICEBOAT_TO_BEAVER_ISLAND,
    "The Taffy Pull": Titles.DAFFY_TAFFY_PULL_THE,
    "The Hickupping Sheriff": Titles.GHOST_SHERIFF_OF_LAST_GASP_THE,
    "The Bathysphere Dive": Titles.DESCENT_INTERVAL_A,
    "The Dogcatcher": Titles.DOGCATCHER_DUCK,
    "Noisy Neighbours": Titles.DONALDS_RAUCOUS_ROLE,
    "The Canoe Contest": Titles.GOOD_CANOES_AND_BAD_CANOES,
    "Billion Dollar Policy": Titles.TROUBLE_INDEMNITY,
    "The Bridge Building Challenge": Titles.CHICKADEE_CHALLENGE_THE,
    "Grandma's Old Bull": Titles.UNORTHODOX_OX_THE,
    "Riches, Riches Everywhere!": Titles.RICHES_RICHES_EVERYWHERE,
    "The Lightning Plant": Titles.TRAPPED_LIGHTNING,
    "The Foam Wall": Titles.INVENTOR_OF_ANYTHING,
    "A Square Inch of Land": Titles.FAULTY_FORTUNE,
    "The Cat Translator": Titles.CAT_BOX_THE,
    "Money on the Move": Titles.MIGRATING_MILLIONS,
    "The Bath Battle": Titles.THREE_UN_DUCKS,
    "Ice Taxi Challenge": Titles.ICE_TAXIS_THE,
    "Housemoving": Titles.SEARCHING_FOR_A_SUCCESSOR,
    "Olympic Try-Outs": Titles.OLYMPIC_HOPEFUL_THE,
    "Backyard Nature Battle": Titles.GOPHER_GOOF_UPS,
    "Swim Cheater": Titles.IN_THE_SWIM,
    "The Uranium Caps": Titles.CAMPING_CONFUSION,
    "The Salmon Hatchery": Titles.MASTER_THE,
    "Whale Project": Titles.WHALE_OF_A_STORY_A,
    "Smoke Writer": Titles.SMOKE_WRITER_IN_THE_SKY,
    "The Forecasting Machine": Titles.FORECASTING_FOLLIES,
    "The Quiz Show Flopper": Titles.COLOSSALEST_SURPRISE_QUIZ_SHOW_THE,
    "Calculated Train Collision": Titles.RUNAWAY_TRAIN_THE,
    "Tricky Fishing Method": Titles.FISHING_MYSTERY,
    "The Imagination Trip": Titles.GYROS_IMAGINATION_INVENTION,
    "The Ultimate Gold-Finder": Titles.SURE_FIRE_GOLD_FINDER_THE,
    "Snow Statue Contest": Titles.STATUES_OF_LIMITATIONS,
    "Border Patrolman": Titles.BORDERLINE_HERO,
    "The Riverboat Race": Titles.FANTASTIC_RIVER_RACE_THE,
    "Hotel Manager": Titles.SAGMORE_SPRINGS_HOTEL,
    "Wild Burro Contest": Titles.TENDERFOOT_TRAP_THE,
    "The Inflated House": Titles.GYRO_BUILDS_A_BETTER_HOUSE,
    "Costume Party Knight": Titles.KNIGHT_IN_SHINING_ARMOR,
    "Pet Service": Titles.DONALDS_PET_SERVICE,
    "The Weather Hole": Titles.IN_KAKIMAW_COUNTRY,
    "Stone Face Cleaners": Titles.LOSING_FACE,
    "Gyro's Super Dye": Titles.DAY_DUCKBURG_GOT_DYED_THE,
    "The Prize Apples": Titles.RED_APPLE_SAP,
    "The Lion's Share": Titles.SPECIAL_DELIVERY,
    "Flowers Everywhere!": Titles.FEARSOME_FLOWERS,
    "The Wishing Stones": Titles.WISHING_STONE_ISLAND,
    "Rocket Around the World": Titles.ROCKET_RACE_AROUND_THE_WORLD,
    "The Chopper Mailman": Titles.PERSISTENT_POSTMAN_THE,
    "Half-Baked Baker": Titles.HALF_BAKED_BAKER_THE,
    "Spring Cleaning": Titles.DODGING_MISS_DAISY,
    "Thor Scares Crows": Titles.GETTING_THOR,
    "Echo Valley": Titles.MOCKING_BIRD_RIDGE,
    "The Catapult Jumping Frog": Titles.OLD_FROGGIE_CATAPULT,
    "The Reindeer Gift": Titles.CODE_OF_DUCKBURG_THE,
    "Daisy's Drama Club": Titles.DRAMATIC_DONALD,
    "The Bird Thought Reader": Titles.KNOW_IT_ALL_MACHINE_THE,
    "The Strange Shipwrecks *": Titles.STRANGE_SHIPWRECKS_THE,
    "The Non-swimmers Pool": Titles.GYRO_GOES_FOR_A_DIP,
    "Cyclone Hill": Titles.HOUSE_ON_CYCLONE_HILL_THE,
    "The Impenetrable Money Bin": Titles.FORBIDIUM_MONEY_BIN_THE,
    "Porpoise Problems": Titles.NOBLE_PORPOISES,
    "Coyote Taming": Titles.LITTLEST_CHICKEN_THIEF_THE,
    "The Flying Farm Hand": Titles.FLYING_FARMHAND_THE,
    "Gold Finder Tracking": Titles.TRACKING_SANDY,
    "Beachcombers' Picnic": Titles.BEACHCOMBERS_PICNIC_THE,
    "Rocket Roasted Turkey Dinner": Titles.ROCKET_ROASTED_CHRISTMAS_TURKEY,
    "Spring": Titles.SPRING_FEVER,
    "Pyramid Hunt": Titles.PYRAMID_SCHEME,
    "The Ghosts of Pizen Bluff": Titles.RETURN_TO_PIZEN_BLUFF,
    "Stalwart Fireman": Titles.LOVELORN_FIREMAN_THE,
    "The Drifting Island": Titles.FLOATING_ISLAND_THE,
    "Forest Tracking Frenzy": Titles.BLACK_FOREST_RESCUE_THE,
    "The Goods Deeds": Titles.GOOD_DEEDS_THE,
    "The Watchful Parent": Titles.WATCHFUL_PARENTS_THE,
    "Mixed-Up Mixer": Titles.MIXED_UP_MIXER,
    "The Dog Sitter": Titles.DOG_SITTER_THE,
    "Mythic Mystery": Titles.MYTHTIC_MYSTERY,
    "Money Bag Coat": Titles.MONEY_BAG_GOAT,
    "Spare that Hair": Titles.SPARE_THAT_HAIR,
    "A Duck's Eye View of Europe": Titles.DUCKS_EYE_VIEW_OF_EUROPE_A,
    "Isle of the Golden Geese": Titles.ISLE_OF_GOLDEN_GEESE,
}

html_file_base = "/home/greg/Books/Carl Barks/Misc/Pay Slips/html-source"

ISSUE_PREFIXES_TO_SKIP = {"NF", "OG"}


@dataclass
class PrelimPaymentInfo:
    issue: str
    title: str
    num_pages: int
    accepted_date: tuple[int, int, int]
    payment: float


def get_prelim_payment_info(row: list[str]) -> PrelimPaymentInfo:
    this_year = int(row[6])

    issue = row[0]
    ttl = get_stripped_new_lines(row[1])
    barks_id = get_stripped_new_lines(row[2])

    num_pages_str = row[3].replace("*", "").strip()
    try:
        num_pages = int(num_pages_str)
    except ValueError:
        raise Exception(f'"{row[3]}" is not an int: "{row}".')

    accepted_date_str = get_stripped_new_lines(row[4])
    try:
        accepted_date = get_date(accepted_date_str, this_year)
    except Exception as e:
        msg = (
            f'Date error for title "{ttl}, issue "{issue}", year {this_year}:'
            f' "{accepted_date_str}": {e}.'
        )
        raise RuntimeError(msg) from e

    payment_str = row[5].replace("*", "").strip()
    if payment_str == "NR":
        payment = 0.0
    else:
        try:
            payment = float(payment_str)
        except ValueError as e:
            msg = f'"{payment_str}" is not a float: "{row}".'
            raise ValueError(msg) from e

    return PrelimPaymentInfo(issue, ttl, num_pages, accepted_date, payment)


def get_stripped_new_lines(text: str) -> str:
    return re.sub("\n *", " ", text)


def get_date(col: str, this_year: int) -> tuple[int, int, int]:
    if col.strip() == "?":
        return -1, -1, -1

    yr = this_year

    mth_day_year = col.split(",")
    if len(mth_day_year) > 1:
        assert len(mth_day_year) == 2
        yr = int(mth_day_year[1].strip(" *"))

    mth_day = mth_day_year[0].split(" ")
    assert len(mth_day) == 2

    day = mth_day[1].strip()
    day = 1 if day == "??" else int(day)

    mth = get_month(mth_day[0].strip())

    return day, mth, yr


def get_month(mth_str: str) -> int:
    mth_str = mth_str.lower()

    for mth in MONTH_AS_LONG_STR:
        if MONTH_AS_LONG_STR[mth].lower() == mth_str:
            return mth

    msg = f'Unknown month "{mth_str}".'
    raise ValueError(msg)


def split_multi_titles(rows: list[list[str]]) -> list[list[str]]:
    new_rows = []
    for r in rows:
        num_new_lines = r[0].count("\n")
        if num_new_lines < 1:
            print("NO need to split: ", r)
            new_rows.append(r)
        else:
            print("Need to split: ", r)
            split = split_row(r, num_new_lines + 1)
            print("After split: ", split)
            new_rows.extend(split)

    return new_rows


def split_row(r: list[str], num_titles: int) -> list[list[str]]:
    title_list = []

    issues = split_column(r[0], num_titles)
    titles = split_column(r[1], num_titles)
    num_pages = split_column(r[3], num_titles)
    accepted_dates = split_column(r[4], num_titles)
    payments = split_column(r[5], num_titles)

    for i in range(num_titles):
        title_list.append(
            [issues[i], titles[i], r[2], num_pages[i], accepted_dates[i], payments[i], r[6]]
        )

    return title_list


def split_column(col: str, num_titles: int) -> list[str]:
    values = col.split("\n")
    if len(values) != num_titles:
        msg = f'Not enough multi-values: {len(values)} != {num_titles} - "{col}".'
        raise ValueError(msg)

    return [v.strip() for v in values]


@dataclass
class PaymentInfo:
    title: Titles
    title_str: str
    issue: str
    num_pages: int
    accepted_date: tuple[int, int, int]
    payment: float


titles_with_prelim_payment_info = []

for year in range(1958, 1960):
    html_file = os.path.join(html_file_base, f"thepayments{year}.html")
    print(f'\nProcessing file "{html_file}"...')

    with open(html_file, encoding="ISO-8859-1") as f:
        html = f.read()

    bs = BeautifulSoup(html, "html.parser")

    table = bs.find("table", border="3")

    year_data = []
    for rw in table.find_all("tr"):
        print("Next row: ", rw)
        cols = rw.find_all(["td"])
        cols = [col.text.strip() for col in cols if col is not None]
        if not cols:
            print("No cols: skipping row: {row}.")
        else:
            if cols[0].startswith("CODE"):
                continue
            cols.append(year)
            print("Appended: ", cols)
            year_data.append(cols)

    titles_with_prelim_payment_info.extend(split_multi_titles(year_data))

for cols in titles_with_prelim_payment_info:
    print("Prelim: ", cols)

title_dict = BARKS_TITLE_DICT
titles_with_payment_info = []
for cols in titles_with_prelim_payment_info[1:]:
    if cols[0][:2] in ISSUE_PREFIXES_TO_SKIP:
        print("Skipping: ", cols)
        continue
    prelim_payment_info = get_prelim_payment_info(cols)
    if prelim_payment_info.num_pages <= 1:
        print("Not enough pages - skipping: ", cols)
        continue

    if prelim_payment_info.title in KYLING_TITLE_MAP:
        title = KYLING_TITLE_MAP[prelim_payment_info.title]
    else:
        title = title_dict.get(prelim_payment_info.title, -1)

    if title == -1:
        print(f'Title "{prelim_payment_info.title}" not found.')
        continue

    titles_with_payment_info.append(
        PaymentInfo(
            title,
            BARKS_TITLES[title],
            prelim_payment_info.issue,
            prelim_payment_info.num_pages,
            prelim_payment_info.accepted_date,
            prelim_payment_info.payment,
        )
    )

titles_with_payment_info = sorted(titles_with_payment_info, key=lambda x: x.title)
payment_info_dict = OrderedDict()

prev_title = -1
for payment_info in titles_with_payment_info:
    print(
        f'{payment_info.title}: "{payment_info.title_str}"'
        f" {payment_info.issue}, {payment_info.num_pages},"
        f" {payment_info.accepted_date}, {payment_info.payment}"
    )
    if prev_title == payment_info.title:
        print("*** ERROR: Repeated title id.")
    if prev_title + 1 != payment_info.title:
        print(
            f"*** ERROR: prev_title {prev_title}"
            f" should be one less than title {payment_info.title}."
        )

    prev_title = payment_info.title

    payment_info_dict[payment_info.title] = payment_info

print(f"{len(titles_with_payment_info)} titles.")

for title in Titles:
    if title not in payment_info_dict:
        print(f'Title "{title.name}" not found.')

for payment_info in titles_with_payment_info:
    print(
        f"Titles.{payment_info.title.name}: PaymentInfo("
        f"Titles.{payment_info.title.name},"
        f" {payment_info.num_pages},"
        f" {payment_info.accepted_date[0]},"
        f" {payment_info.accepted_date[1]},"
        f" {payment_info.accepted_date[2]},"
        f" {payment_info.payment}),"
    )
