from pathlib import Path

from vtracer import convert_image_to_svg_py


def image_file_to_svg(in_file: Path, out_file: Path) -> None:
    # colormode (str, optional): True color image `color` (default) or Binary image `binary`.
    # color_precision (int, optional): Number of significant bits to use in an RGB channel.
    #                                  Defaults to 8.
    # layer_difference (int, optional): Color difference between gradient layers. Defaults to 16.
    # hierarchical (str, optional): Hierarchical clustering. Can be `stacked` (default) or
    #                               non-stacked `cutout`. Only applies to color mode.
    # path_precision (int, optional): Parameter not described in provided options. Defaults to 8.
    # mode (str, optional): Curve fitting mode. Can be `pixel`, `polygon`, `spline`.
    #                       Defaults to 'spline'.
    # corner_threshold (int, optional): Minimum momentary angle (degree) to be considered a corner.
    #                                   Defaults to 60.
    # length_threshold (float, optional): Perform iterative subdivide smooth until all segments are
    #                                     shorter than this length. Defaults to 4.0.
    # max_iterations (int, optional): Parameter not described in provided options. Defaults to 10.
    # splice_threshold (int, optional): Minimum angle displacement (degree) to splice a spline.
    #                                   Defaults to 45.
    # filter_speckle (int, optional): Discard patches smaller than X px in size. Defaults to 4.

    # Testing on three single panel images showed defaults good but 'length_threshold=10' also
    # gives good results with smaller .svg files.

    if not in_file.is_file():
        msg = f'Could not find file "{in_file}".'
        raise FileNotFoundError(msg)

    convert_image_to_svg_py(
        str(in_file),
        str(out_file),
        colormode="binary",
        path_precision=3,
        mode="spline",
        filter_speckle=2,
        corner_threshold=60,
        length_threshold=10.0,
        max_iterations=10,
        splice_threshold=45,  # higher than this is not so good
    )
