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
