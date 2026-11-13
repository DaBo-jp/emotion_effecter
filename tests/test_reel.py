"""背景の区間の並び（`reel`）。置き方は尺を差し替えて、書き出しは ffmpeg で通す。"""
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from emotion_effecter import lyrics, reel, video

FPS = 10
#: 0〜2 / 2〜5 / 5〜8 / 8〜10 秒
SONG = lyrics.parse("[Intro @0:00]\na\n[Instrumental Break @0:02]\n"
                    "[Chorus @0:05]\nb\n[Instrumental Break @0:08]\n")
SONG_F = 100


def _seg(kind, name, until=None, seconds=0.0, transition="fade"):
    return reel.Segment(kind, name, until, transition, seconds)


def _len(lengths):
    return lambda p: lengths[p]


def _spans(segs, lengths=None):
    return [(s.seg.path, s.f0, s.f1, s.overlap)
            for s in reel.place(segs, SONG, SONG_F, FPS, _len(lengths or {}))]


def test_opening_still_closing_is_one_way_to_write_it():
    """mp4 はその尺、残り全部の画像の後ろの mp4 は曲の終わりから逆に置く。"""
    segs = [_seg("video", "open"), _seg("image", "still"),
            _seg("video", "close", seconds=1.0)]
    assert _spans(segs, {"open": 20, "close": 30}) == [
        ("open", 0, 20, 0), ("still", 20, 80, 0), ("close", 70, 100, 10)]


def test_until_takes_the_next_section_of_that_name_and_mp4s_play_anywhere():
    """同じ名前のセクションは、その区間が始まった後に最初に終わるもの。"""
    segs = [_seg("image", "a", until="Instrumental Break"), _seg("video", "m", seconds=0.5),
            _seg("image", "b", until=9.0), _seg("image", "c", until="Instrumental Break")]
    assert _spans(segs, {"m": 25}) == [
        ("a", 0, 50, 0), ("m", 45, 70, 5), ("b", 70, 90, 0), ("c", 90, 100, 0)]


def test_last_mp4_is_cut_at_the_end_of_the_song():
    assert _spans([_seg("image", "a", until=3.0), _seg("video", "m")], {"m": 500}) == [
        ("a", 0, 30, 0), ("m", 30, 100, 0)]


def test_every_placement_problem_is_listed():
    """届かない・短すぎる・無いセクションを全部並べて断る。黙って伸ばさない。"""
    with pytest.raises(ValueError) as e:
        reel.place([_seg("image", "a", until="Bridge"), _seg("image", "b", until=6.0)],
                   SONG, SONG_F, FPS, _len({}))
    assert "until='Bridge'" in str(e.value)
    with pytest.raises(ValueError) as e:
        reel.place([_seg("image", "a", until=1.0), _seg("video", "m", seconds=2.0),
                    _seg("image", "b", until=5.0)], SONG, SONG_F, FPS, _len({"m": 30}))
    msg = str(e.value)
    assert "reel[0]: 区間が短すぎる" in msg and "曲の終わりに届かない" in msg


def test_manifest_problems_are_all_listed(tmp_path):
    for f in ("a.jpg", "m.mp4"):
        (tmp_path / f).write_text("x")
    doc = [{"image": "a.jpg", "in": {"seconds": 1}}, {"image": "a.jpg"},
           {"video": "m.mp4", "until": 3, "in": {"transition": "nope", "seconds": 0}},
           {"image": "gone.jpg"}, {"song": "x"}]
    msg = "\n".join(reel.problems(doc, tmp_path))
    for part in ("reel[0].in: 最初の区間には前が無い", "reel[2] の知らない項目: until",
                 "reel[2].in.seconds", "reel[2].in.transition='nope'", "reel[3] の画像が無い",
                 "reel[4] は"):
        assert part in msg, part
    msg = "\n".join(reel.problems([{"image": "a.jpg"}, {"image": "a.jpg"}], tmp_path))
    assert "残り全部" in msg and "1つだけ" in msg
    msg = "\n".join(reel.problems([{"image": "a.jpg"}, {"image": "a.jpg", "until": 3}],
                                  tmp_path))
    assert "後ろは mp4 だけ" in msg


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")
def test_background_is_written_frame_exact_with_each_seam_its_own_way(tmp_path):
    """赤い画像 → 青い mp4（切り替え）→ 赤い画像（1秒のクロスフェード）。"""
    red, blue = str(tmp_path / "r.png"), str(tmp_path / "b.mp4")
    Image.new("RGB", (64, 36), (255, 0, 0)).save(red)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=blue:size=48x48:rate=24:duration=2", blue], check=True)
    segs = [_seg("image", red, until=1.0), _seg("video", blue),
            _seg("image", red, seconds=1.0)]
    spans = reel.place(segs, SONG, 50, FPS)
    dst = reel.write(str(tmp_path / "bg.mp4"), spans, 60, FPS, (32, 18))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", dst, "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 18, 32, 3).astype(int)
    assert len(fr) == 60 and video.count_frames(dst) == 60
    assert fr[5, 9, 16, 0] > 200 and fr[15, 9, 16, 2] > 200       # 赤 → 青（切り替え）
    assert 60 < fr[25, 9, 16, 0] < 200 and fr[45, 9, 16, 0] > 200  # 混ざって赤へ、余白まで赤
