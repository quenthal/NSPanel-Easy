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
# themes (splash, slider cursors) are left alone. The landscape home page
# also gets its own background (HOME_SLOT), drawn from HOME_SHAPES.
#
# Usage:
#   python3 generate_midnight.py [landscape|portrait|all]   (default: all)
#
# Requirements:
#   - python3 with Pillow and PyYAML

import sys
from pathlib import Path

import yaml
from PIL import Image, ImageChops, ImageDraw, ImageFilter

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

BORDER = 3  # Border width of outlined shapes, in pixels


def solid(alpha: Image.Image, color: tuple) -> Image.Image:
    """A sprite of one color, shaped by `alpha`."""
    out = Image.new("RGBA", alpha.size, color + (0,))
    out.putalpha(alpha)
    return out


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
    "buttons_pages_background_innactive": tint(SURFACE),
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
    "settings_button_action_reboot": tint(SURFACE),
    "settings_button_action_sleep": tint(SURFACE),
    "settings_button_action_theme": tint(SURFACE),
}
for n in range(1, 6):
    STYLES[f"fan_mode_{n}_active_light"] = outlined(BLUE_FILL, BLUE)
    STYLES[f"fan_mode_{n}_inactive_light"] = tint(SURFACE)


# Home page background (landscape only, its own slot after the mapped pictures):
# the shapes behind the home components, as (x0, y0, x1, y1, radius, color).
HOME_SLOT = 134
HOME_SHAPES = {
    "landscape": [
        (8, 34, 471, 166, 18, SURFACE_HI),  # card outline: temperatures, time, weather, values
        (10, 36, 469, 164, 16, BG),         # card inside, plain so the weather picture blends in
        (236, 46, 237, 154, 0, SURFACE_HI),  # card divider
        (8, 216, 117, 280, 16, SURFACE),    # tiles for button01..button04
        (125, 216, 234, 280, 16, SURFACE),
        (242, 216, 351, 280, 16, SURFACE),
        (359, 216, 468, 280, 16, SURFACE),
        (8, 284, 471, 318, 12, SURFACE),    # strip behind the hardware buttons' labels
        (239, 290, 240, 312, 0, SURFACE_HI),  # strip divider
    ],
}


def home_background(orientation: str, size: tuple) -> Image.Image:
    picture = Image.new("RGBA", size, BG + (255,))
    draw = ImageDraw.Draw(picture)
    for x0, y0, x1, y1, radius, color in HOME_SHAPES[orientation]:
        draw.rounded_rectangle((x0, y0, x1, y1), radius, fill=color)
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
        if target.exists() and Image.open(target).size != picture.size:
            raise SystemExit(f"ERROR: {entry['id']}: size {picture.size} differs from {target.name}")
        picture.convert("RGB").save(target)
        written += 1
    if orientation in HOME_SHAPES:
        home_background(orientation, size).convert("RGB").save(out_dir / f"picture-{HOME_SLOT:04d}.png")
        written += 1
    print(f"{orientation}: wrote {written} pictures to {out_dir}")
    return written


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which not in ("landscape", "portrait", "all"):
        raise SystemExit("Usage: generate_midnight.py [landscape|portrait|all]")
    for orientation in (("landscape", "portrait") if which == "all" else (which,)):
        generate(orientation)
