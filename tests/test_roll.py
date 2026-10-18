"""歌詞をエンドロールのように流す（`roll`）。フォントはどの Linux にもある DejaVu で試す。"""
import pickle

import numpy as np
import pytest
from PIL import Image

from emotion_effecter import dims, lyrics, roll

SONG = lyrics.parse("""<!--
S
-->
[Intro @0:00]
[Verse 1 @0:02]
one
two
[Chorus 1 @0:06]
three
[Outro @0:08]
""")

CFG = {"font": "DejaVu Sans", "size": 0.1, "width": 0.3, "gap": 1.0, "line": 1.5}
SIZE = (200, 100)


def _roll(**over):
    return roll.layout(SONG, 10.0, SIZE, {**CFG, **over})


def test_each_section_head_crosses_the_anchor_at_its_start():
    r = _roll()
    blocks = dict(zip([s.name for s in SONG.sections], r.blocks))
    for name, t in (("Verse 1", 2.0), ("Chorus 1", 6.0)):
        assert roll._top(r, blocks[name], t) == pytest.approx(0.5 * SIZE[1], abs=1)


def test_up_moves_up_and_down_moves_down():
    up, down = _roll(), _roll(direction="down")
    b = up.blocks[1]
    assert roll._top(up, b, 3.0) < roll._top(up, b, 2.0)
    assert roll._top(down, down.blocks[1], 3.0) > roll._top(down, down.blocks[1], 2.0)
    # down では塊の下の端が開始時刻に基準の高さを通る
    bot = roll._top(down, down.blocks[1], 2.0) + 2 * down.blocks[1].step
    assert bot == pytest.approx(0.5 * SIZE[1], abs=1)


def test_instrumental_sections_keep_scrolling_at_the_sung_pace():
    r = _roll()
    sung = (r.blocks[1].height + r.blocks[2].height) / (4.0 + 2.0)
    assert r.blocks[0].height == pytest.approx(sung * 2.0)
    assert r.blocks[3].height == pytest.approx(sung * 2.0)


def test_alternating_sides_switch_per_sung_section():
    assert [b.side for b in _roll(position="left_right").blocks if b.lines] == ["left", "right"]
    assert [b.side for b in _roll(position="right_left").blocks if b.lines] == ["right", "left"]
    assert {b.side for b in _roll(position="center").blocks} == {"center"}


def test_draw_puts_text_and_a_translucent_band_in_the_column():
    r = _roll(position="right", band="0,0,255", band_alpha=0.4)
    out = np.asarray(roll.draw(Image.new("RGB", SIZE, (200, 0, 0)), 2.0, r, {})).astype(int)
    x0, x1 = roll.column(r, "right")
    band = out[95, (x0 + x1) // 2]                     # 帯だけの所: 赤 60% + 青 40%
    assert abs(band[0] - 120) <= 2 and abs(band[2] - 102) <= 2
    assert (out[:, :x0 - 10] == (200, 0, 0)).all()     # 列の外は触らない
    assert (out[45:60, x0:x1].min(axis=2) > 200).any()  # 白い文字


def test_long_lines_wrap_to_the_column():
    font = roll._font(roll.find_font("DejaVu Sans", "Regular"), 20, "Regular")
    lines = roll.wrap("a very long line of words that will not fit", font, 120)
    assert len(lines) > 1 and all(font.getlength(x) <= 120 for x in lines)
    assert roll.wrap("あいうえおかきくけこ", font, 40)   # 空白が無ければ文字で


def test_missing_font_is_refused_instead_of_a_silent_fallback():
    """fc-match は無いフォントにも似たものを返す——黙って使わず断る。"""
    bad = roll.problems({"font": "No Such Font JP"})
    assert len(bad) == 1 and "入っていない" in bad[0]
    assert roll.problems({"font": "DejaVu Sans", "weight": "Ultra"})


def test_every_problem_is_listed():
    bad = roll.problems({"font": "DejaVu Sans", "position": "top", "direction": "sideways",
                         "band_alpha": 2, "color": "nope", "speed": 1, "mode": "fly",
                         "band_fade": -1})
    assert len(bad) == 7


def test_card_shows_the_current_section_still_and_fades():
    """card は流れない。セクションの間は同じ位置で、頭と終わりで浮かび・消える。"""
    r = _roll(mode="card", position="center", band="0,0,255", band_alpha=0.5, fade=1.0)
    bg = Image.new("RGB", SIZE, (200, 0, 0))
    shots = {t: np.asarray(roll.draw(bg, t, r, {})).astype(int) for t in (1.0, 2.5, 3.0, 4.0, 5.5)}
    assert (shots[1.0] == (200, 0, 0)).all()                 # 間奏は何も出さない
    assert np.array_equal(shots[3.0], shots[4.0])            # 流れない
    mid = (SIZE[1] // 2, SIZE[0] // 2)
    assert abs(shots[4.0][mid][2] - 128) <= 3 or shots[4.0][mid].min() > 200   # 帯か文字
    lit = lambda a: np.abs(a - (200, 0, 0)).sum()            # noqa: E731
    assert 0 < lit(shots[2.5]) < lit(shots[4.0])             # 浮かんでいる途中
    assert 0 < lit(shots[5.5]) < lit(shots[4.0])             # 消えている途中


def test_roll_survives_pickle_for_parallel_rendering():
    """並列の書き出しは Roll を別プロセスへ渡す ∴ pickle できて、戻しても同じ。"""
    r = _roll(position="left_right")
    assert pickle.loads(pickle.dumps(r)) == r


def test_alternating_band_is_a_full_height_strip_only_on_the_side_with_lyrics():
    """交互の帯は縦に上から下まで、歌詞が見えている側だけ。もう片側は触らない。"""
    r = _roll(position="left_right", band="0,0,255", band_alpha=0.4, band_fade=0.5)
    # 1 秒: 左（Verse 1）が下から入ってきていて、右（Chorus 1）はまだ画面の外
    out = np.asarray(roll.draw(Image.new("RGB", SIZE, (200, 0, 0)), 1.0, r, {})).astype(int)
    lx = sum(roll.column(r, "left")) // 2
    rx = sum(roll.column(r, "right")) // 2
    assert (out[[0, SIZE[1] - 1], lx] == (120, 0, 102)).all()      # 左は上の端から下の端まで帯
    assert (out[:, rx] == (200, 0, 0)).all()                       # 右は歌詞が無いので触らない


def test_band_fades_in_as_the_lyrics_enter():
    r = _roll(position="left_right", band_fade=2.0)
    b = r.blocks[1]
    early = [(b, SIZE[1] - int(b.step))]                            # 1行だけ見えている
    late = [(b, 0)]
    assert 0 < roll.presence(r, "left", early) < roll.presence(r, "left", late) == 1.0
    assert roll.presence(r, "right", late) == 0.0


def test_edge_fade_dims_text_near_the_top_and_bottom_only():
    ramp = roll.edge_ramp(100, 0.2)
    assert ramp[0] < 0.05 and ramp[-1] < 0.05 and ramp[50] == 1.0 and ramp[25] == 1.0
    assert 0.4 < ramp[10] < 0.6
    bg = Image.new("RGB", SIZE, (0, 0, 0))
    r0 = _roll(position="left", band_alpha=0.0)
    r1 = _roll(position="left", band_alpha=0.0, edge_fade=0.3)
    a0, a1 = (np.asarray(roll.draw(bg, 2.5, r, {})).astype(int) for r in (r0, r1))
    x0, x1 = roll.column(r0, "left")
    assert a1[5:10, x0:x1].sum() < a0[5:10, x0:x1].sum() or a0[5:10, x0:x1].sum() == 0
    assert np.array_equal(a1[45:55], a0[45:55])          # 真ん中は同じ


PACES = [None, {"linger": 0.0, "walk": 0.0, "rush": 1.0}, {"linger": 1.0, "walk": 0.0, "rush": 0.0},
         None]


def _paced(**over):
    return roll.layout(SONG, 10.0, SIZE, {**CFG, "pace": True, "bpm": 120, **over},
                       paces=PACES)


def test_pace_tables_cover_every_pace():
    for table in (roll.PACE_LINE, roll.PACE_PULSE, roll.PACE_EDGE):
        assert tuple(table) == dims.PACES


def test_pace_sets_spacing_pulse_and_fade_per_section():
    r = _paced()
    verse, chorus = r.blocks[1], r.blocks[2]                 # rush / linger
    assert verse.step / r.px == roll.PACE_LINE["rush"] and verse.pulse == 1.0
    assert chorus.step / r.px == roll.PACE_LINE["linger"] and chorus.pulse == 0.0
    assert (verse.edge, chorus.edge) == (roll.PACE_EDGE["rush"], roll.PACE_EDGE["linger"])
    assert r.blocks[0].pulse == 0.0 and r.blocks[0].edge == CFG.get("edge_fade", 0.0)


def test_pulse_steps_on_the_beat_but_keeps_the_section_heads():
    """拍ごとに刻んでも、各セクションの頭は開始時刻に基準の高さを通る。"""
    r = _paced()
    for name, t in (("Verse 1", 2.0), ("Chorus 1", 6.0)):
        b = dict(zip([s.name for s in SONG.sections], r.blocks))[name]
        assert roll._top(r, b, t) == pytest.approx(0.5 * SIZE[1], abs=1)
    # 120 BPM = 0.5 秒で1拍。拍の頭の直後はもう大きく進んでいる（ease-out）
    y0, y1, y2 = (r.offset(t) for t in (2.0, 2.1, 2.5))
    assert (y1 - y0) / (y2 - y0) > 0.4                        # 直線なら 0.2
    assert roll.pulsed(0.0, 8, 1.0) == 0.0 and roll.pulsed(1.0, 8, 1.0) == 1.0
    assert roll.pulsed(0.3, 8, 0.0) == 0.3


def test_fade_width_moves_between_sections_over_the_switch_time():
    r = _paced()
    rush, linger = roll.PACE_EDGE["rush"], roll.PACE_EDGE["linger"]
    assert r.edge_at(4.0) == pytest.approx(rush)
    assert r.edge_at(6.0) == pytest.approx((rush + linger) / 2)
    assert r.edge_at(6.0 + roll.EDGE_SWITCH / 2) == pytest.approx(linger)


def test_pace_without_paces_is_refused():
    with pytest.raises(ValueError, match="気持ちの速さ"):
        roll.layout(SONG, 10.0, SIZE, {**CFG, "pace": True})
