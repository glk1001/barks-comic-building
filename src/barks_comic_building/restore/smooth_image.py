from pathlib import Path

from barks_comic_building.restore.gmic_exe import run_gmic


def smooth_image_file(in_file: Path, out_file: Path) -> None:
    smooth_cmd = [
        str(in_file),
        "fx_smooth_anisotropic",
        _get_gmic_smooth_anisotropic_params(),
        "-threshold[-1]",
        "100,1",
        "normalize[-1]",
        "0,255",
        "-output[-1]",
        str(out_file),
    ]

    run_gmic(smooth_cmd)


def _get_gmic_smooth_anisotropic_params() -> str:
    amplitude = 420
    sharpness = 0.5
    anisotropy = 0.6
    alpha = 2.5
    sigma = 5.0
    dl = 0.8
    da = 30
    precision = 2
    interpolation = 0  # nearest
    fast_approx = 1
    repeat = 2
    channels = 0

    return (
        f"{amplitude},"
        f"{sharpness},"
        f"{anisotropy},"
        f"{alpha},"
        f"{sigma},"
        f"{dl},"
        f"{da},"
        f"{precision},"
        f"{interpolation},"
        f"{fast_approx},"
        f"{repeat},"
        f"{channels}"
    )
