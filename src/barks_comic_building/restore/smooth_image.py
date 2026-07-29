from pathlib import Path

from barks_comic_building.restore.gmic_exe import run_gmic

# gmic 'fx_smooth_anisotropic' parameters (fixed).
GMIC_SMOOTH_ANISOTROPIC_PARAMS = (
    "420,"  # amplitude
    "0.5,"  # sharpness
    "0.6,"  # anisotropy
    "2.5,"  # alpha
    "5.0,"  # sigma
    "0.8,"  # dl
    "30,"  # da
    "2,"  # precision
    "0,"  # interpolation (nearest)
    "1,"  # fast_approx
    "2,"  # repeat
    "0"  # channels
)

# The soft threshold that turns the smoothed image back into an ink mask, and with it the
# weight of the line art: lower is thinner. Smoothing puts weight on, and this is the only
# way to take it off again - morphology works a whole pixel at a time, which is several
# times coarser than the correction needed. Measured against the Fantagraphics page on
# volume 9 page 110, the old value of 100 came out 1.3% heavier, 60 lands within 0.2%, and
# 30 sits a little under while keeping the most separation between fine hatching strokes.
SMOOTH_THRESHOLD = 30


def smooth_image_file(in_file: Path, out_file: Path) -> None:
    smooth_cmd = [
        str(in_file),
        "fx_smooth_anisotropic",
        GMIC_SMOOTH_ANISOTROPIC_PARAMS,
        "-threshold[-1]",
        f"{SMOOTH_THRESHOLD},1",
        "normalize[-1]",
        "0,255",
        "-output[-1]",
        str(out_file),
    ]

    run_gmic(smooth_cmd)
