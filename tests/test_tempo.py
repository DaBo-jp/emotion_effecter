"""気持ち + BPM → 流れ・踊りの速さ（`tempo.py`）。"""
import pytest
from cymatics import effects

from emotion_effecter import dims, scenes, tempo

T = tempo.Tempo()


def _mark(arousal, **pace):
    return {"arousal": arousal, **{"pace:" + k: v for k, v in pace.items()}}


def test_arousal_runs_from_calm_to_wild_bars():
    """arousal 0 で 8 小節、1 で 2 小節、0.5 で 4 小節（対数の真ん中）。"""
    assert [tempo.bars(_mark(a), T) for a in (0.0, 0.5, 1.0)] == [8.0, 4.0, 2.0]


def test_pace_halves_or_doubles_the_bars():
    assert tempo.bars(_mark(0.5, rush=1.0), T) == 2.0
    assert tempo.bars(_mark(0.5, linger=1.0), T) == 8.0
    assert tempo.bars(_mark(0.5, walk=1.0), T) == 4.0


def test_bars_snap_to_powers_of_two():
    """少しの違いは同じ値に丸まる ∴ 隣のセクションと無駄に入れ替えない。"""
    assert tempo.bars(_mark(0.45), T) == tempo.bars(_mark(0.55), T) == 4.0
    assert tempo.bars(_mark(0.5, walk=0.6, rush=0.4), T) == 4.0


def test_speed_crosses_the_screen_in_the_bars():
    """120 BPM・4拍子・4小節 → 8 秒で渡りきる。"""
    p = tempo.params(_mark(0.5), 120.0, T)
    assert p["speed"] == pytest.approx(1 / 8)


def test_dance_follows_the_beat_and_the_pace():
    """既定で首振りは2拍に1往復、揺れは1小節に1往復。rush で倍。"""
    p = tempo.params(_mark(0.5), 120.0, T)
    assert (p["rock_hz"], p["sway_hz"]) == pytest.approx((1.0, 0.5))
    q = tempo.params(_mark(0.5, rush=1.0), 120.0, T)
    assert (q["rock_hz"], q["sway_hz"]) == pytest.approx((2.0, 1.0))


def test_instrumental_holds_the_previous_section():
    marks = [None, _mark(1.0), None, _mark(0.0), None]
    got = [o["speed"] for o in tempo.overrides(marks, 120.0, T, tempo.KEYS)]
    assert got == pytest.approx([1 / 4, 1 / 4, 1 / 4, 1 / 16, 1 / 16])


def test_only_fields_the_effect_has():
    names = {f.name for f in effects.get("rune").fields}
    got = tempo.overrides([_mark(0.5)], 120.0, T, names, direction=-0.22)
    assert set(got[0]) == {"speed"} and got[0]["speed"] < 0      # rune は向きを保つ


def test_keys_can_be_changed_per_section():
    """ここが出す引数は `scenes` で変えられて、motif に実在する。"""
    assert set(tempo.KEYS) <= set(scenes.KEYS)
    assert set(tempo.KEYS) <= {f.name for f in effects.get("motif").fields}


def test_steps_cover_every_pace():
    assert set(tempo.STEPS) == set(dims.PACES)


def test_from_mapping_lists_every_problem():
    with pytest.raises(ValueError) as e:
        tempo.from_mapping({"bars_calm": 0.0, "bpm": "fast", "beats_per_bar": 3.5, "nope": 1})
    for part in ("bars_calm", "bpm", "beats_per_bar", "nope"):
        assert part in str(e.value), part


def test_from_mapping_round_trips():
    t = tempo.from_mapping({"bpm": 140, "beats_per_bar": 3})
    assert t.bpm == 140.0 and t.beats_per_bar == 3
    assert tempo.from_mapping(t.to_dict()) == t


def test_summary_names_lyric_sections_only():
    extra = tempo.overrides([_mark(0.5), None], 120.0, T, tempo.KEYS)
    assert tempo.summary(["Verse 1", None], extra, 120.0, T) == "Verse 1 4小節"
