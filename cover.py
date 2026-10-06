import os   # For file path operations

from PIL import Image, ImageDraw, ImageFont   # For composing the cover image

_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_TEMPLATE_PATH = os.path.join(_ASSETS_DIR, "cover_template.png")   # Right 800 px of the cover: blue line, dark strip and logo, without text
_FONT_PATH = os.path.join(_ASSETS_DIR, "RobotoMono-Medium.ttf")

_SIZE = 2400            # The cover is a square of 2400 x 2400 px
_BOOK_WIDTH = 1600      # The book's own cover (2:3) fills the left 1600 px
_TEXT_COLOR = (205, 214, 244)
_TEXT_SIZE = 151        # Font size in px
_TEXT_CENTER_X = 2018   # The text runs bottom to top, centered on this x ...
_TEXT_CENTER_Y = 827    # ... and on this y
_TEXT_MAX_LENGTH = 1500   # Longest allowed text in px; larger text is scaled down to fit

def _render_text(text):
    """
    Render the text in Roboto Mono Medium, rotated by 90 degrees so that it
    reads from bottom to top, and scale it down if it would be longer than
    _TEXT_MAX_LENGTH.

    :param text: The text to render.

    :return: A Pillow image in mode "L" (opacity mask), cropped to the text.
    """
    size = _TEXT_SIZE
    while True:
        font = ImageFont.truetype(_FONT_PATH, size)
        left, top, right, bottom = font.getbbox(text)
        mask = Image.new("L", (right - left + 40, bottom - top + 40), 0)
        ImageDraw.Draw(mask).text((20 - left, 20 - top), text, font=font, fill=255)
        mask = mask.rotate(90, expand=True)
        mask = mask.crop(mask.point(lambda value: 255 if value > 102 else 0).getbbox())
        if mask.height <= _TEXT_MAX_LENGTH or size <= 40:
            return mask
        size -= 4

def make_cover(book_cover_path, version, duration, output_path):
    """
    Compose the audiobook cover: the book's own cover on the left, the
    Earwyrm template (blue line, dark strip, logo) on the right, and
    "v<version> <duration>h" written vertically onto the strip.

    :param book_cover_path: Path to the book's cover image, or None to leave the left side blank.
    :param version: Pipeline version, e.g. "3.1.0".
    :param duration: Duration of the finished audiobook, e.g. "29:16:17".
    :param output_path: Path of the PNG file to write.
    """
    canvas = Image.new("RGB", (_SIZE, _SIZE), (116, 199, 236))

    # Book cover: scale to fill the left area (exact fit for 2:3 covers), then crop the overflow evenly
    if book_cover_path and os.path.isfile(book_cover_path):
        book = Image.open(book_cover_path).convert("RGB")
        scale = max(_BOOK_WIDTH / book.width, _SIZE / book.height)
        book = book.resize((round(book.width * scale), round(book.height * scale)), Image.LANCZOS)
        left = (book.width - _BOOK_WIDTH) // 2
        top = (book.height - _SIZE) // 2
        canvas.paste(book.crop((left, top, left + _BOOK_WIDTH, top + _SIZE)), (0, 0))

    canvas.paste(Image.open(_TEMPLATE_PATH).convert("RGB"), (_BOOK_WIDTH, 0))

    mask = _render_text(f"v{version} {duration}h")
    canvas.paste(Image.new("RGB", mask.size, _TEXT_COLOR),
                 (_TEXT_CENTER_X - mask.width // 2, _TEXT_CENTER_Y - mask.height // 2), mask)

    canvas.save(output_path, "PNG", optimize=True)

if __name__ == "__main__":
    # Quick manual test: python cover.py <book_cover.png> <output.png>
    import sys
    make_cover(sys.argv[1] if len(sys.argv) > 1 else None, "3.0.0", "29:16:17",
               sys.argv[2] if len(sys.argv) > 2 else "cover_test.png")
