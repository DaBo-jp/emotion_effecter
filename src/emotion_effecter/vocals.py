"""ボーカルの書き起こし → 歌詞の行とセクションの時刻。**緩く当てはめる。**

書き起こしは歌詞と1文字ずつは合わない（「解って」→「わかって」、「whole」→「home」、
行の落ち）。そこで

1. 歌詞も書き起こしも、記号と空白を落として小文字の1本の文字列にする
2. 2本の**一致する部分**（difflib）を並び順のまま拾い、歌詞の文字に書き起こしの時刻を写す
3. 行の歌い出し = 行の頭のほう（`HEAD` の割合まで）で最初に一致した文字の時刻。
   拾えなかった行は、前後の拾えた行の間を文字数の割合で埋める。曲の最初の行が
   拾えなければ、声の大きさが閾値を越えた最初の時刻（stem は無音にならないので、
   いちばん大きいところから `BELOW_DB` 下で切る）
4. セクションの頭 = 最初の行の歌い出しの `LEAD` 秒前（前の行の歌い終わりより前には
   しない）。歌の無いセクション（間奏）は前の行の歌い終わり。最初のセクションは 0
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .lyrics import Song

#: 行の頭から、この割合（か2文字）までに一致があれば歌い出しとみなす
HEAD = 0.4
#: セクションの頭を歌い出しより前に置く秒（絵が声より少し先に変わる）
LEAD = 0.25
#: 声がある = いちばん大きいところからこの dB 以内
BELOW_DB = 25.0
#: 声の大きさを測る刻み（秒）
HOP = 0.05
#: 埋めた行どうしの最小の間（秒）
MIN_GAP = 0.1


@dataclass(frozen=True)
class Timing:
    """セクションの頭（秒）、行の歌い出し（セクションごと）、書き起こしで拾えなかった行。"""

    sections: tuple[float, ...]
    lines: tuple[tuple[float, ...], ...]
    filled: tuple[tuple[int, int], ...]


def norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text).lower())


def onset(x: np.ndarray, sr: int, below_db: float = BELOW_DB) -> float | None:
    """声が閾値を越えた最初の秒。声が無ければ None。"""
    hop = max(int(sr * HOP), 1)
    n = len(x) // hop
    if n == 0:
        return None
    rms = np.sqrt(np.mean(x[:n * hop].reshape(n, hop).astype(np.float64) ** 2, axis=1))
    db = 20 * np.log10(rms + 1e-9)
    on = np.flatnonzero(db >= db.max() - below_db)
    return float(on[0] * hop / sr) if len(on) and rms.max() > 1e-6 else None


def _chars(words: Sequence[tuple[float, float, str]]) -> tuple[str, list[float], list[float]]:
    """書き起こし → 1本の文字列と、文字ごとの (時刻, その語の歌い終わり)。"""
    text, at, end = [], [], []
    for a, b, w in words:
        n = norm(w)
        for i, c in enumerate(n):
            text.append(c)
            at.append(a + (b - a) * i / len(n))
            end.append(b)
    return "".join(text), at, end


def _matched(song: Song, words) -> tuple[list[str], dict[int, tuple[float, float]]]:
    """歌詞の行（正規化）と、歌詞の文字の位置 → (時刻, 歌い終わり)。"""
    rows = [norm(ln) for s in song.sections for ln in s.lines]
    heard, at, end = _chars(words)
    sm = difflib.SequenceMatcher(None, "".join(rows), heard, autojunk=False)
    hit = {a + k: (at[b + k], end[b + k])
           for a, b, n in sm.get_matching_blocks() for k in range(n)}
    return rows, hit


def _per_line(rows: list[str], hit) -> tuple[list[float | None], list[float | None]]:
    """行ごとの歌い出しと歌い終わり（拾えなければ None）。"""
    starts, ends, pos = [], [], 0
    for r in rows:
        got = [(k, hit[pos + k]) for k in range(len(r)) if pos + k in hit]
        head = got and got[0][0] <= max(2, len(r) * HEAD)
        starts.append(got[0][1][0] if head else None)
        ends.append(max(t for _, (_, t) in got) if got else None)
        pos += len(r)
    return starts, ends


def _fill(starts: list[float | None], sizes: list[int], first: float | None) -> list[float]:
    """拾えなかった行を、前後の拾えた行の間に文字数の割合で置く。"""
    out = list(starts)
    if out and out[0] is None and first is not None:
        out[0] = first
    known = [i for i, t in enumerate(out) if t is not None]
    if not known:
        raise ValueError("書き起こしが歌詞のどの行とも合わない")
    cum = np.concatenate([[0], np.cumsum(sizes)]).astype(float)
    rate = _rate(out, known, cum)
    for i, t in enumerate(out):
        if t is None:
            out[i] = _between(out, known, cum, i, rate)
    for i in range(1, len(out)):
        out[i] = max(out[i], out[i - 1] + MIN_GAP)
    return [float(t) for t in out]


def _rate(out, known: list[int], cum: np.ndarray) -> float:
    """1文字あたりの秒（拾えた行どうしの中央値）。"""
    r = [(out[j] - out[i]) / max(cum[j] - cum[i], 1) for i, j in zip(known, known[1:])]
    return float(np.median(r)) if r else 0.3


def _between(out, known: list[int], cum: np.ndarray, i: int, rate: float) -> float:
    lo = max((k for k in known if k < i), default=None)
    hi = min((k for k in known if k > i), default=None)
    if lo is not None and hi is not None:
        u = (cum[i] - cum[lo]) / max(cum[hi] - cum[lo], 1)
        return out[lo] + u * (out[hi] - out[lo])
    if lo is not None:
        return out[lo] + rate * (cum[i] - cum[lo])
    return max(out[hi] - rate * (cum[hi] - cum[i]), 0.0)


def _section_starts(song: Song, flat: list[float], ends: list[float | None]) -> list[float]:
    out, i, prev_end = [], 0, 0.0
    for s in song.sections:
        if s.lines:
            out.append(max(flat[i] - LEAD, min(prev_end, flat[i])))
            last = i + len(s.lines) - 1
            prev_end = ends[last] if ends[last] is not None else flat[last]
            i += len(s.lines)
        else:
            out.append(prev_end)
    out[0] = 0.0
    for k in range(1, len(out)):
        out[k] = max(out[k], out[k - 1])
    return out


def align(song: Song, words: Sequence[tuple[float, float, str]],
          first: float | None = None) -> Timing:
    """書き起こし → 時刻。`first` は声の立ち上がり（最初の行が拾えないときに使う）。"""
    rows, hit = _matched(song, words)
    starts, ends = _per_line(rows, hit)
    flat = _fill(starts, [max(len(r), 1) for r in rows], first)
    keys = [(si, li) for si, s in enumerate(song.sections) for li in range(len(s.lines))]
    lines, i = [], 0
    for s in song.sections:
        lines.append(tuple(flat[i:i + len(s.lines)]))
        i += len(s.lines)
    return Timing(tuple(_section_starts(song, flat, ends)), tuple(lines),
                  tuple(k for k, t in zip(keys, starts) if t is None))
