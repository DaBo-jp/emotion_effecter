"""セクションごとの採点 → 毎フレームの感情曲線。

- 歌詞のあるセクションは採点値で一定
- 歌詞の無いセクション（間奏・後奏）は、前後の歌詞セクションの値を直線でつなぐ。
  片側しか無ければその値を保つ
- 最後に `xfade` 秒のハン窓でならす。∴ 境界は xfade 秒かけて移り変わる

曲線の名前は Score の次元（`acceptance` など）と、Choice の確率（`emo:doubt` など）。
聴衆の映像を採点してあれば、その軸（`hype`）も入る。**聴衆の軸は間奏にも値がある**
（聴衆は間奏でこそ沸く）ので、歌詞の軸とは別に置いてからならす。
フレーム番号は曲の先頭から数える（cymatics の `Frame.f` と同じ）ので、
分割書き出しでも同じ値になる。

**`Timeline` は書き換えられない。** 配列は読み取り専用にしてある——描画の途中で
曲線が変われば、区間ごとに違う絵になる。並列の書き出しで別プロセスへ渡すので、
pickle できる形（名前の tuple と2次元配列）で持つ。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from .audience import Cheer
from .lyrics import Song
from .mood import DIMS, Mood
from .pace import Pace

Anchor = dict[str, float] | None


@dataclass(frozen=True)
class Timeline:
    fps: int
    #: 曲線の名前
    names: tuple[str, ...]
    #: (名前の数, フレーム数)。読み取り専用
    values: np.ndarray

    def __post_init__(self):
        v = np.array(self.values, dtype=np.float64)
        v.setflags(write=False)
        object.__setattr__(self, "values", v)

    def at(self, name: str, f: int) -> float:
        row = self.values[self.names.index(name)]
        return float(row[min(max(f, 0), len(row) - 1)])

    def frame(self, f: int) -> dict[str, float]:
        """そのフレームの全曲線。範囲外のフレームは端の値。"""
        i = min(max(f, 0), self.values.shape[1] - 1)
        return dict(zip(self.names, self.values[:, i].tolist()))

    def curve(self, name: str) -> np.ndarray:
        return self.values[self.names.index(name)]


def align(song: Song, items: Sequence[Any], what: str = "採点") -> list[Any]:
    """セクションごとの item（`.section` で名前を持つ）。歌詞の無いセクションは None。
    名前で順に対応づける。

    **対応しないものは黙って捨てない。** item の無い歌詞セクションも、どのセクションにも
    当たらない item も、全部並べて断る。
    """
    queue, out, missing = list(items), [], []
    for sec in song.sections:
        i = next((i for i, m in enumerate(queue) if m.section == sec.name), None)
        if sec.instrumental or i is None:
            out.append(None)
            missing += [] if sec.instrumental else [sec.name]
            continue
        out.append(queue.pop(i))
    bad = (["%sが無い: %s" % (what, n) for n in missing]
           + ["当たるセクションが無い%s: %s" % (what, m.section) for m in queue])
    if bad:
        raise ValueError("歌詞と%sが対応しない:\n  %s" % (what, "\n  ".join(bad)))
    return out


def _values(m: Mood, p: Pace | None) -> dict[str, float]:
    vals = {k: m.scores[k] for k in DIMS}
    vals.update({"emo:" + k: v for k, v in m.distributions["emotion"].items()})
    if p is not None:
        vals.update({"pace:" + k: v for k, v in p.probabilities.items()})
    return vals


def anchors(song: Song, moods: Sequence[Mood],
            paces: Sequence[Pace] | None = None) -> list[Anchor]:
    """セクションごとの値。歌詞の無いセクションは None。

    `paces`（気持ちの速さ）を渡すと `pace:<ラベル>` の確率も入る。
    """
    ms = align(song, moods)
    ps = align(song, paces, "気持ちの速さ") if paces is not None else [None] * len(ms)
    return [None if m is None else _values(m, p) for m, p in zip(ms, ps)]


def cheer_marks(song: Song, cheers: Sequence[Cheer]) -> list[Anchor]:
    """セクションごとの聴衆の軸。**全セクションに要る。** 名前で順に対応づけ、
    対応しないものは全部並べて断る。"""
    names = [c.section for c in cheers]
    want = [s.name for s in song.sections]
    if names != want:
        bad = (["聴衆の採点が無い: %s" % n for n in want if n not in names]
               + ["当たるセクションが無い聴衆の採点: %s" % n for n in names if n not in want])
        bad = bad or ["並びが違う: %s" % " / ".join(names)]
        raise ValueError("歌詞と聴衆の採点が対応しない:\n  " + "\n  ".join(bad))
    return [dict(c.scores) for c in cheers]


def _fill(marks: list[Anchor], frames: list[int], n: int, key: str) -> np.ndarray:
    """セクションの境界フレーム `frames`（先頭 0、末尾 n）に沿って値を置く。"""
    curve = np.zeros(n)
    for j, a in enumerate(marks):
        fs, fe = frames[j], frames[j + 1]
        if a is not None:
            curve[fs:fe] = a[key]
            continue
        prev = next((x[key] for x in reversed(marks[:j]) if x), None)
        nxt = next((x[key] for x in marks[j + 1:] if x), None)
        lo, hi = (prev if prev is not None else nxt), (nxt if nxt is not None else prev)
        curve[fs:fe] = np.linspace(lo, hi, fe - fs)
    return curve


def _smooth(curve: np.ndarray, width: int) -> np.ndarray:
    if width < 2:
        return curve
    win = np.hanning(width)
    win /= win.sum()
    pad = np.pad(curve, width, mode="edge")
    return np.convolve(pad, win, "same")[width:-width]


def build(song: Song, moods: Sequence[Mood], duration: float, fps: int,
          xfade: float = 2.0, cheers: Sequence[Cheer] | None = None) -> Timeline:
    """`song` は開始時刻つき（`[Verse 1 @0:13.35]`）であること。

    `cheers`（聴衆の採点）を渡すと、その軸の曲線も入る。
    """
    if not song.timed:
        raise ValueError("開始時刻の無いセクションがある（sections コマンドで推定する）")
    n = int(duration * fps) + 1
    frames = [min(n, int(round(s.start * fps))) for s in song.sections] + [n]
    sets = [anchors(song, moods)]
    if cheers is not None:
        sets.append(cheer_marks(song, cheers))
    width = int(xfade * fps)
    rows = {k: _smooth(_fill(marks, frames, n, k), width)
            for marks in sets for k in sorted({k for a in marks if a for k in a})}
    names = tuple(sorted(rows))
    return Timeline(fps, names, np.array([rows[k] for k in names]))
