import pytest

from emotion_effecter import policy

ICE, WARM = (200, 250, 255), (255, 176, 150)
CALM = {"acceptance": 0.0, "conflict": 0.0, "valence": 0.5, "arousal": 0.5,
        "dominance": 0.5}


def test_hue_turns_the_requested_way():
    via_violet = policy.mix(ICE, WARM, 0.5, turn=1)
    via_green = policy.mix(ICE, WARM, 0.5, turn=0)
    assert via_violet[2] > via_violet[1]           # 青み > 緑み
    assert via_green[1] > via_green[2]


def test_mix_ends_at_both_colours():
    assert policy.mix(ICE, WARM, 0.0, 1) == ICE
    assert policy.mix(ICE, WARM, 1.0, 1) == WARM


def test_closed_heart_keeps_the_base_colour():
    lk = policy.look(CALM | {"acceptance": 0.3}, t=1.0, base=ICE)
    assert lk.color == ICE


def test_full_acceptance_reaches_warm():
    lk = policy.look(CALM | {"acceptance": 1.0}, t=1.0, base=ICE)
    assert lk.color == WARM


def test_conflict_moves_the_hue_over_time():
    cols = {policy.look(CALM | {"conflict": 1.0}, t=t / 10, base=ICE).color for t in range(20)}
    assert len(cols) > 5


def test_valence_and_arousal_scale_glow_and_gain():
    pol = policy.Policy()
    lo = policy.look(CALM | {"valence": 0.0, "arousal": 0.0}, 0.0, ICE, pol)
    hi = policy.look(CALM | {"valence": 1.0, "arousal": 1.0}, 0.0, ICE, pol)
    assert (lo.glow, hi.glow) == (pol.glow_lo, pol.glow_hi)
    assert (lo.gain, hi.gain) == (pol.gain_lo, pol.gain_hi)


def test_no_movement_returns_the_colour_untouched():
    """HSV に開いて閉じると丸めで1ずれうるので、動かさないときは触らない。"""
    for c in [(255, 248, 235), (150, 24, 36), (1, 2, 3), (200, 250, 255)]:
        assert policy.mix(c, WARM, 0.0, 1) == c and policy.rotate(c, 0.0) == c


def test_from_mapping_lists_every_problem():
    with pytest.raises(ValueError) as e:
        policy.from_mapping({"glow_hi": -1, "turn": 2, "wram": "red"})
    msg = str(e.value)
    assert "知らない項目: wram" in msg and "glow_hi" in msg and "turn" in msg


def test_from_mapping_reads_cymatics_colours():
    assert policy.from_mapping({"warm": "crimson"}).warm == (150, 24, 36)
    assert policy.from_mapping({"warm": [1, 2, 3]}).warm == (1, 2, 3)


def test_default_policy_is_valid():
    assert policy.Policy().problems() == []


def test_dict_roundtrip():
    pol = policy.Policy(warm=(1, 2, 3), glow_hi=2.0)
    assert policy.from_mapping(pol.to_dict()) == pol


def test_grey_base_does_not_sweep_through_other_hues():
    frost, gold = (236, 248, 255), (255, 186, 84)
    mid = policy.mix(frost, gold, 0.5, turn=1)
    assert mid[0] >= mid[1] >= mid[2]          # 金の向き（赤 ≥ 緑 ≥ 青）。ピンクを通らない


def test_channels_can_follow_other_dimensions():
    pol = policy.Policy(color_by="dominance", color_invert=True, glow_by="dominance",
                        glow_lo=2.0, glow_hi=0.5)
    taking = policy.look(CALM | {"dominance": 1.0}, 0.0, ICE, pol)
    yielding = policy.look(CALM | {"dominance": 0.0}, 0.0, ICE, pol)
    assert taking.color == ICE and yielding.color == WARM      # 手放すほど warm へ
    assert (taking.glow, yielding.glow) == (0.5, 2.0)


def test_unknown_dimension_is_refused():
    with pytest.raises(ValueError, match="color_by"):
        policy.from_mapping({"color_by": "openness"})
