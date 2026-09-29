"""Render the map as a short video (one scene per layer) from a versioned map.json.

    python render/render_video.py maps/v2026.09.27.1/map.json                 # 1080x1350 map.mp4
    python render/render_video.py maps/v2026.09.27.1/map.json --vertical      # 1080x1920 map-vertical.mp4
    python render/render_video.py maps/v2026.09.27.1/map.json --seconds-per-layer 2.5 --fps 30

Scenes: intro (hook + title), one scene per layer (number, name, tools as chips, security control),
outro (CTA + version/expiry). Every string comes from map.json (tools, controls, copy); the -video.txt
sidecar is a content manifest of the strings the video uses, not proof of rendering. Every text run is
measured and shrunk or wrapped to stay inside SAFE_MARGIN of the frame and clear of other runs;
tests/test_render.py proves it by pixel-diffing each run on each scene. Layout is pinned to Pillow's
BASIC engine (via render_map.font). Frames are encoded with ffmpeg (H.264, yuv420p, faststart, silent
AAC track so Reels/Shorts accept it). Requires ffmpeg on PATH.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import render_map as RM  # palette, fonts, shield

FPS_DEFAULT = 30


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def blend(hex_color: str, alpha: float, bg: str = RM.BG) -> tuple:
    """Fake alpha for text on a flat background: mix the colour toward bg."""
    c = Image.new("RGB", (1, 1), hex_color).getpixel((0, 0))
    b = Image.new("RGB", (1, 1), bg).getpixel((0, 0))
    return tuple(int(b[i] + (c[i] - b[i]) * alpha) for i in range(3))


SAFE_MARGIN = 40  # px; no text pixel closer than this to a frame edge
FOOT_GAP = 32  # px between the bottom-left footer and the bottom-right progress counter
FOOT_BOTTOM = 84  # px from the bottom edge to the top of the footer line (descenders stay inside SAFE_MARGIN)


class Scene:
    def __init__(self, W: int, H: int, drawn: list[str], skip: frozenset[str] = frozenset()):
        self.W, self.H, self.drawn, self.skip = W, H, drawn, skip
        self.runs: list[tuple[str, tuple[float, float, float, float]]] = []  # (key, bbox) of the last frame
        self.sizes = {
            "hook": 92 if H > W else 84,
            "kicker": 30,
            "layer_no": 34,
            "layer": 96 if H > W else 88,
            "label": 26,
            "chip": 40,
            "ctrl": 44 if H > W else 40,
            "foot": 26,
            "cta": 76 if H > W else 68,
            "small": 34,
        }
        self.names = {"hook": "InterDisplay-Bold.ttf", "kicker": "JetBrainsMono-Medium.ttf",
                      "layer_no": "JetBrainsMono-Medium.ttf", "layer": "InterDisplay-Bold.ttf",
                      "label": "JetBrainsMono-Medium.ttf", "chip": "Inter-SemiBold.ttf", "ctrl": "Inter-SemiBold.ttf",
                      "foot": "JetBrainsMono-Regular.ttf", "cta": "InterDisplay-Bold.ttf", "small": "Inter-Regular.ttf"}
        self.f = {k: RM.font(self.names[k], v) for k, v in self.sizes.items()}

    # ---- measured text ----
    def fit(self, role: str, s: str, max_w: float):
        return RM.fit_font(s, self.names[role], self.sizes[role], max_w, min_size=12)

    def fit_wrap(self, role: str, s: str, max_w: float):
        return RM.fit_wrap(s, self.names[role], self.sizes[role], max_w, min_size=12)

    def text(self, d, key: str, xy, s: str, f, fill, dy: float = 0):
        """Draw one run (unless skipped) and record its bbox; dy shifts the recorded box (block moves)."""
        box = d.textbbox(xy, s, font=f)
        if key not in self.skip:
            d.text(xy, s, font=f, fill=fill)
        self.runs.append((key, (box[0], box[1] + dy, box[2], box[3] + dy)))

    def canvas(self):
        im = Image.new("RGB", (self.W, self.H), RM.BG)
        d = ImageDraw.Draw(im)
        for x in range(0, self.W, RM.GRID_STEP):
            d.rectangle((x, 0, x + 1, self.H), fill=RM.GRID)
        for y in range(0, self.H, RM.GRID_STEP):
            d.rectangle((0, y, self.W, y + 1), fill=RM.GRID)
        return im, d

    def chrome(self, d, copy, progress: str | None):
        m = 60
        h = copy.get("handle", "")
        f_h = self.fit("foot", h, self.W / 3)
        hx = self.W - m - d.textlength(h, font=f_h)
        kicker = copy.get("title", "").upper()
        f_k = self.fit("kicker", kicker, hx - FOOT_GAP - m)
        self.text(d, "kicker", (m, 40), kicker, f_k, RM.MUTED)
        self.text(d, "handle", (hx, 42), h, f_h, RM.MUTED)
        if progress:
            self.text(d, "progress", (self.W - m - d.textlength(progress, font=self.f["foot"]), self.H - FOOT_BOTTOM),
                      progress, self.f["foot"], RM.MUTED)
            return self.W - m - d.textlength(progress, font=self.f["foot"]) - FOOT_GAP
        return self.W - m

    def footer(self, d, key: str, s: str, right: float, fill):
        m = 80
        f = self.fit("foot", s, right - m)
        self.text(d, key, (m, self.H - FOOT_BOTTOM), s, f, fill)

    # ---- scenes ----
    def intro(self, t: float, copy: dict) -> Image.Image:
        self.runs = []
        im, d = self.canvas()
        right = self.chrome(d, copy, None)
        m = 80
        y = self.H * (0.30 if self.H > self.W else 0.26)
        a1, a2, a3 = ease(t / 0.6), ease((t - 0.5) / 0.6), ease((t - 1.1) / 0.6)
        hook1, hook2 = copy.get("video_hook", ""), copy.get("video_hook_accent", "")
        f1, lines1 = self.fit_wrap("hook", hook1, self.W - 2 * m) if hook1 else (None, [])
        for i, line in enumerate(lines1):
            self.text(d, f"hook.{i}", (m, y), line, f1, blend(RM.WHITE, a1)); y += round(f1.size * 108 / self.sizes["hook"])
        y += 20
        f2, lines2 = self.fit_wrap("hook", hook2, self.W - 2 * m) if hook2 else (None, [])
        for i, line in enumerate(lines2):
            self.text(d, f"hook_accent.{i}", (m, y), line, f2, blend(RM.ACCENT, a2)); y += round(f2.size * 108 / self.sizes["hook"])
        y += 60
        sub = copy.get("subtitle", "")
        f3, lines3 = self.fit_wrap("small", sub, self.W - 2 * m)
        for i, line in enumerate(lines3):
            self.text(d, f"subtitle.{i}", (m, y), line, f3, blend(RM.MUTED, a3)); y += 46
        self.footer(d, "version", copy.get("_version_line", ""), right, blend(RM.MUTED, a3))
        return im

    def layer(self, t: float, copy: dict, layer: dict, nxt: dict | None, idx: int, total: int) -> Image.Image:
        self.runs = []
        im, d = self.canvas()
        m = 80
        n = layer["number"]
        bar = RM.BARS.get(n, RM.BARS[1])
        a_head, a_tools, a_ctrl = ease(t / 0.4), ease((t - 0.25) / 0.5), ease((t - 0.6) / 0.5)
        top = 130
        y = top
        block: list[tuple] = []  # runs drawn inside the block that may be shifted down

        def T(key, xy, s, f, fill):
            box = d.textbbox(xy, s, font=f)
            if key not in self.skip:
                d.text(xy, s, font=f, fill=fill)
            block.append((key, box))

        T("layer_no", (m, y), f"LAYER {n:02d}", self.f["layer_no"], blend(bar, a_head)); y += 56
        f_name, name_lines = self.fit_wrap("layer", layer["name"], self.W - 2 * m)
        for i, line in enumerate(name_lines):
            T(f"name.{i}", (m, y), line, f_name, blend(RM.WHITE, a_head)); y += round(f_name.size * 104 / self.sizes["layer"])
        y += 30
        T("tools_label", (m, y), copy.get("column_tools", "TOOLS"), self.f["label"], blend(RM.MUTED, a_tools)); y += 50
        x = m
        chip_h = 64
        f_chip = self.f["chip"]
        widest = max((d.textlength(tl["name"], font=f_chip) for tl in layer["tools"]), default=0)
        if widest + 44 > self.W - 2 * m:  # one chip wider than the frame: shrink every chip's text
            widest_name = max(layer["tools"], key=lambda tl: d.textlength(tl["name"], font=f_chip))["name"]
            f_chip = self.fit("chip", widest_name, self.W - 2 * m - 44)
        for i, tool in enumerate(layer["tools"]):
            name = tool["name"]
            w = d.textlength(name, font=f_chip) + 44
            if x + w > self.W - m:
                x = m; y += chip_h + 16
            a = ease((t - 0.3 - i * 0.06) / 0.35)
            d.rounded_rectangle((x, y, x + w, y + chip_h), radius=12, fill=blend(RM.CARD, a), outline=blend(RM.CARD_BORDER, a), width=2)
            T(f"chip.{i}", (x + 22, y + 11), name, f_chip, blend(RM.WHITE, a))
            x += w + 16
        y += chip_h + 60
        f_ctrl, lines = self.fit_wrap("ctrl", layer["control"], self.W - 2 * m - 150)
        lh = round(f_ctrl.size * 56 / self.sizes["ctrl"])
        card_h = 60 + len(lines) * lh + 40
        box = (m, y, self.W - m, y + card_h)
        d.rounded_rectangle(box, radius=RM.RADIUS, fill=blend(RM.CTRL, a_ctrl), outline=blend(RM.CTRL_BORDER, a_ctrl), width=2)
        label = copy.get("column_control", "SECURITY CONTROL")
        T("ctrl_label", (m + 34, y + 24), label, self.fit("label", label, self.W - 2 * m - 68), blend(RM.ACCENT, a_ctrl))
        c = RM.Canvas(); c.im, c.d = im, d
        if a_ctrl > 0.5:
            RM.draw_shield(c, m + 60, y + 60 + len(lines) * lh // 2 + 10, hw=18, hh=22)
        ty = y + 66
        for i, line in enumerate(lines):
            T(f"ctrl.{i}", (m + 120, ty), line, f_ctrl, blend(RM.CTRL_TEXT, a_ctrl)); ty += lh
        y_end = y + card_h
        # centre the content block vertically (the 9:16 canvas has a lot of room)
        shift = int((self.H - (y_end - top)) / 2 - top)
        shift = max(0, min(shift, self.H - 140 - y_end))
        if shift:
            crop = im.crop((0, top - 20, self.W, y_end + 20))
            im, d = self.canvas()
            im.paste(crop, (0, top - 20 + shift))
        self.runs += [(k, (b[0], b[1] + shift, b[2], b[3] + shift)) for k, b in block]
        d.rounded_rectangle((m - 30, top - 10 + shift, m - 18, y_end + 10 + shift), radius=6, fill=blend(bar, a_head))
        right = self.chrome(d, copy, f"{idx:02d} / {total}")
        if nxt:
            self.footer(d, "next", f"NEXT \u2192 {nxt['number']:02d} {nxt['name']}", right, blend(RM.MUTED, a_ctrl))
        return im

    def outro(self, t: float, copy: dict, m_json: dict) -> Image.Image:
        self.runs = []
        im, d = self.canvas()
        right = self.chrome(d, copy, None)
        m = 80
        a1, a2 = ease(t / 0.5), ease((t - 0.4) / 0.6)
        y = self.H * 0.30
        f1, l1 = self.fit_wrap("cta", copy.get("cta", ""), self.W - 2 * m)
        for i, line in enumerate(l1):
            self.text(d, f"cta.{i}", (m, y), line, f1, blend(RM.WHITE, a1)); y += round(f1.size * 90 / self.sizes["cta"])
        f2, l2 = self.fit_wrap("cta", copy.get("cta_accent", ""), self.W - 2 * m)
        for i, line in enumerate(l2):
            self.text(d, f"cta_accent.{i}", (m, y), line, f2, blend(RM.ACCENT, a1)); y += round(f2.size * 90 / self.sizes["cta"])
        y += 50
        gov = " \u00b7 ".join(g.get("short") or g["name"] for g in m_json.get("governance", []))
        if gov:
            label = copy.get("governance_label", "GOVERN IT ALL")
            self.text(d, "gov_label", (m, y), label, self.fit("label", label, self.W - 2 * m), blend(RM.ACCENT, a2)); y += 44
            f_g, lines = self.fit_wrap("small", gov, self.W - 2 * m)
            for i, line in enumerate(lines):
                self.text(d, f"gov.{i}", (m, y), line, f_g, blend(RM.FOOT_TEXT, a2)); y += 46
        self.footer(d, "version", copy.get("_version_line", ""), right, blend(RM.MUTED, a2))
        return im


def scene_plan(m: dict, spl: float) -> list[tuple[str, float]]:
    return [("intro", 3.2)] + [("layer", spl)] * len(m["layers"]) + [("outro", 4.0)]


def render_scene(sc: Scene, m: dict, copy: dict, k: int, kind: str, t: float) -> Image.Image:
    layers = m["layers"]
    if kind == "intro":
        return sc.intro(t, copy)
    if kind == "outro":
        return sc.outro(t, copy, m)
    li = k - 1
    return sc.layer(t, copy, layers[li], layers[li + 1] if li + 1 < len(layers) else None, li + 1, len(layers))


def video_copy(m: dict) -> dict:
    copy = dict(m.get("copy", {}))
    copy["_version_line"] = RM.version_line(m, repo=False)
    return copy


def build_frames(m: dict, W: int, H: int, fps: int, spl: float, out_dir: Path) -> tuple[int, list[str]]:
    copy = video_copy(m)
    drawn: list[str] = []
    sc = Scene(W, H, drawn)
    layers = m["layers"]
    frame = 0
    for k, (kind, dur) in enumerate(scene_plan(m, spl)):
        n = int(round(dur * fps))
        for i in range(n):
            im = render_scene(sc, m, copy, k, kind, i / fps)
            im.save(out_dir / f"f{frame:05d}.png", "PNG", compress_level=1)
            frame += 1
    # content manifest: every string the video uses (tools, names, controls, copy)
    for layer in layers:
        drawn += [layer["name"], layer["control"]] + [t["name"] for t in layer["tools"]]
    drawn += [v for k, v in copy.items() if not k.startswith("_")] + [copy["_version_line"]]
    drawn += [g.get("short") or g["name"] for g in m.get("governance", [])]
    return frame, drawn


def encode(frames_dir: Path, fps: int, out: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg not found on PATH; frames are in " + str(frames_dir))
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(frames_dir / "f%05d.png"),
           "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
           "-shortest", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-r", str(fps), "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("map_json", type=Path)
    ap.add_argument("--vertical", action="store_true", help="1080x1920 instead of 1080x1350")
    ap.add_argument("--fps", type=int, default=FPS_DEFAULT)
    ap.add_argument("--seconds-per-layer", type=float, default=2.8)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--keep-frames", action="store_true")
    RM.add_expiry_args(ap)
    args = ap.parse_args(argv)
    m = json.loads(args.map_json.read_text(encoding="utf-8"))
    RM.refuse_if_expired(m, dt.date.fromisoformat(args.today) if args.today else dt.date.today(), args.historical)
    W, H = (1080, 1920) if args.vertical else (1080, 1350)
    out = args.out or args.map_json.with_name("map-vertical.mp4" if args.vertical else "map.mp4")
    tmp = Path(tempfile.mkdtemp(prefix="mapvid-"))
    try:
        n, drawn = build_frames(m, W, H, args.fps, args.seconds_per_layer, tmp)
        encode(tmp, args.fps, out)
    finally:
        if not args.keep_frames:
            shutil.rmtree(tmp, ignore_errors=True)
    sidecar = out.with_name(out.stem + "-video.txt")  # not map.txt: that one belongs to the PNG
    sidecar.write_text("\n".join(drawn) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out.name} ({W}x{H}, {n} frames @ {args.fps} fps = {n / args.fps:.1f}s) and {sidecar.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
