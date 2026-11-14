#!/usr/bin/env python3
#
# generate_midnight.py
#
# Generates the pictures of the Midnight theme, which takes the light-theme
# slots of mapping.yaml, and writes them straight into the display sources
# (hmi/src/nspanel_<orientation>/pictures/picture-NNNN.png).
#
# Every light slot is rebuilt from the same source sprite as in
# generate_images.sh, placed on a flat Midnight background and cropped the
# same way, but restyled first: the plain shapes (tiles, sliders, pills) are
# recolored from their alpha with the palette below, and the colored artwork
# (weather, vacuum, color wheel) is placed as it is. Slots shared by both
# themes (splash, slider cursors) are left alone. The landscape home, cover
# and media pages also get their own backgrounds (HOME_SLOT, COVER_SLOT, MEDIA_SLOT), and the
# landscape cover sliders are redrawn horizontal for both themes
# (COVER_SLIDERS), which replaces those dark-theme slots too.
#
# Usage:
#   python3 generate_midnight.py [landscape|portrait|all]   (default: all)
#
# Requirements:
#   - python3 with Pillow and PyYAML

import sys
from pathlib import Path

import yaml
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

PICS_DIR = Path(__file__).resolve().parent.parent
SRC_ROOT = PICS_DIR.parent.parent / "src"
SIZES = {"landscape": (480, 320), "portrait": (320, 480)}

# Midnight palette; keep in sync with Colors::RGB565_MIDNIGHT_* (nextion_constants.h)
BG = (0x0E, 0x14, 0x1D)
SURFACE = (0x1A, 0x22, 0x30)
SURFACE_HI = (0x24, 0x30, 0x47)
BLUE = (0x6F, 0xA8, 0xF5)
BLUE_FILL = (0x24, 0x40, 0x6A)
AMBER = (0xF2, 0xB1, 0x4C)
AMBER_FILL = (0x5A, 0x44, 0x20)
# Tiles: a soft vertical gradient with a thin edge, so they stand out from the background
TILE = "tile"
TILE_TOP = (0x2A, 0x35, 0x4D)
TILE_BOTTOM = (0x1C, 0x24, 0x34)
TILE_EDGE = (0x34, 0x41, 0x5B)

BORDER = 3  # Border width of outlined shapes, in pixels


def solid(alpha: Image.Image, color: tuple) -> Image.Image:
    """A sprite of one color, shaped by `alpha`."""
    out = Image.new("RGBA", alpha.size, color + (0,))
    out.putalpha(alpha)
    return out


def tile_fill(alpha: Image.Image) -> Image.Image:
    """Fills the shapes of `alpha` as tiles: each band of rows gets its own gradient, and the shapes a 1px edge."""
    mask = alpha.point(lambda a: 255 if a > 127 else 0)
    rows = [y for y in range(mask.height) if mask.crop((0, y, mask.width, y + 1)).getbbox()]
    picture = Image.new("RGB", alpha.size, TILE_BOTTOM)
    draw = ImageDraw.Draw(picture)
    start = None
    for i, y in enumerate(rows):
        if start is None:
            start = y
        if i + 1 == len(rows) or rows[i + 1] != y + 1:  # end of a band
            span = max(y - start, 1)
            for row in range(start, y + 1):
                f = (row - start) / span
                draw.line((0, row, mask.width, row), fill=tuple(round(a + (b - a) * f) for a, b in zip(TILE_TOP, TILE_BOTTOM)))
            start = None
    padded = Image.new("L", (mask.width + 2, mask.height + 2), 0)
    padded.paste(mask, (1, 1))
    inner = padded.filter(ImageFilter.MinFilter(3)).crop((1, 1, 1 + mask.width, 1 + mask.height))
    picture.paste(TILE_EDGE, mask=ImageChops.subtract(mask, inner))
    out = picture.convert("RGBA")
    out.putalpha(alpha)
    return out


def tiled(sprite):
    return tile_fill(sprite.getchannel("A"))


def tint(color):
    return lambda sprite: solid(sprite.getchannel("A"), color)


def outlined(fill, border):
    """Fills the shape with `fill` and draws its edge in `border`."""
    def style(sprite):
        alpha = sprite.getchannel("A")
        # Padded first, so a shape touching the sprite's edge still gets a border there
        padded = Image.new("L", (alpha.width + 2 * BORDER, alpha.height + 2 * BORDER), 0)
        padded.paste(alpha.point(lambda a: 255 if a > 127 else 0), (BORDER, BORDER))
        inner = padded.filter(ImageFilter.MinFilter(2 * BORDER + 1)).crop(
            (BORDER, BORDER, BORDER + alpha.width, BORDER + alpha.height))
        out = solid(alpha, border)
        out.paste(Image.new("RGB", alpha.size, fill), mask=inner)
        out.putalpha(alpha)
        return out
    return style


def two_tone(light, dark):
    """Recolors a striped sprite: its lighter pixels to `light`, the others to `dark`."""
    def style(sprite):
        alpha = sprite.getchannel("A")
        luma = sprite.convert("L")
        histogram = luma.histogram(mask=alpha.point(lambda a: 255 if a > 127 else 0))
        used = [v for v, count in enumerate(histogram) if count]
        threshold = (used[0] + used[-1]) // 2
        out = solid(alpha, dark)
        out.paste(Image.new("RGB", sprite.size, light), mask=luma.point(lambda v: 255 if v > threshold else 0))
        out.putalpha(alpha)
        return out
    return style


def dark_gray_to(color, max_luma=70, max_chroma=24):
    """Keeps the artwork but repaints its dark neutral parts (frames, button discs) in `color`."""
    def style(sprite):
        r, g, b, a = sprite.split()
        chroma = ImageChops.subtract(ImageChops.lighter(ImageChops.lighter(r, g), b),
                                     ImageChops.darker(ImageChops.darker(r, g), b))
        luma = sprite.convert("L")
        mask = ImageChops.multiply(luma.point(lambda v: 255 if v <= max_luma else 0),
                                   chroma.point(lambda v: 255 if v <= max_chroma else 0))
        out = sprite.copy()
        out.paste(Image.new("RGBA", sprite.size, color + (255,)), mask=mask)
        out.putalpha(a)
        return out
    return style


def as_is(sprite):
    return sprite


# Style per mapping id. Ids not listed are placed as they are.
STYLES = {
    "buttons_pages_background_innactive": tiled,
    "buttons_pages_background_active": outlined(AMBER_FILL, AMBER),
    "climate_background": dark_gray_to(SURFACE),
    "cover_slider_active_light": tint(BLUE),
    "cover_slider_inactive_light": tint(SURFACE),
    "cover_slider_pair_active_light": tint(BLUE),
    "cover_slider_pair_inactive_light": tint(SURFACE),
    "cover_tilt_slider_active_light": two_tone(BLUE, SURFACE),
    "cover_tilt_slider_inactive": two_tone(SURFACE_HI, SURFACE),
    "fan_slider_active": tint(BLUE),
    "fan_slider_inactive": tint(SURFACE),
    "light_button_brightness_normal": dark_gray_to(SURFACE),
    "light_button_brightness_pressed": dark_gray_to(SURFACE),
    "light_button_color_normal": dark_gray_to(SURFACE),
    "light_button_color_pressed": dark_gray_to(SURFACE),
    "light_button_temp_normal": dark_gray_to(SURFACE),
    "light_button_temp_pressed": dark_gray_to(SURFACE),
    "light_slider_level_active": tint(AMBER),
    "light_slider_level_inactive": tint(SURFACE),
    "settings_brightness_slider_active": tint(BLUE),
    "settings_brightness_slider_inactive": tint(SURFACE),
    "settings_dim_slider_active": tint(BLUE),
    "settings_dim_slider_inactive": tint(SURFACE),
    "settings_button_action_reboot": tiled,
    "settings_button_action_sleep": tiled,
    "settings_button_action_theme": tiled,
}
for n in range(1, 6):
    STYLES[f"fan_mode_{n}_active_light"] = outlined(BLUE_FILL, BLUE)
    STYLES[f"fan_mode_{n}_inactive_light"] = tiled


# Home page background (landscape only, its own slot after the mapped pictures):
# the shapes behind the home components, as (x0, y0, x1, y1, radius, color).
HOME_SLOT = 134
HOME_SHAPES = {
    "landscape": [
        (296, 58, 297, 180, 0, SURFACE_HI),  # divider: indoor temperature and values | time, weather, date
        (8, 198, 155, 278, 16, TILE),       # tiles for button01..button03
        (166, 198, 313, 278, 16, TILE),
        (324, 198, 471, 278, 16, TILE),
        (239, 290, 240, 314, 0, SURFACE_HI),  # divider between the hardware buttons' labels
    ],
}


# Cover page background (landscape only): the tiles behind open, stop and close
COVER_SLOT = 135
COVER_SHAPES = {
    "landscape": [
        (8, 206, 155, 282, 16, TILE),
        (166, 206, 313, 282, 16, TILE),
        (324, 206, 471, 282, 16, TILE),
    ],
}

# Media player background (landscape only): previous and next tiles, and the round play button
MEDIA_SLOT = 136
PLAY = (0x3B, 0x78, 0xD8)  # deeper than BLUE, so the white glyph on it stays readable
MEDIA_SHAPES = {
    "landscape": [
        (104, 168, 191, 228, 16, TILE),
        (289, 168, 376, 228, 16, TILE),
        (204, 162, 276, 234, 36, PLAY),
    ],
}

# Midnight sliders (landscape only): a thin track and a white round knob as the cursor.
# The knob picture carries the track under it: the fill on the start side, the track on the
# other, so it blends in wherever the cursor is.
TRACK = 12           # thickness of the thin track, in pixels
KNOB = 28            # diameter of the knob
KNOB_COLOR = (0xF2, 0xF4, 0xF7)
KNOB_EDGE = (0xB8, 0xC0, 0xCC)
KNOB_H_SLOT, KNOB_V_SLOT = 137, 138  # horizontal (36 high) and vertical (85 wide) knobs
THIN_SLIDERS = {  # slot -> (part, size, vertical)
    88: ("fill", (420, 36), False), 89: ("track", (420, 36), False),   # settings: brightness
    90: ("fill", (420, 36), False), 91: ("track", (420, 36), False),   # settings: dim
    105: ("track", (420, 36), False), 107: ("fill", (420, 36), False),  # cover sliders
    112: ("track", (420, 36), False), 113: ("fill", (420, 36), False),
    109: ("track", (420, 36), False), 111: ("fill", (420, 36), False),
    139: ("track", (244, 36), False), 140: ("fill", (244, 36), False),  # media: volume
    72: ("track", (85, 235), True), 73: ("fill_on", (85, 235), True),   # light level and fan
}
# Dark-theme volume slider, now a picture slider too: track and fill as before, in pills
DARK_VOLUME = {141: (0x29, 0x2C, 0x29), 142: (0x84, 0x00, 0x42)}


def thin_track(size: tuple, color: tuple, vertical: bool, background: tuple = BG) -> Image.Image:
    picture = Image.new("RGB", size, background)
    w, h = size
    box = ((w - TRACK) // 2, 0, (w + TRACK) // 2 - 1, h - 1) if vertical else (0, (h - TRACK) // 2, w - 1, (h + TRACK) // 2 - 1)
    ImageDraw.Draw(picture).rounded_rectangle(box, TRACK // 2, fill=color)
    return picture


def knob(size: tuple, vertical: bool, fill: tuple) -> Image.Image:
    """The knob over the thin track: fill before it (left, or below), track after it."""
    w, h = size
    picture = Image.new("RGB", size, BG)
    draw = ImageDraw.Draw(picture)
    if vertical:
        draw.rectangle(((w - TRACK) // 2, 0, (w + TRACK) // 2 - 1, h // 2 - 1), fill=SURFACE)
        draw.rectangle(((w - TRACK) // 2, h // 2, (w + TRACK) // 2 - 1, h - 1), fill=fill)
    else:
        draw.rectangle((0, (h - TRACK) // 2, w // 2 - 1, (h + TRACK) // 2 - 1), fill=fill)
        draw.rectangle((w // 2, (h - TRACK) // 2, w - 1, (h + TRACK) // 2 - 1), fill=SURFACE)
    x0, y0 = (w - KNOB) // 2, (h - KNOB) // 2
    draw.ellipse((x0, y0, x0 + KNOB - 1, y0 + KNOB - 1), fill=KNOB_EDGE)
    draw.ellipse((x0 + 1, y0 + 1, x0 + KNOB - 2, y0 + KNOB - 2), fill=KNOB_COLOR)
    return picture


def midnight_sliders(out_dir: Path) -> int:
    for slot, (part, size, vertical) in THIN_SLIDERS.items():
        color = {"track": SURFACE, "fill": BLUE, "fill_on": AMBER}[part]
        thin_track(size, color, vertical).save(out_dir / f"picture-{slot:04d}.png")
    knob((36, 36), False, BLUE).save(out_dir / f"picture-{KNOB_H_SLOT:04d}.png")
    knob((85, 36), True, AMBER).save(out_dir / f"picture-{KNOB_V_SLOT:04d}.png")
    for slot, color in DARK_VOLUME.items():
        thin_track((244, 36), color, False, background=(0, 0, 0)).save(out_dir / f"picture-{slot:04d}.png")
    return len(THIN_SLIDERS) + 2 + len(DARK_VOLUME)


# Horizontal cover sliders (landscape only), for both themes: slot -> (theme, part).
# The slider shows its pic1 from the start to the value, and its pic after it.
COVER_SLIDER_SIZE = (420, 36)
COVER_SLIDERS = {  # dark slot -> (theme, part, top-left of the slider on the page)
    104: ("dark", "track", (30, 90)), 106: ("dark", "fill", (30, 90)),     # coverslider (above the tilt slider)
    20: ("dark", "track", (30, 136)), 19: ("dark", "fill", (30, 136)),     # coverslider2 (alone)
    108: ("dark", "track", (30, 164)), 110: ("dark", "fill", (30, 164)),   # tiltslider
}  # the Midnight ones (105, 107, 109, 111, 112, 113) are thin sliders, see THIN_SLIDERS


def shapes_background(shapes: list, size: tuple) -> Image.Image:
    picture = Image.new("RGBA", size, BG + (255,))
    draw = ImageDraw.Draw(picture)
    tiles = Image.new("L", size, 0)
    for x0, y0, x1, y1, radius, color in shapes:
        if color == TILE:
            ImageDraw.Draw(tiles).rounded_rectangle((x0, y0, x1, y1), radius, fill=255)
        else:
            draw.rounded_rectangle((x0, y0, x1, y1), radius, fill=color)
    picture.alpha_composite(tile_fill(tiles))
    return picture


def sprite_color(src: str) -> tuple:
    """The average color of a sprite's opaque pixels, to keep the dark theme's own colors."""
    sprite = Image.open(PICS_DIR / src).convert("RGBA")
    opaque = sprite.getchannel("A").point(lambda a: 255 if a > 127 else 0)
    return tuple(int(v) for v in ImageStat.Stat(sprite.convert("RGB"), mask=opaque).mean)


def cover_slider(theme: str, part: str, place: tuple) -> Image.Image:
    """A dark-theme horizontal cover slider part, on the wave background where the slider sits."""
    w, h = COVER_SLIDER_SIZE
    background = Image.open(PICS_DIR / f"background/background_{theme}_landscape.png").convert("RGB")
    picture = background.crop((place[0], place[1], place[0] + w, place[1] + h))
    color = sprite_color("cover/cover_slider_active.png" if part == "fill" else "cover/cover_slider_inactive.png")
    ImageDraw.Draw(picture).rounded_rectangle((0, 0, w - 1, h - 1), h // 2, fill=color)
    return picture


def source_for(src: str) -> str:
    """The light theme's own artwork is drawn for a white background: use the dark one."""
    src = src.replace("weather/light/", "weather/dark/")
    if src.startswith("cover/") and src.endswith("_light.png"):
        src = src[: -len("_light.png")] + ".png"
    return src


def generate(orientation: str) -> int:
    size = SIZES[orientation]
    out_dir = SRC_ROOT / f"nspanel_{orientation}" / "pictures"
    background = Image.new("RGBA", size, BG + (255,))
    written = 0
    for entry in yaml.safe_load((PICS_DIR / "mapping.yaml").read_text()):
        slot = entry.get("light")
        if slot is None or slot == entry.get("dark"):
            continue  # no light variant, or shared by both themes
        place = entry.get(orientation) or {}
        src = place.get("src") or entry.get("src")
        target = out_dir / f"picture-{slot:04d}.png"
        if entry["id"] == "background_light":
            picture = background
        elif src is None:
            continue  # deprecated slot without a source
        else:
            sprite = Image.open(PICS_DIR / source_for(src)).convert("RGBA")
            sprite = STYLES.get(entry["id"], as_is)(sprite)
            x, y = (int(v) for v in place.get("coordinates", "0,0").split(","))
            w, h = (int(v) for v in place.get("dimensions", f"{sprite.width}x{sprite.height}").split("x"))
            canvas = background.copy()
            canvas.alpha_composite(sprite, (x, y))
            picture = canvas.crop((x, y, x + w, y + h))
        redrawn = orientation == "landscape" and slot in THIN_SLIDERS  # replaced below, maybe at another size
        if target.exists() and not redrawn and Image.open(target).size != picture.size:
            raise SystemExit(f"ERROR: {entry['id']}: size {picture.size} differs from {target.name}")
        picture.convert("RGB").save(target)
        written += 1
    if orientation in HOME_SHAPES:
        shapes_background(HOME_SHAPES[orientation], size).convert("RGB").save(out_dir / f"picture-{HOME_SLOT:04d}.png")
        written += 1
    if orientation in MEDIA_SHAPES:
        shapes_background(MEDIA_SHAPES[orientation], size).convert("RGB").save(out_dir / f"picture-{MEDIA_SLOT:04d}.png")
        written += 1
    if orientation in COVER_SHAPES:
        shapes_background(COVER_SHAPES[orientation], size).convert("RGB").save(out_dir / f"picture-{COVER_SLOT:04d}.png")
        written += 1
    if orientation == "landscape":
        for slot, (theme, part, place) in COVER_SLIDERS.items():
            cover_slider(theme, part, place).save(out_dir / f"picture-{slot:04d}.png")
            written += 1
        written += midnight_sliders(out_dir)
    print(f"{orientation}: wrote {written} pictures to {out_dir}")
    return written


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which not in ("landscape", "portrait", "all"):
        raise SystemExit("Usage: generate_midnight.py [landscape|portrait|all]")
    for orientation in (("landscape", "portrait") if which == "all" else (which,)):
        generate(orientation)
