import json
import wave

import cymatics
import numpy as np
import pytest
from PIL import Image

from emotion_effecter import dims, drive, manifest, overlay, timeline

CROWD = {"effect": "crowd", "place": "over", "params": {"people": 6, "db_floor": -40.0,
                                                         "db_ceil": 0.0},
         "moods": {"bounce": {"by": "arousal", "lo": 0.0, "hi": 0.3},
                   "arms": {"by": "arousal", "lo": 0.0, "hi": 1.0}}}


def test_reads_place_params_and_moods():
    (ov,) = overlay.from_list([{**CROWD, "_note": "注記は読み飛ばす"}])
    assert (ov.effect, ov.place, ov.params["people"]) == ("crowd", "over", 6)
    assert ov.at({"arousal": 0.5}) == {"bounce": 0.15, "arms": 0.5}


def test_place_defaults_to_over_and_nested_params_become_json():
    curve = [[0, 1], [1, 0.2]]
    (ov,) = overlay.from_list([{"effect": "crowd", "params": {"mask_curve": curve}}])
    assert ov.place == "over" and json.loads(ov.params["mask_curve"]) == curve


def test_every_problem_is_listed():
    bad = overlay.problems([
        {"effect": "crowd", "place": "middle", "color": "red",
         "params": {"audio": "x.wav", "nope": 1, "people": 0},
         "moods": {"people": {"by": "arousal", "lo": 1, "hi": 2},
                   "bounce": {"by": "joy", "lo": -1, "hi": "high"},
                   "reach": {"by": "arousal"}}},
        {"effect": "laser"},
    ])
    text = "\n".join(bad)
    for word in ("color", "middle", "audio", "nope", "people", "joy", "bounce.lo",
                 "bounce.hi", "reach", "laser"):
        assert word in text, word
    assert all(b.startswith(("overlays[0]", "overlays[1]")) for b in bad)


def test_not_a_list_is_refused():
    assert overlay.problems({"effect": "crowd"}) == ["overlays は層のリスト"]


def test_manifest_lists_overlay_problems_with_the_rest(tmp_path):
    for f in ("l.md", "a.wav", "i.png"):
        (tmp_path / f).write_text("x")
    doc = {"title": "T", "files": {"lyrics": "l.md", "audio": "a.wav", "image": "i.png"},
           "base": {"effect": "motif"}, "overlays": [{"effect": "laser"}]}
    (tmp_path / "song.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="laser"):
        manifest.load(tmp_path)
    doc["overlays"] = [CROWD]
    (tmp_path / "song.json").write_text(json.dumps(doc), encoding="utf-8")
    assert manifest.load(tmp_path).overlays[0].effect == "crowd"


def test_chunk_safety_counts_the_overlays():
    (ov,) = overlay.from_list([CROWD])
    (arc,) = overlay.from_list([{"effect": "arc"}])
    assert drive.chunk_safe("motif", [ov]) and not drive.chunk_safe("motif", [arc])


def test_overlay_inherits_the_fade_of_the_main_layer():
    (ov,) = overlay.from_list([CROWD])
    lay = drive._overlay_layer("o", ov, {"fade_out_start": 30.0, "fade_out_len": 3.0})
    assert lay.spec["fade_out_start"] == 30.0 and "audio" not in lay.spec
    (own,) = overlay.from_list([{**CROWD, "params": {"fade_out_start": 10.0}}])
    assert drive._overlay_layer("o", own, {"fade_out_start": 30.0}).spec[
        "fade_out_start"] == 10.0


# ------------------------------------------------------------------ 実際に描く
@pytest.fixture
def media(tmp_path):
    sr, n = 44100, 44100 * 2
    t = np.arange(n) / sr
    kick = np.sin(2 * np.pi * 60 * t) * (np.sin(2 * np.pi * 2 * t) > 0)
    with wave.open(str(tmp_path / "a.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((kick * 20000).astype(np.int16).tobytes())
    Image.new("RGB", (320, 180), (90, 90, 140)).save(tmp_path / "i.png")
    return str(tmp_path / "a.wav"), str(tmp_path / "i.png"), tmp_path


def _shot(media, name, tl, ovs, **main):
    audio, image, tmp = media
    png = str(tmp / (name + ".png"))
    params = {"width": 320, "height": 180, "bands": 8, "db_floor": -40.0, "db_ceil": 0.0,
              "audio": audio, "image": image, "out": png + ".mp4", "preview": png,
              "preview_at": 1.0, "cache_dir": str(tmp), **main}
    drive.render("motif", params, tl, ovs=ovs)
    return np.asarray(Image.open(png))


def _flat_timeline(arousal: float) -> timeline.Timeline:
    names = tuple(dims.DIMS)
    row = [arousal if n == "arousal" else 0.5 for n in names]
    return timeline.Timeline(30, names, np.tile(row, (61, 1)).T)


def test_without_mood_it_is_exactly_cymatics_compose(media):
    """感情なしの重ね合わせは、cymatics で直に重ねたものと画素まで同じ。"""
    audio, image, tmp = media
    ovs = overlay.from_list([CROWD])
    ours = _shot(media, "ours", None, ovs)
    png = str(tmp / "direct.png")
    cymatics.compose([("motif", dict(bands=8, db_floor=-40.0, db_ceil=0.0)),
                      ("crowd", dict(people=6, db_floor=-40.0, db_ceil=0.0))],
                     audio=audio, image=image, out=png + ".mp4", width=320, height=180,
                     preview=png, preview_at=1.0, cache_dir=str(tmp))
    assert np.array_equal(ours, np.asarray(Image.open(png)))


def test_arousal_moves_the_overlay(media):
    ovs = overlay.from_list([CROWD])
    calm = _shot(media, "calm", _flat_timeline(0.0), ovs)
    wild = _shot(media, "wild", _flat_timeline(1.0), ovs)
    assert not np.array_equal(calm, wild)


def test_under_is_drawn_below_the_main_layer(media):
    over = _shot(media, "over", None, overlay.from_list([CROWD]))
    under = _shot(media, "under", None, overlay.from_list([{**CROWD, "place": "under"}]))
    assert not np.array_equal(over, under)
