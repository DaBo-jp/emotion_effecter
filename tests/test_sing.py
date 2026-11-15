"""行の時刻（`lines`）と、歌っている行に合わせた歌詞（`sing`：カラオケの帯・縦書き）。"""
import json
import shutil

import numpy as np
import pytest
from PIL import Image

from emotion_effecter import lines, lyrics, manifest, sing

SONG = lyrics.parse("[Intro @0:00]\n\n[Verse 1 @0:02]\n夜明けの街で\nyou are the human\n"
                    "[Chorus 1 @0:08]\n何が好きなの　connection\n")
SIZE = (320, 180)
needs_fonts = pytest.mark.skipif(shutil.which("fc-match") is None, reason="fontconfig が無い")


def test_spread_splits_each_section_by_characters():
    assert lines.spread(SONG, 12.0) == [[], [2.0, 3.565], [8.0]]   # 6文字 : 17文字（空白込み）


def test_build_ends_each_line_at_the_next_or_the_section_end():
    rows = lines.build(SONG, [[], [2.0, 4.0], [8.5]], 12.0)
    assert [(r.text, r.start, r.end) for r in rows] == [
        ("夜明けの街で", 2.0, 4.0), ("you are the human", 4.0, 8.0),
        ("何が好きなの　connection", 8.5, 12.0)]


def test_line_times_are_refused_when_out_of_order_or_miscounted():
    with pytest.raises(ValueError, match="順に増えて"):
        lines.build(SONG, [[], [4.0, 2.0], [8.5]], 12.0)
    with pytest.raises(ValueError, match="数が歌詞の行の数と合わない"):
        lines.build(SONG, [[], [2.0], [8.5]], 12.0)


def test_saved_line_times_are_refused_when_the_lyrics_change(tmp_path):
    p = tmp_path / "lines.json"
    lines.save(p, SONG, [[], [2.0, 4.0], [8.5]])
    assert lines.load(p, SONG) == [[], [2.0, 4.0], [8.5]]
    changed = lyrics.parse("[Intro @0:00]\n\n[Verse 1 @0:02]\n夜明けの町で\nyou are the human\n"
                           "[Chorus 1 @0:08]\n何が好きなの　connection\n")
    with pytest.raises(ValueError, match="歌詞が変わった"):
        lines.load(p, changed)


def _sg(mode="karaoke", **cfg):
    rows = lines.build(SONG, [[], [2.0, 4.0], [8.5]], 12.0)
    return sing.Sing(rows, ((0.0, 2.0), (2.0, 8.0), (8.0, 12.0)), SIZE, 10, tuple(sorted(
        {**sing.DEFAULTS, "mode": mode, "position": sing.MODES[mode][0], "fade": 0.0,
         "lead": 0.5, **cfg}.items())), ("", 0))


def test_two_lines_at_most_the_sung_one_and_the_next():
    sg = _sg()
    assert [i for i, _ in sing.on_screen(sg, 1.6)] == [0]      # セクションの頭は lead 秒前
    assert [i for i, _ in sing.on_screen(sg, 2.5)] == [0, 1]   # 歌っている行と次の行
    assert [i for i, _ in sing.on_screen(sg, 4.5)] == [1]      # 歌い終えた行は消える
    assert [i for i, _ in sing.on_screen(sg, 8.2)] == [2]      # 次のセクションは lead 秒前
    assert sing.on_screen(sg, 1.0) == []


def test_a_line_left_alone_is_cleared_after_a_while():
    """セクションの最後の行の後ろが長い間奏でも、出しっぱなしにしない。"""
    assert sing.until(_sg().lines[2]) == pytest.approx(min(12.0, 8.5 + 1.5 + 0.45 * 17))


def test_runs_split_japanese_from_latin():
    assert sing.runs("何が好きなの　connection") == [("何が好きなの　", True),
                                                     ("connection", False)]
    assert sing.runs("you are") == [("you are", False)]


def test_problems_know_each_mode():
    assert sing.problems({"mode": "karaoke", "position": "left", "size": 3, "sung": 1},
                         None)[:3] == [
        "credits の知らない項目: sung（karaoke では）",
        "credits.position='left' は bottom / top のどれか（karaoke では）",
        "credits.size=3 は 0.01..0.2 の数"]


@needs_fonts
def test_manifest_checks_credits_by_mode(tmp_path):
    for f in ("l.md", "a.wav", "i.png"):
        (tmp_path / f).write_text("x")
    doc = {"title": "T", "files": {"lyrics": "l.md", "audio": "a.wav", "image": "i.png"},
           "base": {"preset": "shape"}, "credits": {"mode": "vertical", "position": "bottom"}}
    (tmp_path / "song.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="right / left のどれか（vertical では）"):
        manifest.load(tmp_path)


def _frame(mode, position, t):
    rows = lines.build(SONG, [[], [2.0, 4.0], [8.5]], 12.0)
    spans = ((0.0, 2.0), (2.0, 8.0), (8.0, 12.0))
    sg = sing.layout(rows, spans, SIZE, {"mode": mode, "position": position, "size": 0.08,
                                         "lead": 0.5, "fade": 0.0})
    bg = Image.new("RGB", SIZE, (0, 0, 0))
    return np.asarray(sing.draw(bg, t, sg, {})).astype(int)


@needs_fonts
def test_karaoke_band_sits_at_the_bottom_with_two_rows():
    f = _frame("karaoke", "bottom", 3.0)
    lit = np.argwhere(f.sum(axis=2) > 300)
    assert lit[:, 0].min() > SIZE[1] // 2                      # 下半分だけ
    rows = np.unique(lit[:, 0] // 8)
    assert rows.max() - rows.min() >= 2                        # 2段
    assert not _frame("karaoke", "bottom", 1.0).any()          # lead 秒前より前は無い
    assert _frame("karaoke", "top", 3.0)[: SIZE[1] // 2].sum() > 0
    assert set(map(tuple, f.reshape(-1, 3))) <= {(r, r, r) for r in range(256)}  # 色は変えない


@needs_fonts
def test_vertical_sits_on_the_chosen_edge():
    right, left = _frame("vertical", "right", 3.0), _frame("vertical", "left", 3.0)
    assert right[:, SIZE[0] // 2:].sum() > 0 and not right[:, : SIZE[0] // 2].any()
    assert left[:, : SIZE[0] // 2].sum() > 0 and not left[:, SIZE[0] // 2:].any()
    assert not _frame("vertical", "right", 1.0).any()          # 間奏（歌詞の無いセクション）
