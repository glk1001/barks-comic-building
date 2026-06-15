from pathlib import Path

from barks_comic_building.restore.gmic_exe import run_gmic

# gmic 'fx_smooth_anisotropic' parameters (fixed).
_GMIC_SMOOTH_ANISOTROPIC_PARAMS = (
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


def smooth_image_file(in_file: Path, out_file: Path) -> None:
    smooth_cmd = [
        str(in_file),
        "fx_smooth_anisotropic",
        _GMIC_SMOOTH_ANISOTROPIC_PARAMS,
        "-threshold[-1]",
        "100,1",
        "normalize[-1]",
        "0,255",
        "-output[-1]",
        str(out_file),
    ]

    run_gmic(smooth_cmd)
