# ruff: noqa: T201

import sys
from pathlib import Path

import typer

from barks_comic_building.restore.upscale_image import (
    DEFAULT_UPSCALER,
    LIBRARY_SCALE,
    OUTPUT_EXTENSION,
    Upscaler,
    UpscalerArg,
    check_upscaler_is_usable,
    upscale_image_file,
)

APP_LOGGING_NAME = "dups"

app = typer.Typer()


def upscale_directory(input_dir: Path, output_dir: Path, scale: int, upscaler: Upscaler) -> int:
    """Upscale every file in a directory, carrying on past the ones that fail.

    The output is always a png, named after the input's stem. It used to keep the input's
    whole name, which the upscale refuses for anything but a png, so the first jpg in the
    directory ended the run with a traceback and nothing upscaled.

    One bad file is reported and passed over rather than ending the run: a directory is
    usually handed over to be left alone with, and finding it abandoned at the third file
    because of a scan that would not decode wastes the whole wait.

    Args:
        input_dir: The directory of images to upscale.
        output_dir: Where the upscaled pngs go.
        scale: How much bigger each output should be than its input.
        upscaler: Which backend to run.

    Returns:
        How many files could not be upscaled.

    """
    num_failed = 0

    # In name order, so that which of two inputs sharing a stem gets upscaled does not
    # depend on the order the filesystem happens to list them in.
    for in_file in sorted(input_dir.iterdir()):
        if not in_file.is_file():
            print(f'WARN: Skipping non-file: "{in_file}".')
            continue

        out_file = output_dir / f"{in_file.stem}{OUTPUT_EXTENSION}"
        if out_file.is_file():
            print(f'WARN: Target file exists - skipping "{in_file.name}": "{out_file}".')
            continue

        try:
            upscale_image_file(in_file, out_file, scale, upscaler)
        except (OSError, RuntimeError, ValueError) as e:
            num_failed += 1
            print(f'ERROR: Could not upscale "{in_file}": {e}')

    return num_failed


@app.command(help="Upscayl a directory of images")
def main(input_dir: Path, output_dir: Path, upscaler: UpscalerArg = DEFAULT_UPSCALER) -> None:
    if not input_dir.is_dir():
        print(f'ERROR: Can\'t find input directory: "{input_dir}".')
        sys.exit(1)

    # True of every file or none, so found out once here rather than once per file.
    try:
        check_upscaler_is_usable(upscaler, LIBRARY_SCALE)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    if not output_dir.is_dir():
        print(f'WARN: Created new output directory: "{output_dir}".')
        output_dir.mkdir(parents=True, exist_ok=True)

    num_failed = upscale_directory(input_dir, output_dir, LIBRARY_SCALE, upscaler)
    if num_failed:
        print(f"ERROR: {num_failed} file(s) could not be upscaled.")
        sys.exit(1)


if __name__ == "__main__":
    app()
