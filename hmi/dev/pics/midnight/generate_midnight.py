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
#   python3 generate_midnight.py [landscape|portrait|all] [--mdi-font FILE]   (default: all)
#
#   --mdi-font: materialdesignicons-webfont.ttf (npm package @mdi/font, Apache 2.0), for the
#   icons on the landscape light page tiles; without it those pictures are left as they are.
#
# Requirements:
#   - python3 with Pillow and PyYAML

import sys
from pathlib import Path

import yaml
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageStat

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
    143: ("track", (316, 36), False), 144: ("fill", (316, 36), False),  # media: progress
    72: ("track", (85, 235), True), 73: ("fill_on", (85, 235), True),   # light level and fan
}
# Dark-theme volume and progress sliders, now picture sliders too: track and fill as before, in pills
DARK_PILLS = {141: ((244, 36), (0x29, 0x2C, 0x29)), 142: ((244, 36), (0x84, 0x00, 0x42)),
              145: ((316, 36), (0x42, 0x00, 0x42)), 146: ((316, 36), (0x84, 0x00, 0x42))}


def thin_track(size: tuple, color: tuple, vertical: bool, background: tuple = BG, track: int = TRACK) -> Image.Image:
    picture = Image.new("RGB", size, background)
    w, h = size
    box = ((w - track) // 2, 0, (w + track) // 2 - 1, h - 1) if vertical else (0, (h - track) // 2, w - 1, (h + track) // 2 - 1)
    ImageDraw.Draw(picture).rounded_rectangle(box, track // 2, fill=color)
    return picture


def knob(size: tuple, vertical: bool, fill, track: int = TRACK, diameter: int = KNOB) -> Image.Image:
    """The knob over the thin track: fill before it (left, or below), track after it.
    With `fill` None (a gradient track), the knob is on the plain background."""
    w, h = size
    picture = Image.new("RGB", size, BG)
    draw = ImageDraw.Draw(picture)
    if fill is None:
        pass
    elif vertical:
        draw.rectangle(((w - track) // 2, 0, (w + track) // 2 - 1, h // 2 - 1), fill=SURFACE)
        draw.rectangle(((w - track) // 2, h // 2, (w + track) // 2 - 1, h - 1), fill=fill)
    else:
        draw.rectangle((0, (h - track) // 2, w // 2 - 1, (h + track) // 2 - 1), fill=fill)
        draw.rectangle((w // 2, (h - track) // 2, w - 1, (h + track) // 2 - 1), fill=SURFACE)
    x0, y0 = (w - diameter) // 2, (h - diameter) // 2
    draw.ellipse((x0, y0, x0 + diameter - 1, y0 + diameter - 1), fill=KNOB_EDGE)
    draw.ellipse((x0 + 1, y0 + 1, x0 + diameter - 2, y0 + diameter - 2), fill=KNOB_COLOR)
    return picture


def midnight_sliders(out_dir: Path) -> int:
    for slot, (part, size, vertical) in THIN_SLIDERS.items():
        color = {"track": SURFACE, "fill": BLUE, "fill_on": AMBER}[part]
        thin_track(size, color, vertical).save(out_dir / f"picture-{slot:04d}.png")
    knob((36, 36), False, BLUE).save(out_dir / f"picture-{KNOB_H_SLOT:04d}.png")
    knob((85, 36), True, AMBER).save(out_dir / f"picture-{KNOB_V_SLOT:04d}.png")
    for slot, (size, color) in DARK_PILLS.items():
        thin_track(size, color, False, background=(0, 0, 0)).save(out_dir / f"picture-{slot:04d}.png")
    return len(THIN_SLIDERS) + 2 + len(DARK_PILLS)


# Light page (landscape only): a column of icon tiles on the right, and horizontal sliders.
# The mode tiles are dual-state buttons, so their pictures carry the icon: normal and selected.
LIGHT_TILE = (74, 42)
LIGHT_TILES = {  # button -> (position, icon codepoint in the MDI webfont, dark normal/pressed, light normal/pressed)
    "light_button": ((396, 48), 0xF00DF, (22, 23), (76, 67)),   # mdi:brightness-6
    "temp_button": ((396, 96), 0xF050F, (24, 25), (77, 68)),    # mdi:thermometer
    "color_button": ((396, 144), 0xF03D8, (26, 27), (78, 69)),  # mdi:palette
}
LIGHT_SLOT = 147  # Midnight light page background: tiles behind the effect and power glyphs
LIGHT_SHAPES = {
    "landscape": [
        (396, 192, 469, 233, 12, TILE),
        (396, 240, 469, 281, 12, TILE),
    ],
}
LIGHT_SLIDER = ((24, 150), (352, 36))  # place and size of lightslider and tempslider
LIGHT_THIN = {148: "track", 149: "fill_on"}  # Midnight lightslider, with a thicker track
LIGHT_TRACK, LIGHT_KNOB = 20, 32
TEMP_TRACK, TEMP_KNOB = 14, 30
KNOB_AMBER_SLOT = 150  # knob of the Midnight lightslider
KNOB_TEMP_SLOT = 151  # knob of the Midnight tempslider, over the gradient
TEXT = (0xF2, 0xF4, 0xF7)
TEXT_SECONDARY = (0x9A, 0xA4, 0xB2)


def wave(place: tuple, size: tuple) -> Image.Image:
    """The dark-theme background under a component."""
    background = Image.open(PICS_DIR / "background/background_dark_landscape.png").convert("RGB")
    return background.crop((place[0], place[1], place[0] + size[0], place[1] + size[1]))


def icon_tile(font, codepoint: int, theme: str, selected: bool, place: tuple) -> Image.Image:
    w, h = LIGHT_TILE
    if theme == "dark":
        picture = wave(place, LIGHT_TILE)
        blue = sprite_color("cover/cover_slider_active.png")
        fill, edge, glyph = ((0x10, 0x30, 0x4C), blue, (0xFF, 0xFF, 0xFF)) if selected else ((0x29, 0x2C, 0x29), None, (0xCE, 0xCF, 0xCE))
        draw = ImageDraw.Draw(picture)
        draw.rounded_rectangle((0, 0, w - 1, h - 1), 12, fill=edge or fill)
        if edge:
            draw.rounded_rectangle((2, 2, w - 3, h - 3), 10, fill=fill)
    else:
        picture = Image.new("RGB", LIGHT_TILE, BG)
        if selected:
            draw = ImageDraw.Draw(picture)
            draw.rounded_rectangle((0, 0, w - 1, h - 1), 12, fill=BLUE)
            draw.rounded_rectangle((2, 2, w - 3, h - 3), 10, fill=BLUE_FILL)
        else:
            mask = Image.new("L", LIGHT_TILE, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), 12, fill=255)
            rgba = picture.convert("RGBA")
            rgba.alpha_composite(tile_fill(mask))
            picture = rgba.convert("RGB")
        glyph = TEXT if selected else TEXT_SECONDARY
    ImageDraw.Draw(picture).text((w / 2, h / 2), chr(codepoint), font=font, fill=glyph, anchor="mm")
    return picture


def light_page(out_dir: Path, mdi_font) -> int:
    written = 0
    if mdi_font is not None:
        font = ImageFont.truetype(str(mdi_font), 28)
        for place, codepoint, dark, light in LIGHT_TILES.values():
            for theme, slots in (("dark", dark), ("light", light)):
                for selected, slot in zip((False, True), slots):
                    icon_tile(font, codepoint, theme, selected, place).save(out_dir / f"picture-{slot:04d}.png")
                    written += 1
    else:
        print("light page tiles skipped: no --mdi-font given")
    place, size = LIGHT_SLIDER
    for slot, part in LIGHT_THIN.items():
        thin_track(size, AMBER if part == "fill_on" else SURFACE, False, track=LIGHT_TRACK).save(out_dir / f"picture-{slot:04d}.png")
    knob((36, 36), False, AMBER, LIGHT_TRACK, LIGHT_KNOB).save(out_dir / f"picture-{KNOB_AMBER_SLOT:04d}.png")
    # as narrow as the knob, so that little of the gradient is hidden beside it
    knob((TEMP_KNOB, 36), False, None, TEMP_TRACK, TEMP_KNOB).save(out_dir / f"picture-{KNOB_TEMP_SLOT:04d}.png")
    w, h = size
    for slot, src in ((28, "light/light_slider_level_inactive.png"), (29, "light/light_slider_level_active.png")):
        picture = wave(place, size)
        ImageDraw.Draw(picture).rounded_rectangle((0, 0, w - 1, h - 1), h // 2, fill=sprite_color(src))
        picture.save(out_dir / f"picture-{slot:04d}.png")
    # colour temperature: the colors down the middle of the vertical gradient, laid out so that its
    # top (the maximum) is on the right: a pill 20 high on the dark theme, with its line cursor, and a
    # thin one on Midnight, with a knob (which leaves a pixel or so of background beside it on the track)
    sprite = Image.open(PICS_DIR / "light/light_slider_temp.png").convert("RGBA")
    column = [sprite.getpixel((sprite.width // 2, y)) for y in range(sprite.height)]
    column = [c[:3] for c in column if c[3] > 250]
    line = Image.new("RGB", (len(column), 1))
    line.putdata(column[::-1])
    gradient = line.resize((w, h), Image.Resampling.BILINEAR)
    for slot, base, track in ((21, wave(place, size), 20), (71, Image.new("RGB", size, BG), TEMP_TRACK)):
        mask = Image.new("L", size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, (h - track) // 2, w - 1, (h + track) // 2 - 1), track // 2, fill=255)
        base.paste(gradient, mask=mask)
        base.save(out_dir / f"picture-{slot:04d}.png")
    written += len(LIGHT_THIN) + 2 + 4
    shapes_background(LIGHT_SHAPES["landscape"], SIZES["landscape"]).convert("RGB").save(out_dir / f"picture-{LIGHT_SLOT:04d}.png")
    return written + 1


# Climate page (landscape only), both themes: round -/+ buttons beside the target temperature on the
# page background. The heating pill and the round device buttons are not on the background: each
# crops one of the full-page tile pictures, so a hidden button leaves nothing behind. The sliders only
# keep the values the -/+ buttons step, so their pictures are the background under them: not shown.
# Its own pictures, so the water heater keeps picture-0037/0064.
CLIMATE_BG = {"light": 152, "dark": 153}
CLIMATE_ROUND = [((24, 66), "-"), ((396, 66), "+")]  # top-left of each 60x60 button, and its sign
CLIMATE_TILES = [((140, 196, 339, 251), 28),   # heating pill (a toggle with off)
                 ((44, 196, 99, 251), 28),     # button08, round
                 ((380, 196, 435, 251), 28)]   # button09, round
CLIMATE_TILE_PICS = {"light": (160, 161), "dark": (162, 163)}  # tiles, active tiles; see page_climate.h
CLIMATE_SLIDER_CURSORS = {168: BG, 169: (0, 0, 0)}  # Midnight, dark
CLIMATE_SLIDERS = {  # slot -> (theme, top-left on the page, width); track and fill alike
    154: ("light", (24, 282), 432), 155: ("light", (24, 282), 432),    # climateslider
    164: ("light", (24, 282), 212), 165: ("light", (24, 282), 212),    # slider_low, slider_high
    156: ("dark", (24, 282), 432), 157: ("dark", (24, 282), 432),      # climateslider
    158: ("dark", (24, 282), 212), 159: ("dark", (24, 282), 212),      # slider_low
    166: ("dark", (244, 282), 212), 167: ("dark", (244, 282), 212),    # slider_high
}


def climate_page(out_dir: Path) -> int:
    dark_bg = Image.open(PICS_DIR / "background/background_dark_landscape.png")
    backgrounds = {}
    for theme, slot in CLIMATE_BG.items():
        dark = theme == "dark"
        surface = (0x29, 0x2C, 0x29) if dark else TILE
        shapes = [(x, y, x + 59, y + 59, 30, surface) for (x, y), _ in CLIMATE_ROUND]
        picture = shapes_background(shapes, SIZES["landscape"], dark_bg if dark else None)
        draw = ImageDraw.Draw(picture)
        sign = (0xFF, 0xFF, 0xFF) if dark else TEXT
        for (x, y), kind in CLIMATE_ROUND:
            cx, cy = x + 30, y + 30
            draw.rectangle((cx - 11, cy - 1, cx + 11, cy + 1), fill=sign)
            if kind == "+":
                draw.rectangle((cx - 1, cy - 11, cx + 1, cy + 11), fill=sign)
        picture.convert("RGB").save(out_dir / f"picture-{slot:04d}.png")
        backgrounds[theme] = picture.convert("RGB")
        # tiles over the same background
        normal, active = CLIMATE_TILE_PICS[theme]
        base = picture.convert("RGBA")
        tiles = shapes_background([(*r, radius, surface) for r, radius in CLIMATE_TILES], SIZES["landscape"], base)
        tiles.convert("RGB").save(out_dir / f"picture-{normal:04d}.png")
        on = base.copy()
        draw = ImageDraw.Draw(on)
        edge, fill = ((0xFA, 0xA4, 0x20), (0x4A, 0x2E, 0x10)) if dark else (AMBER, AMBER_FILL)
        for (x0, y0, x1, y1), radius in CLIMATE_TILES:
            draw.rounded_rectangle((x0, y0, x1, y1), radius, fill=edge)
            draw.rounded_rectangle((x0 + 2, y0 + 2, x1 - 2, y1 - 2), radius - 2, fill=fill)
        on.convert("RGB").save(out_dir / f"picture-{active:04d}.png")
    for slot, (theme, (x, y), width) in CLIMATE_SLIDERS.items():
        backgrounds[theme].crop((x, y, x + width, y + 36)).save(out_dir / f"picture-{slot:04d}.png")
    # their cursors: one pixel of the background color
    for slot, color in CLIMATE_SLIDER_CURSORS.items():
        Image.new("RGB", (1, 1), color).save(out_dir / f"picture-{slot:04d}.png")
    return 3 * len(CLIMATE_BG) + len(CLIMATE_SLIDERS) + len(CLIMATE_SLIDER_CURSORS)


# Horizontal cover sliders (landscape only), for both themes: slot -> (theme, part).
# The slider shows its pic1 from the start to the value, and its pic after it.
COVER_SLIDER_SIZE = (420, 36)
COVER_SLIDERS = {  # dark slot -> (theme, part, top-left of the slider on the page)
    104: ("dark", "track", (30, 90)), 106: ("dark", "fill", (30, 90)),     # coverslider (above the tilt slider)
    20: ("dark", "track", (30, 136)), 19: ("dark", "fill", (30, 136)),     # coverslider2 (alone)
    108: ("dark", "track", (30, 164)), 110: ("dark", "fill", (30, 164)),   # tiltslider
}  # the Midnight ones (105, 107, 109, 111, 112, 113) are thin sliders, see THIN_SLIDERS


def shapes_background(shapes: list, size: tuple, base: Image.Image = None) -> Image.Image:
    picture = base.convert("RGBA") if base is not None else Image.new("RGBA", size, BG + (255,))
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


def generate(orientation: str, mdi_font=None) -> int:
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
        light_slots = {s for _, _, dark, light in LIGHT_TILES.values() for s in dark + light} | {21, 71}
        redrawn = orientation == "landscape" and (slot in THIN_SLIDERS or slot in light_slots)  # replaced below, at another size
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
        written += light_page(out_dir, mdi_font)
        written += climate_page(out_dir)
    print(f"{orientation}: wrote {written} pictures to {out_dir}")
    return written


if __name__ == "__main__":
    args = sys.argv[1:]
    mdi = None
    if "--mdi-font" in args:
        at = args.index("--mdi-font")
        mdi = Path(args[at + 1])
        del args[at:at + 2]
    which = args[0] if args else "all"
    if which not in ("landscape", "portrait", "all"):
        raise SystemExit("Usage: generate_midnight.py [landscape|portrait|all] [--mdi-font FILE]")
    for orientation in (("landscape", "portrait") if which == "all" else (which,)):
        generate(orientation, mdi if orientation == "landscape" else None)
