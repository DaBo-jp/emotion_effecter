"""三段の組み立てを、合成した短い音と絵で最後まで通す。ffmpeg が要る。"""
import json
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from emotion_effecter import lyrics, production, timeline, video
from tests.conftest import make_mood

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")

FPS = 10


def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.fixture
def media(tmp_path):
    wav, img = str(tmp_path / "a.wav"), str(tmp_path / "b.png")
    _ff("-f", "lavfi", "-i", "sine=frequency=220:duration=6", "-ac", "2", wav)
    Image.fromarray(np.full((72, 128, 3), 40, np.uint8)).save(img)
    clips = []
    for name in ("open", "close"):
        clips.append(str(tmp_path / ("%s.mp4" % name)))
        _ff("-f", "lavfi", "-i", "testsrc=size=128x72:rate=24:duration=1.02", clips[-1])
    return wav, img, clips


def test_three_parts_add_up_to_the_song(tmp_path, media):
    wav, img, (opening, closing) = media
    song = lyrics.parse("[Verse 1 @0:00]\na\n[Chorus 1 @0:03]\nb")
    tl = timeline.build(song, [make_mood("Verse 1", 0.0), make_mood("Chorus 1", 1.0)],
                        6.0, FPS)
    out = str(tmp_path / "out.mp4")
    params = dict(audio=wav, image=img, width=128, height=72, fps=FPS, bands=8,
                  cache_dir=str(tmp_path))
    rec = production.produce("stave", params, tl, out, opening=opening, closing=closing,
                             jobs=2, chunk_seconds=2)
    assert rec["cut"] == {"fps": FPS, "total": 60, "body0": 10, "body1": 50, "fade": 0}
    assert sum(c["frames"] for c in rec["chunks"]) == 40
    assert video.count_frames(out) == 60
    assert abs(video.probe_duration(out) - 6.0) < 0.05


def test_record_sits_next_to_the_output(tmp_path, media):
    wav, img, (opening, _closing) = media
    out = str(tmp_path / "out.mp4")
    params = dict(audio=wav, image=img, width=128, height=72, fps=FPS, bands=8,
                  cache_dir=str(tmp_path))
    production.produce("stave", params, None, out, opening=opening, chunk_seconds=2)
    rec = json.loads(open(out + ".plan.json", encoding="utf-8").read())
    assert rec["mood"] is False and rec["policy"] == production.Policy().to_dict()
    assert set(rec["sources"]) == {"audio", "image", "opening"}   # 無い入力は書かない
    assert rec["spec"]["bands"] == 8 and "out" not in rec["spec"]


def test_crossfade_keeps_the_length_and_draws_the_overlap(tmp_path, media):
    """クロスフェードでも尺は曲のまま。本編は重なりのぶん前後に長く描く。"""
    wav, img, (opening, closing) = media
    out = str(tmp_path / "out.mp4")
    params = dict(audio=wav, image=img, width=128, height=72, fps=FPS, bands=8,
                  cache_dir=str(tmp_path))
    rec = production.produce("stave", params, None, out, opening=opening, closing=closing,
                             chunk_seconds=2, fade=0.3)
    assert rec["cut"] == {"fps": FPS, "total": 60, "body0": 10, "body1": 50, "fade": 3}
    assert rec["chunks"][0]["f0"] == 7 and sum(c["frames"] for c in rec["chunks"]) == 46
    assert video.count_frames(out) == 60
    assert abs(video.probe_duration(out) - 6.0) < 0.05


def test_crossfade_longer_than_a_clip_is_refused(tmp_path, media):
    wav, _img, (opening, _closing) = media
    with pytest.raises(ValueError, match="クロスフェード"):
        production.cut(wav, FPS, opening, None, 2.0)


def test_crossfade_blends_at_the_seam(tmp_path):
    """つなぎ目の真ん中は前後の絵の半々。重ねたぶん短くなる。"""
    clips = []
    for name, col in (("a", "red"), ("b", "blue")):
        clips.append(str(tmp_path / ("%s.mp4" % name)))
        _ff("-f", "lavfi", "-i", "color=c=%s:size=32x18:rate=10:duration=1" % col, clips[-1])
    dst = video.crossfade(clips, [10, 10], 4, 10, str(tmp_path / "x.mp4"))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", dst, "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 18, 32, 3).astype(int)
    assert len(fr) == 16
    assert fr[3, 9, 16, 0] > 200 and fr[12, 9, 16, 2] > 200
    assert 60 < fr[8, 9, 16, 0] < 200 and 60 < fr[8, 9, 16, 2] < 200


@pytest.mark.parametrize("name", video.TRANSITIONS)
def test_every_transition_is_known_to_ffmpeg(tmp_path, name):
    """宣言した切り替え方は全部、この ffmpeg で通る。ffmpeg が変われば落ちる。"""
    clips = []
    for c, col in (("a", "red"), ("b", "blue")):
        clips.append(str(tmp_path / ("%s.mp4" % c)))
        _ff("-f", "lavfi", "-i", "color=c=%s:size=32x18:rate=10:duration=0.5" % col, clips[-1])
    dst = video.crossfade(clips, [5, 5], 2, 10, str(tmp_path / "x.mp4"), name)
    assert video.count_frames(dst) == 8


def test_unknown_transition_is_refused(tmp_path):
    with pytest.raises(ValueError, match="知らない切り替え"):
        video.crossfade(["a", "b"], [5, 5], 2, 10, str(tmp_path / "x.mp4"), "spin")


def test_credits_go_through_parallel_rendering(tmp_path, media):
    """流れる歌詞を、区間に分けた並列の書き出しに通す（別プロセスへ渡せること）。"""
    from emotion_effecter import roll
    wav, img, (opening, closing) = media
    song = lyrics.parse("[Verse 1 @0:00]\na\nb\n[Chorus 1 @0:03]\nc")
    rl = roll.layout(song, 6.0, (128, 72), {"font": "DejaVu Sans"})
    out = str(tmp_path / "out.mp4")
    params = dict(audio=wav, image=img, width=128, height=72, fps=FPS, bands=8,
                  cache_dir=str(tmp_path))
    rec = production.produce("stave", params, None, out, opening=opening, closing=closing,
                             jobs=2, chunk_seconds=2, roll=rl)
    assert rec["credits"]["font"] == "DejaVu Sans" and video.count_frames(out) == 60


def test_without_clips_the_last_frame_is_not_dropped(tmp_path, media):
    """Opening も Closing も無い（live など）と本編が曲の終わりまで届く。最後の区間で
    1フレーム落ちていた（cymatics 04e9e82 で直した）。"""
    wav, img, _clips = media
    out = str(tmp_path / "out.mp4")
    params = dict(audio=wav, image=img, width=128, height=72, fps=FPS, bands=8,
                  cache_dir=str(tmp_path))
    production.produce("stave", params, None, out, jobs=2, chunk_seconds=2)
    assert video.count_frames(out) == 60


def test_fade_in_is_black_until_the_start_then_rises(tmp_path):
    """開始秒までは真っ黒、そこから秒数で元の絵へ。フレーム数は変わらない。"""
    src = str(tmp_path / "w.mp4")
    _ff("-f", "lavfi", "-i", "color=c=white:size=32x18:rate=10:duration=3", src)
    dst = video.finish(src, str(tmp_path / "x.mp4"), 30, 10, black_in=(1.0, 1.0))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", dst, "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 18, 32).astype(int)
    assert len(fr) == 30
    assert fr[5].max() < 30 and 60 < fr[15, 9, 16] < 200 and fr[25].min() > 220


def test_black_fade_in_keeps_the_length_and_is_recorded(tmp_path, media):
    wav, img, (_opening, closing) = media
    out = str(tmp_path / "out.mp4")
    params = dict(audio=wav, image=img, width=128, height=72, fps=FPS, bands=8,
                  cache_dir=str(tmp_path))
    rec = production.produce("stave", params, None, out, closing=closing, chunk_seconds=2,
                             black=(2.0, 1.0))
    assert rec["black"] == {"in": [2.0, 1.0], "out": None} and video.count_frames(out) == 60


def test_fade_out_falls_to_black_at_the_end(tmp_path):
    """最後の秒数で黒へ。それより前は元の絵のまま。フレーム数は変わらない。"""
    src = str(tmp_path / "w.mp4")
    _ff("-f", "lavfi", "-i", "color=c=white:size=32x18:rate=10:duration=3", src)
    dst = video.finish(src, str(tmp_path / "x.mp4"), 30, 10, black_out=1.0)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", dst, "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 18, 32).astype(int)
    assert len(fr) == 30
    assert fr[15].min() > 220 and 60 < fr[25, 9, 16] < 200 and fr[29].max() < 40


def _gray(path, h, w):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(int)


def test_channel_tears_snows_then_lands_on_the_next_clip(tmp_path):
    """`channel`：真ん中で乱れが一番強く（砂嵐でざらつく）、端では前後の絵のまま。"""
    clips = []
    for name, c in (("a", "black"), ("b", "white")):
        clips.append(str(tmp_path / ("%s.mp4" % name)))
        _ff("-f", "lavfi", "-i", "color=c=%s:size=64x36:rate=10:duration=1" % c, clips[-1])
    dst = video.crossfade(clips, [10, 10], 6, 10, str(tmp_path / "x.mp4"), "channel")
    fr = _gray(dst, 36, 64)
    assert len(fr) == 14
    assert fr[3].max() < 30 and fr[-1].min() > 225               # 前後は素の黒と白
    assert fr[7].std() > 3 * max(fr[3].std(), fr[-1].std(), 1)  # 真ん中は乱れる
    again = _gray(video.crossfade(clips, [10, 10], 6, 10, str(tmp_path / "y.mp4"),
                                  "channel"), 36, 64)
    assert (again == fr).all()                                   # 何度でも同じ絵


def test_channel_works_inside_a_chain(tmp_path):
    srcs = []
    for name, c in (("a", "red"), ("b", "blue")):
        p = str(tmp_path / ("%s.mp4" % name))
        _ff("-f", "lavfi", "-i", "color=c=%s:size=64x36:rate=10:duration=1" % c, p)
        srcs.append(video.source(p, False, 10, 10, (64, 36)))
    dst = video.chain(srcs, [10, 10], [0, 4], ["fade", "channel"], 10,
                      str(tmp_path / "x.mp4"), (64, 36))
    assert video.count_frames(dst) == 16


def test_crt_draws_scanlines_and_a_band_that_moves_down(tmp_path):
    from emotion_effecter import crt

    src = str(tmp_path / "g.mp4")
    _ff("-f", "lavfi", "-i", "color=c=gray:size=64x40:rate=10:duration=2", src)
    c = crt.Crt(scanlines=0.5, pitch=4, band=0.6, band_height=0.25, band_seconds=2.0)
    dst = video.finish(src, str(tmp_path / "x.mp4"), 20, 10,
                       layers=crt.layers(c, (64, 40), str(tmp_path)))
    fr = _gray(dst, 40, 64)
    assert len(fr) == 20
    rows = fr[0].mean(axis=1)
    assert rows[2] < rows[0] - 20                                 # 縞の芯は暗い
    band_at = [int(np.argmax(f.mean(axis=1) - rows)) for f in fr[4:16:4]]
    assert band_at == sorted(band_at) and band_at[0] < band_at[-1]  # 上から下へ


def test_crt_band_can_move_up():
    from emotion_effecter import crt

    assert crt.band_y(crt.Crt()) == "mod(t/8.000000,1)*(H+h)-h"
    assert crt.band_y(crt.Crt(band_direction="up")) == "H-mod(t/8.000000,1)*(H+h)"


def test_crt_is_recorded_and_keeps_the_length(tmp_path, media):
    from emotion_effecter import crt

    wav, img, (_opening, closing) = media
    out = str(tmp_path / "out.mp4")
    params = dict(audio=wav, image=img, width=128, height=72, fps=FPS, bands=8,
                  cache_dir=str(tmp_path))
    rec = production.produce("stave", params, None, out, closing=closing, chunk_seconds=2,
                             crt=crt.Crt(band_direction="up"))
    assert rec["crt"]["band_direction"] == "up" and video.count_frames(out) == 60


def test_crossfade_finishes_in_the_same_pass(tmp_path):
    """つなぎ目を重ねるときは、仕上げ（黒・重ね）も同じ1回の書き出しで。
    別々に書き出したのと同じ絵になる（どちらも1回ずつ丸めるぶんの差だけ）。"""
    from emotion_effecter import crt

    clips = []
    for name, col in (("a", "gray"), ("b", "white")):
        clips.append(str(tmp_path / ("%s.mp4" % name)))
        _ff("-f", "lavfi", "-i", "color=c=%s:size=64x40:rate=10:duration=2" % col, clips[-1])
    lays = tuple(crt.layers(crt.Crt(scanlines=0.5, band=0.6), (64, 40), str(tmp_path)))
    fin = video.Finish(black_in=(0.0, 0.5), black_out=0.5, layers=lays)
    one = _gray(video.crossfade(clips, [20, 20], 6, 10, str(tmp_path / "one.mp4"), "fade",
                                fin), 40, 64)
    two = _gray(video.finish(video.crossfade(clips, [20, 20], 6, 10, str(tmp_path / "x.mp4")),
                             str(tmp_path / "two.mp4"), 34, 10, fin.black_in, fin.black_out,
                             fin.layers), 40, 64)
    assert len(one) == len(two) == 34
    assert one[0].max() < 30 and one[-1].mean() < one[20].mean() / 3    # 黒から入って黒へ
    assert np.abs(one - two).max() <= 6


def test_finish_without_anything_still_writes(tmp_path):
    src = str(tmp_path / "w.mp4")
    _ff("-f", "lavfi", "-i", "color=c=white:size=32x18:rate=10:duration=1", src)
    assert video.count_frames(video.finish(src, str(tmp_path / "x.mp4"), 10, 10)) == 10


def test_channel_seam_is_the_same_picture_as_the_ffmpeg_expression(tmp_path):
    """つなぎ目を別に描いても（`channel_seam`）、ffmpeg の数式（`channel_expr`）で描いたのと
    同じ絵。10fps なら P がどちらでも同じ float になり、書き出す前の絵は画素まで同じ
    （x264 の判断が数画素だけ変わる）。"""
    clips = []
    for name, src in (("a", "testsrc2"), ("b", "mandelbrot")):
        clips.append(str(tmp_path / ("%s.mp4" % name)))
        _ff("-f", "lavfi", "-i", "%s=size=64x36:rate=10" % src, "-frames:v", "12", clips[-1])
    new = _gray(video.crossfade(clips, [12, 12], 6, 10, str(tmp_path / "x.mp4"), "channel"),
                36, 64)
    old = str(tmp_path / "old.mp4")
    pre = "[0:v]settb=AVTB,setpts=PTS-STARTPTS[v0];[1:v]settb=AVTB,setpts=PTS-STARTPTS[v1];"
    _ff("-i", clips[0], "-i", clips[1], "-filter_complex",
        pre + video._xfade("[v0]", "[v1]", "channel", 6, 6, 10, "[o]"), "-map", "[o]",
        "-frames:v", "18", *video.ENCODE, old)
    diff = np.abs(new - _gray(old, 36, 64))
    assert len(new) == 18 and diff.mean() < 0.05 and diff.max() <= 8


def test_channel_falls_back_to_the_expression_when_clips_are_short(tmp_path):
    """前の素材が重なりより短い（つなぎ目どうしが重なる）ときは数式で描く。"""
    assert not video._separable([10, 4, 10], [0, 3, 3], 2)
    assert video._separable([10, 6, 10], [0, 3, 3], 2)
