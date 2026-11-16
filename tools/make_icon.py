"""Draw the app icon (tools/app.ico): a form on a blue tile, matching the
browser tab icon. Needs Pillow:  python tools/make_icon.py"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "app.ico"
BLUE, WHITE, LINE = (31, 78, 140, 255), (255, 255, 255, 255), (31, 78, 140, 255)


def draw(size: int = 512) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 32
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(7 * s), fill=BLUE)
    # page with a folded corner
    d.polygon([(10 * s, 7 * s), (19.5 * s, 7 * s), (23 * s, 10.5 * s), (23 * s, 25 * s), (10 * s, 25 * s)], fill=WHITE)
    d.polygon([(19.5 * s, 7 * s), (19.5 * s, 10.5 * s), (23 * s, 10.5 * s)], fill=(200, 214, 232, 255))
    # filled-in lines
    for y, x2 in ((14.5, 20), (17.5, 20), (20.5, 17.5)):
        d.rounded_rectangle([12.5 * s, (y - 0.8) * s, x2 * s, (y + 0.8) * s], radius=int(0.8 * s), fill=LINE)
    return img


if __name__ == "__main__":
    draw().save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT)
