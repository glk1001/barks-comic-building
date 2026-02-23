from pathlib import Path

from barks_comic_building.restore.gmic_exe import run_gmic


def overlay_inpainted_file_with_black_ink(
    inpaint_file: Path,
    black_ink_file: Path,
    out_file: Path,
) -> None:
    if not inpaint_file.is_file():
        msg = f'File not found: "{inpaint_file}".'
        raise FileNotFoundError(msg)
    if not black_ink_file.is_file():
        msg = f'File not found: "{black_ink_file}".'
        raise FileNotFoundError(msg)

    overlay_cmd = [
        str(inpaint_file),
        str(black_ink_file),
        "+channels[-1]",
        "100%",
        "+image[0]",
        "[1],0%,0%,0,0,1,[2],255",
        "output[-1]",
        str(out_file),
    ]

    run_gmic(overlay_cmd)
