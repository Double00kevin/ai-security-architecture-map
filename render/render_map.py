"""Render the AI Architecture Map PNG from a versioned map.json.

    python render/render_map.py maps/v2026.09.27/map.json            # writes map.png next to it
    python render/render_map.py maps/v2026.09.27/map.json -o out.png

Every string on the picture comes from map.json (tools, controls, governance, copy). The renderer
also writes <output>.txt, a content manifest listing every string it asked to draw. The manifest is
not proof of rendering (it cannot show clipping or overlap); tests/test_render.py proves that by
pixel-diffing each text run.

Text layout is pinned to Pillow's BASIC engine so output does not depend on whether libraqm is
installed. Every text run is measured and shrunk or wrapped to fit inside SAFE_MARGIN of the canvas
and inside its own box.

Look: reproduces map v2026.09.26 (2160x2700, dark navy, three-column cards, colour bar per layer group).
Fonts: Inter and JetBrains Mono, both SIL OFL, bundled in render/fonts/ with their licences.
Dependencies: Pillow only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import functools
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONTS = HERE / "fonts"

# ---- palette (sampled from the v2026.09.26 PNG) ----
BG = "#0a0f1e"
GRID = "#101627"
CARD = "#111830"
CARD_BORDER = "#243055"
CTRL = "#221625"
CTRL_BORDER = "#853445"
SHIELD_BG = "#281c2e"
WHITE = "#eef2ff"
TOOLS_TEXT = "#c9d1ea"
MUTED = "#8a96b8"
CTRL_TEXT = "#f3d9dc"
ACCENT = "#ff5c6c"
FOOT_BG = "#101627"
FOOT_BORDER = "#9d3d4c"
FOOT_TEXT = "#dde3f7"
BARS = {1: "#5b8cff", 2: "#5b8cff", 3: "#a77bff", 4: "#a77bff", 5: "#2fd1b5", 6: "#2fd1b5", 7: "#2fd1b5",
        8: "#2fd1b5", 9: "#ffb547", 10: "#ffb547", 11: "#ffb547", 12: "#7bd66a"}

# ---- geometry (pixels on the 2160x2700 canvas) ----
W, H = 2160, 2700
GRID_STEP = 108
MARGIN_L, MARGIN_R = 80, 2080
ROW_TOP, ROW_PITCH, ROW_H = 333, 168, 153
RADIUS = 14
BAR_W = 12
COL_LAYER = (80, 601)
COL_TOOLS = (634, 1377)
COL_CTRL = (1410, 2051)
HEADER_Y = 292
TITLE_Y = 64
SUBTITLE_Y = 186
FOOT = (84, 2362, 2076, 2444)
CTA_Y = 2522
VERSION_Y = 2604  # version / review line under the CTA; its text must stay above H - SAFE_MARGIN
SAFE_MARGIN = 48  # no text pixel may land closer than this to the canvas edge
LAYOUT = ImageFont.Layout.BASIC  # pinned: identical output with or without libraqm


@functools.lru_cache(maxsize=None)
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), int(size), layout_engine=LAYOUT)


@functools.lru_cache(maxsize=65536)
def _length(s: str, f) -> float:
    return f.getlength(s)


def text_width(s: str, f, spacing: float = 0.0) -> float:
    return _length(s, f) + spacing * max(len(s) - 1, 0)


def wrap(s: str, f, max_w: float, spacing: float = 0.0) -> list[str]:
    words, lines, cur = s.split(" "), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if cur and text_width(trial, f, spacing) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def fit_font(s: str, name: str, size: int, max_w: float, min_size: int = 12, spacing: float = 0.0):
    """Largest font <= size whose one-line width of s fits max_w."""
    f = font(name, size)
    while text_width(s, f, spacing) > max_w and f.size > min_size:
        f = font(name, f.size - 1)
    return f


def fit_wrap(s: str, name: str, size: int, max_w: float, max_lines: int | None = None, min_size: int = 12):
    """Wrap s to max_w; shrink the font until no line overflows (a single long word) and, if given, the
    paragraph has at most max_lines. Returns (font, lines)."""
    f = font(name, size)
    while True:
        lines = wrap(s, f, max_w)
        if (all(text_width(ln, f) <= max_w for ln in lines) and (max_lines is None or len(lines) <= max_lines)) \
                or f.size <= min_size:
            return f, lines
        f = font(name, f.size - 1)


class Canvas:
    def __init__(self, skip: frozenset[str] = frozenset()) -> None:
        self.im = Image.new("RGB", (W, H), BG)
        self.d = ImageDraw.Draw(self.im)
        self.drawn: list[str] = []  # content manifest for the sidecar
        self.runs: list[tuple[str, tuple[float, float, float, float]]] = []  # (key, layout bbox) per text run
        self.skip = skip  # run keys NOT to draw (tests: pixel-diff each run)

    # -- primitives --
    def run(self, key: str, xy, s: str, f, fill, spacing: float = 0.0) -> float:
        """Draw one text run at xy; returns the x after it. Layout never depends on `skip`."""
        x, y = xy
        if not spacing:
            box = self.d.textbbox((x, y), s, font=f)
            if key not in self.skip:
                self.d.text((x, y), s, font=f, fill=fill)
            end = x + text_width(s, f)
        else:
            x0, boxes = x, []
            for ch in s:
                boxes.append(self.d.textbbox((x, y), ch, font=f))
                if key not in self.skip:
                    self.d.text((x, y), ch, font=f, fill=fill)
                x += text_width(ch, f) + spacing
            box = (x0, min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
            end = x
        self.runs.append((key, box))
        return end

    def text(self, key, xy, s, f, fill, spacing: float = 0.0) -> float:
        self.drawn.append(s)
        return self.run(key, xy, s, f, fill, spacing)

    def width(self, s, f, spacing: float = 0.0) -> float:
        return text_width(s, f, spacing)

    def wrap(self, s: str, f, max_w: float) -> list[str]:
        return wrap(s, f, max_w)

    def paragraph(self, key, xy, lines, f, fill, line_h, valign_box_h=None, s=None):
        x, y = xy
        if valign_box_h is not None:
            block = line_h * len(lines) - (line_h - f.size)  # tighten last line
            y = y + (valign_box_h - block) / 2 - f.size * 0.18
        for i, ln in enumerate(lines):
            self.run(f"{key}.{i}", (x, y), ln, f, fill)
            y += line_h
        self.drawn.append(s if s is not None else " ".join(lines))
        return lines

    def rrect(self, box, fill=None, outline=None, width=2, radius=RADIUS):
        self.d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

    def dashed_rrect(self, box, color, radius=12, dash=14, gap=10, width=2):
        # rounded corners solid, straight edges dashed
        x0, y0, x1, y1 = box
        self.d.rounded_rectangle(box, radius=radius, outline=color, width=width)
        # punch gaps into the straight edges by painting FOOT_BG over the line
        for x in range(x0 + radius + dash, x1 - radius, dash + gap):
            self.d.rectangle((x, y0, min(x + gap, x1 - radius), y0 + width - 1), fill=BG)
            self.d.rectangle((x, y1 - width + 1, min(x + gap, x1 - radius), y1), fill=BG)
        for y in range(y0 + radius + dash, y1 - radius, dash + gap):
            self.d.rectangle((x0, y, x0 + width - 1, min(y + gap, y1 - radius)), fill=BG)
            self.d.rectangle((x1 - width + 1, y, x1, min(y + gap, y1 - radius)), fill=BG)


def draw_grid(c: Canvas) -> None:
    for x in range(0, W, GRID_STEP):
        c.d.rectangle((x, 0, x + 1, H), fill=GRID)
    for y in range(0, H, GRID_STEP):
        c.d.rectangle((0, y, W, y + 1), fill=GRID)


def _quad(p0, p1, p2, n=12):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in (i / n for i in range(n + 1))]


def draw_shield(c: Canvas, cx: int, cy: int, hw: int = 15, hh: int = 18) -> None:
    """Outline shield with a check mark, like the original: flat top, straight sides, curved point."""
    top, side_end = cy - hh, cy + hh * 0.05
    pts = [(cx - hw, top), (cx + hw, top), (cx + hw, side_end)]
    pts += _quad((cx + hw, side_end), (cx + hw, cy + hh * 0.85), (cx, cy + hh))
    pts += _quad((cx, cy + hh), (cx - hw, cy + hh * 0.85), (cx - hw, side_end))
    c.d.line(pts + [pts[0], pts[1]], fill=ACCENT, width=4, joint="curve")
    c.d.line([(cx - hw * 0.45, cy - hh * 0.05), (cx - hw * 0.1, cy + hh * 0.3), (cx + hw * 0.5, cy - hh * 0.4)],
             fill=ACCENT, width=4, joint="curve")


def draw_card_with_bar(c: Canvas, box, bar_color: str) -> None:
    x0, y0, x1, y1 = box
    mask = Image.new("L", (x1 - x0 + 1, y1 - y0 + 1), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, x1 - x0, y1 - y0), radius=RADIUS, fill=255)
    layer = Image.new("RGB", mask.size, CARD)
    ImageDraw.Draw(layer).rectangle((0, 0, BAR_W - 1, y1 - y0), fill=bar_color)
    c.im.paste(layer, (x0, y0), mask)
    c.d.rounded_rectangle(box, radius=RADIUS, outline=CARD_BORDER, width=2)
    # the bar covers the left border
    c.d.rectangle((x0 + 2, y0 + RADIUS, x0 + BAR_W - 1, y1 - RADIUS), fill=bar_color)


def render(m: dict, skip: frozenset[str] = frozenset()) -> Canvas:
    c = Canvas(skip)
    draw_grid(c)
    copy = m.get("copy", {})
    inner = W - 2 * SAFE_MARGIN

    f_hdr = font("JetBrainsMono-Medium.ttf", 22)
    f_num = font("JetBrainsMono-Regular.ttf", 24)
    f_foot_label = font("JetBrainsMono-Medium.ttf", 22)
    f_handle = font("JetBrainsMono-Regular.ttf", 34)

    # title + subtitle (each shrinks to fit the margins)
    t1, t2 = copy.get("title", m.get("title", "")) + " \u2014 ", copy.get("title_accent", "")
    f_title = fit_font(t1 + t2, "InterDisplay-Bold.ttf", 102, MARGIN_R - MARGIN_L, min_size=60)
    x = c.text("title", (MARGIN_L, TITLE_Y), t1, f_title, WHITE)
    c.text("title_accent", (x, TITLE_Y), t2, f_title, ACCENT)
    sub = copy.get("subtitle", "")
    f_sub = fit_font(sub, "Inter-Regular.ttf", 38, MARGIN_R - MARGIN_L, min_size=24)
    c.text("subtitle", (MARGIN_L, SUBTITLE_Y), sub, f_sub, MUTED)

    # column headers (each must stay inside its column)
    for key, col, label, colour in (("hdr_layer", COL_LAYER, copy.get("column_layer", "LAYER"), MUTED),
                                    ("hdr_tools", COL_TOOLS, copy.get("column_tools", "TOOLS"), MUTED),
                                    ("hdr_control", COL_CTRL, copy.get("column_control", "SECURITY CONTROL"), ACCENT)):
        f = fit_font(label, "JetBrainsMono-Medium.ttf", 22, col[1] - col[0] - 8, spacing=6)
        c.text(key, (col[0] + (4 if key == "hdr_layer" else 0), HEADER_Y), label, f, colour, spacing=6)

    # rows
    for i, layer in enumerate(m["layers"]):
        y0 = ROW_TOP + i * ROW_PITCH
        y1 = y0 + ROW_H
        n = layer["number"]
        k = f"L{n:02d}"
        # layer card
        draw_card_with_bar(c, (COL_LAYER[0], y0, COL_LAYER[1], y1), BARS.get(n, "#5b8cff"))
        f_layer, name_lines = fit_wrap(layer["name"], "Inter-Bold.ttf", 38, 350, max_lines=3)
        lh = round(f_layer.size * 46 / 38)
        block_h = lh * len(name_lines)
        ty = y0 + (ROW_H - block_h) / 2 - 4
        c.text(f"{k}.num", (COL_LAYER[0] + 44, ty + (block_h - 24) / 2 - 2), f"{n:02d}", f_num, MUTED)
        for j, ln in enumerate(name_lines):
            c.run(f"{k}.name.{j}", (172, ty + lh * j), ln, f_layer, WHITE)
        c.drawn.append(layer["name"])
        # tools card
        c.rrect((COL_TOOLS[0], y0, COL_TOOLS[1], y1), fill=CARD, outline=CARD_BORDER)
        tools = " \u00b7 ".join(t["name"] for t in layer["tools"])
        f_tools, lines = fit_wrap(tools, "Inter-Regular.ttf", 32, COL_TOOLS[1] - COL_TOOLS[0] - 60, max_lines=3, min_size=20)
        c.paragraph(f"{k}.tools", (COL_TOOLS[0] + 30, y0), lines, f_tools, TOOLS_TEXT, round(f_tools.size * 42 / 32), ROW_H, s=tools)
        for t in layer["tools"]:
            c.drawn.append(t["name"])
        # control card
        c.rrect((COL_CTRL[0], y0, COL_CTRL[1], y1), fill=CTRL, outline=CTRL_BORDER)
        draw_shield(c, COL_CTRL[0] + 48, (y0 + y1) // 2)
        f_ctrl, lines = fit_wrap(layer["control"], "Inter-Regular.ttf", 30, COL_CTRL[1] - COL_CTRL[0] - 112, max_lines=3, min_size=20)
        c.paragraph(f"{k}.ctrl", (COL_CTRL[0] + 90, y0), lines, f_ctrl, CTRL_TEXT, round(f_ctrl.size * 40 / 30), ROW_H, s=layer["control"])

    # governance footer: label and list share one line inside the dashed box
    if m.get("governance"):
        c.d.rounded_rectangle(FOOT, radius=12, fill=FOOT_BG)
        c.dashed_rrect(FOOT, FOOT_BORDER)
        fy = FOOT[1] + (FOOT[3] - FOOT[1]) / 2
        label = copy.get("governance_label", "GOVERN IT ALL")
        f_lab = fit_font(label, "JetBrainsMono-Medium.ttf", 22, (FOOT[2] - FOOT[0]) * 0.3, spacing=6)
        x = c.text("gov_label", (FOOT[0] + 34, fy - 14), label, f_lab, ACCENT, spacing=6)
        gov = " \u00b7 ".join(g.get("short") or g["name"] for g in m["governance"])
        gx = x + 28
        f_g = fit_font(gov, "Inter-Regular.ttf", 32, FOOT[2] - 30 - gx, min_size=16)  # shrink rather than overflow
        c.text("gov", (gx, fy - f_g.size * 0.68), gov, f_g, FOOT_TEXT)
        for g in m["governance"]:
            c.drawn.append(g.get("short") or g["name"])

    # CTA + handle: the handle is right-aligned; the CTA must end before it
    handle = copy.get("handle", "")
    hx = MARGIN_R - text_width(handle, f_handle)
    cta, cta2 = copy.get("cta", "") + " ", copy.get("cta_accent", "")
    f_cta = fit_font(cta + cta2, "Inter-Bold.ttf", 44, hx - 40 - MARGIN_L, min_size=20)
    x = c.text("cta", (MARGIN_L, CTA_Y), cta, f_cta, WHITE)
    c.text("cta_accent", (x, CTA_Y), cta2, f_cta, ACCENT)
    c.text("handle", (hx, CTA_Y + 10), handle, f_handle, MUTED)

    # provenance + review deadline: a reposted PNG still says which version it is and when it lapses
    line = version_line(m)
    f_ver = fit_font(line, "JetBrainsMono-Regular.ttf", 26, MARGIN_R - MARGIN_L, min_size=16)
    c.text("version", (MARGIN_L, VERSION_Y), line, f_ver, MUTED)
    return c


def version_line(m: dict, repo: bool = True) -> str:
    """Provenance and deadline printed on every shareable render, built only from map.json: the map
    version, the oldest review behind it, when it is due for review, and where the receipts live."""
    if m.get("schema_version", 1) >= 3:  # checks may be a review or an automated re-check
        parts = [f"map {m['version']}", f"checked {m.get('oldest_check') or m['date']}", f"re-check due {m['expires']}"]
    else:
        parts = [f"map {m['version']}", f"oldest review {m.get('oldest_review') or m['date']}", f"review due {m['expires']}"]
    if repo and m.get("copy", {}).get("repo"):
        parts.append(m["copy"]["repo"])
    return " \u00b7 ".join(parts)


def refuse_if_expired(m: dict, today: dt.date, historical: bool) -> None:
    """An expired map is not re-rendered as if it were current. --historical renders it anyway,
    for archives and for `drift map verify`."""
    exp = m.get("expires")
    if not exp:
        raise SystemExit("map.json has no `expires`; refusing to render")
    if dt.date.fromisoformat(exp) < today and not historical:
        raise SystemExit(f"{m.get('version')} expired on {exp}; refusing to render (pass --historical to render an archive copy)")


def add_expiry_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--historical", action="store_true", help="render even if the map has expired (archive copy)")
    ap.add_argument("--today", help=argparse.SUPPRESS)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("map_json", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="output PNG (default: map.png next to map.json)")
    add_expiry_args(ap)
    args = ap.parse_args(argv)
    m = json.loads(args.map_json.read_text(encoding="utf-8"))
    refuse_if_expired(m, dt.date.fromisoformat(args.today) if args.today else dt.date.today(), args.historical)
    out = args.out or args.map_json.with_name("map.png")
    c = render(m)
    c.im.save(out, "PNG", optimize=True)
    sidecar = out.with_suffix(".txt")
    sidecar.write_text("\n".join(c.drawn) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out.name} ({W}x{H}) and {sidecar.name} ({len(c.drawn)} strings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
