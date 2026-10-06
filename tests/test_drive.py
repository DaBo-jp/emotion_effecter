from dataclasses import dataclass, field

import numpy as np
import pytest
from cymatics import effects

from emotion_effecter import drive, policy, timeline


@dataclass(frozen=True)
class _Ctx:
    col: tuple
    s: dict = field(default_factory=lambda: {"glow": 1.4})


@dataclass(frozen=True)
class _Frame:
    f: int
    t: float
    levels: np.ndarray


def test_neutral_look_leaves_frame_untouched():
    lv = np.linspace(0, 1, 8, dtype=np.float32)
    ctx, fr = drive.apply(_Ctx((200, 250, 255)), _Frame(3, 0.3, lv),
                          policy.Look((200, 250, 255), glow=1.0, gain=1.0))
    assert ctx.col == (200, 250, 255) and ctx.s["glow"] == 1.4
    assert fr.levels is lv


def test_gain_keeps_dtype_and_clips():
    lv = np.array([0.5, 0.95], dtype=np.float64)
    _ctx, fr = drive.apply(_Ctx((0, 0, 0)), _Frame(0, 0.0, lv), policy.Look((0, 0, 0), 1.0, 1.1))
    assert fr.levels.dtype == np.float64 and fr.levels[1] == 1.0


def test_wrap_swaps_only_draw():
    eff = effects.get("stave")
    tl = timeline.Timeline(30, (), np.zeros((0, 1)))
    w = drive.wrap(eff, tl, policy.Policy())
    assert w.fields == eff.fields and w.module.ENVELOPE == eff.module.ENVELOPE
    assert w.module.stage is eff.module.stage and w.module.draw is not eff.module.draw


def test_chunk_windows_land_on_exact_frames(tmp_path):
    fps = 30
    chunks = drive.plan_chunks(300, 7050, 750, str(tmp_path))
    assert sum(c.frames for c in chunks) == 6750 and chunks[-1].frames == 750
    for c in chunks:
        w = c.window(fps)
        assert int(w["start"] * fps) == c.f0 and int(w["duration"] * fps) == c.frames


def test_render_refuses_a_bad_policy():
    with pytest.raises(ValueError, match="glow_hi"):
        drive.render("stave", {}, None, policy.Policy(glow_hi=-1.0))


def test_chunk_safety_follows_the_envelope():
    assert drive.chunk_safe("stave") and not drive.chunk_safe("arc")
