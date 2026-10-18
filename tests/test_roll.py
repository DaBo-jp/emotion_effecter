"""歌詞をエンドロールのように流す（`roll`）。フォントはどの Linux にもある DejaVu で試す。"""
import numpy as np
import pytest
from PIL import Image

from emotion_effecter import lyrics, roll

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
    bot = roll._top(down, down.blocks[1], 2.0) + 2 * down.step
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
                         "band_alpha": 2, "color": "nope", "speed": 1, "mode": "fly"})
    assert len(bad) == 6


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
