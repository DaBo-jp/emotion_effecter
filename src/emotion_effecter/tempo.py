"""気持ち（昂ぶり・気持ちの速さ）と BPM → セクションごとの流れる速さ・数・踊りの速さ。
**写像はここにだけ書く。**

- `speed` — 画面を渡りきるのに N 小節。昂ぶり 0 で `bars_calm`、1 で `bars_wild` の
  間を対数でとり、気持ちの速さで割って、**1オクターブを `snap` 段に刻んで丸める**
- `rate` — 画面に居る数（湧く数 × 渡りきる秒数）を、気持ちの速さで `density_gain`
  オクターブぶん増減する。速く流れても数が減らないよう、湧く数は速さにも比例させる
- `sway_hz` — 拍の周波数 × 気持ちの速さの倍率 ÷ `sway_beats`（既定で1小節に1往復）
- `rock_hz` — 拍の周波数 × 気持ちの速さの倍率 ÷ `rock_beats`（既定で2拍に1往復＝拍ごとに傾く）

気持ちの速さ（`pace` の確率）は倍率の log2 の期待値にする: linger −1（半分）/
walk 0 / rush +1（倍）。

**昂ぶりは曲の中で引き伸ばす（`stretch`）。** 曲によって昂ぶりの幅は狭い——
Irrational は全セクションが 0.34〜0.75 に収まり、0..1 を前提にした写像では
ほとんど差が出なかった。`stretch=1` で曲の最小〜最大を 0..1 に広げ、0 で生の値。

**丸める理由。** 隣のセクションと少しだけ違う値は、見分けがつかないのに境界の
入れ替え（2秒の重ね描き）だけを生む。刻みに乗せれば、同じ乗り方のセクションは
同じ値になる。`snap=1` で2のべき（倍・半分）、2 で √2 刻み。

歌詞の無いセクションは直前の歌詞セクションの値を保つ（無ければ直後）。間奏で
気持ちは採点されていない——速さを変える理由が無い。

描画も cymatics も知らない純粋な計算。値の範囲は `RANGES` が唯一の宣言で、
`problems()` が全部並べて返す。
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields, replace
from types import MappingProxyType
from typing import Any

from .dims import PACES

#: 気持ちの速さ → 倍率の log2。名前は `dims.PACES`
STEPS: Mapping[str, int] = MappingProxyType({"linger": -1, "walk": 0, "rush": 1})

#: ここが決める引数
KEYS: tuple[str, ...] = ("speed", "rate", "sway_hz", "rock_hz")

Mark = Mapping[str, float] | None


@dataclass(frozen=True)
class Tempo:
    #: 0 なら音源から推定した BPM を使う。推定が倍・半分にずれた曲は手で書く
    bpm: float = 0.0
    beats_per_bar: int = 4
    #: 昂ぶり 0 / 1 で画面を渡りきる小節数（丸める前）
    bars_calm: float = 8.0
    bars_wild: float = 2.0
    #: 揺れ・首振りの1往復の拍数（気持ちの速さの倍率で割る前）
    sway_beats: float = 4.0
    rock_beats: float = 2.0
    #: 昂ぶりを曲の最小〜最大へ引き伸ばす割合。0 で生の値、1 で 0..1 いっぱい
    stretch: float = 1.0
    #: 1オクターブを何段に刻むか。1 で2のべき
    snap: int = 2
    #: 気持ちの速さ1段で、画面に居る数を何オクターブ増減するか。0 で数を変えない
    density_gain: float = 1.0

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
    "stretch": (0.0, 1.0),
    "snap": (1, 12),
    "density_gain": (0.0, 3.0),
})

#: 整数で書く項目
INTS: tuple[str, ...] = ("beats_per_bar", "snap")


def from_mapping(d: Mapping[str, Any]) -> Tempo:
    """song.json の `tempo`。**知らない項目・数でない値・範囲外は全部並べて断る。**"""
    known = {f.name for f in fields(Tempo)}
    bad = ["知らない項目: %s" % k for k in sorted(set(d) - known)]
    vals = {}
    for k, v in d.items():
        if k not in known:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            bad.append("%s=%r は数で書く" % (k, v))
        elif k in INTS and v != int(v):
            bad.append("%s=%r は整数で書く" % (k, v))
        else:
            vals[k] = int(v) if k in INTS else float(v)
    t = replace(Tempo(), **vals)
    bad += t.problems()
    if bad:
        raise ValueError("tempo が通らない:\n  " + "\n  ".join(bad))
    return t


def pace_step(mark: Mapping[str, float]) -> float:
    """気持ちの速さの倍率の log2 の期待値。`pace:` の確率が無ければ 0（walk）。"""
    return sum(p * STEPS[k] for k in PACES if (p := mark.get("pace:" + k)) is not None)


def _q(x: float, t: Tempo) -> float:
    """log2 の値を刻みに乗せる。"""
    return round(x * t.snap) / t.snap


def stretched(marks: Sequence[Mark], t: Tempo) -> list[Mark]:
    """昂ぶりを曲の最小〜最大へ `stretch` だけ引き伸ばした marks。幅が無ければ真ん中へ。"""
    vals = [m["arousal"] for m in marks if m is not None]
    lo, hi = min(vals, default=0.0), max(vals, default=1.0)

    def one(a: float) -> float:
        full = (a - lo) / (hi - lo) if hi - lo > 1e-9 else 0.5
        return a + (full - a) * t.stretch

    return [None if m is None else {**m, "arousal": one(m["arousal"])} for m in marks]


def bars(mark: Mapping[str, float], t: Tempo) -> float:
    """画面を渡りきる小節数。刻みに乗る。"""
    a = min(1.0, max(0.0, mark["arousal"]))
    lo, hi = math.log2(t.bars_calm), math.log2(t.bars_wild)
    return 2.0 ** _q(lo + (hi - lo) * a - pace_step(mark), t)


def params(mark: Mapping[str, float], bpm: float, t: Tempo,
           base: Mapping[str, float]) -> dict[str, float]:
    """1セクションの引数。`base` は effect の元の値（`speed` / `rate` の基準と、
    どの引数を持つか）。持たない引数は出さない。"""
    beat_hz, step = bpm / 60.0, pace_step(mark)
    m = 2.0 ** _q(step, t)
    speed = beat_hz / (t.beats_per_bar * bars(mark, t))
    out = {"speed": math.copysign(speed, base.get("speed", 1.0)),
           "sway_hz": beat_hz * m / t.sway_beats,
           "rock_hz": beat_hz * m / t.rock_beats}
    if "rate" in base and "speed" in base:
        dens = 2.0 ** _q(t.density_gain * step, t)
        out["rate"] = base["rate"] * speed / abs(base["speed"]) * dens
    return {k: v for k, v in out.items() if k in base}


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


def overrides(marks: Sequence[Mark], bpm: float, t: Tempo,
              base: Mapping[str, float]) -> list[dict[str, float]]:
    """セクションごとに変える引数。`base` は effect の元の値（`params()`）。"""
    if bpm <= 0:
        raise ValueError("bpm=%r" % bpm)
    if base.get("speed", 1.0) == 0:
        raise ValueError("speed=0 の effect は速さを比べられない")
    return [params(m, bpm, t, base) for m in _held(stretched(marks, t))]


def summary(names: Sequence[str | None], extra: Sequence[Mapping[str, float]], bpm: float,
            t: Tempo) -> str:
    """「Verse 1 4小節 / Chorus 1 2小節」。名前が None のセクション（間奏）は出さない。"""
    return " / ".join("%s %g小節" % (n, round(bpm / 60.0 / t.beats_per_bar / abs(e["speed"]), 3))
                      for n, e in zip(names, extra) if n is not None and "speed" in e)
