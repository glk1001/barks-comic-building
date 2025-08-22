# ruff: noqa: ERA001, E501

from __future__ import annotations

import concurrent.futures
import logging
import os
import shutil
import sys
import traceback
from datetime import datetime
from typing import TYPE_CHECKING

from additional_file_writing import (
    write_dest_panels_bboxes,
    write_json_metadata,
    write_metadata_file,
    write_readme_file,
    write_srce_dest_map,
)
from barks_build_comic_images.build_comic_images import ComicBookImageBuilder
from barks_build_comic_images.consts import (
    DEST_JPG_COMPRESS_LEVEL,
    DEST_JPG_QUALITY,
    MIN_HD_SRCE_HEIGHT,
)
from barks_build_comic_images.image_io import open_image_for_reading
from barks_fantagraphics.barks_titles import get_safe_title
from barks_fantagraphics.comics_consts import (
    DEST_TARGET_ASPECT_RATIO,
    DEST_TARGET_HEIGHT,
    DEST_TARGET_WIDTH,
    DEST_TARGET_X_MARGIN,
    PageType,
)
from barks_fantagraphics.comics_utils import (
    delete_all_files_in_directory,
    get_abbrev_path,
    get_clean_path,
)
from barks_fantagraphics.pages import (
    EMPTY_IMAGE_FILEPATH,
    get_max_timestamp,
    get_page_num_str,
    get_sorted_srce_and_dest_pages_with_dimensions,
)
from comic_utils.pil_image_utils import METADATA_PROPERTY_GROUP
from zipping import create_symlinks_to_comic_zip, zip_comic_book

if TYPE_CHECKING:
    from barks_fantagraphics.comic_book import (
        ComicBook,
    )
    from barks_fantagraphics.page_classes import (
        CleanPage,
        ComicDimensions,
        RequiredDimensions,
        SrceAndDestPages,
    )
    from PIL.Image import Image as PilImage

USE_CONCURRENT_PROCESSES = True
_process_page_error = False


class ComicBookBuilder:
    def __init__(self, comic: ComicBook) -> None:
        self._comic = comic
        self._image_builder = ComicBookImageBuilder(comic, EMPTY_IMAGE_FILEPATH)

        self._srce_dim: ComicDimensions | None = None
        self._required_dim: RequiredDimensions | None = None

        self._srce_and_dest_pages: SrceAndDestPages | None = None

    def get_srce_dim(self) -> ComicDimensions:
        return self._srce_dim

    def get_required_dim(self) -> RequiredDimensions:
        return self._required_dim

    def get_srce_and_dest_pages(self) -> SrceAndDestPages:
        return self._srce_and_dest_pages

    def get_max_dest_page_timestamp(self) -> float:
        return get_max_timestamp(self._srce_and_dest_pages.dest_pages)

    def build(self) -> None:
        self._init_pages()

        self._create_comic_book()

        self._log_comic_book_params()

        self._zip_and_symlink_comic_book()

    def _init_pages(self) -> None:
        logging.debug("Initializing pages...")
        self._srce_and_dest_pages, self._srce_dim, self._required_dim = (
            self._get_srce_and_dest_pages_and_dimensions(self._comic)
        )
        self._image_builder.set_required_dim(self._required_dim)

    @staticmethod
    def _get_srce_and_dest_pages_and_dimensions(
        comic: ComicBook,
    ) -> tuple[SrceAndDestPages, ComicDimensions, RequiredDimensions]:
        srce_and_dest_pages, srce_dim, required_dim = (
            get_sorted_srce_and_dest_pages_with_dimensions(comic, get_full_paths=True)
        )

        assert srce_dim.max_panels_bbox_width >= srce_dim.min_panels_bbox_width > 0
        assert srce_dim.max_panels_bbox_height >= srce_dim.min_panels_bbox_height > 0
        assert srce_dim.max_panels_bbox_width >= srce_dim.av_panels_bbox_width > 0
        assert srce_dim.max_panels_bbox_height >= srce_dim.av_panels_bbox_height > 0
        assert required_dim.panels_bbox_width == round(
            DEST_TARGET_WIDTH - (2 * DEST_TARGET_X_MARGIN)
        )

        logging.debug(f"Srce average panels bbox width: {srce_dim.av_panels_bbox_width}.")
        logging.debug(f"Srce average panels bbox height: {srce_dim.av_panels_bbox_height}.")
        logging.debug(f"Required panels bbox width: {required_dim.panels_bbox_width}.")
        logging.debug(f"Required panels bbox height: {required_dim.panels_bbox_height}.")
        logging.debug(f"Required page num y bottom: {required_dim.page_num_y_bottom}.")
        logging.debug("")

        return srce_and_dest_pages, srce_dim, required_dim

    def _create_comic_book(self) -> None:
        logging.debug("Creating comic book...")
        self._create_dest_dirs()
        self._process_pages()
        self._process_additional_files()

    def _process_pages(self) -> None:
        logging.debug("Processing pages...")
        delete_all_files_in_directory(self._comic.get_dest_dir())
        delete_all_files_in_directory(self._comic.get_dest_image_dir())

        global _process_page_error  # noqa: PLW0603
        _process_page_error = False

        if USE_CONCURRENT_PROCESSES:
            # max_workers = min(32, (os.cpu_count() or 1) + 4)
            max_workers = None
            # with concurrent.futures.ProcessPoolExecutor() as executor:
            with concurrent.futures.ThreadPoolExecutor(max_workers) as executor:
                for srce_page, dest_page in zip(
                    self._srce_and_dest_pages.srce_pages,
                    self._srce_and_dest_pages.dest_pages,
                ):
                    executor.submit(self._process_page, srce_page, dest_page)
        else:
            for srce_page, dest_page in zip(
                self._srce_and_dest_pages.srce_pages,
                self._srce_and_dest_pages.dest_pages,
            ):
                self._process_page(srce_page, dest_page)

        if _process_page_error:
            raise RuntimeError("There were errors while processing pages.")

    def _process_page(
        self,
        srce_page: CleanPage,
        dest_page: CleanPage,
    ) -> None:
        def check_srce_page_image_min_height() -> None:
            if srce_page_image.height < MIN_HD_SRCE_HEIGHT:
                msg = (
                    f"Srce image error: min required height {MIN_HD_SRCE_HEIGHT}."
                    f' Poor srce file resolution for "{srce_page.page_filename}":'
                    f" {srce_page_image.width} x {srce_page_image.height}."
                )
                raise ValueError(msg)

        # noinspection PyBroadException
        try:
            srce_page_image = open_image_for_reading(srce_page.page_filename)
            if srce_page.page_type == PageType.BODY:
                check_srce_page_image_min_height()

            logging.info(
                f'Convert "{get_abbrev_path(srce_page.page_filename)}"'
                f" (page-type {srce_page.page_type.name})"
                f' to "{get_abbrev_path(dest_page.page_filename)}"'
                f" (page {get_page_num_str(dest_page):>2}.",
            )

            logging.info(
                f'Creating dest image "{get_abbrev_path(dest_page.page_filename)}"'
                f' from srce file "{get_abbrev_path(srce_page.page_filename)}".',
            )
            dest_page_image = self._image_builder.get_dest_page_image(
                srce_page_image,
                srce_page,
                dest_page,
            )

            self._save_dest_image(dest_page, dest_page_image, srce_page)
            logging.info(f'Saved changes to image "{get_abbrev_path(dest_page.page_filename)}".')

            logging.info("")
        except Exception:
            _, _, tb = sys.exc_info()
            tb_info = traceback.extract_tb(tb)
            filename, line, func, text = tb_info[-1]
            err_msg = f'Error in process page at "{filename}:{line}" for statement "{text}".'
            logging.exception(err_msg)
            global _process_page_error  # noqa: PLW0603
            _process_page_error = True

    def _save_dest_image(
        self,
        dest_page: CleanPage,
        dest_page_image: PilImage,
        srce_page: CleanPage,
    ) -> None:
        dest_page_image.save(
            dest_page.page_filename,
            optimize=True,
            compress_level=DEST_JPG_COMPRESS_LEVEL,
            quality=DEST_JPG_QUALITY,
            comment="\n".join(self._get_dest_jpg_comments(srce_page, dest_page)),
        )

    @staticmethod
    def _get_dest_jpg_comments(srce_page: CleanPage, dest_page: CleanPage) -> list[str]:
        now_str = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")

        prefix = METADATA_PROPERTY_GROUP
        indent = "      "
        return [
            indent,
            f'{indent}{prefix}:Srce file: "{get_clean_path(srce_page.page_filename)}"',
            f'{indent}{prefix}:Dest file: "{get_clean_path(dest_page.page_filename)}"',
            f"{indent}{prefix}:Dest created: {now_str}",
            f"{indent}{prefix}:Srce page num: {srce_page.page_num}",
            f"{indent}{prefix}:Srce page type: {srce_page.page_type.name}",
            f"{indent}{prefix}:Srce panels bbox:"
            f" {dest_page.panels_bbox.x_min}, {dest_page.panels_bbox.y_min},"
            f" {dest_page.panels_bbox.x_max}, {dest_page.panels_bbox.y_max}",
            f"{indent}{prefix}:Dest page num: {dest_page.page_num}",
        ]

    def _process_additional_files(self) -> None:
        shutil.copy2(self._comic.ini_file, self._comic.get_dest_dir())

        write_readme_file(self._comic)
        write_metadata_file(self._comic, self._srce_and_dest_pages.dest_pages)
        write_json_metadata(
            self._comic,
            self._srce_dim,
            self._required_dim,
            self._srce_and_dest_pages.dest_pages,
        )
        write_srce_dest_map(
            self._comic,
            self._srce_dim,
            self._required_dim,
            self._srce_and_dest_pages,
        )
        write_dest_panels_bboxes(self._comic, self._srce_and_dest_pages.dest_pages)

    def _create_dest_dirs(self) -> None:
        if not os.path.isdir(self._comic.get_dest_image_dir()):
            os.makedirs(self._comic.get_dest_image_dir())

        if not os.path.isdir(self._comic.get_dest_image_dir()):
            msg = f'Could not make directory "{self._comic.get_dest_image_dir()}".'
            raise RuntimeError(msg)

    def _zip_and_symlink_comic_book(self) -> None:
        zip_comic_book(self._comic)
        create_symlinks_to_comic_zip(self._comic)

    # noinspection LongLine
    def _log_comic_book_params(self) -> None:
        logging.info("")

        calc_panels_bbox_height = round(
            (self._srce_dim.av_panels_bbox_height * self._required_dim.panels_bbox_width)
            / self._srce_dim.av_panels_bbox_width,
        )

        # fmt: off
        logging.info(f'Comic book series:    "{self._comic.series_name}".')
        logging.info(f'Comic book title:     "{get_safe_title(self._comic.get_comic_title())}".')
        logging.info(f'Comic issue title:    "{self._comic.get_comic_issue_title()}".')
        logging.info(f"Number in series:     {self._comic.number_in_series}.")
        logging.info(f"Chronological number  {self._comic.chronological_number}.")
        logging.info(f"Dest x margin:        {DEST_TARGET_X_MARGIN}.")
        logging.info(f"Dest width:           {DEST_TARGET_WIDTH}.")
        logging.info(f"Dest height:          {DEST_TARGET_HEIGHT}.")
        logging.info(f"Dest aspect ratio:    {DEST_TARGET_ASPECT_RATIO :.2f}.")
        logging.info(f"Dest jpeg quality:    {DEST_JPG_QUALITY}.")
        logging.info(f"Dest compress level:  {DEST_JPG_COMPRESS_LEVEL}.")
        logging.info(f"Srce min bbox wid:    {self._srce_dim.min_panels_bbox_width}.")
        logging.info(f"Srce max bbox wid:    {self._srce_dim.max_panels_bbox_width}.")
        logging.info(f"Srce min bbox hgt:    {self._srce_dim.min_panels_bbox_height}.")
        logging.info(f"Srce max bbox hgt:    {self._srce_dim.max_panels_bbox_height}.")
        logging.info(f"Srce av bbox wid:     {self._srce_dim.av_panels_bbox_width}.")
        logging.info(f"Srce av bbox hgt:     {self._srce_dim.av_panels_bbox_height}.")
        logging.info(f"Req panels bbox wid:  {self._required_dim.panels_bbox_width}.")
        logging.info(f"Req panels bbox hgt:  {self._required_dim.panels_bbox_height}.")
        logging.info(f"Calc panels bbox ht:  {calc_panels_bbox_height}.")
        logging.info(f"Page num y bottom:    {self._required_dim.page_num_y_bottom}.")
        logging.info(f'Ini file:             "{get_clean_path(self._comic.ini_file)}".')
        logging.info(f'Srce dir:             "{get_abbrev_path(self._comic.dirs.srce_dir)}".')
        logging.info(f'Srce upscayled dir:   "{get_abbrev_path(self._comic.dirs.srce_upscayled_dir)}".')
        logging.info(f'Srce restored dir:    "{get_abbrev_path(self._comic.dirs.srce_restored_dir)}".')
        logging.info(f'Srce fixes dir:       "{get_abbrev_path(self._comic.dirs.srce_fixes_dir)}".')
        logging.info(f'Srce upscayled fixes: "{get_abbrev_path(self._comic.dirs.srce_upscayled_fixes_dir)}".')
        logging.info(f'Srce segments dir:    "{get_abbrev_path(self._comic.dirs.panel_segments_dir)}".')
        logging.info(f'Dest dir:             "{get_abbrev_path(self._comic.get_dest_dir())}".')
        logging.info(f'Dest comic zip:       "{get_abbrev_path(self._comic.get_dest_comic_zip())}".')
        logging.info(f'Dest series symlink:  "{get_abbrev_path(self._comic.get_dest_series_comic_zip_symlink())}".')
        logging.info(f'Dest year symlink:    "{get_abbrev_path(self._comic.get_dest_year_comic_zip_symlink())}".')
        logging.info("")
        # fmt: on
