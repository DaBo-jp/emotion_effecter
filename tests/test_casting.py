import pytest
from cymatics import effects

from emotion_effecter import casting, dims

FLAT = {e: 0.5 for e in dims.ELEMENTS}


def test_declaration_is_clean():
    assert casting.problems() == []


def test_problems_lists_everything():
    bad = casting._cast("arc", {}, {"lava": 1.0, "fire": 0.0}, 0, "")
    msgs = casting.problems({"x": bad})
    assert len(msgs) == 3


def test_every_effect_is_cast_or_excluded_with_a_reason():
    """黙って外さない。cymatics に effect が増えたらここで落ちる。"""
    cast = {c.effect for c in casting.CASTS.values()}
    assert cast | set(casting.EXCLUDED) == set(effects.names())
    assert not cast & set(casting.EXCLUDED)


@pytest.mark.parametrize("name", list(casting.CASTS))
def test_cast_params_are_fields_of_the_effect(name):
    c = casting.CASTS[name]
    known = {f.name for f in effects.get(c.effect).fields}
    assert set(c.params) <= known


def test_tempo_fit_peaks_at_center_and_is_symmetric_in_octaves():
    assert casting.tempo_fit(100, 100) == 1.0
    assert casting.tempo_fit(200, 100) == pytest.approx(casting.tempo_fit(50, 100))
    assert casting.tempo_fit(200, 100) < casting.tempo_fit(120, 100)


def test_flat_song_ranks_by_tempo_only():
    """どの属性も同じなら属性の合い方は全員 0。順位はテンポだけで決まる。"""
    ranked = casting.rank(FLAT, 70)
    assert all(s.fit == pytest.approx(0) for s in ranked)
    assert ranked[0].cast.tempo == 70


def test_dominant_element_wins():
    metal = FLAT | {"metal": 1.0}
    assert casting.rank(metal, 120)[0].name == "scope"
    fire = FLAT | {"fire": 1.0}
    assert casting.rank(fire, 80)[0].name == "sparks"


def test_parts_sum_to_fit():
    s = casting.rank(FLAT | {"dark": 0.9, "earth": 0.7}, 70)[0]
    assert sum(s.parts.values()) == pytest.approx(s.fit)


def test_rank_refuses_missing_elements_listing_them():
    with pytest.raises(ValueError, match="water.*earth"):
        casting.rank({"metal": 1.0}, 120)


def test_report_marks_current_effect():
    ranked = casting.rank(FLAT | {"metal": 1.0}, 120)
    md = casting.report("T", FLAT, FLAT, 120, ranked, current="line")
    assert "scope ◀ 今" in md and "harmonic ◀ 今" in md
    assert md.count("◀ 今") == 2
