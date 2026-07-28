"""Survey the ink and paper colours the Fantagraphics volumes were produced with.

The library was not made in one run: some volumes carry their ink as a dark grey around
(35, 29, 29), which is what 100% K comes out as through a CMYK conversion, and others have
had it forced to pure black. A few volumes hold pages of both kinds. Anything that keys off
the exact ink colour therefore has to work it out per page - this survey is how to see what
is actually there.
"""

import time
from collections import Counter
from pathlib import Path

import cv2 as cv
import numpy as np
import typer
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.fanta_comics_info import FIRST_VOLUME_NUMBER, LAST_VOLUME_NUMBER
from comic_utils.common_typer_options import LogLevelArg, VolumesArg
from intspan import intspan
from loguru import logger

from barks_comic_building.cli_setup import init_logging
from barks_comic_building.restore.palette_snap import get_flat_palette

APP_LOGGING_NAME = "inks"

DEFAULT_PAGES_PER_VOLUME = 5

INK_MAX_LUMINANCE = 110
PAPER_MIN_LUMINANCE = 200

# Pages outside this ink coverage are covers, title pages or near blank ones, and their
# palettes say nothing about how the comic art was produced.
MIN_INK_COVERAGE = 0.05
MAX_INK_COVERAGE = 0.35

_BGR_LUMINANCE_WEIGHTS = np.array([0.114, 0.587, 0.299])


def get_page_ink_and_paper(image_file: Path) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    """Work out a page's ink and paper colours from its flat areas.

    Args:
        image_file: The page image to examine.

    Returns:
        The ink and paper colours as RGB tuples, or None if the page is not comic art
        or has no usable palette.

    """
    image = cv.imread(str(image_file))
    if image is None:
        logger.warning(f'Could not read image file: "{image_file}".')
        return None

    grey = cv.cvtColor(image, cv.COLOR_BGR2GRAY)
    ink_coverage = float((grey < INK_MAX_LUMINANCE).mean())
    if not MIN_INK_COVERAGE <= ink_coverage <= MAX_INK_COVERAGE:
        logger.debug(f'Not comic art (ink coverage {ink_coverage:.1%}) - skipping: "{image_file}".')
        return None

    palette = get_flat_palette(image)
    if len(palette) == 0:
        return None

    luminance = palette @ _BGR_LUMINANCE_WEIGHTS
    inks = palette[luminance < INK_MAX_LUMINANCE]
    papers = palette[luminance > PAPER_MIN_LUMINANCE]
    if len(inks) == 0 or len(papers) == 0:
        return None

    ink = inks[np.argmin(luminance[luminance < INK_MAX_LUMINANCE])]
    paper = papers[np.argmax(luminance[luminance > PAPER_MIN_LUMINANCE])]

    return tuple(int(v) for v in ink[::-1]), tuple(int(v) for v in paper[::-1])


def get_sample_pages(image_dir: Path, pages_per_volume: int) -> list[Path]:
    """Pick pages spread through a volume, avoiding the covers at either end."""
    images = sorted(p for p in image_dir.iterdir() if p.suffix.lower() in {".jpg", ".png"})
    if not images:
        return []

    step = max(1, len(images) // (pages_per_volume + 2))
    return images[step : len(images) - step : step][:pages_per_volume]


def survey_volume(
    comics_database: ComicsDatabase, volume: int, pages_per_volume: int
) -> tuple[Counter, Counter]:
    """Collect the ink and paper colours found across a volume's sampled pages."""
    image_dir = comics_database.get_fantagraphics_volume_image_dir(volume)
    if not image_dir.is_dir():
        logger.warning(f'Volume {volume} image dir not found - skipping: "{image_dir}".')
        return Counter(), Counter()

    inks: Counter = Counter()
    papers: Counter = Counter()
    for page in get_sample_pages(image_dir, pages_per_volume):
        found = get_page_ink_and_paper(page)
        if found is None:
            continue
        inks[found[0]] += 1
        papers[found[1]] += 1

    return inks, papers


def survey_volumes(
    comics_database: ComicsDatabase, volumes: list[int], pages_per_volume: int
) -> None:
    """Report the ink and paper colours for each volume, then for the library."""
    start = time.time()

    all_inks: Counter = Counter()
    all_papers: Counter = Counter()
    num_pages = 0

    for volume in volumes:
        inks, papers = survey_volume(comics_database, volume, pages_per_volume)
        if not inks:
            logger.warning(f"Volume {volume}: no comic art pages sampled.")
            continue

        num_pages += sum(inks.values())
        all_inks.update(inks)
        all_papers.update(papers)

        ink, ink_count = inks.most_common(1)[0]
        paper = papers.most_common(1)[0][0]
        summary = f"Volume {volume:2d}: ink {ink!s:16s} paper {paper!s:16s}"
        if len(inks) == 1:
            logger.info(f"{summary} ({ink_count} pages, consistent)")
        else:
            others = ", ".join(f"{c}x{k}" for k, c in inks.most_common()[1:])
            logger.warning(f"{summary} ({ink_count}/{sum(inks.values())} pages; also {others})")

    logger.info(f"\nInk colours over all {num_pages} sampled pages:")
    for ink, count in all_inks.most_common():
        logger.info(f"  {ink!s:18s} {count:4d} pages  {100 * count / max(num_pages, 1):5.1f}%")

    logger.info("Paper colours:")
    for paper, count in all_papers.most_common(5):
        logger.info(f"  {paper!s:18s} {count:4d} pages  {100 * count / max(num_pages, 1):5.1f}%")

    if len(all_inks) > 1:
        logger.warning(
            f"\n{len(all_inks)} different ink colours found - derive the ink per page"
            f" rather than assuming one for the library or for a volume."
        )

    logger.info(f"\nTime taken to survey {num_pages} pages: {int(time.time() - start)}s.")


app = typer.Typer()


@app.command(help="Survey the ink and paper colours used across Fantagraphics volumes")
def main(
    volumes_str: VolumesArg = "",
    pages: int = DEFAULT_PAGES_PER_VOLUME,
    log_level_str: LogLevelArg = "INFO",
) -> None:
    init_logging(APP_LOGGING_NAME, "ink-survey.log", log_level_str)

    volumes = (
        list(intspan(volumes_str))
        if volumes_str
        else list(range(FIRST_VOLUME_NUMBER, LAST_VOLUME_NUMBER + 1))
    )
    comics_database = ComicsDatabase()

    survey_volumes(comics_database, volumes, pages)


if __name__ == "__main__":
    app()
