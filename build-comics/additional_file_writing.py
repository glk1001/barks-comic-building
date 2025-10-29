import json
from datetime import datetime
from pathlib import Path

from barks_build_comic_images.consts import (
    DEST_JPG_COMPRESS_LEVEL,
    DEST_JPG_QUALITY,
    DEST_PANELS_BBOXES_FILENAME,
    DEST_SRCE_MAP_FILENAME,
    DOUBLE_PAGES,
    DOUBLE_PAGES_SECTION,
    JSON_METADATA_FILENAME,
    METADATA_FILENAME,
    PAGE_NUMBERS_SECTION,
    README_FILENAME,
    SUMMARY_FILENAME,
)
from barks_fantagraphics.barks_titles import NON_COMIC_TITLES, get_safe_title
from barks_fantagraphics.comic_book import (
    ComicBook,
    ModifiedType,
)
from barks_fantagraphics.comics_consts import (
    DEST_TARGET_ASPECT_RATIO,
    DEST_TARGET_HEIGHT,
    DEST_TARGET_WIDTH,
    DEST_TARGET_X_MARGIN,
    FRONT_MATTER_PAGES,
    PAINTING_PAGES,
    PageType,
)
from barks_fantagraphics.comics_utils import get_clean_path, get_timestamp_as_str, get_timestamp_str
from barks_fantagraphics.page_classes import (
    CleanPage,
    ComicDimensions,
    RequiredDimensions,
    SrceAndDestPages,
)
from barks_fantagraphics.pages import (
    get_page_mod_type,
    get_page_num_str,
    get_srce_dest_map,
)
from comic_utils.comic_consts import ROMAN_NUMERALS
from comic_utils.timing import Timing


def write_summary_file(  # noqa: PLR0913, PLR0915
    comic: ComicBook,
    srce_dim: ComicDimensions,
    required_dim: RequiredDimensions,
    pages: SrceAndDestPages,
    max_dest_timestamp: float,
    timing: Timing,
) -> None:
    summary_file = comic.get_dest_dir() / SUMMARY_FILENAME

    calc_panels_bbox_height = round(
        (srce_dim.av_panels_bbox_height * required_dim.panels_bbox_width)
        / srce_dim.av_panels_bbox_width,
    )

    series_symlink_timestamp = get_timestamp_str(comic.get_dest_series_comic_zip_symlink())
    year_symlink_timestamp = get_timestamp_str(comic.get_dest_year_comic_zip_symlink())

    has_modified_cover = any(
        (get_page_mod_type(comic, srce) != ModifiedType.ORIGINAL)
        and (srce.page_type == PageType.COVER)
        for srce in pages.srce_pages
    )
    modified_body_pages = [
        get_page_num_str(dest)
        for srce, dest in zip(pages.srce_pages, pages.dest_pages, strict=True)
        if (get_page_mod_type(comic, srce) != ModifiedType.ORIGINAL)
        and (dest.page_type == PageType.BODY)
    ]

    ini_file = get_clean_path(comic.ini_file)
    srce_dir = get_clean_path(comic.dirs.srce_dir)
    srce_upscayled_dir = get_clean_path(comic.dirs.srce_upscayled_dir)
    srce_restored_dir = get_clean_path(comic.dirs.srce_restored_dir)
    srce_fixes_dir = get_clean_path(comic.dirs.srce_fixes_dir)
    srce_upscayled_fixes_dir = get_clean_path(comic.dirs.srce_upscayled_fixes_dir)
    dest_dir = get_clean_path(comic.get_dest_dir())
    dest_comic_zip = get_clean_path(comic.get_dest_comic_zip())
    dest_series_zip_symlink = get_clean_path(comic.get_dest_series_comic_zip_symlink())
    dest_year_zip_symlink = get_clean_path(comic.get_dest_year_comic_zip_symlink())
    title_font_file = get_clean_path(comic.title_font_file)
    intro_inset_file = get_clean_path(comic.intro_inset_file)

    with summary_file.open("w") as f:
        f.write("Run Summary:\n")
        f.write(f"time of run              = {timing.start_time}\n")
        f.write(f"time taken               = {timing.get_elapsed_time_in_seconds()} seconds\n")
        f.write(f'title                    = "{comic.title}"\n')
        f.write(f'ini title                = "{comic.get_ini_title()}"\n')
        f.write(f'issue title              = "{comic.issue_title}"\n')
        f.write(f'comic title              = "{comic.get_comic_title()}"\n')
        f.write(f'ini file                 = "{ini_file}"\n')
        f.write(f'srce dir                 = "{srce_dir}"\n')
        f.write(f'srce upscayled dir       = "{srce_upscayled_dir}"\n')
        f.write(f'srce restored dir        = "{srce_restored_dir}"\n')
        f.write(f'srce fixes dir           = "{srce_fixes_dir}"\n')
        f.write(f'srce upscayled fixes dir = "{srce_upscayled_fixes_dir}"\n')
        f.write(f'dest dir                 = "{dest_dir}"\n')
        f.write(f'dest comic_zip           = "{dest_comic_zip}"\n')
        f.write(f'dest series zip symlink  = "{dest_series_zip_symlink}"\n')
        f.write(f'dest year zip symlink    = "{dest_year_zip_symlink}"\n')
        f.write(f'ini file timestamp       = "{get_timestamp_str(comic.ini_file)}"\n')
        f.write(f'max dest timestamp       = "{get_timestamp_as_str(max_dest_timestamp)}"\n')
        f.write(f'comic zip timestamp      = "{get_timestamp_str(comic.get_dest_comic_zip())}"\n')
        f.write(f'series symlink timestamp = "{series_symlink_timestamp}"\n')
        f.write(f'year symlink timestamp   = "{year_symlink_timestamp}"\n')
        f.write(f'title font file          = "{title_font_file}"\n')
        f.write(f"chronological number     = {comic.chronological_number}\n")
        f.write(f'series                   = "{comic.series_name}"\n')
        f.write(f"series book num          = {comic.number_in_series}\n")
        f.write(f"submitted date           = {comic.submitted_date}\n")
        f.write(f"submitted year           = {comic.submitted_year}\n")
        f.write(f"publication date         = {comic.publication_date}\n")
        f.write(f"publication text         = \n{comic.publication_text}\n")
        f.write(f"has modified cover       = {has_modified_cover}\n")
        f.write(f"modified body pages      = {', '.join(modified_body_pages)}\n")
        f.write(f'intro inset file         = "{intro_inset_file}"\n')
        f.write(f"title font size          = {comic.title_font_size}\n")
        f.write(f"author font size         = {comic.author_font_size}\n")
        f.write(f"DEST_TARGET_X_MARGIN     = {DEST_TARGET_X_MARGIN}\n")
        f.write(f"DEST_TARGET_WIDTH        = {DEST_TARGET_WIDTH}\n")
        f.write(f"DEST_TARGET_HEIGHT       = {DEST_TARGET_HEIGHT}\n")
        f.write(f"DEST_TARGET_ASPECT_RATIO = {DEST_TARGET_ASPECT_RATIO:.2f}\n")
        f.write(f"DEST_JPG_QUALITY         = {DEST_JPG_QUALITY}\n")
        f.write(f"DEST_JPG_COMPRESS_LEVEL  = {DEST_JPG_COMPRESS_LEVEL}\n")
        f.write(f"srce min panels bbox wid = {srce_dim.min_panels_bbox_width}\n")
        f.write(f"srce max panels bbox wid = {srce_dim.max_panels_bbox_width}\n")
        f.write(f"srce av panels bbox wid  = {srce_dim.av_panels_bbox_width}\n")
        f.write(f"srce min panels bbox hgt = {srce_dim.min_panels_bbox_height}\n")
        f.write(f"srce max panels bbox_hgt = {srce_dim.max_panels_bbox_height}\n")
        f.write(f"srce av panels bbox hgt  = {srce_dim.av_panels_bbox_height}\n")
        f.write(f"req panels bbox width    = {required_dim.panels_bbox_width}\n")
        f.write(f"req panels bbox height   = {required_dim.panels_bbox_height}\n")
        f.write(f"calc panels bbox height  = {calc_panels_bbox_height}\n")
        f.write(f"page num y bottom        = {required_dim.page_num_y_bottom}\n")
        f.write("\n")

        f.write("Pages Config Summary:\n")
        f.writelines(
            f"pages = {pg.page_filenames:11}, page type = {pg.page_type.name:12}\n"
            for pg in comic.config_page_images
        )
        f.write("\n")

        f.write("Page List Summary:\n")
        for srce_page, dest_page in zip(pages.srce_pages, pages.dest_pages, strict=True):
            srce_is_modded = (
                " ***M" if get_page_mod_type(comic, srce_page) != ModifiedType.ORIGINAL else ""
            )
            srce_filename = f'"{Path(srce_page.page_filename).name}" {srce_is_modded}'
            dest_filename = f'"{Path(dest_page.page_filename).name}"'
            dest_page_type = f'"{dest_page.page_type.name}"'
            f.write(
                f"Added srce {srce_filename:17}"
                f" as dest {dest_filename:6},"
                f" type {dest_page_type:14}, "
                f" page {dest_page.page_num:2} ({get_page_num_str(dest_page):>3}),"
                f" bbox ({dest_page.panels_bbox.x_min:3}, {dest_page.panels_bbox.y_min:3},"
                f" {dest_page.panels_bbox.x_max:3}, {dest_page.panels_bbox.y_max:3}).\n",
            )
        f.write("\n")


def write_readme_file(comic: ComicBook) -> None:
    readme_file = comic.get_dest_dir() / README_FILENAME
    with readme_file.open("w") as f:
        f.write(f'Title:       "{get_safe_title(comic.title)}"\n')
        f.write(f'Ini Title:   "{comic.get_ini_title()}"\n')
        f.write(f'Issue Title: "{get_safe_title(comic.issue_title)}"\n')
        f.write("\n")
        now_str = datetime.now().astimezone().strftime("%b %d %Y %H:%M:%S")
        f.write(f"Created:           {now_str}\n")
        f.write(f'Archived ini file: "{comic.ini_file.name}"\n')


def write_metadata_file(comic: ComicBook, dest_pages: list[CleanPage]) -> None:
    metadata_file = comic.get_dest_dir() / METADATA_FILENAME

    double_pages = {}
    page_num_str = {}
    body_start_page_num = -1
    left = True
    for index, page in enumerate(dest_pages):
        orig_page_num = index + 1
        if page.page_type not in FRONT_MATTER_PAGES and body_start_page_num == -1:
            body_start_page_num = orig_page_num
        if body_start_page_num == -1:
            page_num_str[orig_page_num] = ROMAN_NUMERALS[orig_page_num]
        else:
            page_num_str[orig_page_num] = str(orig_page_num - body_start_page_num + 1)
        if page.page_type in DOUBLE_PAGES:
            if left:
                double_pages[orig_page_num] = (orig_page_num, orig_page_num + 1)
            else:
                double_pages[orig_page_num] = (orig_page_num - 1, orig_page_num)
            left = not left

    with metadata_file.open("w") as f:
        f.write(f"[{DOUBLE_PAGES_SECTION}]\n")
        for page in double_pages:
            left_page = double_pages[page][0]
            right_page = double_pages[page][1]
            f.write(f"{page}: {left_page},{right_page}" + "\n")
        f.write("\n")

        f.write(f"[{PAGE_NUMBERS_SECTION}]\n")
        for page, num_str in page_num_str.items():
            f.write(f"{page}: {num_str}" + "\n")
        f.write("\n")


def write_json_metadata(
    comic: ComicBook,
    srce_dim: ComicDimensions,
    required_dim: RequiredDimensions,
    dest_pages: list[CleanPage],
) -> None:
    metadata_file = comic.get_dest_dir() / JSON_METADATA_FILENAME
    metadata = {
        "title": get_safe_title(comic.title),
        "ini_title": comic.get_ini_title(),
        "issue_title": get_safe_title(comic.issue_title),
        "comic_title": get_safe_title(comic.get_comic_title()),
        "series_name": comic.series_name,
        "number_in_series": comic.number_in_series,
        "srce_dir": str(get_clean_path(comic.dirs.srce_dir)),
        "dest_dir": str(get_clean_path(comic.get_dest_dir())),
        "publication_date": comic.publication_date,
        "submitted_date": comic.submitted_date,
        "submitted_year": comic.submitted_year,
        "srce_min_panels_bbox_width": srce_dim.min_panels_bbox_width,
        "srce_max_panels_bbox_width": srce_dim.max_panels_bbox_width,
        "srce_av_panels_bbox_width": srce_dim.av_panels_bbox_width,
        "srce_min_panels_bbox_height": srce_dim.min_panels_bbox_height,
        "srce_max_panels_bbox_height": srce_dim.max_panels_bbox_height,
        "srce_av_panels_bbox_height": srce_dim.av_panels_bbox_height,
        "required_dim": [
            required_dim.panels_bbox_width,
            required_dim.panels_bbox_height,
            required_dim.page_num_y_bottom,
        ],
        "page_counts": get_page_counts(comic, dest_pages),
    }
    with metadata_file.open("w") as f:
        # noinspection PyTypeChecker
        json.dump(metadata, f, indent=4)


def get_page_counts(comic: ComicBook, dest_pages: list[CleanPage]) -> dict[str, int]:
    page_counts = {}

    front_page_count = len([p for p in dest_pages if p.page_type == PageType.FRONT])
    assert front_page_count <= 1

    title_page_count = len([p for p in dest_pages if p.page_type == PageType.TITLE])
    assert title_page_count == 1 or comic.get_title_enum() in NON_COMIC_TITLES

    cover_page_count = len([p for p in dest_pages if p.page_type == PageType.COVER])
    assert cover_page_count <= 1

    painting_page_count = len([p for p in dest_pages if p.page_type in PAINTING_PAGES])

    splash_page_count = len([p for p in dest_pages if p.page_type == PageType.SPLASH])

    front_matter_page_count = len(
        [p for p in dest_pages if p.page_type in [PageType.FRONT_MATTER, PageType.FRONT_NO_PANELS]]
    )

    story_page_count = len([p for p in dest_pages if p.page_type == PageType.BODY])

    # TODO(glk): What about paintings???
    back_matter_page_count = len(
        [
            p
            for p in dest_pages
            if p.page_type
            in [PageType.BACK_MATTER, PageType.BACK_NO_PANELS, PageType.BACK_NO_PANELS_DOUBLE]
        ],
    )

    blank_page_count = len([p for p in dest_pages if p.page_type == PageType.BLANK_PAGE])

    total_page_count = len(dest_pages)
    assert total_page_count == (
        front_page_count
        + title_page_count
        + cover_page_count
        + painting_page_count
        + splash_page_count
        + front_matter_page_count
        + story_page_count
        + back_matter_page_count
        + blank_page_count
    )

    page_counts["front"] = front_page_count
    page_counts["painting"] = painting_page_count
    page_counts["title"] = title_page_count
    page_counts["cover"] = cover_page_count
    page_counts["splash"] = splash_page_count
    page_counts["front_matter"] = front_matter_page_count
    page_counts["story"] = story_page_count
    page_counts["back_matter"] = back_matter_page_count
    page_counts["blank"] = blank_page_count

    page_counts["total"] = total_page_count

    return page_counts


def write_srce_dest_map(
    comic: ComicBook,
    srce_dim: ComicDimensions,
    required_dim: RequiredDimensions,
    pages: SrceAndDestPages,
) -> None:
    src_dst_map_file = comic.get_dest_dir() / DEST_SRCE_MAP_FILENAME
    srce_dest_map = get_srce_dest_map(comic, srce_dim, required_dim, pages)
    with src_dst_map_file.open("w") as f:
        # noinspection PyTypeChecker
        json.dump(srce_dest_map, f, indent=4)


def write_dest_panels_bboxes(
    comic: ComicBook,
    dest_pages: list[CleanPage],
) -> None:
    dst_bboxes_file = comic.get_dest_dir() / DEST_PANELS_BBOXES_FILENAME
    bboxes_dict = {}
    for dest_page in dest_pages:
        bbox_key = Path(dest_page.page_filename).name
        bboxes_dict[bbox_key] = dest_page.panels_bbox.get_box()

    with dst_bboxes_file.open("w") as f:
        # noinspection PyTypeChecker
        json.dump(bboxes_dict, f, indent=4)
