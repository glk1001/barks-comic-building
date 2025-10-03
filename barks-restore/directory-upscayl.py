# ruff: noqa: T201

import sys
from pathlib import Path

from src.upscale_image import upscale_image_file

APP_LOGGING_NAME = "dups"

if __name__ == "__main__":
    scale = 4

    input_image_dir = Path(sys.argv[1])
    output_image_dir = Path(sys.argv[2])

    if not input_image_dir.is_dir():
        print(f'ERROR: Can\'t find input directory: "{input_image_dir}".')
        sys.exit(1)
    if not output_image_dir.is_dir():
        print(f'WARN: Created new output directory: "{output_image_dir}".')
        output_image_dir.mkdir(parents=True, exist_ok=True)

    for in_filename in input_image_dir.iterdir():
        in_file = input_image_dir / in_filename
        if not in_file.is_file():
            continue

        out_file = output_image_dir / in_filename
        if out_file.is_file():
            print(f'WARN: Target file exists - skipping: "{out_file}".')
            continue

        upscale_image_file(in_file, out_file, scale)
