"""セクションごとの流れの向き（`scenes.py`）と、それを描く `drive.in_scenes`。"""
import json
import shutil
import subprocess
from dataclasses import dataclass, field

import numpy as np
import pytest
from cymatics import effects
from PIL import Image

from emotion_effecter import drive, lyrics, manifest, scenes

FPS = 10
#: Verse 1 [0, 10) / Instrumental Break [10, 20) / Chorus 1 [20, ...) フレーム
SONG = lyrics.parse("""<!--
Song
-->
[Verse 1 @0:00]
a
[Instrumental Break @0:01]
[Chorus 1 @0:02]
b
""")


def _sc(doc, effect="motif", xfade=0.4):
    return scenes.build(SONG, doc, effect, FPS, xfade)


# ------------------------------------------------------------ 表
def test_unlisted_sections_keep_the_base():
    sc = _sc({})
    assert sc.is_plain and sc.at(0) == (({}, 1.0),) and sc.at(25) == (({}, 1.0),)


def test_boundary_hands_over_in_xfade():
    """境界の前後 xfade/2 で、古い流れから新しい流れへ濃さを渡す。**描く順は古い→新しい。**"""
    sc = _sc({"Chorus 1": {"flow": "in"}})            # 境界はフレーム 20、xfade 4
    assert sc.at(17) == (({}, 1.0),)
    for f, k in ((18, 0.0), (19, 0.25), (20, 0.5), (21, 0.75)):
        (old, a), (new, b) = sc.at(f)
        assert old == {} and new == {"flow": "in"}
        assert (a, b) == pytest.approx((1 - k, k))
    assert sc.at(22) == (({"flow": "in"}, 1.0),)


def test_same_settings_on_both_sides_do_not_blend():
    sc = _sc({"Verse 1": {"flow": "left"}, "Instrumental Break": {"flow": "left"}})
    assert sc.at(10) == (({"flow": "left"}, 1.0),)


def test_zero_xfade_switches_on_the_frame():
    sc = _sc({"Chorus 1": {"flow": "in"}}, xfade=0.0)
    assert sc.at(19) == (({}, 1.0),) and sc.at(20) == (({"flow": "in"}, 1.0),)


def test_values_are_coerced_like_the_cli():
    sc = _sc({"Chorus 1": {"flow": "in", "flow_x": 1}})
    assert sc.at(25)[0][0]["flow_x"] == 1.0 and isinstance(sc.at(25)[0][0]["flow_x"], float)


def test_a_repeated_section_name_applies_to_every_one():
    song = lyrics.parse("<!--\nS\n-->\n[Break @0:00]\n[Verse @0:01]\na\n[Break @0:02]\n")
    sc = scenes.build(song, {"Break": {"flow": "down"}}, "motif", FPS, 0.0)
    assert [sc.at(f)[0][0] for f in (5, 15, 25)] == [{"flow": "down"}, {}, {"flow": "down"}]


def test_every_problem_is_listed():
    """**知らない名前・変えられない項目・範囲外・持たない effect を全部並べて断る。**"""
    doc = {"Chorus 9": {"flow": "in"}, "Verse 1": {"flow": "sideways", "size": 3},
           "Chorus 1": {"flow_x": 2.0}, "_note": "注記は読み飛ばす"}
    with pytest.raises(ValueError) as e:
        _sc(doc)
    msg = str(e.value)
    for part in ("Chorus 9", "sideways", "size は変えられない", "flow_x"):
        assert part in msg, part
    assert "_note" not in msg


def test_effects_without_flow_are_refused():
    assert "持たない" in "".join(scenes.problems({"Verse 1": {"flow": "in"}}, "stave"))


def test_untimed_lyrics_are_refused():
    with pytest.raises(ValueError, match="開始時刻"):
        scenes.build(lyrics.parse("<!--\nS\n-->\n[Verse]\na\n"), {}, "motif", FPS)


def test_keys_are_flow_fields_of_cymatics():
    """変えられる項目は cymatics の宣言に実在する。名前が変われば落ちる。"""
    names = {f.name for f in effects.get("motif").fields}
    assert set(scenes.KEYS) <= names


# ------------------------------------------------------------ song.json
def _manifest(tmp_path, sections):
    for f in ("l.md", "a.wav", "i.png"):
        (tmp_path / f).write_text("x")
    doc = {"title": "T", "files": {"lyrics": "l.md", "audio": "a.wav", "image": "i.png"},
           "base": {"effect": "motif"}, "sections": sections}
    (tmp_path / "song.json").write_text(json.dumps(doc), encoding="utf-8")
    return manifest.load(tmp_path)


def test_manifest_carries_sections(tmp_path):
    m = _manifest(tmp_path, {"_note": "n", "Chorus 1": {"flow": "out"}})
    assert m.sections == {"Chorus 1": {"flow": "out"}}


def test_manifest_lists_bad_sections(tmp_path):
    with pytest.raises(ValueError, match="sections: Chorus 1: .*flow"):
        _manifest(tmp_path, {"Chorus 1": {"flow": "nowhere"}})


# ------------------------------------------------------------ 描く
@pytest.fixture(scope="module")
def media(tmp_path_factory):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg が無い")
    d = tmp_path_factory.mktemp("media")
    wav, img = str(d / "a.wav"), str(d / "b.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "anoisesrc=d=3:c=pink:a=0.5:seed=7", "-ac", "2", wav], check=True)
    Image.fromarray(np.full((72, 128, 3), 60, np.uint8)).save(img)
    return wav, img, str(d)


def _shot(media, sc, t, tag):
    wav, img, d = media
    png = "%s/%s.png" % (d, tag)
    drive.render("motif", dict(audio=wav, image=img, out=d + "/x.mp4", width=128, height=72,
                               fps=FPS, preview=png, preview_at=t, cache_dir=d,
                               db_floor=-60.0, db_ceil=-10.0, rate=12.0, size=10.0),
                 None, sc=sc)
    return np.asarray(Image.open(png))


def test_plain_scenes_are_pixel_identical(media):
    """**何も変えないなら包まない。** 素の cymatics と画素まで同じ。"""
    a = _shot(media, None, 2.5, "none")
    b = _shot(media, _sc({}), 2.5, "plain")
    assert np.array_equal(a, b)


def test_a_section_draws_its_own_flow(media):
    base = _shot(media, None, 2.5, "base")
    sc = _sc({"Chorus 1": {"flow": "in"}})
    assert not np.array_equal(base, _shot(media, sc, 2.5, "in"))
    # 前のセクションは base のまま
    assert np.array_equal(_shot(media, None, 0.5, "v0"), _shot(media, sc, 0.5, "v1"))


def test_the_boundary_draws_both_flows(media):
    """境界の真ん中は、古い流れだけとも新しい流れだけとも違う絵。"""
    old = _shot(media, None, 2.0, "old")
    new = _shot(media, _sc({"Instrumental Break": {"flow": "in"},
                            "Chorus 1": {"flow": "in"}}), 2.0, "new")
    mid = _shot(media, _sc({"Chorus 1": {"flow": "in"}}), 2.0, "mid")
    assert not np.array_equal(mid, old) and not np.array_equal(mid, new)


@dataclass(frozen=True)
class _Ctx:
    """cymatics の Ctx のうち `variant()` が読むものだけ。"""

    s: dict
    derived: dict = field(default_factory=dict)
    work: object = None
    w: int = 320
    h: int = 180


def test_variant_rebuilds_stage_for_the_new_flow():
    """引数を変えたら `derive()` と `stage()` も作り直す（流れの画面の大きさが変わる）。"""
    eff = effects.get("motif")
    s = eff.spec_from(audio="a", image="b", out="c")
    c = drive.variant(eff.module, _Ctx(s), {"flow": "right"})
    assert c.work[1].kind == "right" and c.derived["flow_w"] == pytest.approx(180)
    assert drive.variant(eff.module, _Ctx(s), {}) == _Ctx(s)


def test_base_and_emotion_share_the_sections(tmp_path, monkeypatch):
    """**base にも sections を入れる。** compare の上下の違いを感情だけにするため。"""
    from emotion_effecter import workflow
    got = {}
    monkeypatch.setattr(workflow, "score", lambda *a: [])
    monkeypatch.setattr(workflow, "sections", lambda *a: SONG)
    monkeypatch.setattr(workflow, "build_timeline", lambda *a: "tl")
    monkeypatch.setattr(workflow, "build_scenes", lambda m, song: "sc")
    monkeypatch.setattr(workflow, "produce",
                        lambda m, out, tl, o, jobs=0, sc=None: got.update({out: (tl, sc)}))

    @dataclass(frozen=True)
    class _M:
        def file(self, role):
            return None

    o = workflow.run(_M(), tmp_path, steps=("emotion", "base"), say=lambda *_: None)
    assert got == {o["emotion"]: ("tl", "sc"), o["base"]: (None, "sc")}
