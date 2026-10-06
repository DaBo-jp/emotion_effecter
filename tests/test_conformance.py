"""全 effect にかかる不変条件。cymatics に effect が増えればそのぶん増える。

**中立な写像で包んだ effect は、素の cymatics と画素まで一致する。** 包むことで
何かが漏れていれば（色の丸め・glow の型・レベルの dtype）ここで落ちる。
"""
import shutil
import subprocess

import numpy as np
import pytest
from cymatics import effects
from PIL import Image

from emotion_effecter import drive, policy, timeline

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")

FPS = 10
BG = 60
NEUTRAL = policy.Policy(glow_lo=1.0, glow_hi=1.0, gain_lo=1.0, gain_hi=1.0)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    wav, img = str(d / "a.wav"), str(d / "b.png")
    # 正弦波だけだと帯域の大半が無音で、rune は1画素も描かない（比べる意味が無い）
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "anoisesrc=d=3:c=pink:a=0.5:seed=7", "-ac", "2", wav], check=True)
    Image.fromarray(np.full((72, 128, 3), BG, np.uint8)).save(img)
    return wav, img, str(d)


def _calm(n: int) -> timeline.Timeline:
    names = ("arousal", "conflict", "acceptance", "valence", "dominance")
    return timeline.Timeline(FPS, names, np.array([[0.5] * n, [0.0] * n, [0.0] * n, [0.5] * n,
                                                  [0.5] * n]))


def _shot(media, name: str, tl, tag: str) -> np.ndarray:
    wav, img, d = media
    png = "%s/%s_%s.png" % (d, name, tag)
    drive.render(name, dict(audio=wav, image=img, out=d + "/x.mp4", width=128, height=72,
                            fps=FPS, preview=png, preview_at=1.5, cache_dir=d),
                 tl, NEUTRAL)
    return np.asarray(Image.open(png))


@pytest.mark.parametrize("name", effects.names())
def test_neutral_wrap_is_pixel_identical(media, name):
    plain = _shot(media, name, None, "plain")
    wrapped = _shot(media, name, _calm(4 * FPS), "wrapped")
    assert (np.abs(plain.astype(int) - BG).sum(2) > 10).sum() > 50, "何も描いていない"
    assert np.array_equal(plain, wrapped)


@pytest.mark.parametrize("name", effects.names())
def test_mood_changes_the_picture(media, name):
    """感情が動けば絵も動く。包んだのに何も変わらない effect は配線が切れている。"""
    n = 4 * FPS
    warm = timeline.Timeline(FPS, ("arousal", "conflict", "acceptance", "valence", "dominance"),
                             np.array([[1.0] * n, [0.0] * n, [1.0] * n, [1.0] * n, [0.5] * n]))
    plain = _shot(media, name, None, "plain2")
    moved = _shot(media, name, warm, "warm")
    assert not np.array_equal(plain, moved)
