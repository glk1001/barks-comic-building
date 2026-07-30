# This module reports its findings to stdout by design - they are the program's output,
# not logging - so `print` is not a debugging leftover here. `artifact_renaming.py`
# carries the same suppression for the same reason.
# ruff: noqa: T201
import json
import stat
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from barks_build_comic_images.consts import DEST_NON_IMAGE_FILES
from barks_fantagraphics import panel_bounding
from barks_fantagraphics.barks_titles import ENUM_TO_STR_TITLE, Titles
from barks_fantagraphics.comic_book import ComicBook, get_total_num_pages
from barks_fantagraphics.comic_book_info import (
    NON_COMIC_TITLES,
    SYNTHETIC_TITLES,
    get_collection_page_nums,
)
from barks_fantagraphics.comics_consts import (
    BARKS_ROOT_DIR,
    BOUNDED_SUBDIR,
    IMAGES_SUBDIR,
    PNG_FILE_EXT,
    THE_CHRONOLOGICAL_DIR,
    THE_CHRONOLOGICAL_DIRS_DIR,
    THE_COMICS_DIR,
    THE_YEARS_COMICS_DIR,
)
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_utils import (
    get_relpath,
    get_safe_title,
    get_timestamp,
    get_timestamp_as_str,
)
from barks_fantagraphics.fanta_comics_info import (
    FIRST_VOLUME_NUMBER,
    LAST_VOLUME_NUMBER,
    SERIES_MISC,
)
from barks_fantagraphics.page_classes import SrceAndDestPages
from barks_fantagraphics.pages import (
    SrceDependency,
    get_restored_srce_dependencies,
    get_sorted_srce_and_dest_pages,
)
from comic_utils.comic_consts import JPG_FILE_EXT
from comic_utils.sys_utils import get_hash_str
from loguru import logger

from barks_comic_building.build.artifact_renaming import run_artifact_rename_fix
from barks_comic_building.build.stage_covers import (
    get_staged_links_by_title as get_cover_staged_links,
)
from barks_comic_building.build.stage_one_pagers import (
    get_staged_links_by_title as get_one_pager_staged_links,
)
from barks_comic_building.build.utils import (
    TIMESTAMP_SEPS,
    MaxTimestamp,
    ZipOutOfDateErrors,
    ZipSymlinkOutOfDateErrors,
    check_zip_freshness,
    check_zip_symlink_freshness,
    fold_max,
    get_file_out_of_date_with_other_file_msg,
    get_file_out_of_date_wrt_max_timestamp_msg,
    is_stale,
    walk_srce_dependency_chain,
)
from barks_comic_building.restore.restore_ledger import LEDGER_FILENAME as RESTORE_LEDGER_FILENAME
from barks_comic_building.restore.upscale_ledger import LEDGER_FILENAME as UPSCALE_LEDGER_FILENAME

ERROR_MSG_PREFIX = "ERROR: "
BLANK_ERR_MSG_PREFIX = f"{' ':<{len(ERROR_MSG_PREFIX)}}"

RESTORE_LEDGER_FILE = BARKS_ROOT_DIR / RESTORE_LEDGER_FILENAME
UPSCALE_LEDGER_FILE = BARKS_ROOT_DIR / UPSCALE_LEDGER_FILENAME

# Ceiling for *ordinary* added fixes pages - real pages appended past the end of a
# volume (e.g. volume 1's 251-268). The synthetic collections' staged pages are not
# covered by this band: they are validated against `get_collection_page_nums`, which
# tracks the collection tables automatically.
MAX_EXTRA_FIXES_PAGE_NUM = 300

STORIES_WITH_NON_BARKS_SCRIPTS_THAT_ARE_OK = {
    Titles.VICTORY_GARDEN_THE,
    Titles.TOYLAND,  # cspell:disable-line
}

# Titles with no intro inset image of their own: the non-comic articles, plus the
# synthetic collections ("All One-Pagers", "All Covers"), which are assembled from
# other titles' pages rather than being real Barks stories.
TITLES_WITHOUT_INSETS = frozenset(NON_COMIC_TITLES) | frozenset(SYNTHETIC_TITLES)


def _as_str(timestamp: float) -> str:
    """Render a timestamp for a finding, in the one format every finding uses."""
    return get_timestamp_as_str(timestamp, *TIMESTAMP_SEPS)


@contextmanager
def _quiet_panel_bbox_height_warnings() -> Iterator[None]:
    """Silence the shared panel-bounding height warning for the duration of a check.

    A short page legitimately has a panels bbox shorter than the volume average, and the
    integrity run visits every page of every title, so the warning is noise here.

    Restored on the way out because this is a module global in a *shared* package. The
    unrestored assignment it replaces was harmless only for as long as nothing called
    this method twice in one process - the moment a test does, the flag leaks into every
    later test in the session.
    """
    previous = panel_bounding.warn_on_panels_bbox_height_less_than_av
    panel_bounding.warn_on_panels_bbox_height_less_than_av = False
    try:
        yield
    finally:
        panel_bounding.warn_on_panels_bbox_height_less_than_av = previous


class AddedFixesFault(StrEnum):
    """Why an added fixes page - one with no original scan behind it - is not valid."""

    NOT_NUMERIC = "not numeric"
    OUT_OF_RANGE = "out of range"
    UNUSED = "unused"


class FixesFault(StrEnum):
    """Why a file in a fixes tree does not belong there."""

    NOT_AN_IMAGE = "not an image"
    NOTE_WITHOUT_IMAGE = "note without image"
    IN_BOTH_TREES = "in both trees"
    ADDED_WITHOUT_ORIGINAL = "added without original"


@dataclass(frozen=True, slots=True)
class FixesTreeSpec:
    """One fixes tree's naming and pairing policy.

    The two trees differ only in these facts: what the tree is called in a message, which
    extensions a fix may use, and which other tree must not hold a fix for the same page.
    Everything else was duplicated - around 160 lines of it, which is how the two copies
    came to disagree about whether the upscayled tree's own directory is checked at all.
    """

    # How the tree is named in a message: "Fixes file" / "fixes", and the other tree.
    label: str
    tree_label: str
    conflicting_label: str
    allowed_exts: tuple[str, ...]


STANDARD_FIXES = FixesTreeSpec(
    label="Fixes file",
    tree_label="fixes",
    conflicting_label="upscayled fixes",
    allowed_exts=(JPG_FILE_EXT, PNG_FILE_EXT),
)

UPSCAYLED_FIXES = FixesTreeSpec(
    label="Upscayled fixes file",
    tree_label="upscayled fixes",
    conflicting_label="fixes",
    allowed_exts=(PNG_FILE_EXT,),
)

# A fixes note: a text file recording why the page beside it was fixed.
FIXES_NOTE_SUFFIX = "-fix.txt"


def _is_fixes_note(file: Path) -> bool:
    """Return whether a file is a `-fix.txt` note rather than a fixed image."""
    return file.name.endswith(FIXES_NOTE_SUFFIX)


def is_expected_subdir(name: str, spec: FixesTreeSpec) -> bool:
    """Return whether a subdirectory belongs in this fixes tree.

    Only `bounded`, and only in the standard tree, whose panel-bounds files live there.
    Every other directory is reported: a half-copied "042/" is not a fix, and neither is a
    `bounded` under the upscayled tree, where nothing writes one.

    Args:
        name: The subdirectory's name.
        spec: Which of the two trees it was found in.

    Returns:
        True if it belongs there and should be skipped rather than reported.

    """
    return spec is STANDARD_FIXES and name == BOUNDED_SUBDIR


def explain_as_added_page(
    fault: FixesFault, spec: FixesTreeSpec, added_fault: AddedFixesFault | None
) -> bool:
    """Return whether a fault should be worded as an invalid added page.

    Only the standard tree has an added-pages band, so only its faults may be described in
    terms of one. The upscayled tree decides whether a page may exist without an original
    by `is_fixes_special_case_added` instead, so quoting a page num range at it would point
    the reader at a rule that does not govern the file they are looking at.

    Args:
        fault: What is wrong with the file.
        spec: Which tree it was found in.
        added_fault: The standard tree's added-page verdict, if there is one.

    Returns:
        True to use the added-page wording, False for the plain missing-original wording.

    """
    return (
        fault is FixesFault.ADDED_WITHOUT_ORIGINAL
        and spec is STANDARD_FIXES
        and added_fault is not None
    )


@dataclass(frozen=True, slots=True)
class AddedPagePolicy:
    """Where one volume may have fixes pages with no original scan behind them.

    Built once per volume. An added page must be numbered either in the volume's
    ordinary extra-pages band (`num_fanta_pages + 1` up to `MAX_EXTRA_FIXES_PAGE_NUM`)
    or in its staged synthetic-collection range, and must be referenced by one of the
    volume's ini files.
    """

    num_fanta_pages: int
    collection_page_nums: frozenset[int]
    used_page_nums: frozenset[str]

    def classify(self, page_num_str: str) -> AddedFixesFault | None:
        """Say why an added page is not valid, or None if it is.

        Takes the stem rather than the path, so the policy can be checked with no
        filesystem at all.

        Args:
            page_num_str: The fixes file's stem.

        Returns:
            The fault, or None if the added page is valid.

        """
        if not page_num_str.isnumeric():
            return AddedFixesFault.NOT_NUMERIC

        page_num = int(page_num_str)
        in_extra_band = self.num_fanta_pages < page_num <= MAX_EXTRA_FIXES_PAGE_NUM
        if page_num not in self.collection_page_nums and not in_extra_band:
            return AddedFixesFault.OUT_OF_RANGE

        if page_num_str not in self.used_page_nums:
            return AddedFixesFault.UNUSED

        return None

    def collection_range_msg(self) -> str:
        """Return the staged-collection part of the page num range error message."""
        if not self.collection_page_nums:
            return ""

        return (
            f" or staged collection range"
            f" [{min(self.collection_page_nums)}..{max(self.collection_page_nums)}]"
        )


@dataclass(frozen=True, slots=True)
class FixesFileFacts:
    """What the filesystem says about one fixes file.

    Every I/O question the policy needs, answered by the caller. Bundling them is what
    lets `classify_fixes_file` be a pure function of the facts, so the ordering of the
    checks is visible in one place and testable as a table.
    """

    is_note: bool
    note_pair_present: bool
    original_exists: bool
    present_in_other_tree: bool
    added_page_allowed: bool


def classify_fixes_file(
    suffix: str, spec: FixesTreeSpec, facts: FixesFileFacts
) -> FixesFault | None:
    """Say why one file in a fixes tree does not belong there, or None if it does.

    Args:
        suffix: The file's extension.
        spec: The tree's policy.
        facts: What the filesystem says about the file.

    Returns:
        The fault, or None if the file is valid.

    """
    if facts.is_note:
        return None if facts.note_pair_present else FixesFault.NOTE_WITHOUT_IMAGE

    if suffix not in spec.allowed_exts:
        return FixesFault.NOT_AN_IMAGE

    if facts.present_in_other_tree:
        return FixesFault.IN_BOTH_TREES

    if not facts.original_exists and not facts.added_page_allowed:
        return FixesFault.ADDED_WITHOUT_ORIGINAL

    return None


def _fixes_fault_msg(fault: FixesFault, spec: FixesTreeSpec, file: Path, original: Path) -> str:
    """Word one fixes-tree fault.

    Args:
        fault: What is wrong with the file.
        spec: The tree's naming.
        file: The offending file.
        original: The original scan the page would have replaced.

    Returns:
        The message, ready to print.

    """
    exts = " or ".join(spec.allowed_exts)

    if fault is FixesFault.NOTE_WITHOUT_IMAGE:
        return f'{ERROR_MSG_PREFIX}{spec.label} note has no {exts} match: "{file}".'

    if fault is FixesFault.NOT_AN_IMAGE:
        return f'{ERROR_MSG_PREFIX}{spec.label} must be {exts}: "{file}".'

    if fault is FixesFault.IN_BOTH_TREES:
        return (
            f'{ERROR_MSG_PREFIX}{spec.label} "{file}" should not also have a'
            f" matching {spec.conflicting_label} file."
        )

    return (
        f'{ERROR_MSG_PREFIX}{spec.label} "{file}" does not have a matching'
        f' original file: "{original}".'
    )


def _added_fixes_fault_msg(
    added_fault: AddedFixesFault,
    spec: FixesTreeSpec,
    file: Path,
    policy: AddedPagePolicy,
) -> str:
    """Word the reason a page with no original scan is not a valid addition.

    Args:
        added_fault: Why the added page is not valid.
        spec: The tree's naming.
        file: The offending file.
        policy: The volume's added-page policy, for the range in the message.

    Returns:
        The message, ready to print.

    """
    if added_fault is AddedFixesFault.NOT_NUMERIC:
        return f'{ERROR_MSG_PREFIX}Invalid {spec.tree_label} file: "{file}".'

    if added_fault is AddedFixesFault.UNUSED:
        return f'{ERROR_MSG_PREFIX}{spec.label} is not used in any ini files: "{file}".'

    return (
        f"{ERROR_MSG_PREFIX}{spec.label} is outside page num range"
        f" [{policy.num_fanta_pages + 1}..{MAX_EXTRA_FIXES_PAGE_NUM}]"
        f'{policy.collection_range_msg()}: "{file}".'
    )


@dataclass(frozen=True, slots=True)
class PageNumberFaults:
    """What is wrong with a volume's original-scan filenames."""

    non_numeric: list[str]
    out_of_order: list[tuple[str, int]]  # (stem, the number expected in that slot)
    actual_count: int


def unexpected_entries(dir_path: Path, allowed: Iterable[Path]) -> list[Path] | None:
    """Return a directory's entries that are not in the allowed set.

    Set-based. The former `in` against a list was O(entries x allowed), and one caller
    passes every zip symlink in the library - some hundreds - once per series directory.

    Sorted, so a long run of unexpected files reads in filename order rather than in
    whatever order the filesystem hands back.

    Args:
        dir_path: The directory to sweep.
        allowed: The paths that belong there.

    Returns:
        The unexpected entries, or None if the directory is missing - which the two
        callers report differently, one as a finding of its own.

    """
    if not dir_path.is_dir():
        return None

    allowed_paths = set(allowed)

    return sorted(entry for entry in dir_path.iterdir() if entry not in allowed_paths)


def dating_dependencies(
    dependencies: Sequence[SrceDependency], ini_file: Path
) -> list[SrceDependency]:
    """Drop the dependencies whose timestamps must not date a build.

    Only the ini file is dropped, and for two reasons that both point the same way.

    Its content is already checked properly: `check_hashes` compares the ini's hash
    against the `ini_hash` recorded in the comic's metadata at build time, so a real edit
    is caught exactly, with no reference to timestamps at all.

    And its timestamp is not evidence of anything. The ini files are git-tracked, in a
    different repository from the comics, so a checkout, pull or branch switch rewrites
    every mtime without changing a byte. Treating that as "the build is stale" reported
    2982 of 3323 findings on one real tree - 90% of the report - from a single bulk mtime
    bump in which not one ini's content had actually changed.

    The intro inset and a hand-drawn panel bounds fix stay. They are content files under
    the comics root rather than in git, nothing hashes them, and an edit to either really
    does mean the page needs rebuilding.

    Args:
        dependencies: A dest page's dependencies, as the pipeline reports them.
        ini_file: The comic's ini file.

    Returns:
        The dependencies that may date the build.

    """
    return [dependency for dependency in dependencies if dependency.file != ini_file]


def _has_staged_original_scan(links: list[tuple[Path, Path]]) -> bool:
    """Return whether a member's original-scan jpg is staged.

    Every other artifact is optional - a stage that has not been run yet - but without
    the original scan the collection has no image for the member at all.
    """
    return any(link.exists() for link, _ in links if link.suffix == JPG_FILE_EXT)


def check_collection_staged_links(
    collection: Titles, links_by_title: dict[Titles, list[tuple[Path, Path]]]
) -> int:
    """Check one collection's staged links against the sources they were made from.

    Module level, and takes the link map rather than a database: it consults no checker
    state, so requiring a `ComicsIntegrityChecker` to reach it only ever meant a test had
    to invent a database it would never touch.

    Args:
        collection: The collection title, for the error messages.
        links_by_title: Each member's `(link, source)` candidates.

    Returns:
        0 if the collection's staging is consistent, 1 otherwise.

    """
    collection_str = ENUM_TO_STR_TITLE[collection]
    restage_msg = f'Restage "{collection_str}"'
    ret_code = 0

    for title, links in links_by_title.items():
        title_str = ENUM_TO_STR_TITLE[title]

        for link, source in links:
            if link.is_symlink() and not link.exists():
                print(
                    f"{ERROR_MSG_PREFIX}Staged link for"
                    f' "{title_str}" is dangling: "{get_relpath(link)}"'
                    f' -> "{link.readlink()}".\n'
                    f"{BLANK_ERR_MSG_PREFIX}{restage_msg}.",
                )
                ret_code = 1
            elif link.is_symlink() and link.resolve() != source.resolve():
                # The page's own files are fine; it is the mapping that is wrong.
                print(
                    f"{ERROR_MSG_PREFIX}Staged link for"
                    f' "{title_str}" points at the wrong source:'
                    f' "{get_relpath(link)}"\n'
                    f'{BLANK_ERR_MSG_PREFIX}points at "{link.readlink()}"\n'
                    f'{BLANK_ERR_MSG_PREFIX}expected  "{get_relpath(source)}"\n'
                    f"{BLANK_ERR_MSG_PREFIX}The location table has changed without a"
                    f" restage, so members may be under each other's pages."
                    f" {restage_msg}.",
                )
                ret_code = 1
            elif link.exists() and not link.is_symlink() and source.is_file():
                # A real file with no upstream source is normal - the pipeline fills a
                # missing stage in place. One that *does* have an upstream source has
                # diverged from it and will not pick up a re-restore.
                print(
                    f"{ERROR_MSG_PREFIX}Staged file for"
                    f' "{title_str}" is a copy, not a link: "{get_relpath(link)}".\n'
                    f"{BLANK_ERR_MSG_PREFIX}It will not track"
                    f' "{get_relpath(source)}". {restage_msg}.',
                )
                ret_code = 1

        if not _has_staged_original_scan(links):
            print(
                f'{ERROR_MSG_PREFIX}"{title_str}" is located but has no staged'
                f' original scan, so "{collection_str}" has no page for it.\n'
                f"{BLANK_ERR_MSG_PREFIX}{restage_msg}.",
            )
            ret_code = 1

    return ret_code


def check_contiguous_page_numbers(stems: Sequence[str]) -> PageNumberFaults:
    """Verify a volume's original scans are numbered 1..n with no gaps.

    Takes stems rather than paths, so it needs no filesystem, and reports every fault
    rather than the first: one gap misnumbers every later page, and seeing the whole run
    is what says whether a file is missing or the numbering restarts.

    A non-numeric stem is collected, not raised. `int(file.stem)` used to be unguarded,
    so one stray "notes.txt" aborted the check for all thirty volumes with a ValueError
    out of a function whose contract is to return 0 or 1. It also counted toward the
    expected page number, shifting every page after it.

    Args:
        stems: The filename stems, in directory order.

    Returns:
        Every fault found, and the number of pages actually seen.

    """
    non_numeric: list[str] = []
    out_of_order: list[tuple[str, int]] = []
    expected_page_num = 0

    for stem in stems:
        if not stem.isnumeric():
            non_numeric.append(stem)
            continue

        expected_page_num += 1
        if int(stem) != expected_page_num:
            out_of_order.append((stem, expected_page_num))

    return PageNumberFaults(non_numeric, out_of_order, expected_page_num)


@dataclass
class HashErrors:
    metadata_file: Path | None = None
    metadata_missing_hash: Path | None = None
    expected_hash: str = ""
    file_to_hash: Path | None = None
    file_hash: str = ""


@dataclass
class OutOfDateErrors:
    title: str
    dest_dir_files_missing: list[Path]
    dest_dir_files_out_of_date: list[Path]
    srce_and_dest_files_missing: list[tuple[Path, Path]]
    srce_and_dest_files_out_of_date: list[tuple[Path, Path]]
    unexpected_dest_image_files: list[Path]
    exception_errors: list[str]
    zip_errors: ZipOutOfDateErrors
    series_zip_symlink_errors: ZipSymlinkOutOfDateErrors
    year_zip_symlink_errors: ZipSymlinkOutOfDateErrors
    max_srce: MaxTimestamp | None = None
    max_dest: MaxTimestamp | None = None

    @property
    def file_findings(self) -> bool:
        """Whether any per-file finding was recorded - missing, stale, or an exception."""
        return bool(
            self.srce_and_dest_files_missing
            or self.srce_and_dest_files_out_of_date
            or self.dest_dir_files_missing
            or self.dest_dir_files_out_of_date
            or self.exception_errors
        )

    @property
    def zip_findings(self) -> bool:
        """Whether the zip or either of its symlinks is missing or out of date."""
        zip_flags = (
            self.zip_errors.missing,
            self.zip_errors.out_of_date_wrt_srce,
            self.zip_errors.out_of_date_wrt_dest,
        )
        symlink_flags = (
            (symlink.missing, symlink.out_of_date_wrt_zip, symlink.out_of_date_wrt_dest)
            for symlink in (self.series_zip_symlink_errors, self.year_zip_symlink_errors)
        )

        return any(zip_flags) or any(any(flags) for flags in symlink_flags)

    @property
    def is_error(self) -> bool:
        """Whether this title has anything to report - the exit code, and nothing else.

        Derived, so that every field the report can print is reachable from here by
        construction. This used to be a separately-maintained assignment, and it had
        drifted: it omitted `dest_dir_files_out_of_date` and both symlinks'
        out-of-date-versus-dest flags, so those three findings printed as errors and the
        run still exited 0. Nothing enforced the correspondence, because there was
        nothing to enforce it against - a stored field can always be one term short.
        """
        return self.file_findings or self.zip_findings or bool(self.unexpected_dest_image_files)


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

    def check_comics_integrity(
        self, titles: list[str], *, fix_names: bool = False, apply_fixes: bool = False
    ) -> int:
        with _quiet_panel_bbox_height_warnings():
            return self._check_comics_integrity(
                titles, fix_names=fix_names, apply_fixes=apply_fixes
            )

    def _check_comics_integrity(
        self, titles: list[str], *, fix_names: bool, apply_fixes: bool
    ) -> int:
        print()

        if self._check_preconditions() != 0:
            return 1

        if fix_names:
            # A third tier, between the other two: the gates validate the build's
            # *inputs*, this repairs its *outputs*, and the report below then
            # describes whatever remains. Its findings stay out of `OutOfDateErrors`
            # because it is a whole-tree operation with no per-title home.
            if run_artifact_rename_fix(self.comics_database, apply=apply_fixes) != 0:
                return 1
            if not apply_fixes:
                # A dry run deliberately changed nothing, so there is no point
                # reporting on a tree we already know is stale.
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

    def _check_preconditions(self) -> int:
        """Run the gate checks that must pass before any per-title check is meaningful.

        These validate the *inputs* to the build - the read-only original tree, the
        directory structure, the fixes-and-additions files, and the ini/series-info
        agreement. A failure here aborts the run and is printed immediately rather
        than collected, because per-title results computed against a malformed source
        tree are noise: one broken input would produce a wall of downstream errors
        that all disappear once the input is fixed.

        Per-title findings are the other tier - they accumulate into `OutOfDateErrors`
        and are reported together at the end.

        Returns:
            0 if every precondition holds, 1 otherwise.

        """
        if self.check_comics_source_is_readonly() != 0:
            return 1

        if self.check_directory_structure() != 0:
            return 1

        if self.check_ini_files_match_series_info() != 0:
            return 1

        if self.check_staged_collection_links() != 0:
            return 1

        if self.check_fantagraphics_files() != 0:
            return 1

        return 0

    @staticmethod
    def make_out_of_date_errors(title: str) -> OutOfDateErrors:
        return OutOfDateErrors(
            title=title,
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

        num_pages = self.comics_database.get_num_pages_in_fantagraphics_volume(volume)
        faults = check_contiguous_page_numbers(
            [file.stem for file in sorted(fanta_original_image_dir.iterdir())]
        )

        ret_code = 0

        for stem in faults.non_numeric:
            print(
                f'{ERROR_MSG_PREFIX}For volume "{fanta_original_image_dir}",'
                f' original image file is not a page number: "{stem}".'
            )
            ret_code = 1

        for stem, expected_image_num in faults.out_of_order:
            print(
                f'{ERROR_MSG_PREFIX}For volume "{fanta_original_image_dir}",'
                f" expecting image num {expected_image_num} but the original image file"
                f' is out of order: "{stem}".'
            )
            ret_code = 1

        if num_pages != faults.actual_count:
            print(
                f'{ERROR_MSG_PREFIX}For volume "{fanta_original_image_dir}",'
                f" expecting {num_pages} images but got {faults.actual_count} images."
            )
            ret_code = 1

        return ret_code

    def check_all_fixes_and_additions_files(self) -> int:
        ret_code = 0

        for volume in range(FIRST_VOLUME_NUMBER, LAST_VOLUME_NUMBER + 1):
            if self.check_fixes_tree(volume, STANDARD_FIXES) != 0:
                ret_code = 1
            if self.check_fixes_tree(volume, UPSCAYLED_FIXES) != 0:
                ret_code = 1

        return ret_code

    def _fixes_tree_dirs(self, volume: int, spec: FixesTreeSpec) -> tuple[Path, Path, Path]:
        """Return one tree's `(root, images, other tree's images)` directories.

        Args:
            volume: The Fantagraphics volume.
            spec: Which of the two trees.

        Returns:
            The tree's root and image dirs, and the conflicting tree's image dir.

        """
        database = self.comics_database
        if spec is UPSCAYLED_FIXES:
            return (
                database.get_fantagraphics_upscayled_fixes_volume_dir(volume),
                database.get_fantagraphics_upscayled_fixes_volume_image_dir(volume),
                database.get_fantagraphics_fixes_volume_image_dir(volume),
            )

        return (
            database.get_fantagraphics_fixes_volume_dir(volume),
            database.get_fantagraphics_fixes_volume_image_dir(volume),
            database.get_fantagraphics_upscayled_fixes_volume_image_dir(volume),
        )

    def check_fixes_tree(self, volume: int, spec: FixesTreeSpec) -> int:
        """Check one volume's fixes tree against that tree's policy.

        Args:
            volume: The Fantagraphics volume.
            spec: Which of the two trees, and its naming and pairing rules.

        Returns:
            0 if every file in the tree belongs there, 1 otherwise.

        """
        original_image_dir = self.comics_database.get_fantagraphics_volume_image_dir(volume)
        root_dir, images_dir, other_tree_dir = self._fixes_tree_dirs(volume, spec)

        if self.check_basic_fixes(spec, root_dir, images_dir) != 0:
            return 1

        # Per-volume, so built once rather than per fixes file.
        policy = AddedPagePolicy(
            self.comics_database.get_num_pages_in_fantagraphics_volume(volume),
            get_collection_page_nums(volume),
            self._get_used_page_nums(volume),
        )

        ret_code = 0
        for file in sorted(images_dir.iterdir()):
            if file.is_dir() and is_expected_subdir(file.name, spec):
                continue

            is_note = _is_fixes_note(file)
            stem = file.name[: -len(FIXES_NOTE_SUFFIX)] if is_note else file.stem
            original_file = original_image_dir / (stem + JPG_FILE_EXT)

            added_fault = policy.classify(stem)
            if spec is UPSCAYLED_FIXES:
                # The upscayled tree has no added-pages band of its own: a page with no
                # original is allowed only where the database says one was added.
                added_page_allowed = ComicBook.is_fixes_special_case_added(volume, stem)
            else:
                added_page_allowed = added_fault is None

            facts = FixesFileFacts(
                is_note=is_note,
                note_pair_present=any(
                    (images_dir / (stem + ext)).is_file() for ext in spec.allowed_exts
                ),
                original_exists=original_file.is_file(),
                present_in_other_tree=any(
                    (other_tree_dir / (stem + ext)).is_file()
                    for ext in (JPG_FILE_EXT, PNG_FILE_EXT)
                ),
                added_page_allowed=added_page_allowed,
            )

            fault = classify_fixes_file(file.suffix, spec, facts)
            if fault is None:
                continue

            if explain_as_added_page(fault, spec, added_fault) and added_fault is not None:
                print(_added_fixes_fault_msg(added_fault, spec, file, policy))
            else:
                print(_fixes_fault_msg(fault, spec, file, original_file))
            ret_code = 1

        return ret_code

    def check_basic_fixes(self, spec: FixesTreeSpec, root_dir: Path, images_dir: Path) -> int:
        """Check a fixes tree's own shape before looking at what is in it.

        Each tree checks its own directories. The upscayled check used to test the
        *standard* fixes dir while naming the upscayled one in the message, so the
        upscayled tree's own existence was never actually checked.

        Args:
            spec: Which of the two trees.
            root_dir: The tree's volume root, which should hold only the images dir.
            images_dir: The tree's images dir.

        Returns:
            0 if the tree is shaped correctly, 1 otherwise.

        """
        if self._get_num_files_in_dir(root_dir) != 1:
            print(f'{ERROR_MSG_PREFIX}Directory "{root_dir}" has too many files.')
            return 1

        if not images_dir.is_dir():
            print(
                f'{ERROR_MSG_PREFIX}Could not find {spec.tree_label} directory: "{images_dir}".',
            )
            return 1

        return 0

    def _get_used_page_nums(self, volume: int) -> frozenset[str]:
        """Return every original page num referenced by an ini file in this volume.

        Uses `page_images_in_order`, not `config_page_images`: ini page keys may be
        ranges ("005-012"), and only the former has them expanded to one entry per
        page. The synthetic collections need no special case here - the database
        injects their staged pages into the comic's page list at load time, so those
        pages already count as used.
        """
        used: set[str] = set()

        for title, _info in self.comics_database.get_configured_titles_in_fantagraphics_volumes(
            [volume]
        ):
            comic = self.comics_database.get_comic_book(title)
            used.update(page.page_filenames for page in comic.page_images_in_order)

        return frozenset(used)

    @staticmethod
    def _not_used(page_num_str: str, used_page_nums: frozenset[str]) -> bool:
        return page_num_str not in used_page_nums

    @staticmethod
    def _get_num_files_in_dir(dir_path: Path) -> int:
        return len(list(dir_path.iterdir()))

    def check_folder_and_contents_are_readonly(self, dir_path: Path) -> int:
        ret_code = 0

        for file_path in sorted(dir_path.iterdir()):
            if file_path.is_dir():
                if file_path.stat().st_mode & stat.S_IWRITE:
                    print(f'{ERROR_MSG_PREFIX}Directory "{file_path}" is not readonly.')
                    ret_code = 1
                if self.check_folder_and_contents_are_readonly(file_path) != 0:
                    ret_code = 1
                    continue

            if file_path.stat().st_mode & stat.S_IWRITE:
                print(f'{ERROR_MSG_PREFIX}File "{file_path}" is not readonly.')
                ret_code = 1

        return ret_code

    def check_directory_structure(self) -> int:
        logger.info("Check complete directory structure.")

        database = self.comics_database
        volume_dir_getters = [
            database.get_fantagraphics_upscayled_volume_image_dir,
            database.get_fantagraphics_restored_volume_image_dir,
            database.get_fantagraphics_restored_upscayled_volume_image_dir,
            database.get_fantagraphics_restored_svg_volume_image_dir,
            database.get_fantagraphics_restored_ocr_raw_volume_dir,
            database.get_fantagraphics_fixes_volume_image_dir,
            database.get_fantagraphics_upscayled_fixes_volume_image_dir,
            database.get_fantagraphics_fixes_scraps_volume_image_dir,
            database.get_fantagraphics_panel_segments_volume_dir,
        ]

        ret_code = 0
        for volume in range(FIRST_VOLUME_NUMBER, LAST_VOLUME_NUMBER + 1):
            for get_dir in volume_dir_getters:
                if not self._found_dir(get_dir(volume)):
                    ret_code = 1

        if ret_code == 0:
            logger.info("The directory structure is correct.")
        else:
            logger.error("There were issues with the directory structure.")

        return ret_code

    @staticmethod
    def _found_dir(dir_path: Path) -> bool:
        if not dir_path.is_dir():
            print(f'{ERROR_MSG_PREFIX}Could not find directory "{dir_path}".')
            return False
        return True

    def check_staged_collection_links(self) -> int:
        """Check the synthetic collections' staged links still agree with their sources.

        Every other check here asks whether a file exists and whether it is newer than
        another file. None of that can catch a staged link pointing at the *wrong*
        source: a wrong-but-present source looks perfectly up to date, and the page
        built from it is a valid image - just of the wrong gag. So the staging layer is
        checked against the location tables it was generated from.

        The failure this guards is silent and destructive. A one-pager or cover
        inserted into (or removed from) ONE_PAGER_LOCATIONS/COVER_LOCATIONS shifts the
        collection page of every later member, because the page is `base + index`. Skip
        the restage and the on-disk links stay attached to the old page numbers, so the
        built cbz shows members under each other's pages.

        Returns:
            0 if every collection's staging is consistent, 1 otherwise.

        """
        logger.info("Checking the synthetic collections' staged links.")

        ret_code = 0
        for collection, links_by_title in (
            (Titles.ALL_ONE_PAGERS, get_one_pager_staged_links(self.comics_database)),
            (Titles.ALL_COVERS, get_cover_staged_links(self.comics_database)),
        ):
            if check_collection_staged_links(collection, links_by_title) != 0:
                ret_code = 1

        if ret_code == 0:
            logger.info("All staged collection links are consistent.")
        else:
            logger.error("Some staged collection links were inconsistent.")

        return ret_code

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
            self.comics_database.get_root_dir("Fantagraphics-alternate-downloads"),
            self.comics_database.get_root_dir("Fantagraphics-censorship-fixes"),
            self.comics_database.get_root_dir("Articles"),
            self.comics_database.get_root_dir("Barks Panels Pngs"),
            self.comics_database.get_root_dir("Books"),
            self.comics_database.get_root_dir("Bugs"),
            self.comics_database.get_root_dir("CBL_Index"),
            self.comics_database.get_root_dir("Comics Scans"),
            self.comics_database.get_root_dir("Compleat Barks Disney Reader"),
            self.comics_database.get_root_dir("Glk Covers"),
            self.comics_database.get_root_dir("Misc"),
            self.comics_database.get_root_dir("Not-controversial-restored"),
            self.comics_database.get_root_dir("Paintings"),
            self.comics_database.get_root_dir("Projects"),
            THE_COMICS_DIR,
            RESTORE_LEDGER_FILE,
            UPSCALE_LEDGER_FILE,
        ]

        # These are the artifact tree roots, not per-volume directories: every one of
        # these getters takes no volume argument. They used to be appended inside a loop
        # over all thirty volumes - and into `extra_srce_dirs` itself rather than a copy
        # - so the list held thirty identical runs of the same ten paths.
        database = self.comics_database
        srce_dirs = [
            *extra_srce_dirs,
            database.get_fantagraphics_original_root_dir(),
            database.get_fantagraphics_upscayled_root_dir(),
            database.get_fantagraphics_restored_root_dir(),
            database.get_fantagraphics_restored_upscayled_root_dir(),
            database.get_fantagraphics_restored_svg_root_dir(),
            database.get_fantagraphics_restored_ocr_root_dir(),
            database.get_fantagraphics_fixes_root_dir(),
            database.get_fantagraphics_upscayled_fixes_root_dir(),
            database.get_fantagraphics_fixes_scraps_root_dir(),
            database.get_fantagraphics_panel_segments_root_dir(),
        ]

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
        title_str = get_safe_title(comic.get_comic_title())

        if (
            self.check_comic_structure(comic, title_str) != 0
            or self.check_story_attributes(comic, title_str) != 0
            or self.check_out_of_date_files(comic) != 0
        ):
            ret_code = 1

        return ret_code

    def check_all_titles(self) -> int:
        ret_code = 0

        for title in self.comics_database.get_all_story_titles():
            comic = self.comics_database.get_comic_book(title)
            title_str = get_safe_title(comic.get_comic_title())

            if self.check_comic_structure(comic, title_str) != 0:
                ret_code = 1
                continue

            if self.check_story_attributes(comic, title_str) != 0:
                ret_code = 1
                continue

            if self.check_out_of_date_files(comic) != 0:
                ret_code = 1

        return ret_code

    def check_comic_structure(self, comic: ComicBook, title_str: str) -> int:
        num_pages = get_total_num_pages(comic)
        if (num_pages <= 1) and (comic.get_title_enum() not in NON_COMIC_TITLES):
            print(f'\n{ERROR_MSG_PREFIX}For "{title_str}", the page count is too small.')
            return 1

        errors = HashErrors()
        if self.check_hashes(comic, errors) != 0:
            self.print_hash_errors(errors)
            return 1

        logger.info(f'There are no structural problems with "{title_str}".')
        return 0

    @staticmethod
    def check_story_attributes(comic: ComicBook, title_str: str) -> int:
        if (
            ("script" in comic.extra_pub_info.lower())
            and (comic.fanta_info.series_name != SERIES_MISC)
            and (comic.get_title_enum() not in STORIES_WITH_NON_BARKS_SCRIPTS_THAT_ARE_OK)
        ):
            print(f'\n{ERROR_MSG_PREFIX}For "{title_str}", script not by Barks should be in MISC.')
            return 1

        logger.info(f'There are no story attribute problems with "{title_str}".')
        return 0

    @staticmethod
    def check_hashes(comic: ComicBook, errors: HashErrors) -> int:
        ini_hash = get_hash_str(comic.ini_file)
        metadata_file = comic.get_metadata_filepath()
        if not metadata_file.is_file():
            # A configured title with no metadata has not been built. That is a
            # finding to report, not a reason to abort the whole run.
            errors.metadata_file = metadata_file
            return 1

        metadata = json.loads(metadata_file.read_text())
        if "ini_hash" not in metadata:
            # Reported, not warned past. This hash is now the *only* check on the ini -
            # `dating_dependencies` drops its timestamp deliberately - so a comic whose
            # metadata predates the hash being recorded would otherwise have its ini
            # checked by nothing at all. Rebuilding records it.
            errors.metadata_missing_hash = metadata_file
            return 1

        metadata_hash = metadata["ini_hash"]
        if ini_hash != metadata_hash:
            errors.expected_hash = metadata_hash
            errors.file_to_hash = comic.ini_file
            errors.file_hash = ini_hash
            return 1

        return 0

    @staticmethod
    def print_hash_errors(errors: HashErrors) -> None:
        if errors.metadata_file is not None:
            print(
                f"{ERROR_MSG_PREFIX}Comic has not been built - there is no"
                f' metadata file: "{errors.metadata_file}".',
            )
            return

        if errors.metadata_missing_hash is not None:
            print(
                f"{ERROR_MSG_PREFIX}Comic metadata records no ini hash, so its ini file"
                f' is unchecked - rebuild it: "{errors.metadata_missing_hash}".',
            )
            return

        print(
            f'{ERROR_MSG_PREFIX} Hash mismatch for "{errors.file_to_hash}":'
            f' expected hash = "{errors.expected_hash}", file hash = "{errors.file_hash}".',
        )

    def check_out_of_date_files(self, comic: ComicBook) -> int:
        title = get_safe_title(comic.get_comic_title())
        logger.info(f'Checking title "{title}".')

        out_of_date_errors = self.make_out_of_date_errors(title)

        self.check_srce_and_dest_files(comic, out_of_date_errors)
        self.check_zip_files(comic, out_of_date_errors)
        self.check_additional_files(comic, out_of_date_errors)

        self.print_check_errors(out_of_date_errors)

        ret_code = 1 if out_of_date_errors.is_error else 0

        if ret_code == 0:
            logger.info(f'There are no out of date problems with "{title}".')

        return ret_code

    def check_srce_and_dest_files(self, comic: ComicBook, errors: OutOfDateErrors) -> None:
        errors.max_srce = None
        errors.max_dest = None
        errors.srce_and_dest_files_missing = []
        errors.srce_and_dest_files_out_of_date = []
        errors.exception_errors = []

        inset_file = comic.intro_inset_file
        if comic.get_title_enum() not in TITLES_WITHOUT_INSETS and not inset_file.is_file():
            errors.exception_errors.append(f'Inset file not found: "{inset_file}"')
            return

        try:
            srce_and_dest_pages = get_sorted_srce_and_dest_pages(comic, get_full_paths=True)
        except Exception as e:  # noqa: BLE001
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

        for srce_page, dest_page in zip(
            srce_and_dest_pages.srce_pages, srce_and_dest_pages.dest_pages, strict=True
        ):
            dest_file = Path(dest_page.page_filename)
            if not dest_file.is_file():
                errors.srce_and_dest_files_missing.append(
                    (Path(srce_page.page_filename), dest_file),
                )
                continue

            dest_timestamp = get_timestamp(dest_file)
            chain = walk_srce_dependency_chain(
                dating_dependencies(
                    get_restored_srce_dependencies(comic, srce_page), comic.ini_file
                ),
                dest_file,
                dest_timestamp,
                errors.max_srce,
                is_a_comic=is_a_comic,
            )

            errors.srce_and_dest_files_out_of_date.extend(chain.stale_pairs)
            errors.max_srce = chain.max_srce
            errors.max_dest = fold_max(errors.max_dest, dest_file, dest_timestamp)

    @staticmethod
    def check_unexpected_dest_image_files(
        comic: ComicBook,
        srce_and_dest_pages: SrceAndDestPages,
        errors: OutOfDateErrors,
    ) -> None:
        dest_image_dir = comic.get_dest_image_dir()
        unexpected = unexpected_entries(
            dest_image_dir, (Path(page.page_filename) for page in srce_and_dest_pages.dest_pages)
        )

        if unexpected is None:
            errors.dest_dir_files_missing.append(dest_image_dir)
            return

        errors.unexpected_dest_image_files.extend(unexpected)

    def _check_dest_dir_info_files(self, dest_dirs_info_list: list[tuple[Path, Path]]) -> int:
        """Check each built comic's directory holds only its images, ini and info files.

        Args:
            dest_dirs_info_list: Each title's `(ini file, dest dir)`.

        Returns:
            0 if every dest directory holds only what it should, 1 otherwise.

        """
        ret_code = 0

        for ini_file, dest_dir in dest_dirs_info_list:
            allowed = {dest_dir / IMAGES_SUBDIR, dest_dir / ini_file.name} | {
                dest_dir / name for name in DEST_NON_IMAGE_FILES
            }
            unexpected = unexpected_entries(dest_dir, allowed)

            if unexpected is None:
                print(f'{ERROR_MSG_PREFIX}The dest directory "{dest_dir}" is missing.')
                ret_code = 1
                continue

            for file in unexpected:
                print(f'{ERROR_MSG_PREFIX}The info file "{file}" was unexpected.')
                ret_code = 1

        return ret_code

    def check_unexpected_files(  # noqa: PLR0913
        self,
        srce_dirs_list: list[Path],
        dest_dirs_info_list: list[tuple[Path, Path]],
        allowed_zip_files: list[Path],
        allowed_zip_series_symlink_dirs: set[Path],
        allowed_zip_series_symlinks: list[Path],
        allowed_zip_year_symlink_dirs: set[Path],
        allowed_zip_year_symlinks: list[Path],
    ) -> int:
        allowed_main_dir_files = [
            THE_CHRONOLOGICAL_DIRS_DIR,
            THE_CHRONOLOGICAL_DIR,
            THE_YEARS_COMICS_DIR,
            *allowed_zip_series_symlink_dirs,
        ]

        # Each namespace to sweep, as (what to call it, where, what belongs there).
        sweeps: list[tuple[str, Path, Iterable[Path]]] = [
            ("main", BARKS_ROOT_DIR, srce_dirs_list),
            ("main", THE_COMICS_DIR, allowed_main_dir_files),
        ]

        if dest_dirs_info_list:
            allowed_dest_dirs = [dest_dir for _ini_file, dest_dir in dest_dirs_info_list]
            sweeps.append(("dest", allowed_dest_dirs[0].parent, allowed_dest_dirs))

        if allowed_zip_files:
            sweeps.append(("zip", allowed_zip_files[0].parent, allowed_zip_files))

        # Sorted: these dirs come from a set, so the report would otherwise jump between
        # series - and between years - at random.
        if allowed_zip_series_symlinks:
            sweeps.extend(
                ("series", symlink_dir, allowed_zip_series_symlinks)
                for symlink_dir in sorted(allowed_zip_series_symlink_dirs)
            )

        if allowed_zip_year_symlinks:
            year_parent_dir = next(iter(allowed_zip_year_symlink_dirs)).parent
            sweeps.append(("year dir", year_parent_dir, allowed_zip_year_symlink_dirs))
            sweeps.extend(
                ("year", symlink_dir, allowed_zip_year_symlinks)
                for symlink_dir in sorted(allowed_zip_year_symlink_dirs)
            )

        ret_code = self._check_dest_dir_info_files(dest_dirs_info_list)

        for label, directory, allowed in sweeps:
            if self.check_files_in_dir(label, directory, allowed) != 0:
                ret_code = 1

        if ret_code != 0:
            print()

        return ret_code

    @staticmethod
    def check_files_in_dir(file_type: str, dir_path: Path, allowed_files: Iterable[Path]) -> int:
        unexpected = unexpected_entries(dir_path, allowed_files)

        if unexpected is None:
            print(f'{ERROR_MSG_PREFIX}The directory "{dir_path}" is missing.')
            return 1

        for file in unexpected:
            print(f'{ERROR_MSG_PREFIX}The {file_type} directory file "{file}" was unexpected.')

        return 1 if unexpected else 0

    def check_zip_files(self, comic: ComicBook, errors: OutOfDateErrors) -> None:
        errors.zip_errors = check_zip_freshness(
            comic.get_dest_comic_zip(), errors.max_srce, errors.max_dest
        )

        if not self._check_symlinks:
            logger.info("Check symlinks flag turned off. Not checking.")
            return

        # Both symlinks are graded, even when the first is missing. This used to `return`
        # at the first missing one, so a missing series symlink hid the year symlink's
        # state entirely and two runs were needed to see both faults.
        errors.series_zip_symlink_errors = check_zip_symlink_freshness(
            comic.get_dest_series_comic_zip_symlink(), errors.zip_errors, errors.max_dest
        )
        errors.year_zip_symlink_errors = check_zip_symlink_freshness(
            comic.get_dest_year_comic_zip_symlink(), errors.zip_errors, errors.max_dest
        )

    @staticmethod
    def check_additional_files(comic: ComicBook, errors: OutOfDateErrors) -> None:
        dest_dir = comic.get_dest_dir()
        if not dest_dir.is_dir():
            errors.dest_dir_files_missing.append(dest_dir)
            return

        # Sorted: `DEST_NON_IMAGE_FILES` is a set, so the findings would otherwise come
        # out in a different order on every run.
        for file in sorted(DEST_NON_IMAGE_FILES):
            file_path = dest_dir / file
            if not file_path.is_file():
                errors.dest_dir_files_missing.append(file_path)
                continue
            if is_stale(get_timestamp(file_path), errors.max_srce):
                errors.dest_dir_files_out_of_date.append(file_path)

    def print_check_errors(self, errors: OutOfDateErrors) -> None:
        if errors.file_findings:
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

        if errors.zip_errors.out_of_date_wrt_srce and errors.max_srce is not None:
            print(
                f'{ERROR_MSG_PREFIX}For "{errors.title}", the zip file\n'
                f'{BLANK_ERR_MSG_PREFIX}"{errors.zip_errors.file}"\n'
                f"{BLANK_ERR_MSG_PREFIX}is out of date with the srce file"
                f' "{errors.max_srce.file}"\n'
                f"{BLANK_ERR_MSG_PREFIX}'{_as_str(errors.zip_errors.timestamp)}'"
                f" < '{_as_str(errors.max_srce.timestamp)}'.",
            )

        if errors.zip_errors.out_of_date_wrt_dest and errors.max_dest is not None:
            print(
                f'{ERROR_MSG_PREFIX}For "{errors.title}", the zip file\n'
                f'{BLANK_ERR_MSG_PREFIX}"{errors.zip_errors.file}"\n'
                f"{BLANK_ERR_MSG_PREFIX}is out of date with the max dest file timestamp:\n"
                f"{BLANK_ERR_MSG_PREFIX}'{_as_str(errors.zip_errors.timestamp)}'"
                f" < '{_as_str(errors.max_dest.timestamp)}'.",
            )

        self.print_symlink_findings(errors, "series", errors.series_zip_symlink_errors)
        self.print_symlink_findings(errors, "year", errors.year_zip_symlink_errors)

        if len(errors.unexpected_dest_image_files) > 0:
            print()
            self.print_unexpected_dest_image_files_errors(errors)

    @staticmethod
    def print_symlink_findings(
        errors: OutOfDateErrors,
        which: str,
        symlink_errors: ZipSymlinkOutOfDateErrors,
    ) -> None:
        """Report one zip symlink's staleness findings.

        Args:
            errors: The title's findings, for the title name and the dest maximum.
            which: "series" or "year", naming the symlink in the message.
            symlink_errors: That symlink's verdict.

        """
        if symlink_errors.out_of_date_wrt_zip:
            print(
                f'{ERROR_MSG_PREFIX}For "{errors.title}", the {which} symlink\n'
                f'{BLANK_ERR_MSG_PREFIX}"{symlink_errors.symlink}"\n'
                f"{BLANK_ERR_MSG_PREFIX}is out of date with the zip file\n"
                f'{BLANK_ERR_MSG_PREFIX}"{errors.zip_errors.file}":\n'
                f"{BLANK_ERR_MSG_PREFIX}'{_as_str(symlink_errors.timestamp)}'"
                f" < '{_as_str(errors.zip_errors.timestamp)}'.",
            )

        if symlink_errors.out_of_date_wrt_dest and errors.max_dest is not None:
            print(
                f'{ERROR_MSG_PREFIX}For "{errors.title}", the {which} symlink\n'
                f'{BLANK_ERR_MSG_PREFIX}"{symlink_errors.symlink}"\n'
                f"{BLANK_ERR_MSG_PREFIX}is out of date with the max dest file timestamp:\n"
                f"{BLANK_ERR_MSG_PREFIX}'{_as_str(symlink_errors.timestamp)}'"
                f" < '{_as_str(errors.max_dest.timestamp)}'.",
            )

    @staticmethod
    def print_unexpected_dest_image_files_errors(errors: OutOfDateErrors) -> None:
        for file in errors.unexpected_dest_image_files:
            print(f'{ERROR_MSG_PREFIX} The dest image file "{get_relpath(file)}" was unexpected.')

    @staticmethod
    def _print_dest_dir_findings(errors: OutOfDateErrors) -> None:
        """Report the title's info files: the missing ones, then the stale ones."""
        if errors.dest_dir_files_missing:
            for missing_file in errors.dest_dir_files_missing:
                print(f'{ERROR_MSG_PREFIX}The dest file "{missing_file}" is missing.')
            print()

        # `max_srce` is what makes a dest dir file out of date, so it is always set when
        # the list is non-empty. Narrowed rather than asserted: this used to be a bare
        # `assert` over an invariant held by two fields assigned 380 lines apart.
        if errors.dest_dir_files_out_of_date and errors.max_srce is not None:
            for out_of_date_file in errors.dest_dir_files_out_of_date:
                print(
                    get_file_out_of_date_wrt_max_timestamp_msg(
                        out_of_date_file,
                        errors.max_srce,
                        ERROR_MSG_PREFIX,
                    ),
                )
            print()

        if errors.exception_errors:
            for err_msg in errors.exception_errors:
                print(f'{ERROR_MSG_PREFIX} For "{errors.title}", there was an error: {err_msg}.')
            print()

    @staticmethod
    def _print_page_tally(errors: OutOfDateErrors) -> None:
        """Report one tally line naming whichever kinds of page finding occurred."""
        counted = [
            f"{len(findings)} {noun}"
            for findings, noun in (
                (errors.srce_and_dest_files_missing, "missing dest files"),
                (errors.srce_and_dest_files_out_of_date, "out of date dest files"),
            )
            if findings
        ]

        if counted:
            print(
                f'{ERROR_MSG_PREFIX} For "{errors.title}", there were {" and ".join(counted)}.\n',
            )

    @staticmethod
    def print_out_of_date_or_missing_errors(errors: OutOfDateErrors) -> None:
        for srce_file, dest_file in errors.srce_and_dest_files_missing:
            print(
                f'{ERROR_MSG_PREFIX} There is no dest file "{dest_file}"'
                f' matching srce file "{srce_file}".',
            )
        for srce_file, dest_file in errors.srce_and_dest_files_out_of_date:
            print(get_file_out_of_date_with_other_file_msg(dest_file, srce_file, ERROR_MSG_PREFIX))

        if errors.file_findings:
            print()

        ComicsIntegrityChecker._print_dest_dir_findings(errors)
        ComicsIntegrityChecker._print_page_tally(errors)
