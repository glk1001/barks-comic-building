# ruff: noqa: T201

import sys
from pathlib import Path

import typer

from barks_comic_building.restore.upscale_image import upscale_image_file

APP_LOGGING_NAME = "dups"

app = typer.Typer()


@app.command(help="Upscayl a directory of images")
def main(input_dir: Path, output_dir: Path) -> None:
    scale = 4

    if not input_dir.is_dir():
        print(f'ERROR: Can\'t find input directory: "{input_dir}".')
        sys.exit(1)
    if not output_dir.is_dir():
        print(f'WARN: Created new output directory: "{output_dir}".')
        output_dir.mkdir(parents=True, exist_ok=True)

    for in_filename in input_dir.iterdir():
        in_file = input_dir / in_filename
        if not in_file.is_file():
            print(f'WARN: Skipping non-file: "{in_file}".')
            continue

        out_file = output_dir / in_filename
        if out_file.is_file():
            print(f'WARN: Target file exists - skipping: "{out_file}".')
            continue

        upscale_image_file(in_file, out_file, scale)


if __name__ == "__main__":
    app()
