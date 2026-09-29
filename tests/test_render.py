"""The rendered map draws every tool name from map.json, spelled exactly the same."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "render"))
import render_map as RM  # noqa: E402

from drift import mapgen as M  # noqa: E402
from drift import registry as R  # noqa: E402
from tests.conftest import claim  # noqa: E402

CTL = [{"layer": i, "name": f"Layer {i}", "control": f"Control {i}"} for i in range(1, 13)]


def mini_map():
    claims = [claim(id=f"L{layer:02d}-t{k}", layer=layer, layer_name=f"Layer {layer}", tool=f"Tool {layer}.{k} (x)")
              for layer, n in enumerate(R.LAYER_COUNTS, start=1) for k in range(n)]
    return M.build_map(claims, CTL, "v2026.09.27",
                       governance=[{"name": "NIST AI RMF", "source_url": "https://www.nist.gov/itl/ai-risk-management-framework"}],
                       copy=M.load_copy())


def names_in(m):
    return [t["name"] for layer in m["layers"] for t in layer["tools"]]


def test_sidecar_lists_every_tool_exactly(tmp_path):
    m = mini_map()
    p = tmp_path / "map.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    assert RM.main([str(p), "-o", str(tmp_path / "map.png"), "--today", "2026-09-28"]) == 0
    drawn = (tmp_path / "map.txt").read_text(encoding="utf-8").splitlines()
    missing = [n for n in names_in(m) if n not in drawn]
    assert missing == []
    assert (tmp_path / "map.png").stat().st_size > 50_000
    from PIL import Image
    assert Image.open(tmp_path / "map.png").size == (RM.W, RM.H)


def test_every_string_drawn_comes_from_map_json(tmp_path):
    """Nothing hard-coded sneaks onto the picture: every drawn string is in map.json (tools, controls, copy, governance)."""
    m = mini_map()
    c = RM.render(m)
    allowed = set(names_in(m)) | {layer["control"] for layer in m["layers"]} | {layer["name"] for layer in m["layers"]}
    allowed |= set(m["copy"].values()) | {g["short"] for g in m["governance"]} | {f"{i:02d}" for i in range(1, 13)}
    allowed |= {" · ".join(names_in(m)[a:b]) for a in range(0, 70) for b in range(a, 70)}  # joined tool lines
    allowed |= {" · ".join(g["short"] for g in m["governance"]), m["copy"]["title"] + " — ", m["copy"]["cta"] + " "}
    allowed |= {RM.version_line(m)}  # built only from map.json fields (version, oldest_review/date, expires, copy.repo)
    stray = [s for s in c.drawn if s not in allowed]
    assert stray == []


def test_latest_real_map_json_renders_all_tools(tmp_path):
    p = M.latest_map()
    if not p.exists():
        pytest.skip("no map built")
    m = json.loads(p.read_text(encoding="utf-8"))
    c = RM.render(m)
    assert all(n in c.drawn for n in names_in(m)) and len(names_in(m)) == sum(R.LAYER_COUNTS)


def test_video_frames_and_sidecar_cover_every_tool(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "render"))
    import render_video as RV
    m = mini_map()
    n, drawn = RV.build_frames(m, 540, 675, fps=2, spl=0.5, out_dir=tmp_path)  # tiny canvas, 2 fps: fast
    assert n == round(3.2 * 2) + 12 * 1 + round(4.0 * 2)
    assert all(name in drawn for name in names_in(m))
    assert all(layer["control"] in drawn for layer in m["layers"])
    assert len(list(tmp_path.glob("f*.png"))) == n


@pytest.mark.parametrize("script", ["render_map", "render_video"])
def test_renderers_refuse_expired_map_unless_historical(tmp_path, script):
    mod = __import__(script)
    m = mini_map()  # expires 2026-10-27
    p = tmp_path / "map.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(SystemExit, match="expired"):
        mod.main([str(p), "-o", str(tmp_path / "out.bin"), "--today", "2026-10-28"])
    if script == "render_map":
        assert mod.main([str(p), "-o", str(tmp_path / "old.png"), "--today", "2026-10-28", "--historical"]) == 0


# ---- F13 / F14: every text run is visible, inside the safe margin, and clear of every other run ----
#
# Bounding boxes from the layout engine are not enough (they can't see clipping by the frame edge or a
# run painted over by a later one). So each frame is rendered once in full and once per text run with
# that run suppressed; the changed pixels are exactly what that run put on screen.

from PIL import Image, ImageChops, ImageFont  # noqa: E402


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def assert_runs_visible_inside_and_apart(render, size, margin, label):
    full, runs = render(frozenset())
    keys = [k for k, _ in runs]
    assert len(keys) == len(set(keys)), f"{label}: duplicate run keys {keys}"
    regions = {}
    for k in keys:
        without, _ = render(frozenset({k}))
        box = ImageChops.difference(full, without).getbbox()
        assert box is not None, f"{label}: run {k!r} changes no pixel (invisible or fully covered)"
        W, H = size
        assert margin <= box[0] and box[2] <= W - margin and margin <= box[1] and box[3] <= H - margin, \
            f"{label}: run {k!r} pixels {box} outside the {margin}px safe margin of {W}x{H}"
        regions[k] = box
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            assert not overlaps(regions[a], regions[b]), f"{label}: runs {a!r} {regions[a]} and {b!r} {regions[b]} overlap"
    return regions


def stress_map():
    """Longer strings than the real map, to prove the fit/wrap logic and not just today's copy."""
    m = mini_map()
    m["version"] = "v2026.12.31.12"
    m["layers"][5]["name"] = "Embeddings, Vector Databases & Rerankers"
    m["layers"][5]["tools"][0]["name"] = "AVeryLongToolNameWithoutAnySpacesAtAllThatMustShrink"
    m["layers"][2]["control"] = ("Step and budget limits, human approval for every irreversible action, and a named "
                                 "owner for each agent")
    m["copy"] = dict(m["copy"], video_hook="Production AI runs on twelve interdependent capability areas.")
    return m


def real_map():
    p = M.latest_map()
    return json.loads(p.read_text(encoding="utf-8"))


def test_layout_engine_is_pinned_to_basic():
    f = RM.font("Inter-Regular.ttf", 20)
    assert f.layout_engine == ImageFont.Layout.BASIC
    import render_video as RV
    assert RV.Scene(1080, 1350, []).f["chip"].layout_engine == ImageFont.Layout.BASIC


@pytest.mark.parametrize("which", ["real", "stress"])
def test_png_text_runs_visible_inside_and_apart(which):
    m = real_map() if which == "real" else stress_map()

    def render(skip):
        c = RM.render(m, skip)
        return c.im, c.runs

    regions = assert_runs_visible_inside_and_apart(render, (RM.W, RM.H), RM.SAFE_MARGIN, f"png/{which}")
    assert "gov" in regions and "handle" in regions and "L12.ctrl.0" in regions


@pytest.mark.parametrize("which", ["real", "stress"])
@pytest.mark.parametrize("size", [(1080, 1350), (1080, 1920)], ids=["4x5", "9x16"])
def test_video_text_runs_visible_inside_and_apart_on_every_scene(which, size):
    import render_video as RV

    m = real_map() if which == "real" else stress_map()
    copy = RV.video_copy(m)
    W, H = size
    for k, (kind, dur) in enumerate(RV.scene_plan(m, 2.8)):
        t = dur - 1 / 30  # last frame of the scene: every fade has finished

        def render(skip, k=k, kind=kind, t=t):
            sc = RV.Scene(W, H, [], skip)
            im = RV.render_scene(sc, m, copy, k, kind, t)
            return im, list(sc.runs)

        label = f"video/{which}/{W}x{H}/{kind}{k if kind == 'layer' else ''}"
        regions = assert_runs_visible_inside_and_apart(render, size, RV.SAFE_MARGIN, label)
        if kind != "layer" or k < len(m["layers"]):
            assert any(r.startswith(("version", "next")) for r in regions), label


def test_long_footer_is_shrunk_to_fit_not_clipped():
    """The v2026.09.27.1 outro footer ran past the right edge of the 1080 px frame."""
    import render_video as RV

    m = real_map()
    sc = RV.Scene(1080, 1350, [])
    sc.outro(3.9, RV.video_copy(m), m)
    (box,) = [b for k, b in sc.runs if k == "version"]
    assert box[2] <= 1080 - RV.SAFE_MARGIN


# ---- R6 (PR #5 review): the PNG carries its version and review deadline ----

def test_png_pixels_change_when_freshness_metadata_changes():
    """Changing version, date, expiry and oldest review must change the picture, not only the JSON."""
    import copy as _copy
    from PIL import ImageChops
    m1 = mini_map()
    m2 = _copy.deepcopy(m1)
    m2.update(version="v2099.01.01", date="2099-01-01", expires="2099-01-31", oldest_check="2099-01-01")
    a, b = RM.render(m1).im, RM.render(m2).im
    assert ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox() is not None
    line = RM.version_line(m2)
    assert "v2099.01.01" in line and "re-check due 2099-01-31" in line and "checked 2099-01-01" in line
    assert line in RM.render(m2).drawn


def test_png_version_line_names_the_repository():
    m = mini_map()
    m.setdefault("copy", {})["repo"] = "github.com/Double00kevin/ai-security-architecture-map"
    assert RM.version_line(m).endswith("github.com/Double00kevin/ai-security-architecture-map")


def test_chip_font_is_fitted_to_the_widest_rendered_label_not_the_longest_string():
    """The longest string (narrow glyphs) is not the widest chip; the wide one must still fit."""
    import render_video as RV

    m = mini_map()
    layer = dict(m["layers"][0])
    layer["tools"] = [{"name": "W" * 30}, {"name": "i" * 60}]
    sc = RV.Scene(1080, 1350, [])
    sc.layer(2.7, RV.video_copy(m), layer, None, 1, 12)
    chips = [b for k, b in sc.runs if k.startswith("chip.")]
    assert chips and all(b[2] <= 1080 - RV.SAFE_MARGIN for b in chips), chips


def test_schema_2_maps_keep_their_published_wording():
    """v2026.09.28 (schema 2) must re-render exactly as published: its PNG sidecar is verified in CI."""
    m = mini_map()
    m.update(schema_version=2, oldest_review="2026-09-28", expires="2026-10-28")
    assert "oldest review 2026-09-28 · review due 2026-10-28" in RM.version_line(m)


# ---- A17 (2026-09-29 audit): the poster says what it is, and what it is not ----

def test_copy_is_scoped_as_capability_areas_not_a_universal_stack():
    copy = M.load_copy()
    assert copy["subtitle"] == ("12 capability areas an AI build can draw on, example tools for each, "
                                "and one security control to start with.")
    assert copy["video_hook"] == "An AI build can touch up to 12 layers."
    assert copy["video_hook_accent"] == "Every one you use is an attack surface."
    assert copy["scope_note"] == "Illustrative. Not an endorsement or a complete security baseline."
    text = " ".join(copy.values()).lower()
    assert "every ai build runs on" not in text and "production ai runs on" not in text


def test_png_draws_the_scope_note_at_its_design_size_between_footer_and_cta():
    m = mini_map()
    c = RM.render(m)
    assert m["copy"]["scope_note"] in c.drawn
    (box,) = [b for k, b in c.runs if k == "scope"]
    (cta,) = [b for k, b in c.runs if k == "cta"]
    assert RM.FOOT[3] < box[1] and box[3] < cta[1]
    assert box[2] <= RM.MARGIN_R
    assert RM.fit_font(m["copy"]["scope_note"], "Inter-Regular.ttf", RM.SCOPE_SIZE, RM.MARGIN_R - RM.MARGIN_L,
                       min_size=RM.SCOPE_SIZE).size == RM.SCOPE_SIZE  # fits without shrinking


@pytest.mark.parametrize("size", [(1080, 1350), (1080, 1920)], ids=["4x5", "9x16"])
def test_video_end_card_draws_the_scope_note(size):
    import render_video as RV
    m = mini_map()
    sc = RV.Scene(*size, [])
    sc.outro(3.9, RV.video_copy(m), m)
    assert any(k.startswith("scope.") for k, _ in sc.runs)
