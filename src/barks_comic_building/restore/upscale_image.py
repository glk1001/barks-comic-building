import subprocess
from collections import deque
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from barks_fantagraphics.comics_utils import get_clean_path
from barks_fantagraphics.fanta_comics_info import FANTAGRAPHICS_UPSCAYLED_FIXES_DIRNAME
from comic_utils.pil_image_utils import add_png_metadata
from loguru import logger
from PIL import Image

from barks_comic_building.restore.image_checks import (
    MAX_THUMBNAIL_DEVIATION,
    get_thumbnail_deviation,
)

Image.MAX_IMAGE_PIXELS = None


class Upscaler(StrEnum):
    """The upscaling backends that can be used to enlarge a page."""

    UPSCAYL = "upscayl"
    WAIFU2X = "waifu2x"


DEFAULT_UPSCALER = Upscaler.WAIFU2X

UpscalerArg = Annotated[Upscaler, typer.Option("--upscaler", help="Upscaling backend")]

OUTPUT_FORMAT = "png"
OUTPUT_EXTENSION = ".png"

# The png metadata keys the upscale writes its provenance into. The per-backend model keys
# are also how the backend is worked out for a page written before the "Upscaler" key
# existed, so they are named here rather than spelled out where they are written.
SRCE_FILE_KEY = "Srce file"
SCALE_KEY = "Scale"
UPSCALER_KEY = "Upscaler"
UPSCAYL_MODEL_KEY = "Upscayl model"
WAIFU2X_MODEL_KEY = "Waifu2x model"
WAIFU2X_NOISE_LEVEL_KEY = "Waifu2x noise level"

UPSCAYL_BIN = Path.home() / ".local/share/upscayl/bin/upscayl-bin"
UPSCAYL_MODELS_DIR = Path.home() / ".local/share/upscayl/models"
UPSCAYL_MODEL = "ultramix_balanced"
UPSCAYL_SCALES = (2, 3, 4)

# Upscayl's auto tile size ("0") is broken on Ubuntu 26.04: the Vulkan submit fails with
# VK_ERROR_DEVICE_LOST, after which Upscayl writes an all-black image and still exits 0. A
# custom tile size avoids it, the same as the "Custom Tile Size" setting in the Upscayl GUI.
# Tile sizes from 32 to 144 all work, 160 and above fail the same way as auto does. Running
# two Upscayl jobs over the same GPU at once also brings on the failure, whatever the tile
# size, so keep batch runs sequential. waifu2x is unaffected and needs no tile size.
UPSCAYL_TILE_SIZE = 100

WAIFU2X_DIR = Path.home() / ".local/share/waifu2x-ncnn-vulkan"
WAIFU2X_BIN = WAIFU2X_DIR / "waifu2x-ncnn-vulkan"
WAIFU2X_MODEL = "cunet"
WAIFU2X_MODELS_DIR = WAIFU2X_DIR / f"models-{WAIFU2X_MODEL}"
WAIFU2X_SCALES = (1, 2, 4, 8, 16, 32)

# Denoise level 1 measured best on flat restored art: it takes the JPEG ringing down a little
# while leaving the flat fills alone. Levels 2 and 3 denoise harder but start shifting the flat
# colours, which matters more than the ringing on this material.
WAIFU2X_NOISE_LEVEL = 1

# A broken run still exits 0 and writes a correctly sized PNG that is all black, or blacked out
# below the first few rows, so every result is compared against its source. The comparison and
# its threshold live in `image_checks`, which the restore uses too - both stages have the same
# failure and it is worth them having the same answer to it.

# Enough of a failing run's output to diagnose it, bounded so that a backend stuck in a
# loop cannot fill memory with its complaints.
_MAX_KEPT_OUTPUT_LINES = 40

# The tree whose contents were made by hand. Every other tree in the library can be
# rebuilt by re-running something; a page in this one cannot be got back at all. So
# nothing an upscaler produces may be written into it, whichever tool is asking.
#
# The plain fixes tree is deliberately absent: no upscale destination ever
# resolves there - the batch run's dest is the plain upscayled page or this tree - and
# both manual tools refuse an output path that already exists, so guarding it would
# only stop new files being made beside a fix, which destroys nothing.
HAND_EDITED_DIRNAMES = (FANTAGRAPHICS_UPSCAYLED_FIXES_DIRNAME,)


def _get_upscayl_run_args(in_file: Path, out_file: Path, scale: int) -> list[str]:
    return [
        str(UPSCAYL_BIN),
        "-i",
        str(in_file),
        "-o",
        str(out_file),
        "-s",
        str(scale),
        "-n",
        UPSCAYL_MODEL,
        "-f",
        OUTPUT_FORMAT,
        "-c",
        "0",
        "-t",
        str(UPSCAYL_TILE_SIZE),
        "-m",
        str(UPSCAYL_MODELS_DIR),
        "-v",
    ]


def _get_waifu2x_run_args(in_file: Path, out_file: Path, scale: int) -> list[str]:
    return [
        str(WAIFU2X_BIN),
        "-i",
        str(in_file),
        "-o",
        str(out_file),
        "-s",
        str(scale),
        "-n",
        str(WAIFU2X_NOISE_LEVEL),
        "-f",
        OUTPUT_FORMAT,
        "-m",
        str(WAIFU2X_MODELS_DIR),
        "-v",
    ]


def _get_run_args(upscaler: Upscaler, in_file: Path, out_file: Path, scale: int) -> list[str]:
    if upscaler == Upscaler.UPSCAYL:
        return _get_upscayl_run_args(in_file, out_file, scale)
    return _get_waifu2x_run_args(in_file, out_file, scale)


def _get_metadata(upscaler: Upscaler, in_file: Path, scale: int) -> dict[str, str]:
    # Deferred: upscale_recipe reads this module's constants, so importing it at module
    # level would be a cycle. Every path that writes an upscayled page comes through here,
    # which is what keeps a page made by the single-file tool from reading as stale.
    from barks_comic_building.restore.upscale_recipe import get_current_recipe  # noqa: PLC0415
    from barks_comic_building.restore.upscale_state import (  # noqa: PLC0415
        RECIPE_ID_KEY,
        RECIPE_KEY,
        UPSCALE_DATE_KEY,
    )

    metadata = {
        SRCE_FILE_KEY: f'"{get_clean_path(in_file)}"',
        SCALE_KEY: str(scale),
        UPSCALER_KEY: str(upscaler),
    }

    if upscaler == Upscaler.UPSCAYL:
        # Kept under its old key so the metadata of previously upscayled pages still lines up.
        metadata[UPSCAYL_MODEL_KEY] = UPSCAYL_MODEL
    else:
        metadata[WAIFU2X_MODEL_KEY] = WAIFU2X_MODEL
        metadata[WAIFU2X_NOISE_LEVEL_KEY] = str(WAIFU2X_NOISE_LEVEL)

    # The recipe travels with the page, expanded as well as hashed, so that what this page
    # was made with can be read off the file itself rather than having to be looked up
    # somewhere that might not have survived alongside it.
    recipe = get_current_recipe(upscaler, scale)
    metadata[RECIPE_ID_KEY] = recipe.recipe_id
    metadata[RECIPE_KEY] = recipe.as_json()
    metadata[UPSCALE_DATE_KEY] = datetime.now().astimezone().isoformat(timespec="seconds")

    return metadata


def check_upscaler_is_usable(upscaler: Upscaler, scale: int) -> None:
    """Check the backend can actually be run at this scale.

    A run-level precondition rather than a per-page one, so a batch can call it once
    up front: neither of these can be true for one page and false for the next, and
    finding out per page would mean thousands of identical failures instead of one.

    Args:
        upscaler: The backend to check.
        scale: The requested upscale factor.

    Raises:
        FileNotFoundError: If the backend's binary is not installed.
        ValueError: If the backend cannot handle the requested scale.

    """
    binary = UPSCAYL_BIN if upscaler == Upscaler.UPSCAYL else WAIFU2X_BIN
    if not binary.is_file():
        msg = f'Could not find the {upscaler} binary: "{binary}".'
        raise FileNotFoundError(msg)

    scales = UPSCAYL_SCALES if upscaler == Upscaler.UPSCAYL else WAIFU2X_SCALES
    if scale not in scales:
        msg = f"{upscaler} cannot scale by {scale} - it only handles {list(scales)}."
        raise ValueError(msg)


def _run_upscaler(upscaler: Upscaler, run_args: list[str]) -> None:
    """Run the backend, logging everything it says and keeping it in case it fails.

    Neither backend reports progress - they print a device banner on stderr at the start
    and one "done" line on stdout at the end, with the whole page in between. So the point
    of reading them is not to follow along, it is to have what they said when something
    goes wrong: which GPU was picked, and whatever the failure was.

    stderr is merged into stdout rather than given a pipe of its own, because reading two
    pipes from one thread deadlocks as soon as either fills. Lines go to the log at debug,
    since a device banner per page is not worth a log line per page at info, and are
    repeated in the error if the run fails.

    Args:
        upscaler: The backend being run, for the error message.
        run_args: Its full command line.

    Raises:
        RuntimeError: If the backend exits non-zero, carrying what it printed.

    """
    process = subprocess.Popen(  # noqa: S603
        run_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    output: deque[str] = deque(maxlen=_MAX_KEPT_OUTPUT_LINES)
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.strip()
        if line:
            output.append(line)
            logger.debug(line)

    # wait() rather than poll(): stdout reaching EOF does not mean the process has been
    # reaped yet, and poll() returning None there would read as a failure on a good run.
    return_code = process.wait()
    if return_code != 0:
        said = "\n".join(output)
        msg = f"{upscaler} failed (exit {return_code})."
        raise RuntimeError(f"{msg}\n{said}" if said else msg)


def _check_upscaled_output(upscaler: Upscaler, in_file: Path, out_file: Path, scale: int) -> None:
    with Image.open(in_file) as in_image:
        expected_width, expected_height = in_image.width * scale, in_image.height * scale
    with Image.open(out_file) as out_image:
        out_width, out_height = out_image.size

    if abs(out_width - expected_width) > 1 or abs(out_height - expected_height) > 1:
        msg = (
            f"{upscaler} wrote a {out_width}x{out_height} image"
            f" but {expected_width}x{expected_height} was expected."
        )
        raise RuntimeError(msg)

    deviation = get_thumbnail_deviation(in_file, out_file)
    if deviation > MAX_THUMBNAIL_DEVIATION:
        msg = (
            f"{upscaler} exited cleanly but its image does not match the source"
            f" (mean deviation {deviation:.1f} > {MAX_THUMBNAIL_DEVIATION}) - it is"
            f" probably black or truncated. Check that nothing else was using the GPU."
        )
        if upscaler == Upscaler.UPSCAYL:
            msg += f" Then try a smaller UPSCAYL_TILE_SIZE than {UPSCAYL_TILE_SIZE}."
        raise RuntimeError(msg)


def get_hand_edited_tree(out_file: Path) -> Path | None:
    """Return the hand-edited tree a path would be written into, if any.

    The resolved path is tested as well as the given one, since a page can be reached
    through a symlinked volume directory - the staged collections are built that way -
    and the name of the tree only appears once the links have been followed.

    Args:
        out_file: The path something is about to be written to.

    Returns:
        The hand-edited directory it lies under, or None.

    """
    for candidate in (out_file, out_file.parent.resolve() / out_file.name):
        for parent in candidate.parents:
            if parent.name in HAND_EDITED_DIRNAMES:
                return parent

    return None


def upscale_image_file(
    in_file: Path,
    out_file: Path,
    scale: int = 2,
    upscaler: Upscaler = DEFAULT_UPSCALER,
) -> None:
    """Enlarge an image by the given scale, using the given upscaling backend.

    Args:
        in_file: The image to enlarge.
        out_file: Where to write the enlarged png.
        scale: How much bigger the output should be than the input.
        upscaler: Which backend to run.

    Raises:
        FileNotFoundError: If the backend's binary is not installed.
        ValueError: If the backend cannot handle the requested scale, if the output
            path is a symlink, or if it lies in a hand-edited tree.
        RuntimeError: If the backend fails, carrying what it printed, or returns an
            image that does not match the source. The unusable output file is
            deleted first.

    """
    assert out_file.suffix == OUTPUT_EXTENSION

    # Collection titles carry pages that are symlinks to another volume's, and writing
    # to one of those paths follows the link: the other volume's page would be replaced
    # by an upscale of a different source image, and neither end would say so. Refused
    # here as well as in the page state, because there is no caller for whom it is right.
    if out_file.is_symlink():
        msg = (
            f'Refusing to upscale onto a symlink: "{out_file}"'
            f' points at "{out_file.resolve()}", which belongs to another volume.'
        )
        raise ValueError(msg)

    # Likewise refused here as well as in the page state. A hand-edited page is the one
    # thing in the library that no re-run can reproduce, so the writer refuses the whole
    # tree outright rather than trusting every caller to have worked out that this
    # particular path is one.
    hand_edited_tree = get_hand_edited_tree(out_file)
    if hand_edited_tree is not None:
        msg = (
            f'Refusing to upscale into the hand-edited tree "{hand_edited_tree.name}":'
            f' "{out_file}". Those pages were made by hand and cannot be remade.'
        )
        raise ValueError(msg)

    check_upscaler_is_usable(upscaler, scale)

    _run_upscaler(upscaler, _get_run_args(upscaler, in_file, out_file, scale))

    try:
        _check_upscaled_output(upscaler, in_file, out_file, scale)
    except RuntimeError:
        # Leaving a corrupt file behind would make the batch runs skip it from then on.
        out_file.unlink(missing_ok=True)
        raise

    add_png_metadata(out_file, _get_metadata(upscaler, in_file, scale))
