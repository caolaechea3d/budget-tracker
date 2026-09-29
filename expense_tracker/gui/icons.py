"""Colorful emoji icons for categories, drawn with Pillow when it's installed.

Without Pillow (or without a color emoji font) the app still works: `Icons.get` returns None and
`Icons.text` puts the plain emoji character in front of the name instead.
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
except ImportError:  # Pillow is optional
    Image = None

EMOJI_FONTS = [
    Path(r"C:\Windows\Fonts\seguiemj.ttf"),
    Path("/System/Library/Fonts/Apple Color Emoji.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
    Path("/usr/share/fonts/noto/NotoColorEmoji.ttf"),
]
# Bitmap emoji fonts (Apple, Noto) only load at specific sizes.
FONT_SIZES = (109, 160, 137, 96, 72, 64)
SUPERSAMPLE = 4


def _load_emoji_font():
    if Image is None:
        return None
    for path in EMOJI_FONTS:
        if not path.exists():
            continue
        for size in FONT_SIZES:
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return None


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


class Icons:
    """Creates and caches icon images. One instance per Tk root."""

    def __init__(self, master: tk.Misc, size: int = 20):
        self.master = master
        self.scale = max(1.0, master.winfo_fpixels("1i") / 96)
        self.size = round(size * self.scale)
        self._font = _load_emoji_font()
        self._cache: dict[tuple, tk.PhotoImage] = {}

    @property
    def enabled(self) -> bool:
        return self._font is not None

    def text(self, icon: str, name: str) -> str:
        """Label text to use next to (or instead of) an icon image."""
        return name if self.enabled else f"{icon}  {name}".strip()

    def get(self, icon: str, color: str = "#8d99ae", size: int | None = None, badge: bool = True):
        """A rounded colored badge with the emoji inside (PhotoImage), or None without Pillow."""
        if not self.enabled or not icon:
            return None
        size = size or self.size
        key = (icon, color, size, badge)
        if key not in self._cache:
            self._cache[key] = ImageTk.PhotoImage(self._render(icon, color, size, badge), master=self.master)
        return self._cache[key]

    def dot(self, color: str, size: int | None = None):
        """A plain colored circle (for chart legends)."""
        if Image is None:
            return None
        size = size or round(self.size * 0.6)
        key = ("dot", color, size)
        if key not in self._cache:
            big = size * SUPERSAMPLE
            img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
            ImageDraw.Draw(img).ellipse((0, 0, big - 1, big - 1), fill=color)
            self._cache[key] = ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS), master=self.master)
        return self._cache[key]

    def _render(self, icon: str, color: str, size: int, badge: bool):
        big = size * SUPERSAMPLE
        img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        if badge:
            r, g, b = _hex_to_rgb(color)
            ImageDraw.Draw(img).rounded_rectangle(
                (0, 0, big - 1, big - 1), radius=big // 4, fill=(r, g, b, 70)
            )
        glyph = self._glyph(icon.replace("\ufe0f", ""))
        if glyph is not None:
            inner = int(big * (0.68 if badge else 0.92))
            glyph.thumbnail((inner, inner), Image.LANCZOS)
            img.alpha_composite(glyph, ((big - glyph.width) // 2, (big - glyph.height) // 2))
        return img.resize((size, size), Image.LANCZOS)

    def _glyph(self, icon: str):
        canvas = Image.new("RGBA", (260, 260), (0, 0, 0, 0))
        try:
            ImageDraw.Draw(canvas).text((130, 130), icon, font=self._font, embedded_color=True, anchor="mm")
        except (OSError, ValueError):
            return None
        box = canvas.getbbox()
        return canvas.crop(box) if box else None


def enable_dpi_awareness() -> None:
    """Sharp text on high-DPI Windows displays."""
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except (ImportError, AttributeError, OSError):
            pass
