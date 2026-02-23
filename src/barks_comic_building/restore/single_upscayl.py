# ruff: noqa: T201

import sys
from pathlib import Path

import typer

from barks_comic_building.restore.upscale_image import upscale_image_file

app = typer.Typer()


@app.command(help="Make single upscayled file")
def main(input_file: Path, scale: int = 4) -> None:
    assert 2 <= scale <= 12  # noqa: PLR2004

    input_image_dir = input_file.parent
    input_image_stem = input_file.stem
    output_upscayl_file = input_image_dir / f"{input_image_stem}-upscayl-x{scale}.png"

    if output_upscayl_file.is_file():
        print(f'ERROR: Can\'t overwrite target file: "{output_upscayl_file}".')
        sys.exit(1)

    upscale_image_file(input_file, output_upscayl_file, scale)


if __name__ == "__main__":
    app()
