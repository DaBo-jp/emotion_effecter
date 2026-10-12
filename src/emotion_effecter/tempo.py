"""気持ち（昂ぶり・気持ちの速さ）と BPM → セクションごとの流れる速さと踊りの速さ。
**写像はここにだけ書く。**

| 引数 | 決め方 |
|---|---|
| `speed` | 画面を渡りきるのに N 小節。昂ぶり（arousal）0 で `bars_calm`、1 で `bars_wild` の間を対数でとり、気持ちの速さで割って、**2のべきに丸める** |
| `sway_hz` | 拍の周波数 × 気持ちの速さの倍率 ÷ `sway_beats`（既定で1小節に1往復） |
| `rock_hz` | 拍の周波数 × 気持ちの速さの倍率 ÷ `rock_beats`（既定で2拍に1往復＝拍ごとに傾く） |

気持ちの速さ（`pace` の確率）は倍率の log2 の期待値にする: linger −1（半分）/
walk 0 / rush +1（倍）。

**丸める理由。** 隣のセクションと少しだけ違う値は、見分けがつかないのに境界の
入れ替え（2秒の重ね描き）だけを生む。2のべきの小節なら、同じ乗り方のセクションは
同じ値になり、違うときははっきり倍・半分になる。

歌詞の無いセクションは直前の歌詞セクションの値を保つ（無ければ直後）。間奏で
気持ちは採点されていない——速さを変える理由が無い。

描画も cymatics も知らない純粋な計算。値の範囲は `RANGES` が唯一の宣言で、
`problems()` が全部並べて返す。
"""
from __future__ import annotations

import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import asdict, dataclass, fields, replace
from types import MappingProxyType
from typing import Any

from .dims import PACES

#: 気持ちの速さ → 倍率の log2。名前は `dims.PACES`
STEPS: Mapping[str, int] = MappingProxyType({"linger": -1, "walk": 0, "rush": 1})

#: ここが決める引数
KEYS: tuple[str, ...] = ("speed", "sway_hz", "rock_hz")

Mark = Mapping[str, float] | None


@dataclass(frozen=True)
class Tempo:
    #: 0 なら音源から推定した BPM を使う。推定が倍・半分にずれた曲は手で書く
    bpm: float = 0.0
    beats_per_bar: int = 4
    #: arousal 0 / 1 で画面を渡りきる小節数（丸める前）
    bars_calm: float = 8.0
    bars_wild: float = 2.0
    #: 揺れ・首振りの1往復の拍数（気持ちの速さの倍率で割る前）
    sway_beats: float = 4.0
    rock_beats: float = 2.0

    def problems(self) -> list[str]:
        """範囲を外れた項目を全部。空なら通る。"""
        return ["%s=%r は %s..%s の外" % (k, getattr(self, k), lo, hi)
                for k, (lo, hi) in RANGES.items() if not lo <= getattr(self, k) <= hi]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


#: 項目の範囲（両端を含む）。**範囲の宣言はここだけ**
RANGES: Mapping[str, tuple[float, float]] = MappingProxyType({
    "bpm": (0.0, 400.0),
    "beats_per_bar": (1, 16),
    "bars_calm": (0.25, 64.0),
    "bars_wild": (0.25, 64.0),
    "sway_beats": (0.25, 64.0),
    "rock_beats": (0.25, 64.0),
})


def from_mapping(d: Mapping[str, Any]) -> Tempo:
    """song.json の `tempo`。**知らない項目・数でない値・範囲外は全部並べて断る。**"""
    known = {f.name for f in fields(Tempo)}
    bad = ["知らない項目: %s" % k for k in sorted(set(d) - set(known))]
    vals = {}
    for k, v in d.items():
        if k not in known:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            bad.append("%s=%r は数で書く" % (k, v))
        elif k == "beats_per_bar" and v != int(v):
            bad.append("%s=%r は整数で書く" % (k, v))
        else:
            vals[k] = int(v) if k == "beats_per_bar" else float(v)
    t = replace(Tempo(), **vals)
    bad += t.problems()
    if bad:
        raise ValueError("tempo が通らない:\n  " + "\n  ".join(bad))
    return t


def pace_step(mark: Mapping[str, float]) -> float:
    """気持ちの速さの倍率の log2 の期待値。`pace:` の確率が無ければ 0（walk）。"""
    return sum(p * STEPS[k] for k in PACES if (p := mark.get("pace:" + k)) is not None)


def bars(mark: Mapping[str, float], t: Tempo) -> float:
    """画面を渡りきる小節数。2のべき。"""
    a = min(1.0, max(0.0, mark["arousal"]))
    lo, hi = math.log2(t.bars_calm), math.log2(t.bars_wild)
    return 2.0 ** round(lo + (hi - lo) * a - pace_step(mark))


def params(mark: Mapping[str, float], bpm: float, t: Tempo) -> dict[str, float]:
    """1セクションの `speed` / `sway_hz` / `rock_hz`。"""
    beat_hz = bpm / 60.0
    m = 2.0 ** round(pace_step(mark))
    return {"speed": beat_hz / (t.beats_per_bar * bars(mark, t)),
            "sway_hz": beat_hz * m / t.sway_beats,
            "rock_hz": beat_hz * m / t.rock_beats}


def _held(marks: Sequence[Mark]) -> list[Mapping[str, float]]:
    """歌詞の無いセクション（None）を直前の値で埋める。先頭側は直後の値。"""
    first = next((m for m in marks if m is not None), None)
    if first is None:
        raise ValueError("歌詞のあるセクションが無い")
    out, last = [], first
    for m in marks:
        last = m if m is not None else last
        out.append(last)
    return out


def overrides(marks: Sequence[Mark], bpm: float, t: Tempo, has: Collection[str],
              direction: float = 1.0) -> list[dict[str, float]]:
    """セクションごとに変える引数。`has` は effect が持つ引数の名前（持たないものは出さない）。

    `direction` は speed の符号（rune は負で右から左へ流れる）。
    """
    if bpm <= 0:
        raise ValueError("bpm=%r" % bpm)
    sign = -1.0 if direction < 0 else 1.0
    out = []
    for mark in _held(marks):
        p = params(mark, bpm, t)
        p["speed"] *= sign
        out.append({k: v for k, v in p.items() if k in has})
    return out


def summary(names: Sequence[str | None], extra: Sequence[Mapping[str, float]], bpm: float,
            t: Tempo) -> str:
    """「Verse 1 4小節 / Chorus 1 2小節」。名前が None のセクション（間奏）は出さない。"""
    return " / ".join("%s %g小節" % (n, round(bpm / 60.0 / t.beats_per_bar / abs(e["speed"]), 3))
                      for n, e in zip(names, extra) if n is not None and "speed" in e)
