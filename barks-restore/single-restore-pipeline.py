# ruff: noqa: T201

import sys
import time
from pathlib import Path

from loguru import logger
from src.restore_pipeline import RestorePipeline, check_for_errors

if __name__ == "__main__":
    SCALE = 4
    srce_file = Path(sys.argv[1])
    srce_upscale_file = Path(sys.argv[2])
    dest_restored_file = Path(sys.argv[3])
    dest_upscayled_restored_file = Path(sys.argv[4])
    dest_svg_restored_file = Path(sys.argv[5])

    out_dir = dest_restored_file.parent
    if not out_dir.is_dir():
        print(f'ERROR: Can\'t find output directory: "{out_dir}".')
        sys.exit(1)

    work_dir = Path("/tmp/") / "working"  # noqa: S108
    work_dir.mkdir(parents=True, exist_ok=True)

    input_image_dir = srce_file.parent
    input_image_stem = srce_file.stem

    start_restore = time.time()

    restore_process = RestorePipeline(
        work_dir,
        srce_file,
        srce_upscale_file,
        SCALE,
        dest_restored_file,
        dest_upscayled_restored_file,
        dest_svg_restored_file,
    )
    restore_process.do_part1()
    restore_process.do_part2_memory_hungry()
    restore_process.do_part3()
    restore_process.do_part4_memory_hungry()

    logger.info(f'\nTime taken to restore all files": {int(time.time() - start_restore)}s.')

    check_for_errors([restore_process])
