import concurrent.futures
import sys
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import typer
from barks_fantagraphics.barks_titles import ENUM_TO_STR_TITLE, STR_TITLE_TO_ENUM, Titles
from barks_fantagraphics.comic_book import ModifiedType, get_page_str
from barks_fantagraphics.comic_book_info import (
    get_located_one_pagers,
    get_one_pager_fanta_vol_and_page,
)
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_utils import get_abbrev_path
from comic_utils.comic_consts import (
    JPG_FILE_EXT,
    JSON_FILE_EXT,
    OVERALL_BOUNDS_ONLY_SUFFIX,
    PNG_FILE_EXT,
)
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from comic_utils.panel_bounding_box_processor import BoundingBoxProcessor
from comic_utils.panel_segmentation import (
    get_panel_segments_finding_msg,
    validate_panel_segments,
)
from intspan import ParseError, intspan
from loguru import logger

from barks_comic_building.cli_setup import get_comic_titles, init_logging
from barks_comic_building.log_setup import bind_run_id
from barks_comic_building.restore.ledger_common import new_run_id, now

APP_LOGGING_NAME = "bpan"


class PageBoundsOutcome(StrEnum):
    """What happened to one page."""

    SKIPPED = "skipped"  # Already bounded, or linked from another volume.
    OK = "ok"
    SAVED_WITH_FAULTS = "saved_with_faults"  # Written, but the validator objected.
    FAILED = "failed"  # An exception; nothing written.

    @property
    def is_error(self) -> bool:
        return self in (PageBoundsOutcome.SAVED_WITH_FAULTS, PageBoundsOutcome.FAILED)


COMIC_BUILDING_DIR = Path(__file__).parent.parent.parent.parent


@dataclass(frozen=True)
class _TitlePages:
    """One title's work: the volume it sits in, and the page files to bound.

    The volume rather than the `ComicBook` it came from. The comic was only ever asked
    for its fixes image dir, which is `get_fantagraphics_fixes_volume_image_dir` for the
    same volume - so carrying the number instead lets a one-pager, which has no `.ini`
    for `get_comic_book` to open, be just another job here.
    """

    title: str
    volume: int
    page_pairs: list[tuple[Path, Path]]


def parse_fanta_pages(fanta_pages_str: str) -> set[str] | None:
    """Turn the `--fanta-page` argument into the set of page numbers to process.

    Args:
        fanta_pages_str: An `intspan` list of Fanta volume pages - single pages, inclusive
            ranges, or a mix ("202,205,210-214"). Page numbers are zero-padded to match
            the page filenames, so "5" and "005" are the same page. An empty string means
            every page.

    Returns:
        The page numbers to keep, or `None` if every page is wanted.

    Raises:
        typer.BadParameter: The list is not a page list `intspan` accepts, or it names a
            page that cannot exist.

    """
    if not fanta_pages_str.strip():
        return None

    try:
        page_nums = list(intspan(fanta_pages_str))
    except ParseError as parse_error:
        msg = f'Not a page list in --fanta-page: "{fanta_pages_str}" - {parse_error}.'
        raise typer.BadParameter(msg) from parse_error

    # intspan is happy with zero and with negatives ("-202" is the page number -202, not a
    # half-written range), and neither is a page.
    if any(page_num < 1 for page_num in page_nums):
        msg = f'Not a page number in --fanta-page: "{fanta_pages_str}".'
        raise typer.BadParameter(msg)

    return {get_page_str(page_num) for page_num in page_nums}


def _get_page_pairs(
    srce_files: list[tuple[Path, ModifiedType]],
    dest_files: list[Path],
    fanta_pages: set[str] | None,
) -> list[tuple[Path, Path]]:
    """Pair each source page with its panel segments file, keeping the wanted pages only.

    The page number is read off the segments file rather than the source: the source may
    be any of the restored, upscayled or fixes files, but the segments file is always the
    Fanta page number.
    """
    page_pairs = [
        (srce_file, dest_file)
        for (srce_file, _), dest_file in zip(srce_files, dest_files, strict=True)
    ]
    if fanta_pages is None:
        return page_pairs

    return [
        (srce_file, dest_file)
        for srce_file, dest_file in page_pairs
        if dest_file.stem in fanta_pages
    ]


def one_pager_for_title(title_str: str) -> Titles | None:
    """Return the located one-pager `title_str` names, or None if it names something else.

    A one-pager has no `.ini` of its own - it is a member of the `All One-Pagers`
    collection - so it is absent from the volume title lists `get_comic_titles` builds,
    and `--title` on one fails before reaching any of the work here.

    Args:
        title_str: The `--title` argument.

    Returns:
        The one-pager, or None for an ordinary title, an empty argument, or a one-pager
        whose location is still a placeholder.

    """
    title = STR_TITLE_TO_ENUM.get(title_str)
    if title is None:
        return None

    volume, _page = get_one_pager_fanta_vol_and_page(title)

    return title if volume is not None else None


def one_pagers_on_pages(volumes: list[int], fanta_pages: set[str] | None) -> list[Titles]:
    """Return the located one-pagers of `volumes` whose page was asked for by number.

    Only the pages `--fanta-page` names, never a bare volume run. A one-pager is a page
    of its volume and could defensibly be bounded by one, but a volume's one-pagers are
    already bounded, and sweeping nine of them into a `--force` run nobody asked for is
    the kind of surprise this tool should not spring.

    Args:
        volumes: The volumes `--volume` chose.
        fanta_pages: The pages `--fanta-page` named, or None for every page.

    Returns:
        The one-pagers to bound alongside the volumes' ordinary titles.

    """
    if not volumes or fanta_pages is None:
        return []

    wanted = []
    for title in get_located_one_pagers():
        volume, page = get_one_pager_fanta_vol_and_page(title)
        if volume in volumes and page is not None and get_page_str(page) in fanta_pages:
            wanted.append(title)

    return wanted


def one_pager_job(comics_database: ComicsDatabase, title: Titles) -> _TitlePages | None:
    """Return the bounding job for a one-pager's single page, in the volume it lives in.

    Its own volume, not the collection: the collection's copies are symlinks back to here
    (or, where the volume never restored the page, files the collection owns outright),
    and `get_page_panel_bounds` refuses a linked page precisely so that bounds are made
    against the volume's own `bounded/` override. This is the run that refusal points at,
    and until now there was no way to reach it.

    Args:
        comics_database: The database supplying the volume directory paths.
        title: The located one-pager to bound.

    Returns:
        The job, or None when the page has no restored file to bound - the state of the
        one-pagers whose volume never restored them, which live only in the collection.

    """
    volume, page = get_one_pager_fanta_vol_and_page(title)
    if volume is None or page is None:
        return None

    page_str = get_page_str(page)
    srce_file = comics_database.get_fantagraphics_restored_volume_image_dir(volume) / (
        page_str + PNG_FILE_EXT
    )
    dest_file = comics_database.get_fantagraphics_panel_segments_volume_dir(volume) / (
        page_str + JSON_FILE_EXT
    )

    # The same rule `ComicBook.get_final_srce_story_file` applies to every other page of
    # an ordinary volume: the restored png, or nothing worth bounding.
    if not srce_file.is_file():
        logger.warning(
            f'"{ENUM_TO_STR_TITLE[title]}" is volume {volume} page {page_str}, but it has'
            f' no restored file "{get_abbrev_path(srce_file)}" to bound. Restore it first,'
            f" or bound it in the collection if that is where it was restored."
        )
        return None

    return _TitlePages(ENUM_TO_STR_TITLE[title], volume, [(srce_file, dest_file)])


def _get_titles_to_process(
    comics_database: ComicsDatabase,
    title_list: list[str],
    fanta_pages: set[str] | None,
) -> list[_TitlePages]:
    """Work out which pages of which titles to bound, before any of them are processed.

    Titles left with no wanted page are dropped. A one-pager in the list is built from
    its location rather than from a `ComicBook`, which it has no `.ini` for.

    Raises:
        typer.BadParameter: A requested page is in none of the titles - a mistyped page
            number is worth saying so up front, rather than after a long run has bounded
            the pages that did match.

    """
    titles_to_process: list[_TitlePages] = []
    matched_pages: set[str] = set()

    for title in title_list:
        one_pager = one_pager_for_title(title)
        if one_pager is not None:
            # A one-pager with no restored file is dropped like any title with no wanted
            # page, but its page still counts as found: "not in the selected titles" would
            # send someone hunting for a typo in a page number that is exactly right.
            _volume, page = get_one_pager_fanta_vol_and_page(one_pager)
            if page is not None:
                matched_pages.add(get_page_str(page))
            job = one_pager_job(comics_database, one_pager)
            if job is not None:
                titles_to_process.append(job)
            continue

        comic = comics_database.get_comic_book(title)
        page_pairs = _get_page_pairs(
            comic.get_final_srce_story_files(RESTORABLE_PAGE_TYPES),
            comic.get_srce_panel_segments_files(RESTORABLE_PAGE_TYPES),
            fanta_pages,
        )
        matched_pages.update(dest_file.stem for _, dest_file in page_pairs)
        if page_pairs:
            titles_to_process.append(
                _TitlePages(title, comics_database.get_fanta_volume_int(title), page_pairs)
            )

    if fanta_pages is not None and (unmatched := fanta_pages - matched_pages):
        msg = f"Fanta pages not found in the selected titles: {', '.join(sorted(unmatched))}."
        raise typer.BadParameter(msg)

    return titles_to_process


def panel_bounds(
    comics_database: ComicsDatabase,
    title_list: list[str],
    work_dir: Path,
    *,
    force: bool,
    fanta_pages: set[str] | None = None,
) -> int:
    """Make the panel bounds file for every restorable page of each title.

    Args:
        comics_database: The comics database.
        title_list: The titles to process.
        work_dir: Where Kumiko's intermediate files go.
        force: Remake panel bounds files that already exist.
        fanta_pages: Process these Fanta volume pages only; `None` means every page.

    Returns:
        The number of pages that had errors - failed outright, or saved with faults.

    """
    start = time.time()

    titles_to_process = _get_titles_to_process(comics_database, title_list, fanta_pages)

    # Every error line from here on, including those from the forked page workers,
    # carries this run id, so one run's errors can be told apart from the next in the
    # never-rotated errors file.
    bind_run_id(new_run_id(now()))

    num_page_files = 0
    error_pages: list[tuple[Path, PageBoundsOutcome]] = []
    for title_pages in titles_to_process:
        title = title_pages.title
        page_pairs = title_pages.page_pairs
        pages_desc = "all pages" if fanta_pages is None else f"{len(page_pairs)} selected pages"
        logger.info(f'Getting panel bounds for {pages_desc} in "{title}"...')

        title_work_dir = work_dir / title
        title_work_dir.mkdir(parents=True, exist_ok=True)

        title_vol_dir = comics_database.get_fantagraphics_panel_segments_volume_dir(
            title_pages.volume
        )
        title_vol_dir.mkdir(parents=True, exist_ok=True)

        bounding_box_processor = BoundingBoxProcessor(title_work_dir, COMIC_BUILDING_DIR)

        fixes_image_dir = comics_database.get_fantagraphics_fixes_volume_image_dir(
            title_pages.volume
        )
        if not fixes_image_dir.is_dir():
            msg = f'Could not find panel bounds directory "{fixes_image_dir}".'
            raise FileNotFoundError(msg)
        # TODO(glk): Put this in barks_fantagraphics
        srce_panels_bounds_override_dir = fixes_image_dir / "bounded"

        with concurrent.futures.ProcessPoolExecutor() as executor:
            futures = {
                executor.submit(
                    get_page_panel_bounds,
                    bounding_box_processor,
                    srce_panels_bounds_override_dir,
                    srce_file,
                    dest_file,
                    force=force,
                ): dest_file
                for srce_file, dest_file in page_pairs
            }
            for future, dest_file in futures.items():
                outcome = future.result()
                if outcome.is_error:
                    error_pages.append((dest_file, outcome))

        num_page_files += len(page_pairs)

    logger.info(f"\nTime taken to process all {num_page_files} files: {int(time.time() - start)}s.")

    _log_run_summary(num_page_files, error_pages)

    return len(error_pages)


def _log_run_summary(num_pages: int, error_pages: list[tuple[Path, PageBoundsOutcome]]) -> None:
    """Say at the end how many pages went wrong, and which - one line per page.

    The per-page errors are logged as they happen, from worker processes, so they land in
    the errors file interleaved with other pages'. This summary is the one place the
    run's failures are listed together.
    """
    if not error_pages:
        logger.success(f"All {num_pages} pages bounded without errors.")
        return

    logger.error(f"{len(error_pages)} of {num_pages} pages had errors:")
    for dest_file, outcome in sorted(error_pages):
        logger.error(f'    {outcome}: "{get_abbrev_path(dest_file)}"')


def get_page_panel_bounds(
    bounding_box_processor: BoundingBoxProcessor,
    srce_panels_bounds_override_dir: Path,
    srce_file: Path,
    dest_file: Path,
    *,
    force: bool,
) -> PageBoundsOutcome:
    """Make one page's panel bounds file.

    Args:
        bounding_box_processor: The Kumiko wrapper.
        srce_panels_bounds_override_dir: Where hand-drawn panel bounds fixes live.
        srce_file: The page to find panels in.
        dest_file: Where to write the panel segments.
        force: Remake the panel bounds file if it already exists.

    Returns:
        What happened. Never raises: an exception is logged and reported as `FAILED`.

    """
    # noinspection PyBroadException
    try:
        # Before anything else, and deliberately ahead of the force check: a symlink on
        # either side means this page belongs to another volume, staged into a synthetic
        # collection. Writing it here would compute the bounds against *this* comic's
        # `bounded/` directory, keyed by the collection page number, so the page's real
        # hand-drawn override is not found and is silently dropped. `barks-batch-restore`
        # and `barks-batch-upscayl` refuse the same way (`PageState.LINKED`); this one
        # used to write through.
        #
        # Both sides are checked because they are linked at different times. Staging only
        # links an artifact that already exists, so a home volume that has not been
        # panel-bounded yet leaves no segments link to catch - and that is precisely the
        # window in which someone reaches for this command. The write then lands in the
        # collection's own tree rather than through the link, which is quieter still: it
        # survives until the next staging run replaces it, and every collection build in
        # between bakes in bounds made without the override. The source scan is linked
        # from the start (the restored png, or the fixes jpg it falls back to), so it is
        # the signal that survives that window.
        if srce_file.is_symlink() or dest_file.is_symlink():
            linked_file = srce_file if srce_file.is_symlink() else dest_file
            logger.info(
                f"Page is linked from another volume - skipping:"
                f' "{get_abbrev_path(linked_file)}".'
                f" Run the panel bounds for the volume it lives in instead."
            )
            return PageBoundsOutcome.SKIPPED

        if not srce_file.is_file():
            msg = f'Could not find srce file: "{srce_file}".'
            raise FileNotFoundError(msg)  # noqa: TRY301
        if dest_file.is_file():
            if not force:
                logger.warning(f'Dest file exists - skipping: "{get_abbrev_path(dest_file)}".')
                return PageBoundsOutcome.SKIPPED
            logger.info(f'Dest file exists - remaking: "{get_abbrev_path(dest_file)}".')

        logger.info(
            f'Using Kumiko to get page panel bounds for "{get_abbrev_path(srce_file)}"'
            f' - saving to dest file "{get_abbrev_path(dest_file)}".'
        )

        segment_info = bounding_box_processor.get_panels_segment_info_from_kumiko(
            srce_file,
            srce_panels_bounds_override_dir,
        )

        has_faults = _log_segment_faults(segment_info, srce_panels_bounds_override_dir, srce_file)

        bounding_box_processor.save_panels_segment_info(dest_file, segment_info)

    except Exception:  # noqa: BLE001
        logger.exception(f'Error getting panel bounds for "{get_abbrev_path(srce_file)}": ')
        return PageBoundsOutcome.FAILED

    return PageBoundsOutcome.SAVED_WITH_FAULTS if has_faults else PageBoundsOutcome.OK


def _log_segment_faults(
    segment_info: dict[str, Any],
    srce_panels_bounds_override_dir: Path,
    srce_file: Path,
) -> bool:
    """Log every validation fault in the fresh segments; return whether there were any.

    The file is saved regardless. The integrity checker is the gate; saving keeps the
    batch moving and leaves the faulty file where `barks-check-build` will report it with
    the same messages.
    """
    overall_bounds_override = srce_panels_bounds_override_dir / (
        srce_file.stem + OVERALL_BOUNDS_ONLY_SUFFIX + JPG_FILE_EXT
    )
    findings = validate_panel_segments(
        segment_info,
        has_overall_bounds_override=overall_bounds_override.is_file(),
        panel_order_override=BoundingBoxProcessor.get_panel_order_override(
            srce_panels_bounds_override_dir, srce_file
        ),
    )
    if not findings:
        return False

    for finding in findings:
        logger.error(
            f'Panel segments fault for "{get_abbrev_path(srce_file)}":'
            f" {get_panel_segments_finding_msg(finding)}"
        )
    logger.error(
        f'Saving the panel segments for "{get_abbrev_path(srce_file)}" anyway'
        f' - fix the panels with a "bounded" override and re-run.'
    )
    return True


app = typer.Typer()


@app.command(help="Make panel bounds files")
def main(  # noqa: PLR0913
    work_dir: Path = typer.Option(...),  # noqa: B008
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    fanta_pages_str: str = typer.Option(
        "",
        "--fanta-page",
        "-p",
        help='Fanta volume pages to process, e.g. "202,205,210-214". Filters whichever'
        " titles --volume or --title chose. Default: every restorable page.",
    ),
    force: bool = typer.Option(
        default=False,
        help="Make panel bounds files even when they already exist, overwriting them.",
    ),
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "batch-panel-bounds.log", log_level_str)

    fanta_pages = parse_fanta_pages(fanta_pages_str)

    # Checked only when `--volume` was not given, so that passing both still falls through
    # to `get_comic_titles` and its "mutually exclusive" message.
    one_pager = None if volumes_str else one_pager_for_title(title_str)
    if one_pager is not None:
        comics_database, titles = ComicsDatabase(), [ENUM_TO_STR_TITLE[one_pager]]
    else:
        comics_database, titles = get_comic_titles(volumes_str, title_str)
        titles += [
            ENUM_TO_STR_TITLE[title]
            for title in one_pagers_on_pages(list(intspan(volumes_str)), fanta_pages)
        ]

    work_dir.mkdir(parents=True, exist_ok=True)

    num_error_pages = panel_bounds(
        comics_database, titles, work_dir, force=force, fanta_pages=fanta_pages
    )
    if num_error_pages:
        sys.exit(1)


if __name__ == "__main__":
    app()
