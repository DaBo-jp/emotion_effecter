"""気持ち + BPM → 流れ・数・踊りの速さ（`tempo.py`）。"""
import pytest
from cymatics import effects

from emotion_effecter import dims, scenes, tempo

#: 2のべきに丸め、引き伸ばさない（写像の芯だけを見る）
T = tempo.Tempo(snap=1, stretch=0.0)
MOTIF = {"speed": 0.15, "rate": 4.0, "sway_hz": 0.6, "rock_hz": 1.1}


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


def test_finer_snap_has_steps_between_octaves():
    """snap=2 なら √2 刻み。2のべきでは同じだった 4 小節と 2.83 小節が分かれる。"""
    t = tempo.Tempo(snap=2, stretch=0.0)
    assert tempo.bars(_mark(0.5, walk=0.5, rush=0.5), t) == pytest.approx(2 ** 1.5)
    assert tempo.bars(_mark(0.5), t) == 4.0


def test_stretch_spreads_the_song_over_the_whole_range():
    """曲の最小〜最大が 0..1 になる。0 で生のまま。歌詞の無いセクションは None のまま。"""
    marks = [_mark(0.4), None, _mark(0.6), _mark(0.5)]
    full = tempo.stretched(marks, tempo.Tempo(stretch=1.0))
    assert [m and m["arousal"] for m in full] == pytest.approx([0.0, None, 1.0, 0.5])
    half = tempo.stretched(marks, tempo.Tempo(stretch=0.5))
    assert half[0]["arousal"] == pytest.approx(0.2)
    assert tempo.stretched(marks, tempo.Tempo(stretch=0.0)) == marks


def test_stretch_of_a_flat_song_goes_to_the_middle():
    marks = [_mark(0.9), _mark(0.9)]
    assert [m["arousal"] for m in tempo.stretched(marks, tempo.Tempo())] == [0.5, 0.5]


def test_speed_crosses_the_screen_in_the_bars():
    """120 BPM・4拍子・4小節 → 8 秒で渡りきる。"""
    p = tempo.params(_mark(0.5), 120.0, T, MOTIF)
    assert p["speed"] == pytest.approx(1 / 8)


def test_dance_follows_the_beat_and_the_pace():
    """既定で首振りは2拍に1往復、揺れは1小節に1往復。rush で倍。"""
    p = tempo.params(_mark(0.5), 120.0, T, MOTIF)
    assert (p["rock_hz"], p["sway_hz"]) == pytest.approx((1.0, 0.5))
    q = tempo.params(_mark(0.5, rush=1.0), 120.0, T, MOTIF)
    assert (q["rock_hz"], q["sway_hz"]) == pytest.approx((2.0, 1.0))


def _on_screen(p):
    """画面に居る数 = 湧く数 × 渡りきる秒数。"""
    return p["rate"] / abs(p["speed"])


def test_rate_keeps_the_count_when_walking():
    """walk なら速さが変わっても画面に居る数は元と同じ（速く流れても減らない）。"""
    p = tempo.params(_mark(1.0), 120.0, T, MOTIF)
    assert _on_screen(p) == pytest.approx(_on_screen(MOTIF))


def test_rate_grows_with_the_pace():
    """rush で倍、linger で半分（density_gain=1）。0 なら数を変えない。"""
    rush = tempo.params(_mark(0.5, rush=1.0), 120.0, T, MOTIF)
    linger = tempo.params(_mark(0.5, linger=1.0), 120.0, T, MOTIF)
    assert _on_screen(rush) == pytest.approx(2 * _on_screen(MOTIF))
    assert _on_screen(linger) == pytest.approx(_on_screen(MOTIF) / 2)
    flat = tempo.params(_mark(0.5, rush=1.0), 120.0,
                        tempo.Tempo(snap=1, stretch=0.0, density_gain=0.0), MOTIF)
    assert _on_screen(flat) == pytest.approx(_on_screen(MOTIF))


def test_instrumental_holds_the_previous_section():
    marks = [None, _mark(1.0), None, _mark(0.0), None]
    got = [o["speed"] for o in tempo.overrides(marks, 120.0, T, MOTIF)]
    assert got == pytest.approx([1 / 4, 1 / 4, 1 / 4, 1 / 16, 1 / 16])


def test_only_fields_the_effect_has():
    """rune は揺れ・首振りを持たない。speed の向き（負で右から左）は保つ。"""
    got = tempo.overrides([_mark(0.5)], 120.0, T, {"speed": -0.22, "rate": 6.0})
    assert set(got[0]) == {"speed", "rate"} and got[0]["speed"] < 0 < got[0]["rate"]


def test_keys_can_be_changed_per_section():
    """ここが出す引数は `scenes` で変えられて、motif に実在する。"""
    assert set(tempo.KEYS) <= set(scenes.KEYS)
    assert set(tempo.KEYS) <= {f.name for f in effects.get("motif").fields}


def test_steps_cover_every_pace():
    assert set(tempo.STEPS) == set(dims.PACES)


def test_from_mapping_lists_every_problem():
    with pytest.raises(ValueError) as e:
        tempo.from_mapping({"bars_calm": 0.0, "bpm": "fast", "beats_per_bar": 3.5,
                            "snap": 0, "stretch": 2, "nope": 1})
    for part in ("bars_calm", "bpm", "beats_per_bar", "snap", "stretch", "nope"):
        assert part in str(e.value), part


def test_from_mapping_round_trips():
    t = tempo.from_mapping({"bpm": 140, "beats_per_bar": 3, "snap": 3})
    assert t.bpm == 140.0 and t.beats_per_bar == 3 and t.snap == 3
    assert tempo.from_mapping(t.to_dict()) == t


def test_summary_names_lyric_sections_only():
    extra = tempo.overrides([_mark(0.5), None], 120.0, T, MOTIF)
    assert tempo.summary(["Verse 1", None], extra, 120.0, T) == "Verse 1 4小節"
