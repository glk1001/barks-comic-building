from collections.abc import Callable
from pathlib import Path

import cv2 as cv
import typer
from barks_fantagraphics.comic_book_info import BARKS_TITLE_DICT
from barks_fantagraphics.comics_consts import PNG_FILE_EXT, RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import draw_panel_bounds_on_image
from barks_fantagraphics.panel_boxes import TitlePanelBoxes, check_page_panel_boxes
from comic_utils.common_typer_options import LogLevelArg, TitleArg
from comic_utils.cv_image_utils import get_bw_image_from_alpha
from kivy.app import App
from kivy.core.image import Texture
from kivy.core.window import Window
from kivy.input.motionevent import MotionEvent
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image as KivyImage
from kivy.uix.label import Label
from loguru import logger
from PIL import Image

from barks_comic_building.cli_setup import init_logging

APP_LOGGING_NAME = "span"

_KEY_RIGHT = 275
_KEY_LEFT = 276


def _build_page_images(
    comics_database: ComicsDatabase, title: str
) -> list[tuple[str, Image.Image]]:
    comic = comics_database.get_comic_book(title)
    svg_files = comic.get_srce_restored_svg_story_files(RESTORABLE_PAGE_TYPES)
    title_pages_panel_boxes = TitlePanelBoxes(comics_database).get_page_panel_boxes(
        BARKS_TITLE_DICT[title]
    )

    pages: list[tuple[str, Image.Image]] = []
    for svg_file in svg_files:
        fanta_page = svg_file.stem

        png_file = Path(str(svg_file) + PNG_FILE_EXT)
        if not png_file.is_file():
            msg = f'Page PNG not found: "{png_file}".'
            raise FileNotFoundError(msg)
        bw_image = get_bw_image_from_alpha(png_file)
        pil_image = Image.fromarray(cv.merge([bw_image, bw_image, bw_image])).convert("RGBA")

        page_panel_boxes = title_pages_panel_boxes.pages[fanta_page]
        check_page_panel_boxes(pil_image.size, page_panel_boxes)
        draw_panel_bounds_on_image(pil_image, page_panel_boxes)

        pages.append((fanta_page, pil_image))

    return pages


def _pil_to_texture(pil: Image.Image) -> Texture:
    tex = Texture.create(size=pil.size)
    tex.blit_buffer(pil.tobytes(), colorfmt="rgba", bufferfmt="ubyte")
    tex.flip_vertical()

    return tex


class _ClickNavLayout(BoxLayout):
    """Vertical BoxLayout that splits clicks left-of-centre vs right-of-centre."""

    def __init__(
        self,
        on_left_click: Callable[[], None],
        on_right_click: Callable[[], None],
        **kwargs,  # noqa: ANN003
    ) -> None:
        super().__init__(**kwargs)
        self._on_left_click = on_left_click
        self._on_right_click = on_right_click

    def on_touch_down(self, touch: MotionEvent) -> bool:
        if not self.collide_point(*touch.pos):
            return False
        if getattr(touch, "button", "left") != "left":
            return False
        if touch.x < self.center_x:
            self._on_left_click()
        else:
            self._on_right_click()
        return True


class _PanelBoundsViewer(App):
    def __init__(
        self,
        title: str,
        pages: list[tuple[str, Image.Image]],
        start_page: int,
    ) -> None:
        super().__init__()
        self._title_str = title
        self._pages = pages
        self._index = max(0, min(len(pages) - 1, start_page - 1))
        self._page_label: Label | None = None
        self._image_widget: KivyImage | None = None

    def build(self) -> BoxLayout:
        self.title = f"Panel bounds — {self._title_str}"
        Window.size = (1000, 1400)

        root = _ClickNavLayout(
            on_left_click=lambda: self._go(-1),
            on_right_click=lambda: self._go(+1),
            orientation="vertical",
        )

        self._page_label = Label(size_hint_y=None, height=30)
        self._image_widget = KivyImage(allow_stretch=True, keep_ratio=True)

        root.add_widget(self._page_label)
        root.add_widget(self._image_widget)

        Window.bind(on_key_down=self._on_key_down)
        self._show_current()

        return root

    def _on_key_down(
        self,
        _window: object,
        key: int,
        _scancode: int,
        _codepoint: str | None,
        _modifiers: list,
    ) -> bool:
        if key == _KEY_LEFT:
            self._go(-1)
            return True
        if key == _KEY_RIGHT:
            self._go(+1)
            return True
        return False

    def _go(self, delta: int) -> None:
        new_index = self._index + delta
        if 0 <= new_index < len(self._pages):
            self._index = new_index
            self._show_current()

    def _show_current(self) -> None:
        fanta_page, pil_image = self._pages[self._index]
        assert self._page_label is not None
        assert self._image_widget is not None

        self._page_label.text = (
            f"Page {self._index + 1} of {len(self._pages)}   [fanta: {fanta_page}]"
        )
        self._image_widget.texture = _pil_to_texture(pil_image)


def show_panel_bounds(comics_database: ComicsDatabase, title: str, start_page: int) -> None:
    """Display panel-bounds overlays for ``title`` in a Kivy viewer window.

    Args:
        comics_database: The comics database used to resolve the title.
        title: The Barks title to display.
        start_page: 1-based page index to show first. Clamped to the available range.

    """
    logger.info(f'Showing panel bounds for "{title}"...')

    pages = _build_page_images(comics_database, title)
    if not pages:
        logger.error(f'No restorable pages found for "{title}".')
        return

    _PanelBoundsViewer(title=title, pages=pages, start_page=start_page).run()


app = typer.Typer()


@app.command(help="Show panel bounds for title")
def main(
    title_str: TitleArg,
    page: int = typer.Option(1, "--page", "-p", help="Page number to start on (1-based)."),
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    comics_database = ComicsDatabase()

    show_panel_bounds(comics_database, title_str, page)


if __name__ == "__main__":
    app()
