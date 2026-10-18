"""セクションごとのキー画像: 解析（scenery）→ 置き場所（placement）→ 背景（backdrop）。"""
import io
import json
import shutil
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest
from cymatics import effects
from PIL import Image

from emotion_effecter import backdrop, drive, lyrics, manifest, placement, scenery, scenes

SONG = lyrics.parse("""<!--
S
-->
[Verse 1 @0:00]
a
[Chorus 1 @0:01]
b
[Verse 2 @0:02]
c
[Chorus 2 @0:03]
d
""")

BOXES = {"face": (0.4, 0.1, 0.6, 0.4), "person": (0.3, 0.1, 0.8, 1.0),
         "sky": (0.0, 0.0, 1.0, 0.3), "ground": (0.0, 0.7, 1.0, 1.0),
         "light": (0.7, 0.2, 0.8, 0.3)}


def _scenery(anchors, present=None):
    present = {k: 0.9 for k in scenery.LANDMARKS} | (present or {})
    return scenery.Scenery((1568, 875), dict(BOXES), {k: 0.8 for k in BOXES}, present,
                           {a: 0.0 for a in scenery.ANCHORS} | anchors)


ARC = {f.name for f in effects.get("arc").fields}
MOTIF = {f.name for f in effects.get("motif").fields}


# ------------------------------------------------------------ scenery
def test_questions_box_and_presence_for_every_landmark():
    assert set(scenery.boxes()) == {"box:" + k for k in scenery.LANDMARKS}
    assert set(scenery.questions()) == {"has:" + k for k in scenery.LANDMARKS} | {"at"}
    assert set(placement.REGION) == set(scenery.ANCHORS)
    assert set(scenery.BOX_TARGETS) == set(scenery.LANDMARKS)
    assert {v for v in placement.REGION.values() if v} <= set(scenery.LANDMARKS)


def test_from_response_reads_boxes_presence_and_anchor():
    box = SimpleNamespace(box=SimpleNamespace(left=0.1, top=0.2, right=0.3, bottom=0.4),
                          confidence=0.7)
    boxed = SimpleNamespace(boxes={"box:" + k: box for k in scenery.LANDMARKS})
    resp = SimpleNamespace(nouls={"has:" + k: SimpleNamespace(noul=0.6) for k in scenery.LANDMARKS},
                           choices={"at": SimpleNamespace(probabilities={"sky": 0.8})})
    sc = scenery.from_response((10, 20), boxed, resp)
    assert sc.boxes["sky"] == (0.1, 0.2, 0.3, 0.4) and sc.present["face"] == 0.6
    assert sc.anchors == {"sky": 0.8}


def test_saved_scenery_is_reused_only_for_the_same_question(tmp_path):
    sc, key = _scenery({"sky": 1.0}), {"image": "abc", "effect": "arc", "lyrics": "x"}
    scenery.save(tmp_path / "s.json", key, sc)
    assert scenery.load(tmp_path / "s.json", key) == sc
    assert scenery.load(tmp_path / "s.json", {**key, "lyrics": "y"}) is None


def test_prepare_shrinks_to_what_jev_accepts(tmp_path):
    Image.new("RGB", (2752, 1536), (10, 20, 30)).save(tmp_path / "big.jpg")
    assert max(Image.open(io.BytesIO(scenery.prepare(tmp_path / "big.jpg"))).size) == 1568
    Image.new("RGB", (400, 200)).save(tmp_path / "small.png")
    with pytest.raises(ValueError, match="小さすぎる"):
        scenery.prepare(tmp_path / "small.png")


# ------------------------------------------------------------ placement
def test_halo_circles_the_head_without_hiding_holes():
    p = placement.params(_scenery({"face": 0.9}), ARC, 1000, 500)
    assert (p["cx"], p["cy"]) == (0.5, 0.25)
    assert p["radius"] == pytest.approx(placement.HALO * 200)   # 頭の箱の長辺 0.2×1000
    assert p["holes"] == [] and p["holes_unit"] == "fraction"


def test_flow_goes_to_the_sky_and_keeps_the_face_clear():
    p = placement.params(_scenery({"sky": 0.9}), MOTIF, 1000, 500)
    assert (p["flow_x"], p["flow_y"]) == (0.5, 0.15) and "cx" not in p
    assert p["holes"] == [[[0.5, 0.25], pytest.approx(placement.HOLE * 0.3)]]


def test_missing_landmark_falls_back_to_the_next_anchor():
    sc = _scenery({"light": 0.6, "ground": 0.3}, present={"light": 0.1})
    assert placement.anchor(sc) == "ground"
    assert placement.anchor(_scenery({"light": 0.9, "whole": 0.1}, {"light": 0.0})) == "whole"


def test_open_is_the_wider_side_of_the_person():
    assert placement.region(_scenery({"open": 1.0}), "open") == (0.0, 0.0, 0.3, 1.0)
    p = placement.params(_scenery({"open": 1.0}), MOTIF, 1000, 500)
    assert (p["flow_x"], p["flow_y"]) == (0.15, 0.5)
    alone = _scenery({"open": 1.0}, present={"person": 0.0})
    assert placement.region(alone, "open") == (0.0, 0.0, 1.0, 1.0)


def test_whole_screen_uses_automatic_radius_and_the_centre():
    p = placement.params(_scenery({"whole": 1.0}), ARC, 1000, 500)
    assert (p["cx"], p["cy"], p["radius"]) == (0.5, 0.5, 0.0)


def test_placement_values_pass_the_scene_checks():
    """出した値は scenes の検証を通る（セクションごとに変えられる項目の範囲内）。"""
    for eff, fields in (("arc", ARC), ("motif", MOTIF)):
        extra = [placement.params(_scenery({a: 1.0}), fields, 1280, 720)
                 for a in ("face", "sky", "open", "whole")]
        sc = scenes.build(SONG, {}, eff, 10, 0.0, extra)
        assert len(sc.overrides) == 4


# ------------------------------------------------------------ backdrop
def test_sections_without_a_key_keep_the_previous_image():
    assert backdrop.keyed(SONG, {"Chorus 1": "c.jpg", "Chorus 2": "d.jpg"}, "i.jpg") == [
        "i.jpg", "c.jpg", "c.jpg", "d.jpg"]


def test_crossfade_straddles_the_boundary():
    starts, ims = [0, 10, 20], ["a", "b", "b"]
    assert backdrop.weights(starts, ims, 5, 4) == [("a", 1.0)]
    assert backdrop.weights(starts, ims, 8, 4) == [("a", 1.0), ("b", 0.0)]
    assert backdrop.weights(starts, ims, 10, 4) == [("a", 0.5), ("b", 0.5)]
    assert backdrop.weights(starts, ims, 12, 4) == [("b", 1.0)]
    assert backdrop.weights(starts, ims, 20, 4) == [("b", 1.0)]    # 同じ画像は混ぜない


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")
def test_backdrop_video_switches_images(tmp_path):
    for name, col in (("r.png", (255, 0, 0)), ("b.png", (0, 0, 255))):
        Image.new("RGB", (64, 64), col).save(tmp_path / name)
    ims = [str(tmp_path / "r.png"), str(tmp_path / "b.png")]
    dst = backdrop.write(str(tmp_path / "bg.mp4"), ims, [0, 10], 20, 10, (32, 18), 2)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", dst, "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 18, 32, 3).astype(int)
    assert len(fr) == 20
    assert fr[2, 9, 16, 0] > 200 and fr[18, 9, 16, 2] > 200


# ------------------------------------------------------------ manifest
def test_keys_are_resolved_and_missing_images_listed(tmp_path):
    for f in ("l.md", "a.wav", "i.png", "k.jpg"):
        (tmp_path / f).write_text("x")
    doc = {"title": "T", "files": {"lyrics": "l.md", "audio": "a.wav", "image": "i.png"},
           "base": {"effect": "smoke", "params": {"beam": 0}},
           "keys": {"_note": "n", "Chorus 1": "k.jpg"}}
    assert manifest.problems({**doc, "base": {"effect": "arc"}}, tmp_path) == [
        'keys: キー画像の背景は動画になるので明滅は使えない（base の params に "beam": 0 と書く）']
    (tmp_path / "song.json").write_text(json.dumps(doc), encoding="utf-8")
    assert manifest.load(tmp_path).keys == {"Chorus 1": str((tmp_path / "k.jpg").resolve())}
    doc["keys"] = {"Verse 1": "none.jpg", "Bridge": 3}
    assert sorted(manifest.problems(doc, tmp_path)) == [
        "keys.Bridge は画像のファイル名", "keys.Verse 1 の画像が無い: %s"
        % (tmp_path / "none.jpg").resolve()]


# ------------------------------------------------------------ drive
def test_section_holes_fade_only_the_layer():
    """セクションの透かす円は、層の絵だけを薄める。円の中心では描く前のまま。"""
    plan = SimpleNamespace(width=40, height=20)
    ctx = SimpleNamespace(quad=None, box=SimpleNamespace(is_full=True), plan=plan,
                          s={"holes_unit": "px"})
    k = drive.section_holes(ctx, {"holes": "[[[20, 10], 10]]"})
    assert k[10, 20] < 0.2 and k[0, 0] == 1.0
    assert drive.section_holes(ctx, {"holes": ""}) is None
    mod = SimpleNamespace(draw=lambda img, c, f: Image.new("RGB", img.size, (255, 255, 255)))
    out = np.asarray(drive._holed(mod, Image.new("RGB", (40, 20)), ctx, None, k))
    assert out[10, 20, 0] < 60 and out[0, 0, 0] == 255


def test_section_holes_refuse_a_boxed_layer():
    ctx = SimpleNamespace(quad=None, box=SimpleNamespace(is_full=False), s={})
    with pytest.raises(ValueError, match="箱"):
        drive.section_holes(ctx, {"holes": "[[[1, 1], 1]]"})
