# ruff: noqa: C901, T201

import os
from dataclasses import dataclass
from pathlib import Path

from barks_build_comic_images.consts import DEST_NON_IMAGE_FILES
from barks_fantagraphics import panel_bounding
from barks_fantagraphics.barks_titles import NON_COMIC_TITLES, get_safe_title
from barks_fantagraphics.comic_book import (
    ComicBook,
    get_page_num_str,
    get_total_num_pages,
)
from barks_fantagraphics.comics_consts import (
    BARKS_ROOT_DIR,
    IMAGES_SUBDIR,
    PNG_FILE_EXT,
    THE_CHRONOLOGICAL_DIR,
    THE_CHRONOLOGICAL_DIRS_DIR,
    THE_COMICS_DIR,
    THE_YEARS_COMICS_DIR,
)
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_utils import get_relpath, get_timestamp, get_timestamp_as_str
from barks_fantagraphics.fanta_comics_info import (
    FIRST_VOLUME_NUMBER,
    LAST_VOLUME_NUMBER,
)
from barks_fantagraphics.page_classes import SrceAndDestPages
from barks_fantagraphics.pages import (
    get_restored_srce_dependencies,
    get_sorted_srce_and_dest_pages,
)
from comic_utils.comic_consts import JPG_FILE_EXT
from loguru import logger
from utils import (
    DATE_SEP,
    DATE_TIME_SEP,
    HOUR_SEP,
    get_file_out_of_date_with_other_file_msg,
    get_file_out_of_date_wrt_max_timestamp_msg,
)

ERROR_MSG_PREFIX = "ERROR: "
BLANK_ERR_MSG_PREFIX = f"{' ':<{len(ERROR_MSG_PREFIX)}}"

MAX_FIXES_PAGE_NUM = 300


@dataclass
class ZipOutOfDateErrors:
    file: str = ""
    missing: bool = False
    out_of_date_wrt_ini: bool = False
    out_of_date_wrt_srce: bool = False
    out_of_date_wrt_dest: bool = False
    timestamp: float = 0.0


@dataclass
class ZipSymlinkOutOfDateErrors:
    symlink: str = ""
    missing: bool = False
    out_of_date_wrt_ini: bool = False
    out_of_date_wrt_zip: bool = False
    out_of_date_wrt_dest: bool = False
    timestamp: float = 0.0


@dataclass
class OutOfDateErrors:
    title: str
    ini_file: str
    dest_dir_files_missing: list[str]
    dest_dir_files_out_of_date: list[str]
    srce_and_dest_files_missing: list[tuple[str, str]]
    srce_and_dest_files_out_of_date: list[tuple[str, str]]
    unexpected_dest_image_files: list[str]
    exception_errors: list[str]
    zip_errors: ZipOutOfDateErrors
    series_zip_symlink_errors: ZipSymlinkOutOfDateErrors
    year_zip_symlink_errors: ZipSymlinkOutOfDateErrors
    is_error: bool = False
    max_srce_timestamp: float = 0.0
    max_srce_file: str = ""
    max_dest_timestamp: float = 0.0
    max_dest_file: str = ""
    ini_timestamp: float = 0.0


class ComicsIntegrityChecker:
    def __init__(
        self,
        comics_db: ComicsDatabase,
        no_check_for_unexpected_files: bool,
        no_check_symlinks: bool,
    ) -> None:
        self.comics_database = comics_db

        self._check_for_unexpected_files = not no_check_for_unexpected_files
        self._check_symlinks = not no_check_symlinks

    def check_comics_integrity(self, titles: list[str]) -> int:
        panel_bounding.warn_on_panels_bbox_height_less_than_av = False

        print()

        if self.check_comics_source_is_readonly() != 0:
            return 1

        if self.check_directory_structure() != 0:
            return 1

        if self.check_fantagraphics_files() != 0:
            return 1

        if self.check_ini_files_match_series_info() != 0:
            return 1

        unexpected_files = self.check_no_unexpected_files() != 0

        if not titles:
            ret_code = self.check_all_titles()
        else:
            ret_code = 0
            for title in titles:
                ret = self.check_single_title(title)
                if ret != 0:
                    ret_code = ret

        if ret_code == 0:
            if not unexpected_files:
                print("\nThere were no problems found.\n")
            else:
                print("\nThere were no other problems found.\n")
                ret_code = 1

        return ret_code

    @staticmethod
    def make_out_of_date_errors(title: str, ini_file: str) -> OutOfDateErrors:
        return OutOfDateErrors(
            title=title,
            ini_file=ini_file,
            dest_dir_files_missing=[],
            dest_dir_files_out_of_date=[],
            srce_and_dest_files_out_of_date=[],
            srce_and_dest_files_missing=[],
            unexpected_dest_image_files=[],
            exception_errors=[],
            zip_errors=ZipOutOfDateErrors(),
            series_zip_symlink_errors=ZipSymlinkOutOfDateErrors(),
            year_zip_symlink_errors=ZipSymlinkOutOfDateErrors(),
        )

    def check_comics_source_is_readonly(self) -> int:
        logger.info("Checking Fantagraphics original directories are readonly.")

        ret_code = self.check_folder_and_contents_are_readonly(
            self.comics_database.get_fantagraphics_original_root_dir(),
        )

        if ret_code == 0:
            logger.info("All Fantagraphics original directories are readonly.")
        else:
            logger.error("There are Fantagraphics original directories that are not readonly.")

        return ret_code

    def check_fantagraphics_files(self) -> int:
        logger.info("Checking Fantagraphics files.")

        ret_code = self.check_all_fantagraphics_original_dirs()
        ret = self.check_all_fixes_and_additions_files()
        if ret != 0:
            ret_code = ret

        if ret_code == 0:
            logger.info("All Fantagraphics files are OK.")
        else:
            logger.error("There were issues with some Fantagraphics files.")

        return ret_code

    def check_all_fantagraphics_original_dirs(self) -> int:
        ret_code = 0

        for volume in range(FIRST_VOLUME_NUMBER, LAST_VOLUME_NUMBER + 1):
            if self.check_fantagraphics_original_dirs(volume) != 0:
                ret_code = 1

        return ret_code

    def check_fantagraphics_original_dirs(self, volume: int) -> int:
        fanta_original_image_dir = Path(
            self.comics_database.get_fantagraphics_volume_image_dir(volume)
        )

        images = sorted(fanta_original_image_dir.iterdir())

        ret_code = 0
        expected_image_num = 0
        for file in images:
            expected_image_num += 1
            image_num = int(file.stem)
            if image_num != expected_image_num:
                print(
                    f"{ERROR_MSG_PREFIX}Expecting image num {expected_image_num}."
                    f' Original image file is out of order: "{file}".'
                )
                ret_code = 1

        num_pages = self.comics_database.get_num_pages_in_fantagraphics_volume(volume)
        if num_pages != expected_image_num:
            print(
                f'{ERROR_MSG_PREFIX}For volume "{fanta_original_image_dir}",'
                f" expecting {num_pages} images but got {expected_image_num} images."
            )
            ret_code = 1

        return ret_code

    def check_all_fixes_and_additions_files(self) -> int:
        ret_code = 0

        for volume in range(FIRST_VOLUME_NUMBER, LAST_VOLUME_NUMBER + 1):
            if self.check_standard_fixes_and_additions_files(volume) != 0:
                ret_code = 1
            if self.check_upscayled_fixes_and_additions_files(volume) != 0:
                ret_code = 1

        return ret_code

    def check_standard_fixes_and_additions_files(self, volume: int) -> int:
        fanta_original_image_dir = self.comics_database.get_fantagraphics_volume_image_dir(volume)
        num_fanta_pages = self.comics_database.get_num_pages_in_fantagraphics_volume(volume)

        fixes_root_dir = self.comics_database.get_fantagraphics_fixes_volume_dir(volume)
        fixes_dir = self.comics_database.get_fantagraphics_fixes_volume_image_dir(volume)
        upscayled_fixes_dir = (
            self.comics_database.get_fantagraphics_upscayled_fixes_volume_image_dir(volume)
        )

        if self.check_basic_fixes(fixes_root_dir, fixes_dir, upscayled_fixes_dir) != 0:
            return 1

        # Standard fixes files.
        ret_code = 0
        for file in os.listdir(fixes_dir):
            # TODO: Should 'bounded' be here?
            if file == "bounded":
                continue

            file_stem = Path(file).stem
            original_file = os.path.join(fanta_original_image_dir, file_stem + JPG_FILE_EXT)

            # TODO: Another special case. Needed?
            if file.endswith("-fix.txt"):
                jpg_file = os.path.join(fixes_dir, file[: -len("-fix.txt")] + JPG_FILE_EXT)
                png_file = os.path.join(fixes_dir, file[: -len("-fix.txt")] + PNG_FILE_EXT)
                if not os.path.isfile(jpg_file) and not os.path.isfile(png_file):
                    print(f'{ERROR_MSG_PREFIX}Fixes text file has no .jpg or .png match: "{file}".')
                    ret_code = 1
                continue

            jpg_fixes_file = os.path.join(fixes_dir, file_stem + JPG_FILE_EXT)
            png_fixes_file = os.path.join(fixes_dir, file_stem + PNG_FILE_EXT)
            if not os.path.isfile(jpg_fixes_file) and not os.path.isfile(png_fixes_file):
                print(
                    f"{ERROR_MSG_PREFIX}Fixes file must be a .jpg or .png file:"
                    f' "{jpg_fixes_file}".',
                )
                ret_code = 1
                continue

            # Must be a jpg or png file.
            if (Path(file).suffix != JPG_FILE_EXT) and (Path(file).suffix != PNG_FILE_EXT):
                print(f'{ERROR_MSG_PREFIX}Fixes file must be a .jpg or .png: "{jpg_fixes_file}".')
                ret_code = 1
                continue

            # Must not also be matching upscayl fixes file.
            upscayl_fixes_file = os.path.join(upscayled_fixes_dir, file_stem + PNG_FILE_EXT)
            if os.path.isfile(upscayl_fixes_file):
                print(
                    f"{ERROR_MSG_PREFIX}Fixes file should not have"
                    f' matching upscayled fixes file: "{upscayl_fixes_file}".',
                )
                ret_code = 1
                continue

            fixes_file = jpg_fixes_file if os.path.isfile(jpg_fixes_file) else png_fixes_file

            if not os.path.isfile(original_file):
                # If it's an added file it must have a valid page number.
                page_num = Path(file).stem
                if not page_num.isnumeric():
                    print(f'{ERROR_MSG_PREFIX}Invalid fixes file: "{fixes_file}".')
                    ret_code = 1
                    continue
                page_num = int(page_num)
                if page_num <= num_fanta_pages or page_num > MAX_FIXES_PAGE_NUM:
                    print(
                        f"{ERROR_MSG_PREFIX}Fixes file is outside page num range"
                        f' [{num_fanta_pages}..{MAX_FIXES_PAGE_NUM}]: "{fixes_file}".',
                    )
                    ret_code = 1
                    continue

                # If it's an added file it must be used in some ini file.
                if self._not_used(page_num):
                    print(
                        f"{ERROR_MSG_PREFIX}Fixes file is not used in any ini files:"
                        f' "{fixes_file}".',
                    )
                    ret_code = 1
                    continue

        return ret_code

    def check_basic_fixes(
        self, fixes_root_dir: str, fixes_dir: str, upscayled_fixes_dir: str
    ) -> int:
        if self._get_num_files_in_dir(fixes_root_dir) != 1:
            print(f'{ERROR_MSG_PREFIX}Directory "{fixes_root_dir}" has too many files.')
            return 1

        if not os.path.isdir(fixes_dir):
            print(f'{ERROR_MSG_PREFIX}Could not find fixes directory "{fixes_dir}".')
            return 1

        if not os.path.isdir(upscayled_fixes_dir):
            print(
                f"{ERROR_MSG_PREFIX}Could not find upscayled fixes directory:"
                f' "{upscayled_fixes_dir}".',
            )
            return 1

        return 0

    def check_upscayled_fixes_and_additions_files(self, volume: int) -> int:
        fanta_original_image_dir = self.comics_database.get_fantagraphics_volume_image_dir(volume)
        fixes_dir = self.comics_database.get_fantagraphics_fixes_volume_image_dir(volume)

        ret_code = 0

        # Basic 'upscayled fixes' check.
        upscayled_fixes_root_dir = (
            self.comics_database.get_fantagraphics_upscayled_fixes_volume_dir(volume)
        )
        if self._get_num_files_in_dir(upscayled_fixes_root_dir) != 1:
            print(f'{ERROR_MSG_PREFIX}Directory "{upscayled_fixes_root_dir}" has too many files.')
            return 1

        upscayled_fixes_dir = (
            self.comics_database.get_fantagraphics_upscayled_fixes_volume_image_dir(volume)
        )
        if not os.path.isdir(fixes_dir):
            print(
                f"{ERROR_MSG_PREFIX}Could not find upscayled fixes directory:"
                f' "{upscayled_fixes_dir}".',
            )
            return 1

        # Upscayled fixes files.
        for file in os.listdir(upscayled_fixes_dir):
            file_stem = Path(file).stem
            original_file = os.path.join(fanta_original_image_dir, file_stem + JPG_FILE_EXT)
            fixes_file = os.path.join(fixes_dir, file)
            upscayled_fixes_file = os.path.join(upscayled_fixes_dir, file)

            if not os.path.isfile(upscayled_fixes_file):
                print(
                    f"{ERROR_MSG_PREFIX}Upscayled fixes file must be a file:"
                    f' "{upscayled_fixes_file}".',
                )
                ret_code = 1
                continue

            # TODO: Another special case. Needed?
            if file.endswith("-fix.txt"):
                matching_fixes_file = os.path.join(
                    upscayled_fixes_dir,
                    file[: -len("-fix.txt")] + PNG_FILE_EXT,
                )
                if not os.path.isfile(matching_fixes_file):
                    print(
                        f"{ERROR_MSG_PREFIX}Upscayled fixes text file has no match:"
                        f' "{upscayled_fixes_file}".',
                    )
                    ret_code = 1
                continue

            # Must be a png file.
            if Path(file).suffix != PNG_FILE_EXT:
                print(
                    f"{ERROR_MSG_PREFIX}Upscayled fixes file must be a png:"
                    f' "{upscayled_fixes_file}".',
                )
                ret_code = 1
                continue

            # Upscayled fixes cannot be additions?
            # TODO: Will need comic object here to get censored titles
            if not os.path.isfile(original_file) and not ComicBook.is_fixes_special_case_added(
                volume,
                get_page_num_str(original_file),
            ):
                print(
                    f"{ERROR_MSG_PREFIX}Upscayled fixes file does not have matching original file:"
                    f' "{upscayled_fixes_file}".',
                )
                ret_code = 1
                continue

            if os.path.isfile(fixes_file):
                print(
                    f"{ERROR_MSG_PREFIX}Upscayled fixes file cannot have a matching fixes"
                    f' file: "{upscayled_fixes_file}".',
                )
                ret_code = 1
                continue

        return ret_code

    # TODO: Fill this out
    @staticmethod
    def _not_used(_page_num: int) -> bool:
        return False

    @staticmethod
    def _get_num_files_in_dir(dirname: str) -> int:
        return len(list(os.listdir(dirname)))

    def check_folder_and_contents_are_readonly(self, dir_path: str) -> int:
        ret_code = 0

        for f in os.listdir(dir_path):
            file_path = os.path.join(dir_path, f)

            if os.path.isdir(file_path):
                if os.access(file_path, os.W_OK):
                    print(f'{ERROR_MSG_PREFIX}Directory "{file_path}" is not readonly.')
                    ret_code = 1
                if self.check_folder_and_contents_are_readonly(file_path) != 0:
                    ret_code = 1
                    continue

            if os.access(file_path, os.W_OK):
                print(f'{ERROR_MSG_PREFIX}File "{file_path}" is not readonly.')
                ret_code = 1

        return ret_code

    def check_directory_structure(self) -> int:
        logger.info("Check complete directory structure.")

        ret_code = 0
        for volume in range(FIRST_VOLUME_NUMBER, LAST_VOLUME_NUMBER + 1):
            if not self._found_dir(
                self.comics_database.get_fantagraphics_upscayled_volume_image_dir(volume)
            ):
                ret_code = 1

            if not self._found_dir(
                self.comics_database.get_fantagraphics_restored_volume_image_dir(volume)
            ):
                ret_code = 1

            if not self._found_dir(
                self.comics_database.get_fantagraphics_restored_upscayled_volume_image_dir(volume)
            ):
                ret_code = 1

            if not self._found_dir(
                self.comics_database.get_fantagraphics_restored_svg_volume_image_dir(volume)
            ):
                ret_code = 1

            if not self._found_dir(
                self.comics_database.get_fantagraphics_restored_ocr_volume_dir(volume)
            ):
                ret_code = 1

            if not self._found_dir(
                self.comics_database.get_fantagraphics_fixes_volume_image_dir(volume)
            ):
                ret_code = 1

            if not self._found_dir(
                self.comics_database.get_fantagraphics_upscayled_fixes_volume_image_dir(volume)
            ):
                ret_code = 1

            if not self._found_dir(
                self.comics_database.get_fantagraphics_fixes_scraps_volume_image_dir(volume)
            ):
                ret_code = 1

            if not self._found_dir(
                self.comics_database.get_fantagraphics_panel_segments_volume_dir(volume)
            ):
                ret_code = 1

        if ret_code == 0:
            logger.info("The directory structure is correct.")
        else:
            logger.error("There were issues with the directory structure.")

        return ret_code

    @staticmethod
    def _found_dir(dirname: str) -> bool:
        if not os.path.isdir(dirname):
            print(f'{ERROR_MSG_PREFIX}Could not find directory "{dirname}".')
            return False
        return True

    def check_ini_files_match_series_info(self) -> int:
        logger.info("Checking ini file titles match series info.")

        ret_code = 0

        for volume in range(FIRST_VOLUME_NUMBER, LAST_VOLUME_NUMBER + 1):
            titles_and_info = self.comics_database.get_configured_titles_in_fantagraphics_volumes(
                [volume]
            )
            ini_titles = {t[0] for t in titles_and_info}
            titles_and_info = self.comics_database.get_all_titles_in_fantagraphics_volumes([volume])
            series_info_titles = {t[0] for t in titles_and_info}
            for ini_title in ini_titles:
                if ini_title not in series_info_titles:
                    print(
                        f"{ERROR_MSG_PREFIX}For volume {volume}, ini title is not"
                        f' in SERIES_INFO: "{ini_title}".',
                    )
                    ret_code = 1

        if ret_code == 0:
            logger.info("All ini file titles match series info.")
        else:
            logger.error("There were some ini file titles not in series info.")

        return ret_code

    def check_no_unexpected_files(self) -> int:
        logger.info("Check no unexpected files.")

        if not self._check_for_unexpected_files:
            logger.info("Check unexpected flag turned off. Not checking.")
            return 0

        ret_code = 0

        extra_srce_dirs = [
            self.comics_database.get_root_dir("Fantagraphics-censorship-fixes"),
            self.comics_database.get_root_dir("Articles"),
            self.comics_database.get_root_dir("Books"),
            self.comics_database.get_root_dir("Bugs"),
            self.comics_database.get_root_dir("CBL_Index"),
            self.comics_database.get_root_dir("Comics Scans"),
            self.comics_database.get_root_dir("Glk Covers"),
            self.comics_database.get_root_dir("Misc"),
            self.comics_database.get_root_dir("Not-controversial-restored"),
            self.comics_database.get_root_dir("Paintings"),
            THE_COMICS_DIR,
        ]

        srce_dirs = extra_srce_dirs
        for _volume in range(FIRST_VOLUME_NUMBER, LAST_VOLUME_NUMBER + 1):
            srce_dirs.append(self.comics_database.get_fantagraphics_original_root_dir())
            srce_dirs.append(self.comics_database.get_fantagraphics_upscayled_root_dir())
            srce_dirs.append(self.comics_database.get_fantagraphics_restored_root_dir())
            srce_dirs.append(self.comics_database.get_fantagraphics_restored_upscayled_root_dir())
            srce_dirs.append(self.comics_database.get_fantagraphics_restored_svg_root_dir())
            srce_dirs.append(self.comics_database.get_fantagraphics_restored_ocr_root_dir())
            srce_dirs.append(self.comics_database.get_fantagraphics_fixes_root_dir())
            srce_dirs.append(self.comics_database.get_fantagraphics_upscayled_fixes_root_dir())
            srce_dirs.append(self.comics_database.get_fantagraphics_fixes_scraps_root_dir())
            srce_dirs.append(self.comics_database.get_fantagraphics_panel_segments_root_dir())

        dest_dirs = []
        zip_files = []
        zip_series_symlink_dirs = set()
        zip_series_symlinks = []
        zip_year_symlink_dirs = set()
        zip_year_symlinks = []
        for title in self.comics_database.get_all_story_titles():
            comic = self.comics_database.get_comic_book(title)

            dest_dirs.append((self.comics_database.get_ini_file(title), comic.get_dest_dir()))
            zip_files.append(comic.get_dest_comic_zip())
            zip_series_symlink_dirs.add(comic.get_dest_series_zip_symlink_dir())
            zip_series_symlinks.append(comic.get_dest_series_comic_zip_symlink())
            zip_year_symlink_dirs.add(comic.get_dest_year_zip_symlink_dir())
            zip_year_symlinks.append(comic.get_dest_year_comic_zip_symlink())

        if (
            self.check_unexpected_files(
                srce_dirs,
                dest_dirs,
                zip_files,
                zip_series_symlink_dirs,
                zip_series_symlinks,
                zip_year_symlink_dirs,
                zip_year_symlinks,
            )
            != 0
        ):
            ret_code = 1

        if ret_code == 0:
            logger.info("There are no unexpected files.")
        else:
            logger.error("There were some unexpected or missing files.")

        return ret_code

    def check_single_title(self, title: str) -> int:
        ret_code = 0

        comic = self.comics_database.get_comic_book(title)

        if self.check_comic_structure(comic) != 0 or self.check_out_of_date_files(comic) != 0:
            ret_code = 1

        return ret_code

    def check_all_titles(self) -> int:
        ret_code = 0

        for title in self.comics_database.get_all_story_titles():
            comic = self.comics_database.get_comic_book(title)

            if self.check_comic_structure(comic) != 0:
                ret_code = 1
                continue

            if self.check_out_of_date_files(comic) != 0:
                ret_code = 1

        return ret_code

    @staticmethod
    def check_comic_structure(comic: ComicBook) -> int:
        title = get_safe_title(comic.get_comic_title())

        num_pages = get_total_num_pages(comic)
        if num_pages <= 1:
            print(f'\n{ERROR_MSG_PREFIX}For "{title}", the page count is too small.')
            return 1

        logger.info(f'There are no structural problems with "{title}".')
        return 0

    def check_out_of_date_files(self, comic: ComicBook) -> int:
        title = get_safe_title(comic.get_comic_title())
        logger.info(f'Checking title "{title}".')

        out_of_date_errors = self.make_out_of_date_errors(title, comic.ini_file)

        self.check_srce_and_dest_files(comic, out_of_date_errors)
        self.check_zip_files(comic, out_of_date_errors)
        self.check_additional_files(comic, out_of_date_errors)

        out_of_date_errors.is_error = (
            len(out_of_date_errors.srce_and_dest_files_missing) > 0
            or len(out_of_date_errors.srce_and_dest_files_out_of_date) > 0
            or len(out_of_date_errors.dest_dir_files_missing) > 0
            or len(out_of_date_errors.unexpected_dest_image_files) > 0
            or len(out_of_date_errors.exception_errors) > 0
            or out_of_date_errors.zip_errors.missing
            or out_of_date_errors.series_zip_symlink_errors.missing
            or out_of_date_errors.year_zip_symlink_errors.missing
            or out_of_date_errors.zip_errors.out_of_date_wrt_srce
            or out_of_date_errors.zip_errors.out_of_date_wrt_dest
            or out_of_date_errors.series_zip_symlink_errors.out_of_date_wrt_zip
            or out_of_date_errors.year_zip_symlink_errors.out_of_date_wrt_zip
            or out_of_date_errors.series_zip_symlink_errors.out_of_date_wrt_ini
            or out_of_date_errors.year_zip_symlink_errors.out_of_date_wrt_ini
        )

        self.print_check_errors(out_of_date_errors)

        ret_code = 1 if out_of_date_errors.is_error else 0

        if ret_code == 0:
            logger.info(f'There are no out of date problems with "{title}".')

        return ret_code

    def check_srce_and_dest_files(self, comic: ComicBook, errors: OutOfDateErrors) -> None:
        errors.max_srce_timestamp = 0.0
        errors.max_dest_timestamp = 0.0
        errors.srce_and_dest_files_missing = []
        errors.srce_and_dest_files_out_of_date = []
        errors.exception_errors = []

        inset_file = comic.intro_inset_file
        if comic.get_title_enum() not in NON_COMIC_TITLES and not os.path.isfile(inset_file):
            errors.exception_errors.append(f'Inset file not found: "{inset_file}"')
            return

        try:
            srce_and_dest_pages = get_sorted_srce_and_dest_pages(comic, get_full_paths=True)
        except Exception as e:
            errors.exception_errors.append(str(e))
            return

        self.check_missing_or_out_of_date_dest_files(comic, srce_and_dest_pages, errors)
        self.check_unexpected_dest_image_files(comic, srce_and_dest_pages, errors)

    @staticmethod
    def check_missing_or_out_of_date_dest_files(
        comic: ComicBook,
        srce_and_dest_pages: SrceAndDestPages,
        errors: OutOfDateErrors,
    ) -> None:
        is_a_comic = comic.get_title_enum() not in NON_COMIC_TITLES

        for pages in zip(
            srce_and_dest_pages.srce_pages, srce_and_dest_pages.dest_pages, strict=True
        ):
            srce_page = pages[0]
            dest_page = pages[1]
            if not os.path.isfile(dest_page.page_filename):
                errors.srce_and_dest_files_missing.append(
                    (srce_page.page_filename, dest_page.page_filename),
                )
            else:
                srce_dependencies = get_restored_srce_dependencies(comic, srce_page)
                prev_timestamp = get_timestamp(dest_page.page_filename)
                prev_file = dest_page.page_filename
                for dependency in srce_dependencies:
                    if not dependency.independent and is_a_comic:
                        if (dependency.timestamp < 0) or (dependency.timestamp > prev_timestamp):
                            errors.srce_and_dest_files_out_of_date.append(
                                (dependency.file, prev_file)
                            )
                        prev_timestamp = dependency.timestamp
                        prev_file = dependency.file
                    if errors.max_srce_timestamp < dependency.timestamp:
                        errors.max_srce_file = dependency.file
                        errors.max_srce_timestamp = dependency.timestamp

                dest_timestamp = get_timestamp(dest_page.page_filename)
                if errors.max_dest_timestamp < dest_timestamp:
                    errors.max_dest_file = dest_page.page_filename
                    errors.max_dest_timestamp = dest_timestamp

    @staticmethod
    def check_unexpected_dest_image_files(
        comic: ComicBook,
        srce_and_dest_pages: SrceAndDestPages,
        errors: OutOfDateErrors,
    ) -> None:
        allowed_dest_image_files = [f.page_filename for f in srce_and_dest_pages.dest_pages]
        dest_image_dir = comic.get_dest_image_dir()
        if not os.path.isdir(dest_image_dir):
            errors.dest_dir_files_missing.append(dest_image_dir)
            return

        for file in os.listdir(dest_image_dir):
            dest_image_file = os.path.join(dest_image_dir, file)
            if dest_image_file not in allowed_dest_image_files:
                errors.unexpected_dest_image_files.append(dest_image_file)

    def check_unexpected_files(
        self,
        srce_dirs_list: list[str],
        dest_dirs_info_list: list[tuple[str, str]],
        allowed_zip_files: list[str],
        allowed_zip_series_symlink_dirs: set[str],
        allowed_zip_series_symlinks: list[str],
        allowed_zip_year_symlink_dirs: set[str],
        allowed_zip_year_symlinks: list[str],
    ) -> int:
        ret_code = 0

        if self.check_files_in_dir("main", BARKS_ROOT_DIR, srce_dirs_list) != 0:
            ret_code = 1

        allowed_main_dir_files = [
            THE_CHRONOLOGICAL_DIRS_DIR,
            THE_CHRONOLOGICAL_DIR,
            THE_YEARS_COMICS_DIR,
            *list(allowed_zip_series_symlink_dirs),
        ]

        if self.check_files_in_dir("main", THE_COMICS_DIR, allowed_main_dir_files) != 0:
            ret_code = 1

        for dest_dir_info in dest_dirs_info_list:
            ini_file = os.path.basename(dest_dir_info[0])
            dest_dir = dest_dir_info[1]

            if not os.path.isdir(dest_dir):
                print(f'{ERROR_MSG_PREFIX}The dest directory "{dest_dir}" is missing.')
                ret_code = 1
                continue

            for file in os.listdir(dest_dir):
                if file in [IMAGES_SUBDIR, ini_file]:
                    continue
                if file not in DEST_NON_IMAGE_FILES:
                    print(
                        f"{ERROR_MSG_PREFIX}The info file"
                        f' "{os.path.join(dest_dir, file)}" was unexpected.',
                    )
                    ret_code = 1

        if dest_dirs_info_list:
            allowed_dest_dirs = [d[1] for d in dest_dirs_info_list]
            dest_dir = os.path.dirname(allowed_dest_dirs[0])
            if self.check_files_in_dir("dest", dest_dir, allowed_dest_dirs) != 0:
                ret_code = 1

        if allowed_zip_files:
            dest_dir = os.path.dirname(allowed_zip_files[0])
            if self.check_files_in_dir("zip", dest_dir, allowed_zip_files) != 0:
                ret_code = 1

        if allowed_zip_series_symlinks:
            for dest_dir in allowed_zip_series_symlink_dirs:
                if self.check_files_in_dir("series", dest_dir, list(allowed_zip_series_symlinks)):
                    ret_code = 1

        if allowed_zip_year_symlinks:
            year_symlink_parent_dir = os.path.dirname(next(iter(allowed_zip_year_symlink_dirs)))
            if (
                self.check_files_in_dir(
                    "year dir",
                    year_symlink_parent_dir,
                    list(allowed_zip_year_symlink_dirs),
                )
                != 0
            ):
                ret_code = 1

            for dest_dir in allowed_zip_year_symlink_dirs:
                if self.check_files_in_dir("year", dest_dir, list(allowed_zip_year_symlinks)):
                    ret_code = 1

        if ret_code != 0:
            print()

        return ret_code

    @staticmethod
    def check_files_in_dir(file_type: str, the_dir: str, allowed_files: list[str]) -> int:
        ret_code = 0

        if not os.path.isdir(the_dir):
            print(f'{ERROR_MSG_PREFIX}The directory "{the_dir}" is missing.')
            return 1

        for file in os.listdir(the_dir):
            full_file = os.path.join(the_dir, file)
            if full_file not in allowed_files:
                print(
                    f"{ERROR_MSG_PREFIX}The {file_type} directory file"
                    f' "{full_file}" was unexpected.'
                )
                ret_code = 1

        return ret_code

    def check_zip_files(self, comic: ComicBook, errors: OutOfDateErrors) -> None:
        if not os.path.exists(comic.get_dest_comic_zip()):
            errors.zip_errors.missing = True
            errors.zip_errors.file = comic.get_dest_comic_zip()
            return

        zip_timestamp = get_timestamp(comic.get_dest_comic_zip())
        if zip_timestamp < errors.max_srce_timestamp:
            errors.zip_errors.out_of_date_wrt_srce = True
            errors.zip_errors.timestamp = zip_timestamp
            errors.zip_errors.file = comic.get_dest_comic_zip()

        if zip_timestamp < errors.max_dest_timestamp:
            errors.zip_errors.out_of_date_wrt_dest = True
            errors.zip_errors.timestamp = zip_timestamp
            errors.zip_errors.file = comic.get_dest_comic_zip()

        ini_timestamp = get_timestamp(errors.ini_file)
        if zip_timestamp < ini_timestamp:
            errors.zip_errors.out_of_date_wrt_ini = True
            errors.zip_errors.timestamp = zip_timestamp
            errors.zip_errors.file = comic.get_dest_comic_zip()
            errors.ini_timestamp = ini_timestamp

        if not self._check_symlinks:
            logger.info("Check symlinks flag turned off. Not checking.")
            return

        if not os.path.exists(comic.get_dest_series_comic_zip_symlink()):
            errors.series_zip_symlink_errors.missing = True
            errors.series_zip_symlink_errors.symlink = comic.get_dest_series_comic_zip_symlink()
            return

        series_zip_symlink_timestamp = get_timestamp(comic.get_dest_series_comic_zip_symlink())
        if series_zip_symlink_timestamp < zip_timestamp:
            errors.series_zip_symlink_errors.out_of_date_wrt_zip = True
            errors.series_zip_symlink_errors.timestamp = series_zip_symlink_timestamp
            errors.series_zip_symlink_errors.symlink = comic.get_dest_series_comic_zip_symlink()
            errors.zip_errors.timestamp = zip_timestamp
            errors.zip_errors.file = comic.get_dest_comic_zip()

        if series_zip_symlink_timestamp < ini_timestamp:
            errors.series_zip_symlink_errors.out_of_date_wrt_ini = True
            errors.series_zip_symlink_errors.timestamp = series_zip_symlink_timestamp
            errors.series_zip_symlink_errors.symlink = comic.get_dest_series_comic_zip_symlink()
            errors.ini_timestamp = ini_timestamp

        if series_zip_symlink_timestamp < errors.max_dest_timestamp:
            errors.series_zip_symlink_errors.out_of_date_wrt_dest = True
            errors.series_zip_symlink_errors.timestamp = series_zip_symlink_timestamp
            errors.series_zip_symlink_errors.symlink = comic.get_dest_series_comic_zip_symlink()

        if not os.path.exists(comic.get_dest_year_comic_zip_symlink()):
            errors.year_zip_symlink_errors.missing = True
            errors.year_zip_symlink_errors.symlink = comic.get_dest_year_comic_zip_symlink()
            return

        year_zip_symlink_timestamp = get_timestamp(comic.get_dest_year_comic_zip_symlink())
        if year_zip_symlink_timestamp < zip_timestamp:
            errors.year_zip_symlink_errors.out_of_date_wrt_zip = True
            errors.year_zip_symlink_errors.timestamp = year_zip_symlink_timestamp
            errors.year_zip_symlink_errors.symlink = comic.get_dest_year_comic_zip_symlink()
            errors.zip_errors.timestamp = zip_timestamp
            errors.zip_errors.file = comic.get_dest_comic_zip()

        if year_zip_symlink_timestamp < ini_timestamp:
            errors.year_zip_symlink_errors.out_of_date_wrt_ini = True
            errors.year_zip_symlink_errors.timestamp = year_zip_symlink_timestamp
            errors.year_zip_symlink_errors.symlink = comic.get_dest_year_comic_zip_symlink()
            errors.ini_timestamp = ini_timestamp

        if year_zip_symlink_timestamp < errors.max_dest_timestamp:
            errors.year_zip_symlink_errors.out_of_date_wrt_dest = True
            errors.year_zip_symlink_errors.timestamp = year_zip_symlink_timestamp
            errors.year_zip_symlink_errors.symlink = comic.get_dest_year_comic_zip_symlink()

    @staticmethod
    def check_additional_files(comic: ComicBook, errors: OutOfDateErrors) -> None:
        dest_dir = comic.get_dest_dir()
        if not os.path.exists(dest_dir):
            errors.dest_dir_files_missing.append(dest_dir)
            return

        for file in DEST_NON_IMAGE_FILES:
            full_file = os.path.join(dest_dir, file)
            if not os.path.exists(full_file):
                errors.dest_dir_files_missing.append(full_file)
                continue
            file_timestamp = get_timestamp(full_file)
            if file_timestamp < errors.max_srce_timestamp:
                errors.dest_dir_files_out_of_date.append(full_file)

    def print_check_errors(self, errors: OutOfDateErrors) -> None:
        if (
            len(errors.srce_and_dest_files_missing) > 0
            or len(errors.srce_and_dest_files_out_of_date) > 0
            or len(errors.dest_dir_files_missing) > 0
            or len(errors.dest_dir_files_out_of_date) > 0
            or len(errors.exception_errors) > 0
        ):
            self.print_out_of_date_or_missing_errors(errors)

        if errors.zip_errors.missing:
            print(
                f'{ERROR_MSG_PREFIX}For "{errors.title}",'
                f' the zip file "{errors.zip_errors.file}" is missing.',
            )

        if errors.series_zip_symlink_errors.missing:
            print(
                f'{ERROR_MSG_PREFIX}For "{errors.title}",'
                f' the series symlink "{errors.series_zip_symlink_errors.symlink}" is missing.',
            )

        if errors.year_zip_symlink_errors.missing:
            print(
                f'{ERROR_MSG_PREFIX}For "{errors.title}",'
                f' the year symlink "{errors.year_zip_symlink_errors.symlink}" is missing.',
            )

        if errors.zip_errors.out_of_date_wrt_srce:
            zip_file_timestamp = get_timestamp_as_str(
                errors.zip_errors.timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            max_srce_timestamp = get_timestamp_as_str(
                errors.max_srce_timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            print(
                f'{ERROR_MSG_PREFIX}For "{errors.title}", the zip file\n'
                f'{BLANK_ERR_MSG_PREFIX}"{errors.zip_errors.file}"\n'
                f"{BLANK_ERR_MSG_PREFIX}is out of date with the srce file"
                f' "{errors.max_srce_file}"\n'
                f"{BLANK_ERR_MSG_PREFIX}'{zip_file_timestamp}' < '{max_srce_timestamp}'.",
            )

        if errors.zip_errors.out_of_date_wrt_dest:
            zip_file_timestamp = get_timestamp_as_str(
                errors.zip_errors.timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            max_dest_timestamp = get_timestamp_as_str(errors.max_dest_timestamp)
            print(
                f'{ERROR_MSG_PREFIX}For "{errors.title}", the zip file\n'
                f'{BLANK_ERR_MSG_PREFIX}"{errors.zip_errors.file}"\n'
                f"{BLANK_ERR_MSG_PREFIX}is out of date with the max dest file timestamp:\n"
                f"{BLANK_ERR_MSG_PREFIX}'{zip_file_timestamp}' < '{max_dest_timestamp}'.",
            )

        if errors.zip_errors.out_of_date_wrt_ini:
            zip_file_timestamp = get_timestamp_as_str(
                errors.zip_errors.timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            ini_file_timestamp = get_timestamp_as_str(
                errors.ini_timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            print(
                f'{ERROR_MSG_PREFIX}For "{errors.title}", the zip file\n'
                f'{BLANK_ERR_MSG_PREFIX}"{errors.zip_errors.file}"\n'
                f"{BLANK_ERR_MSG_PREFIX}is out of date with the ini file timestamp:\n"
                f"{BLANK_ERR_MSG_PREFIX}'{zip_file_timestamp}' < '{ini_file_timestamp}'.",
            )

        if errors.series_zip_symlink_errors.out_of_date_wrt_zip:
            symlink_timestamp = get_timestamp_as_str(
                errors.series_zip_symlink_errors.timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            zip_file_timestamp = get_timestamp_as_str(
                errors.zip_errors.timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            print(
                f'{ERROR_MSG_PREFIX}For "{errors.title}", the series symlink\n'
                f'{BLANK_ERR_MSG_PREFIX}"{errors.series_zip_symlink_errors.symlink}"\n'
                f"{BLANK_ERR_MSG_PREFIX}is out of date with the zip file\n"
                f'{BLANK_ERR_MSG_PREFIX}"{errors.zip_errors.file}":\n'
                f"{BLANK_ERR_MSG_PREFIX}'{symlink_timestamp}' < '{zip_file_timestamp}'.",
            )

        if errors.series_zip_symlink_errors.out_of_date_wrt_ini:
            symlink_timestamp = get_timestamp_as_str(
                errors.series_zip_symlink_errors.timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            ini_file_timestamp = get_timestamp_as_str(
                errors.ini_timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            print(
                f'{ERROR_MSG_PREFIX}For "{errors.title}", the series symlink\n'
                f'{BLANK_ERR_MSG_PREFIX}"{errors.series_zip_symlink_errors.symlink}"\n'
                f"{BLANK_ERR_MSG_PREFIX}is out of date with the ini file timestamp:\n"
                f"{BLANK_ERR_MSG_PREFIX}'{symlink_timestamp}' < '{ini_file_timestamp}'.",
            )

        if errors.series_zip_symlink_errors.out_of_date_wrt_dest:
            symlink_timestamp = get_timestamp_as_str(
                errors.series_zip_symlink_errors.timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            max_dest_timestamp = get_timestamp_as_str(
                errors.max_dest_timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            print(
                f'{ERROR_MSG_PREFIX}For "{errors.title}", the series symlink\n'
                f'{BLANK_ERR_MSG_PREFIX}"{errors.series_zip_symlink_errors.symlink}"\n'
                f"{BLANK_ERR_MSG_PREFIX}is out of date with the max dest file timestamp:\n"
                f"{BLANK_ERR_MSG_PREFIX}'{symlink_timestamp}' < '{max_dest_timestamp}'.",
            )

        if errors.year_zip_symlink_errors.out_of_date_wrt_zip:
            symlink_timestamp = get_timestamp_as_str(
                errors.year_zip_symlink_errors.timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            zip_file_timestamp = get_timestamp_as_str(
                errors.zip_errors.timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            print(
                f'{ERROR_MSG_PREFIX}For "{errors.title}", the year symlink\n'
                f'{BLANK_ERR_MSG_PREFIX}"{errors.year_zip_symlink_errors.symlink}"\n'
                f"{BLANK_ERR_MSG_PREFIX}is out of date with the zip file\n"
                f'{BLANK_ERR_MSG_PREFIX}"{errors.zip_errors.file}":\n'
                f"{BLANK_ERR_MSG_PREFIX}'{symlink_timestamp}' < '{zip_file_timestamp}'.",
            )

        if errors.year_zip_symlink_errors.out_of_date_wrt_ini:
            symlink_timestamp = get_timestamp_as_str(
                errors.year_zip_symlink_errors.timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            ini_file_timestamp = get_timestamp_as_str(
                errors.ini_timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            print(
                f'{ERROR_MSG_PREFIX}For "{errors.title}", the year symlink\n'
                f'{BLANK_ERR_MSG_PREFIX}"{errors.year_zip_symlink_errors.symlink}"\n'
                f"{BLANK_ERR_MSG_PREFIX}is out of date with the ini file timestamp:\n"
                f"{BLANK_ERR_MSG_PREFIX}'{symlink_timestamp}' < '{ini_file_timestamp}'.",
            )

        if errors.year_zip_symlink_errors.out_of_date_wrt_dest:
            symlink_timestamp = get_timestamp_as_str(
                errors.year_zip_symlink_errors.timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            max_dest_timestamp = get_timestamp_as_str(
                errors.max_dest_timestamp,
                DATE_SEP,
                DATE_TIME_SEP,
                HOUR_SEP,
            )
            print(
                f'{ERROR_MSG_PREFIX}For "{errors.title}", the year symlink\n'
                f'{BLANK_ERR_MSG_PREFIX}"{errors.year_zip_symlink_errors.symlink}"\n'
                f"{BLANK_ERR_MSG_PREFIX}is out of date with the max dest file timestamp:\n"
                f"{BLANK_ERR_MSG_PREFIX}'{symlink_timestamp}' < '{max_dest_timestamp}'.",
            )

        if len(errors.unexpected_dest_image_files) > 0:
            print()
            self.print_unexpected_dest_image_files_errors(errors)

    @staticmethod
    def print_unexpected_dest_image_files_errors(errors: OutOfDateErrors) -> None:
        for file in errors.unexpected_dest_image_files:
            print(f'{ERROR_MSG_PREFIX} The dest image file "{get_relpath(file)}" was unexpected.')

    @staticmethod
    def print_out_of_date_or_missing_errors(errors: OutOfDateErrors) -> None:
        for srce_dest in errors.srce_and_dest_files_missing:
            srce_file = srce_dest[0]
            dest_file = srce_dest[1]
            print(
                f'{ERROR_MSG_PREFIX} There is no dest file "{dest_file}"'
                f' matching srce file "{srce_file}".',
            )
        for srce_dest in errors.srce_and_dest_files_out_of_date:
            srce_file = srce_dest[0]
            dest_file = srce_dest[1]
            print(get_file_out_of_date_with_other_file_msg(dest_file, srce_file, ERROR_MSG_PREFIX))

        if (
            len(errors.srce_and_dest_files_missing) > 0
            or len(errors.srce_and_dest_files_out_of_date) > 0
            or len(errors.dest_dir_files_missing) > 0
            or len(errors.dest_dir_files_out_of_date) > 0
        ):
            print()

        if len(errors.dest_dir_files_missing) > 0:
            for err_msg in errors.dest_dir_files_missing:
                print(f'{ERROR_MSG_PREFIX}The dest file "{err_msg}" is missing.')
            print()

        if len(errors.dest_dir_files_out_of_date) > 0:
            for err_msg in errors.dest_dir_files_out_of_date:
                print(
                    get_file_out_of_date_wrt_max_timestamp_msg(
                        err_msg,
                        errors.max_srce_file,
                        errors.max_srce_timestamp,
                        ERROR_MSG_PREFIX,
                    ),
                )
            print()

        if len(errors.exception_errors) > 0:
            for err_msg in errors.exception_errors:
                print(f'{ERROR_MSG_PREFIX} For "{errors.title}", there was an error: {err_msg}.')
            print()

        if (
            len(errors.srce_and_dest_files_missing) > 0
            and len(errors.srce_and_dest_files_out_of_date) > 0
        ):
            print(
                f'{ERROR_MSG_PREFIX} For "{errors.title}",'
                f" there were {len(errors.srce_and_dest_files_missing)} missing dest files"
                f" and {len(errors.srce_and_dest_files_out_of_date)} out of date"
                f" dest files.\n",
            )
        else:
            if len(errors.srce_and_dest_files_missing) > 0:
                print(
                    f'{ERROR_MSG_PREFIX} For "{errors.title}",'
                    f" there were {len(errors.srce_and_dest_files_missing)} missing"
                    f" dest files.\n",
                )

            if len(errors.srce_and_dest_files_out_of_date) > 0:
                print(
                    f'{ERROR_MSG_PREFIX} For "{errors.title}",'
                    f" there were {len(errors.srce_and_dest_files_out_of_date)} out of"
                    f" date dest files.\n",
                )
