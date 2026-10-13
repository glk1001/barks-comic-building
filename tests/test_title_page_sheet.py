"""The title page contact sheet's layout: thumbnails in rows, each labelled under it."""

from barks_fantagraphics.comics_consts import INTRO_PUB_TEXT_FONT_FILE
from PIL import Image, ImageFont

from barks_comic_building.query.title_page_sheet import (
    GAP,
    LABEL_FONT_SIZE,
    LABEL_HEIGHT,
    THUMB_WIDTH,
    fit_label,
    get_thumb_size,
    make_sheet,
)

THUMB_SIZE = (THUMB_WIDTH, 450)
COLORS = [(200, 0, 0), (0, 200, 0), (0, 0, 200), (200, 200, 0), (0, 200, 200)]


class TestTheThumbnails:
    def test_a_thumbnail_keeps_the_pages_shape(self) -> None:
        assert get_thumb_size((2120, 3200)) == (THUMB_WIDTH, round(3200 * THUMB_WIDTH / 2120))


class TestTheSheet:
    @staticmethod
    def _sheet(count: int, columns: int) -> Image.Image:
        thumbs = [(f"{i:03} Story", Image.new("RGB", THUMB_SIZE, COLORS[i])) for i in range(count)]
        return make_sheet(thumbs, columns, THUMB_SIZE)

    def test_the_sheet_holds_whole_rows_of_cells(self) -> None:
        sheet = self._sheet(5, columns=2)  # three rows, the last one short

        cell_width = THUMB_SIZE[0] + GAP
        cell_height = THUMB_SIZE[1] + LABEL_HEIGHT + GAP
        assert sheet.size == (GAP + (2 * cell_width), GAP + (3 * cell_height))

    def test_each_thumbnail_is_in_its_cell_in_reading_order(self) -> None:
        sheet = self._sheet(5, columns=2)

        cell_width = THUMB_SIZE[0] + GAP
        cell_height = THUMB_SIZE[1] + LABEL_HEIGHT + GAP
        for i, color in enumerate(COLORS):
            centre = (
                GAP + ((i % 2) * cell_width) + (THUMB_SIZE[0] // 2),
                GAP + ((i // 2) * cell_height) + (THUMB_SIZE[1] // 2),
            )
            assert sheet.getpixel(centre) == color


class TestTheLabels:
    FONT = ImageFont.truetype(INTRO_PUB_TEXT_FONT_FILE, LABEL_FONT_SIZE)

    def test_a_short_label_is_left_alone(self) -> None:
        assert fit_label("095 Truant Officer Donald", self.FONT, THUMB_WIDTH) == (
            "095 Truant Officer Donald"
        )

    def test_a_long_label_is_cut_short_to_fit(self) -> None:
        label = "999 The Many Faces of Magica De Spell and Some More Words Besides"

        fitted = fit_label(label, self.FONT, THUMB_WIDTH)

        assert fitted.endswith("…")
        assert label.startswith(fitted.removesuffix("…"))
        assert self.FONT.getlength(fitted) <= THUMB_WIDTH
