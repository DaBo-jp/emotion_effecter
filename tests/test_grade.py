import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from emotion_effecter import drive, grade, policy, timeline

RGB = Image.fromarray(np.array([[[200, 40, 90], [10, 220, 160]]], np.uint8))


def test_zero_leaves_the_picture_untouched():
    assert grade.apply(RGB, 0.0, 0.0) is RGB


def test_full_gray_has_no_colour_and_keeps_luma():
    a = np.asarray(grade.apply(RGB, 1.0, 0.0)).astype(int)
    assert (a[..., 0] == a[..., 1]).all() and (a[..., 1] == a[..., 2]).all()
    luma = np.asarray(RGB, np.float32) @ grade.LUMA
    assert np.abs(a[..., 0] - luma).max() <= 1


def test_half_gray_is_between():
    full, half = (np.asarray(grade.apply(RGB, k, 0.0)).astype(int) for k in (1.0, 0.5))
    src = np.asarray(RGB).astype(int)
    assert np.abs(half - (src + full) / 2).max() <= 1


def test_sepia_is_brown():
    r, g, b = np.asarray(grade.apply(RGB, 1.0, 1.0))[0, 0].astype(int)
    assert r > g > b


def test_tone_follows_the_chosen_axes():
    pol = policy.from_mapping({"gray_by": "love", "gray_lo": 1.0, "gray_hi": 0.0,
                               "sepia_by": "tense", "sepia_lo": 0.8, "sepia_hi": 0.0})
    assert policy.toned(pol) and not policy.toned(policy.Policy())
    assert policy.tone({"love": 0.25, "tense": 0.5}, pol) == pytest.approx((0.75, 0.4))


def test_tone_ranges_are_checked():
    with pytest.raises(ValueError, match="(?s)gray_hi.*sepia_lo"):
        policy.from_mapping({"gray_hi": 1.5, "sepia_lo": -0.1})


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")
def test_whole_screen_goes_gray_background_included(tmp_path):
    """灰色は層ではなく画面ぜんたい——背景の色も抜ける。"""
    wav, img = str(tmp_path / "a.wav"), str(tmp_path / "b.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "anoisesrc=d=2:c=pink:a=0.5:seed=7", wav], check=True)
    Image.fromarray(np.full((36, 64, 3), (200, 60, 30), np.uint8)).save(img)
    pol = policy.from_mapping({"gray_lo": 1.0, "gray_hi": 1.0})
    names = ("arousal", "valence", "acceptance", "conflict")
    tl = timeline.Timeline(10, names, np.full((len(names), 20), 0.5))
    png = str(tmp_path / "p.png")
    drive.render("ring", dict(audio=wav, image=img, out=str(tmp_path / "x.mp4"), width=64,
                              height=36, fps=10, preview=png, preview_at=1.0,
                              cache_dir=str(tmp_path)), tl, pol)
    a = np.asarray(Image.open(png).convert("RGB")).astype(int)
    assert np.abs(a[..., 0] - a[..., 2]).max() <= 1
