"""拍の特徴から、歌詞セクションの開始時刻を割り当てる。

セクションの並び（歌詞のタグ）は分かっているので、やることは「どの拍で次へ
移るか」を選ぶことだけ。

1. 拍どうしの自己類似行列から、構造の切れ目らしさ（novelty, Foote）を出す
2. 境界の候補 = novelty の山 ＋ それを**繰り返しの間隔だけずらした位置**。
   Verse → Pre-Chorus のようになだらかに移る境界は山が立たないが、
   2番の同じ位置に山があれば拾える
3. 候補にセクション列を割り当て、次の和を最大にする（ビームサーチ）
   - 境界の novelty
   - **同じ種類のセクション（Chorus 1 / 2 / Last など）が音として似ていること**
   - 同じ種類のセクションの長さが揃っていること
   - **1行あたりの長さがセクション間で揃っていること**（行数が長さの目安。
     これが無いと Verse と Pre-Chorus を取り違えた）

境界ごとに「そこが違う割り当ての最良との差」を確度（margin）として返す。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from .beats import Beats
from .lyrics import Song

NOVELTY_HALF = 8     # novelty の窓の片側（拍）
CANDIDATE_FLOOR = 0.2
MIN_BEATS = 8        # セクションの最短（拍）
PER_START = 30       # ビームに残す数（最後の境界の位置ごと）

W_REP = 2.0          # 同種セクションの類似度
W_LEN = 1.5          # 同種セクションの長さのずれ（比）
W_RATE = 0.5         # 1行あたりの長さのずれ（対数比）

#: margin がこれ未満の境界は耳で確かめる候補
DOUBTFUL = 0.2


@dataclass(frozen=True)
class Boundary:
    section: str
    start: float
    #: 次点の割り当てとのスコア差。小さいほど怪しい（先頭は inf）
    margin: float

    @property
    def doubtful(self) -> bool:
        return self.margin < DOUBTFUL


def kind(name: str) -> str:
    """セクション名 → 種類。同じ種類なら音も似ているはず。

    `Chorus 2` / `Last Chorus` / `Last-Chorus` → `chorus`。`" - "` 以降は注記
    （`Pre-Chorus 1 - high backing vocals`）なので外す。`Drop Chorus` は編成も
    行数も違うので別の種類のまま残す——同じ種類にすると「似ているはず」が
    割り当てを誤らせる。
    """
    n = name.split(" - ", 1)[0].lower().strip()
    n = re.sub(r"\s*\d+$", "", n)
    n = re.sub(r"^(last|final)[-\s]*", "", n)
    return "outro" if n.startswith("outro") else n


def novelty(sim: np.ndarray, k: int = NOVELTY_HALF) -> np.ndarray:
    """チェッカーボード核で切れ目らしさを出す。0..1 に正規化。"""
    t = np.linspace(-1, 1, 2 * k)
    g = np.outer(np.sign(t), np.sign(t)) * np.exp(-4 * np.add.outer(t ** 2, t ** 2))
    p = np.pad(sim, k, mode="edge")
    nv = np.array([(p[i:i + 2 * k, i:i + 2 * k] * g).sum() for i in range(len(sim))])
    return (nv - nv.min()) / (np.ptp(nv) + 1e-9)


def lags(sim: np.ndarray, top: int = 3, min_lag: int = 4 * NOVELTY_HALF) -> list[int]:
    """曲の中で繰り返しが起きている間隔（拍）。対角の平均類似度の山の上位。"""
    prof = np.array([np.diagonal(sim, k).mean() for k in range(len(sim) // 2)])
    peaks = [k for k in range(min_lag, len(prof) - 1)
             if prof[k] >= prof[k - 1] and prof[k] > prof[k + 1]]
    return sorted(peaks, key=lambda k: -prof[k])[:top]


def candidates(nv: np.ndarray, sim: np.ndarray, floor: float = CANDIDATE_FLOOR) -> list[int]:
    """境界の候補（拍番号、昇順）。先頭の 0 は必ず入る。"""
    peaks = [i for i in range(1, len(nv) - 1)
             if nv[i] >= nv[i - 1] and nv[i] > nv[i + 1] and nv[i] > floor]
    shifted = {p + s * k for p in peaks for k in lags(sim) for s in (-1, 1)}
    out: list[int] = [0]
    for c in sorted(set(peaks) | {c for c in shifted if 0 < c < len(nv)}):
        if c - out[-1] > 2:                   # 2拍以内の重複は先のものを残す
            out.append(c)
    return out


# ------------------------------------------------------------- 割り当て
@dataclass(frozen=True)
class _Job:
    kinds: list[str]
    lines: list[int]
    sim: np.ndarray
    nv: np.ndarray

    def paced(self, j: int) -> bool:
        """1行あたりの長さを比べる対象か。Intro / Outro は前奏・後奏を含むので外す。"""
        return self.lines[j] > 0 and self.kinds[j] not in ("intro", "outro")


def _pair(sim: np.ndarray, a: tuple[int, int], b: tuple[int, int]) -> float:
    """同種セクション2つ：頭を揃えて対角に比べた近さ − 長さのずれ。"""
    n = min(a[1] - a[0], b[1] - b[0])
    rep = float(np.mean(sim[np.arange(a[0], a[0] + n), np.arange(b[0], b[0] + n)]))
    la, lb = a[1] - a[0], b[1] - b[0]
    return W_REP * rep - W_LEN * abs(la - lb) / max(la, lb)


def _close(job: _Job, starts: tuple[int, ...], end: int) -> float:
    """最後のセクションを end で閉じたときに増えるスコア。"""
    j = len(starts) - 1
    seg = (starts[j], end)
    gain = job.nv[starts[j]] if j else 0.0
    rate = (end - starts[j]) / max(job.lines[j], 1)
    for i in range(j):
        prev = (starts[i], starts[i + 1])
        if job.kinds[i] == job.kinds[j]:
            gain += _pair(job.sim, prev, seg)
        if job.paced(i) and job.paced(j):
            gain -= W_RATE * abs(np.log(rate * job.lines[i] / (prev[1] - prev[0])))
    return gain


def _reach(cands: list[int], n_beats: int) -> dict[int, int]:
    """候補 c から始めて曲末までに置けるセクションの最大数。"""
    reach: dict[int, int] = {}
    for c in reversed(cands):
        if n_beats - c < MIN_BEATS:
            reach[c] = 0
            continue
        after = [reach[d] for d in cands if d - c >= MIN_BEATS and reach[d]]
        reach[c] = 1 + max(after, default=0)
    return reach


def _prune(states: list) -> list:
    """最後の境界の位置ごとに上位 PER_START 個。位置の偏りで詰むのを防ぐ。"""
    by_last: dict[int, list] = {}
    for s in sorted(states, key=lambda x: -x[0]):
        bucket = by_last.setdefault(s[1][-1], [])
        if len(bucket) < PER_START:
            bucket.append(s)
    return [s for b in by_last.values() for s in b]


def _search(job: _Job, cands: list[int], n_beats: int) -> list[tuple[float, tuple]]:
    """(スコア, 各セクションの開始拍) を良い順に。"""
    n, reach = len(job.kinds), _reach(cands, n_beats)
    beam: list[tuple[float, tuple]] = [(0.0, (0,))]
    for j in range(1, n):
        beam = _prune([(score + _close(job, st, c), st + (c,))
                       for score, st in beam for c in cands
                       if c - st[-1] >= MIN_BEATS and reach[c] >= n - j])
    done = [(s + _close(job, st, n_beats), st) for s, st in beam
            if n_beats - st[-1] >= MIN_BEATS]
    return sorted(done, key=lambda x: -x[0])


def _margins(ranked: list[tuple[float, tuple]]) -> list[float]:
    """境界ごとに、そこが2拍以上違う割り当ての最良との差。"""
    best, starts = ranked[0]
    out = []
    for j, s in enumerate(starts):
        alt = next((sc for sc, st in ranked[1:] if abs(st[j] - s) > 2), None)
        out.append(float("inf") if j == 0 or alt is None else best - alt)
    return out


def estimate(song: Song, beats: Beats) -> list[Boundary]:
    """各セクションの開始時刻。先頭は必ず 0 秒。"""
    sim = beats.similarity()
    nv = novelty(sim)
    job = _Job([kind(s.name) for s in song.sections],
               [len(s.lines) for s in song.sections], sim, nv)
    ranked = _search(job, candidates(nv, sim), len(beats.times))
    if not ranked:
        raise ValueError("セクションを置ききれない（曲が短すぎるか、セクションが多すぎる）")
    starts = ranked[0][1]
    return [Boundary(sec.name, 0.0 if j == 0 else round(float(beats.times[b]), 2), m)
            for j, (sec, b, m) in enumerate(zip(song.sections, starts, _margins(ranked)))]
