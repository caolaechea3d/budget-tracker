"""Simple charts drawn on a Tk canvas: a category donut and monthly bars."""

from __future__ import annotations

import math
import tkinter as tk
from datetime import date
from decimal import Decimal

TEXT = "#222222"
MUTED = "#6b7280"
GRID = "#e5e7eb"
FONT = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_BIG = ("Segoe UI", 13, "bold")
MAX_SLICES = 8


def _nice_step(maximum: float, ticks: int = 4) -> float:
    if maximum <= 0:
        return 1
    raw = maximum / ticks
    power = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * power:
            return m * power
    return 10 * power


def _short(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1000:
        return f"{value / 1000:.1f}k".replace(".0k", "k")
    return f"{value:.0f}"


def draw_donut(
    canvas: tk.Canvas,
    slices: list[tuple[str, Decimal, str, object]],
    center_title: str,
    center_value: str,
    empty_text: str = "No expenses in this period",
) -> None:
    """slices: (label, value, color, icon image or None), largest first."""
    canvas.delete("all")
    width, height = canvas.winfo_width(), canvas.winfo_height()
    if width < 50 or height < 50:
        return
    total = sum((s[1] for s in slices), Decimal("0"))
    if total <= 0:
        canvas.create_text(width / 2, height / 2, text=empty_text, fill=MUTED, font=FONT)
        return

    if len(slices) > MAX_SLICES:
        rest = sum((s[1] for s in slices[MAX_SLICES - 1:]), Decimal("0"))
        slices = [*slices[:MAX_SLICES - 1], ("Others", rest, "#c0c4cc", None)]

    size = min(height - 20, width * 0.5)
    x0, y0 = 16, (height - size) / 2
    start = 90.0
    for label, value, color, _ in slices:
        extent = -float(value / total) * 360
        if abs(extent) >= 359.99:
            canvas.create_oval(x0, y0, x0 + size, y0 + size, fill=color, outline="")
        else:
            canvas.create_arc(x0, y0, x0 + size, y0 + size, start=start, extent=extent,
                              fill=color, outline=canvas["background"], width=2)
        start += extent
    hole = size * 0.58
    cx, cy = x0 + size / 2, y0 + size / 2
    canvas.create_oval(cx - hole / 2, cy - hole / 2, cx + hole / 2, cy + hole / 2,
                       fill=canvas["background"], outline="")
    canvas.create_text(cx, cy - 10, text=center_title, fill=MUTED, font=FONT)
    canvas.create_text(cx, cy + 10, text=center_value, fill=TEXT, font=FONT_BIG)

    # Legend
    lx = x0 + size + 24
    row_h = 26
    ly = max(10, (height - row_h * len(slices)) / 2)
    for i, (label, value, color, image) in enumerate(slices):
        y = ly + i * row_h + row_h / 2
        canvas.create_rectangle(lx, y - 5, lx + 10, y + 5, fill=color, outline="")
        tx = lx + 16
        if image is not None:
            canvas.create_image(tx, y, image=image, anchor="w")
            tx += int(image.width()) + 6
        pct = float(value / total * 100)
        canvas.create_text(tx, y, text=label, anchor="w", fill=TEXT, font=FONT)
        canvas.create_text(width - 12, y, text=f"{value:,.2f}   {pct:4.1f}%", anchor="e", fill=MUTED, font=FONT)


def draw_bars(
    canvas: tk.Canvas,
    months: list[str],
    series: list[tuple[str, dict[str, Decimal], str]],
    highlight: str | None = None,
) -> None:
    """Grouped bars per month. series: (name, {month: value}, color)."""
    canvas.delete("all")
    width, height = canvas.winfo_width(), canvas.winfo_height()
    if width < 80 or height < 80:
        return
    left, right, top, bottom = 48, 12, 34, 34
    plot_w, plot_h = width - left - right, height - top - bottom
    maximum = max((float(v) for _, values, _ in series for v in values.values()), default=0)
    step = _nice_step(maximum)
    top_value = step * max(1, math.ceil(maximum / step)) if maximum > 0 else step * 4

    # Legend
    lx = left
    for name, _, color in series:
        canvas.create_rectangle(lx, 12, lx + 10, 22, fill=color, outline="")
        canvas.create_text(lx + 15, 17, text=name, anchor="w", fill=TEXT, font=FONT)
        lx += 20 + len(name) * 7 + 20

    # Grid + y labels
    ticks = int(round(top_value / step))
    for i in range(ticks + 1):
        value = step * i
        y = top + plot_h - plot_h * value / top_value
        canvas.create_line(left, y, width - right, y, fill=GRID)
        canvas.create_text(left - 6, y, text=_short(value), anchor="e", fill=MUTED, font=FONT)

    group_w = plot_w / max(1, len(months))
    bar_w = min(22, group_w * 0.7 / max(1, len(series)))
    for mi, month in enumerate(months):
        gx = left + mi * group_w + (group_w - bar_w * len(series)) / 2
        if month == highlight:
            canvas.create_rectangle(left + mi * group_w + 2, top, left + (mi + 1) * group_w - 2, top + plot_h,
                                    fill="#f3f4f6", outline="")
            canvas.tag_lower(canvas.find_all()[-1])
        for si, (_, values, color) in enumerate(series):
            value = float(values.get(month, 0))
            if value <= 0:
                continue
            x = gx + si * bar_w
            y = top + plot_h - plot_h * value / top_value
            canvas.create_rectangle(x, y, x + bar_w - 2, top + plot_h, fill=color, outline="")
        year, mon = map(int, month.split("-"))
        label = date(year, mon, 1).strftime("%b")
        if mon == 1 or mi == 0:
            label += f"\n{year}"
        canvas.create_text(left + mi * group_w + group_w / 2, top + plot_h + 6, text=label,
                           anchor="n", fill=TEXT if month == highlight else MUTED, font=FONT, justify="center")
    canvas.create_line(left, top + plot_h, width - right, top + plot_h, fill="#9ca3af")
