# ruff: noqa

import os
import sys
from dataclasses import dataclass
from functools import cmp_to_key
from pathlib import Path

import cv2 as cv
from comic_utils.panel_bounding_box_processor import BoundingBoxProcessor
from comic_utils.panel_segmentation import KumikoBound, get_kumiko_panel_bound
from comic_utils.pil_image_utils import open_pil_image_for_reading
from PIL import Image, ImageDraw
from PIL.Image import Image as PilImage
from PIL.ImageDraw import ImageDraw as PilImageDraw

INPUT_IMAGE_WIDTH = 8700
INPUT_IMAGE_HEIGHT = 12000

PANEL_ROW_START_SIMILARITY_MARGIN = 100
SAFETY_MARGIN = 3
# REQUIRED_HEIGHT = 2800
REQUIRED_HEIGHT = 10500
REQUIRED_OVERALL_HEIGHT = REQUIRED_HEIGHT + 2 * SAFETY_MARGIN


@dataclass
class KumikoBoundWithPanelNum:
    kumiko_bound: KumikoBound
    panel_num: int


BoundsInfo = tuple[KumikoBound, list[KumikoBound]], dict[int, list[KumikoBoundWithPanelNum]]


def get_equidistant_vertical_spacing(bounds_info: BoundsInfo) -> int:
    extra_space, num_rows = get_extra_vertical_space(bounds_info)

    equidistant_space = round(extra_space / (num_rows - 1))
    print(f"equidistant_space = {equidistant_space}, num_rows = {num_rows}")

    return equidistant_space


def get_vertical_start(overall_bound: KumikoBound) -> int:
    return int(overall_bound.top - (REQUIRED_OVERALL_HEIGHT - overall_bound.height) / 2)
    # return overall_bound.top


# noinspection PyTypeChecker
def fix_panels(in_file: str, out_file: str) -> None:
    srce_image = open_pil_image_for_reading(in_file).convert("RGB")
    print(f'"{srce_image}": {srce_image.size}')
    assert srce_image.width == INPUT_IMAGE_WIDTH
    assert srce_image.height == INPUT_IMAGE_HEIGHT

    bounding_box_processor = BoundingBoxProcessor(work_dir, no_panel_expansion=True)
    bounds_info = get_page_panel_bounds(bounding_box_processor, in_file)
    print(bounds_info)
    assert 0 < bounds_info[0].height <= REQUIRED_OVERALL_HEIGHT

    in_file_stem = Path(in_file).stem
    temp_bounded_file = os.path.join(work_dir, in_file_stem + "-bounded.jpg")
    dump_panel_bounding_boxes(srce_image, temp_bounded_file, bounds_info)

    subimages = get_panel_bounded_subimages(srce_image, bounds_info[1])

    vertical_spacing = get_equidistant_vertical_spacing(bounds_info)

    respace_panels(
        srce_image, out_file, Path(in_file).stem, subimages, vertical_spacing, bounds_info
    )


def respace_panels(
    srce_image: PilImage,
    dest_file: str,
    image_name: str,
    subimages: list[PilImage],
    vertical_spacing: int,
    bounds_info: BoundsInfo,
) -> None:
    overall_bound = bounds_info[0]
    row_bounds = bounds_info[2]

    white_page_color = srce_image.getpixel((10, 10))
    x_min = overall_bound.left
    y_min = overall_bound.top
    x_max = overall_bound.left + overall_bound.width - 1
    y_max = overall_bound.top + overall_bound.height - 1
    srce_image.paste(white_page_color, (x_min, y_min, x_max, y_max))

    y_min = 0
    all_subimages = Image.new("RGB", (overall_bound.width, overall_bound.height), white_page_color)
    for panel_row in row_bounds:
        for bound in row_bounds[panel_row]:
            panel_num = bound.panel_num
            subimage = subimages[panel_num - 1]
            x_min = bound.kumiko_bound.left - overall_bound.left

            subimage.save(os.path.join(work_dir, f"{image_name}-panel-{panel_num}.jpg"))
            print(f"subimage {panel_num}: x_min = {x_min}, y_min = {y_min}")

            all_subimages.paste(subimage, (x_min, y_min))

        y_min += row_bounds[panel_row][0].kumiko_bound.height + vertical_spacing
        print(f"New y_min = {y_min}")

    all_subimages.save(os.path.join(work_dir, f"{image_name}-all-panels.jpg"))

    all_subimages = all_subimages.resize(
        size=(overall_bound.width, REQUIRED_OVERALL_HEIGHT),
        resample=Image.Resampling.BICUBIC,
    )
    all_subimages.save(os.path.join(work_dir, f"{image_name}-all-panels-resized.jpg"))

    srce_image.paste(all_subimages, (overall_bound.left, get_vertical_start(overall_bound)))

    srce_image.save(dest_file)


def get_extra_vertical_space(bounds_info: BoundsInfo) -> tuple[int, int]:
    overall_bound = bounds_info[0]
    row_bounds = bounds_info[2]

    total_panel_height = 0
    for panel_row in row_bounds:
        total_panel_height += row_bounds[panel_row][0].kumiko_bound.height
        print(panel_row, total_panel_height)

    extra_space = overall_bound.height - total_panel_height
    num_panel_rows = len(row_bounds.keys())

    print(
        f"Req hgt = {REQUIRED_OVERALL_HEIGHT},"
        f" overall_bound.height = {overall_bound.height},"
        f" total_panel_height = {total_panel_height},"
        f" extra_space = {extra_space},"
        f" num_panel_rows = {num_panel_rows}"
    )

    assert total_panel_height > 0
    assert num_panel_rows >= 3
    assert extra_space > 0

    return extra_space, num_panel_rows


# noinspection PyTypeChecker
def get_page_panel_bounds(
    bounding_box_processor: BoundingBoxProcessor, srce_file: str
) -> BoundsInfo:
    panels_bounds_override_dir = "/tmp"

    if not os.path.isfile(srce_file):
        msg = f'Could not find srce file: "{srce_file}".'
        raise FileNotFoundError(msg)

    segment_info = bounding_box_processor.get_panels_segment_info_from_kumiko(
        srce_file,
        panels_bounds_override_dir,
    )
    temp_bounds_file = os.path.join(work_dir, Path(srce_file).stem + "-bounds.json")
    bounding_box_processor.save_panels_segment_info(temp_bounds_file, segment_info)

    bounds = []
    for panel in segment_info["panels"]:
        bound = get_kumiko_panel_bound(panel)
        x_min = bound.left - SAFETY_MARGIN
        y_min = bound.top - SAFETY_MARGIN
        x_max = bound.left + bound.width - 1 + SAFETY_MARGIN
        y_max = bound.top + bound.height - 1 + SAFETY_MARGIN
        bound = KumikoBound(x_min, y_min, x_max - x_min + 1, y_max - y_min + 1)
        bounds.append(bound)

    bounds = get_correctly_sorted_bounds(bounds)

    panel_row = 0
    prev_panel_top = 0
    row_bounds = {}
    for index, bound in enumerate(bounds):
        if abs(bound.top - prev_panel_top) > PANEL_ROW_START_SIMILARITY_MARGIN:
            panel_row += 1
            prev_panel_top = bound.top
        if panel_row not in row_bounds:
            row_bounds[panel_row] = []
        row_bounds[panel_row].append(KumikoBoundWithPanelNum(bound, index + 1))

    seg_overall_bound = segment_info["overall_bounds"]
    x_min = seg_overall_bound[0] - SAFETY_MARGIN
    y_min = seg_overall_bound[1] - SAFETY_MARGIN
    x_max = seg_overall_bound[2] + SAFETY_MARGIN
    y_max = seg_overall_bound[3] + SAFETY_MARGIN
    overall_bound = KumikoBound(x_min, y_min, x_max - x_min + 1, y_max - y_min + 1)

    return overall_bound, bounds, row_bounds


def get_correctly_sorted_bounds(bounds: list[KumikoBound]) -> list[KumikoBound]:
    def compare_panels(panel1: KumikoBound, panel2: KumikoBound) -> int:
        if abs(panel1.top - panel2.top) < PANEL_ROW_START_SIMILARITY_MARGIN:
            return panel1.left - panel2.left
        return panel1.top - panel2.top

    return sorted(bounds, key=cmp_to_key(compare_panels))


def get_panel_bounded_subimages(srce_image: PilImage, bounds: list[KumikoBound]) -> list[PilImage]:
    subimages = []
    for bound in bounds:
        x_min = bound.left
        y_min = bound.top
        x_max = bound.left + bound.width - 1
        y_max = bound.top + bound.height - 1

        subimages.append(srce_image.crop((x_min, y_min, x_max, y_max)))

    return subimages


def dump_panel_bounding_boxes(
    srce_image: PilImage, dest_file: str, bounds_info: BoundsInfo
) -> None:
    overall_bound = bounds_info[0]
    bounds = bounds_info[1]

    draw = ImageDraw.Draw(srce_image)
    line_width = 1
    color = (256, 0, 0)

    for bound in bounds:
        draw_box(draw, bound, line_width, color)

    color = (0, 256, 0)
    draw_box(draw, overall_bound, line_width, color)

    srce_image = srce_image.convert("RGB")
    srce_image.save(dest_file, optimize=False, compress_level=5)


def draw_box(
    draw: PilImageDraw,
    bound: KumikoBound,
    line_width: int,
    color: tuple[int, int, int],
) -> None:
    x_min = bound.left
    y_min = bound.top
    x_max = bound.left + bound.width - 1
    y_max = bound.top + bound.height - 1

    draw.line([(x_min, y_min), (x_max, y_min)], width=line_width, fill=color)
    draw.line([(x_max, y_min), (x_max, y_max)], width=line_width, fill=color)
    draw.line([(x_max, y_max), (x_min, y_max)], width=line_width, fill=color)
    draw.line([(x_min, y_max), (x_min, y_min)], width=line_width, fill=color)


def scale_image(image_file: str) -> None:
    image = cv.imread(image_file)

    scale = 1.0 / 4.0
    image = cv.resize(image, (0, 0), fx=scale, fy=scale, interpolation=cv.INTER_AREA)

    color_converted = cv.cvtColor(image, cv.COLOR_BGR2RGB)
    pil_image = Image.fromarray(color_converted)

    assert pil_image.width == int(INPUT_IMAGE_WIDTH * scale)
    assert pil_image.height == int(INPUT_IMAGE_HEIGHT * scale)

    pil_image.save(image_file, optimize=True, compress_level=9, quality=95)


if __name__ == "__main__":
    assert len(sys.argv) == 3
    input_image_file = sys.argv[1]
    output_dir = sys.argv[2]

    if not os.path.isfile(input_image_file):
        err_msg = f'Could not find input file "{input_image_file}".'
        raise FileNotFoundError(err_msg)
    if not os.path.isdir(output_dir):
        err_msg = f'Could not find output directory "{output_dir}".'
        raise FileNotFoundError(err_msg)

    work_dir = "/tmp/panels-fix"
    os.makedirs(work_dir, exist_ok=True)

    #    output_file = os.path.join(output_dir, f"{Path(input_image_file).stem}.jpg")
    output_file = os.path.join(output_dir, f"{Path(input_image_file).stem}.png")

    fix_panels(input_image_file, output_file)

    scale_image(output_file)
