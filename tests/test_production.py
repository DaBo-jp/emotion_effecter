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
    assert rec["cut"] == {"fps": FPS, "total": 60, "body0": 10, "body1": 50}
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
