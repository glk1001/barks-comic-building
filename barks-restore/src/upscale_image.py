import subprocess
from pathlib import Path

from barks_fantagraphics.comics_utils import get_clean_path
from comic_utils.pil_image_utils import add_png_metadata
from loguru import logger

UPSCAYL_BIN = Path.home() / ".local/share/upscayl/bin/upscayl-bin"
UPSCAYL_MODELS_DIR = Path.home() / ".local/share/upscayl/models"
UPSCAYL_MODEL = "ultramix_balanced"
UPSCAYL_OUTPUT_FORMAT = "png"
UPSCAYL_OUTPUT_EXTENSION = ".png"


def upscale_image_file(in_file: Path, out_file: Path, scale: int = 2) -> None:
    assert out_file.suffix == UPSCAYL_OUTPUT_EXTENSION

    run_args = [
        UPSCAYL_BIN,
        "-i",
        str(in_file),
        "-o",
        str(out_file),
        "-s",
        str(scale),
        "-n",
        UPSCAYL_MODEL,
        "-f",
        UPSCAYL_OUTPUT_FORMAT,
        "-c",
        "0",
        "-m",
        str(UPSCAYL_MODELS_DIR),
        "-v",
    ]

    process = subprocess.Popen(run_args, stdout=subprocess.PIPE, text=True)

    while True:
        output = process.stdout.readline()
        if output == "" and process.poll() is not None:
            break
        if output:
            logger.info(output.strip())

    rc = process.poll()
    if rc != 0:
        raise RuntimeError("Upscayl failed.")

    metadata = {
        "Srce file": f'"{get_clean_path(in_file)}"',
        "Scale": str(scale),
        "Upscayl model": UPSCAYL_MODEL,
    }
    add_png_metadata(out_file, metadata)
