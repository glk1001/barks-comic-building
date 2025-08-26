# ruff: noqa: T201

import os
import sys

from src.upscale_image import upscale_image_file

APP_LOGGING_NAME = "dups"

if __name__ == "__main__":
    scale = 4

    input_image_dir = sys.argv[1]
    output_image_dir = sys.argv[2]

    if not os.path.isdir(input_image_dir):
        print(f'ERROR: Can\'t find input directory: "{input_image_dir}".')
        sys.exit(1)
    if not os.path.isdir(output_image_dir):
        print(f'WARN: Created new output directory: "{output_image_dir}".')
        os.makedirs(output_image_dir)

    for in_filename in os.listdir(input_image_dir):
        in_file = os.path.join(input_image_dir, in_filename)
        if not os.path.isfile(in_file):
            continue

        out_file = os.path.join(output_image_dir, in_filename)
        if os.path.exists(out_file):
            print(f'WARN: Target file exists - skipping: "{out_file}".')
            continue

        upscale_image_file(in_file, out_file, scale)
