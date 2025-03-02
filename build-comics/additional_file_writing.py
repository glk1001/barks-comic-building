import json
import os
from datetime import datetime
from typing import List, Dict

from barks_fantagraphics.comic_book import ComicBook, get_safe_title
from barks_fantagraphics.comics_consts import (
    PageType,
    get_font_path,
)
from barks_fantagraphics.comics_utils import get_clean_path, get_timestamp_str, get_timestamp_as_str
from barks_fantagraphics.pages import (
    CleanPage,
    SrceAndDestPages,
    get_srce_dest_map,
    get_page_num_str,
)
from barks_fantagraphics.pages import FRONT_MATTER_PAGES, SPLASH_PAGES, PAINTING_PAGES
from consts import (
    DEST_JPG_QUALITY,
    DEST_JPG_COMPRESS_LEVEL,
    DEST_SRCE_MAP_FILENAME,
    DEST_PANELS_BBOXES_FILENAME,
    README_FILENAME,
    SUMMARY_FILENAME,
    METADATA_FILENAME,
    JSON_METADATA_FILENAME,
    DOUBLE_PAGES_SECTION,
    PAGE_NUMBERS_SECTION,
    DEST_TARGET_WIDTH,
    DEST_TARGET_HEIGHT,
    DEST_TARGET_X_MARGIN,
    DEST_TARGET_ASPECT_RATIO,
)
from timing import Timing


def write_summary_file(
    comic: ComicBook,
    pages: SrceAndDestPages,
    max_dest_timestamp: float,
    timing: Timing,
):
    summary_file = os.path.join(comic.get_dest_dir(), SUMMARY_FILENAME)

    calc_panels_bbox_height = int(
        round(
            (comic.srce_av_panels_bbox_height * comic.required_dim.panels_bbox_width)
            / comic.srce_av_panels_bbox_width
        )
    )

    series_symlink_timestamp = get_timestamp_str(comic.get_dest_series_comic_zip_symlink())
    year_symlink_timestamp = get_timestamp_str(comic.get_dest_year_comic_zip_symlink())

    has_modified_cover = any(
        srce.page_is_modified and srce.page_type == PageType.COVER for srce in pages.srce_pages
    )
    modified_body_pages = [
        get_page_num_str(dest)
        for dest in pages.dest_pages
        if dest.page_is_modified and dest.page_type == PageType.BODY
    ]

    ini_file = get_clean_path(comic.ini_file)
    srce_dir = get_clean_path(comic.srce_dir)
    srce_upscayled_dir = get_clean_path(comic.srce_upscayled_dir)
    srce_restored_dir = get_clean_path(comic.srce_restored_dir)
    srce_fixes_dir = get_clean_path(comic.srce_fixes_dir)
    srce_upscayled_fixes_dir = get_clean_path(comic.srce_upscayled_fixes_dir)
    srce_restored_fixes_dir = get_clean_path(comic.srce_restored_fixes_dir)
    dest_dir = get_clean_path(comic.get_dest_dir())
    dest_comic_zip = get_clean_path(comic.get_dest_comic_zip())
    dest_series_zip_symlink = get_clean_path(comic.get_dest_series_comic_zip_symlink())
    dest_year_zip_symlink = get_clean_path(comic.get_dest_year_comic_zip_symlink())
    title_font_file = get_clean_path(get_font_path(comic.title_font_file))
    intro_inset_file = get_clean_path(comic.intro_inset_file)

    with open(summary_file, "w") as f:
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
        f.write(f'srce restored fixes dir  = "{srce_restored_fixes_dir}"\n')
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
        f.write(f"modified body pages      = {", ".join(modified_body_pages)}\n")
        f.write(f'intro inset file         = "{intro_inset_file}"\n')
        f.write(f"title font size          = {comic.title_font_size}\n")
        f.write(f"author font size         = {comic.author_font_size}\n")
        f.write(f"DEST_TARGET_X_MARGIN     = {DEST_TARGET_X_MARGIN}\n")
        f.write(f"DEST_TARGET_WIDTH        = {DEST_TARGET_WIDTH}\n")
        f.write(f"DEST_TARGET_HEIGHT       = {DEST_TARGET_HEIGHT}\n")
        f.write(f"DEST_TARGET_ASPECT_RATIO = {DEST_TARGET_ASPECT_RATIO:.2f}\n")
        f.write(f"DEST_JPG_QUALITY         = {DEST_JPG_QUALITY}\n")
        f.write(f"DEST_JPG_COMPRESS_LEVEL  = {DEST_JPG_COMPRESS_LEVEL}\n")
        f.write(f"srce min panels bbox wid = {comic.srce_min_panels_bbox_width}\n")
        f.write(f"srce max panels bbox wid = {comic.srce_max_panels_bbox_width}\n")
        f.write(f"srce av panels bbox wid  = {comic.srce_av_panels_bbox_width}\n")
        f.write(f"srce min panels bbox hgt = {comic.srce_min_panels_bbox_height}\n")
        f.write(f"srce max panels bbox_hgt = {comic.srce_max_panels_bbox_height}\n")
        f.write(f"srce av panels bbox hgt  = {comic.srce_av_panels_bbox_height}\n")
        f.write(f"req panels bbox width    = {comic.required_dim.panels_bbox_width}\n")
        f.write(f"req panels bbox height   = {comic.required_dim.panels_bbox_height}\n")
        f.write(f"calc panels bbox height  = {calc_panels_bbox_height}\n")
        f.write(f"page num y bottom        = {comic.required_dim.page_num_y_bottom}\n")
        f.write("\n")

        f.write("Pages Config Summary:\n")
        for pg in comic.config_page_images:
            f.write(f"pages = {pg.page_filenames:11}," f" page type = {pg.page_type.name:12}\n")
        f.write("\n")

        f.write("Page List Summary:\n")
        for srce_page, dest_page in zip(pages.srce_pages, pages.dest_pages):
            srce_is_modded = " ***M" if srce_page.page_is_modified else ""
            srce_filename = f'"{os.path.basename(srce_page.page_filename)}" {srce_is_modded}'
            dest_filename = f'"{os.path.basename(dest_page.page_filename)}"'
            dest_page_type = f'"{dest_page.page_type.name}"'
            f.write(
                f"Added srce {srce_filename:17}"
                f" as dest {dest_filename:6},"
                f" type {dest_page_type:14}, "
                f" page {dest_page.page_num:2} ({get_page_num_str(dest_page):>3}),"
                f" bbox ({dest_page.panels_bbox.x_min:3}, {dest_page.panels_bbox.y_min:3},"
                f" {dest_page.panels_bbox.x_max:3}, {dest_page.panels_bbox.y_max:3}).\n"
            )
        f.write("\n")


def write_readme_file(comic: ComicBook):
    readme_file = os.path.join(comic.get_dest_dir(), README_FILENAME)
    with open(readme_file, "w") as f:
        f.write(f'Title:       "{get_safe_title(comic.title)}"\n')
        f.write(f'Ini Title:   "{comic.get_ini_title()}"\n')
        f.write(f'Issue Title: "{get_safe_title(comic.issue_title)}"\n')
        f.write("\n")
        now_str = datetime.now().strftime("%b %d %Y %H:%M:%S")
        f.write(f"Created:           {now_str}\n")
        f.write(f'Archived ini file: "{os.path.basename(comic.ini_file)}"\n')


def write_metadata_file(comic: ComicBook, dest_pages: List[CleanPage]):
    metadata_file = os.path.join(comic.get_dest_dir(), METADATA_FILENAME)
    with open(metadata_file, "w") as f:
        f.write(f"[{DOUBLE_PAGES_SECTION}]\n")
        orig_page_num = 0
        for page in dest_pages:
            orig_page_num += 1
            if page.page_type not in FRONT_MATTER_PAGES:
                break
            f.write(f"{orig_page_num} = False" + "\n")
        f.write("\n")

        body_start_page_num = orig_page_num
        f.write(f"[{PAGE_NUMBERS_SECTION}]\n")
        f.write(f"body_start = {body_start_page_num}\n")


def write_json_metadata(comic: ComicBook, dest_pages: List[CleanPage]):
    metadata_file = os.path.join(comic.get_dest_dir(), JSON_METADATA_FILENAME)
    metadata = dict()
    metadata["title"] = get_safe_title(comic.title)
    metadata["ini_title"] = comic.get_ini_title()
    metadata["issue_title"] = get_safe_title(comic.issue_title)
    metadata["comic_title"] = get_safe_title(comic.get_comic_title())
    metadata["series_name"] = comic.series_name
    metadata["number_in_series"] = comic.number_in_series
    metadata["srce_dir"] = get_clean_path(comic.srce_dir)
    metadata["dest_dir"] = get_clean_path(comic.get_dest_dir())
    metadata["publication_date"] = comic.publication_date
    metadata["submitted_date"] = comic.submitted_date
    metadata["submitted_year"] = comic.submitted_year
    metadata["srce_min_panels_bbox_width"] = comic.srce_min_panels_bbox_width
    metadata["srce_max_panels_bbox_width"] = comic.srce_max_panels_bbox_width
    metadata["srce_av_panels_bbox_width"] = comic.srce_av_panels_bbox_width
    metadata["srce_min_panels_bbox_height"] = comic.srce_min_panels_bbox_height
    metadata["srce_max_panels_bbox_height"] = comic.srce_max_panels_bbox_height
    metadata["srce_av_panels_bbox_height"] = comic.srce_av_panels_bbox_height
    metadata["required_dim"] = [
        comic.required_dim.panels_bbox_width,
        comic.required_dim.panels_bbox_height,
        comic.required_dim.page_num_y_bottom,
    ]
    metadata["page_counts"] = get_page_counts(dest_pages)
    with open(metadata_file, "w") as f:
        # noinspection PyTypeChecker
        json.dump(metadata, f, indent=4)


def get_page_counts(dest_pages: List[CleanPage]) -> Dict[str, int]:
    page_counts = dict()

    front_page_count = len([p for p in dest_pages if p.page_type == PageType.FRONT])
    assert front_page_count <= 1

    title_page_count = len([p for p in dest_pages if p.page_type == PageType.TITLE])
    assert title_page_count == 1

    cover_page_count = len([p for p in dest_pages if p.page_type == PageType.COVER])
    assert cover_page_count <= 1

    painting_page_count = len([p for p in dest_pages if p.page_type in PAINTING_PAGES])

    splash_page_count = len([p for p in dest_pages if p.page_type in SPLASH_PAGES])

    front_matter_page_count = len([p for p in dest_pages if p.page_type == PageType.FRONT_MATTER])

    story_page_count = len([p for p in dest_pages if p.page_type == PageType.BODY])

    back_matter_page_count = len(
        [p for p in dest_pages if p.page_type in [PageType.BACK_MATTER, PageType.BACK_NO_PANELS]]
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
    pages: SrceAndDestPages,
):
    src_dst_map_file = os.path.join(comic.get_dest_dir(), DEST_SRCE_MAP_FILENAME)
    srce_dest_map = get_srce_dest_map(comic, pages)
    with open(src_dst_map_file, "w") as f:
        # noinspection PyTypeChecker
        json.dump(srce_dest_map, f, indent=4)


def write_dest_panels_bboxes(
    comic: ComicBook,
    dest_pages: List[CleanPage],
):
    dst_bboxes_file = os.path.join(comic.get_dest_dir(), DEST_PANELS_BBOXES_FILENAME)
    bboxes_dict = dict()
    for dest_page in dest_pages:
        bbox_key = os.path.basename(dest_page.page_filename)
        bboxes_dict[bbox_key] = dest_page.panels_bbox.get_box()

    with open(dst_bboxes_file, "w") as f:
        # noinspection PyTypeChecker
        json.dump(bboxes_dict, f, indent=4)
