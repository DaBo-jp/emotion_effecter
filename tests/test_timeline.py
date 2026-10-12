import numpy as np
import pytest

from emotion_effecter import lyrics, timeline
from tests.conftest import make_mood


def test_instrumental_section_ramps_between_neighbours(song, moods):
    tl = timeline.build(song, moods, duration=30.0, fps=10, xfade=0.0)
    assert tl.at("acceptance", 50) == 0.0
    assert 0.4 < tl.at("acceptance", 150) < 0.6       # 間奏の中ほど
    assert tl.at("acceptance", 250) == 1.0
    assert tl.at("emo:surrender", 250) == 1.0


def test_curve_reaches_the_last_frame(song, moods):
    tl = timeline.build(song, moods, duration=30.0, fps=10, xfade=0.0)
    assert len(tl.curve("acceptance")) == 301 and tl.at("acceptance", 300) == 1.0


def test_xfade_smooths_the_step(song, moods):
    tl = timeline.build(song, moods, duration=30.0, fps=10, xfade=4.0)
    assert np.all(np.abs(np.diff(tl.curve("acceptance"))) < 0.05)


def test_needs_times(moods):
    with pytest.raises(ValueError):
        timeline.build(lyrics.parse("[Verse 1]\na"), moods, 10.0, 10)


def test_unmatched_moods_are_all_reported(song, moods):
    """黙って捨てない。足りないものも余ったものも全部並べる。"""
    stray = make_mood("Bridge", 0.5)
    with pytest.raises(ValueError) as e:
        timeline.build(song, [moods[0], stray], 30.0, 10)
    assert "採点が無い: Chorus 1" in str(e.value) and "Bridge" in str(e.value)


def test_timeline_cannot_be_rewritten(song, moods):
    tl = timeline.build(song, moods, duration=30.0, fps=10)
    with pytest.raises(ValueError):
        tl.values[0, 0] = 1.0
    with pytest.raises(AttributeError):
        tl.fps = 30


def test_frame_clamps_to_both_ends(song, moods):
    tl = timeline.build(song, moods, duration=30.0, fps=10, xfade=0.0)
    assert tl.frame(-5)["acceptance"] == 0.0 and tl.frame(10 ** 6)["acceptance"] == 1.0


def test_paces_join_the_anchors(song, moods):
    from emotion_effecter.pace import Pace
    ps = [Pace("Verse 1", {"rush": 1.0}, 0.9, "rush"), Pace("Chorus 1", {"walk": 1.0}, 0.9, "walk")]
    marks = timeline.anchors(song, moods, ps)
    assert marks[0]["pace:rush"] == 1.0 and marks[1] is None and marks[2]["pace:walk"] == 1.0
    assert "pace:rush" not in timeline.anchors(song, moods)[0]


def test_unmatched_paces_are_reported(song, moods):
    from emotion_effecter.pace import Pace
    with pytest.raises(ValueError, match="気持ちの速さが無い: Chorus 1"):
        timeline.anchors(song, moods, [Pace("Verse 1", {"walk": 1.0}, 0.9, "walk")])
