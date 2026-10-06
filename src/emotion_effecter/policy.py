"""感情 → 見た目。**写像はここにだけ書く。**

入力はそのフレームの感情（`Timeline.frame()`）、出力は `Look`（色・glow の倍率・
バンドレベルの倍率）。描画を知らない純粋な計算なので、重みを変えても Jev を
呼び直す必要も、書き出す必要もなく試せる。

| 見た目 | 既定で動かす次元 | 動き |
|---|---|---|
| 色（`color_by`） | acceptance（受容） | `--color` → `warm`。`warm_from` 以下は動かさない |
| 色相の揺れ（`wobble_by`） | conflict（葛藤） | 最大 ±`wobble_deg` 度 |
| glow（`glow_by`） | valence（快） | `glow_lo` 〜 `glow_hi` 倍 |
| バンドレベル（`gain_by`） | arousal（昂ぶり） | `gain_lo` 〜 `gain_hi` 倍。控えめ |

**どの次元で動かすかは曲ごとに選べる。** 曲によって物語の軸が違う——Script /
イセカイ / Shape は受容、Architecture は主導権。`color_invert` で向きを返せる
（主導権を手放すほど `warm` へ、など）。次元の名前は `dims.DIMS` から選ぶ。

**動かさないときは値に触らない。** 色を HSV に開いて閉じると丸めで1ずれうるので、
寄せる量や回す角度が 0 のときは元の色をそのまま返す。∴ 中立な Policy で包んだ
effect は、素の cymatics と画素まで一致する（`tests/test_conformance.py`）。

値の範囲は `RANGES` が唯一の宣言で、`problems()` が全部並べて返す。
"""
from __future__ import annotations

import colorsys
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields, replace
from types import MappingProxyType
from typing import Any

from cymatics.model import palette
from cymatics.model.color import parse as parse_color

from .dims import DIMS

RGB = tuple[int, ...]


@dataclass(frozen=True)
class Policy:
    #: 各見た目を動かす次元（`dims.DIMS` のどれか）
    color_by: str = "acceptance"
    wobble_by: str = "conflict"
    glow_by: str = "valence"
    gain_by: str = "arousal"
    #: 真なら color_by の値を 1 − 値 にしてから使う
    color_invert: bool = False
    #: color_by=1 で行き着く色
    warm: RGB = (255, 176, 150)
    #: これ以下の color_by は（受容なら「まだ拒んでいる」として）色を動かさない
    warm_from: float = 0.3
    #: 色相の回る向き。+1=青→紫→赤 / -1=逆回り / 0=近い方。
    #: シアンから暖色へ近い方を回ると黄緑を通る——開いていく気持ちの色に見えない
    turn: int = 1
    #: conflict=1 での色相の揺れ（度）と速さ（Hz）
    wobble_deg: float = 28.0
    wobble_hz: float = 0.4
    #: valence 0 / 1 での glow の倍率
    glow_lo: float = 0.5
    glow_hi: float = 1.8
    #: arousal 0 / 1 でのバンドレベルの倍率
    gain_lo: float = 0.9
    gain_hi: float = 1.1

    def problems(self) -> list[str]:
        """範囲を外れた項目を全部。空なら通る。"""
        out = ["%s=%r は %s..%s の外" % (k, getattr(self, k), lo, hi)
               for k, (lo, hi) in RANGES.items() if not lo <= getattr(self, k) <= hi]
        if self.turn not in (-1, 0, 1):
            out.append("turn=%r は -1 / 0 / 1 のどれか" % self.turn)
        out += ["%s=%r は次元の名前ではない（%s）" % (k, getattr(self, k), " / ".join(DIMS))
                for k in BY if getattr(self, k) not in DIMS]
        return out

    def to_dict(self) -> dict[str, Any]:
        """JSON と同じ形（色は配列）。`from_mapping()` に戻せば同じ Policy になる。"""
        return {**asdict(self), "warm": list(self.warm)}

    def check(self) -> Policy:
        """範囲外があれば全部並べて落とす。通れば自分を返す。"""
        bad = self.problems()
        if bad:
            raise ValueError("Policy が通らない:\n  " + "\n  ".join(bad))
        return self


#: 次元を選ぶ項目
BY: tuple[str, ...] = ("color_by", "wobble_by", "glow_by", "gain_by")

#: 数値の項目の範囲（両端を含む）。**範囲の宣言はここだけ**
RANGES: Mapping[str, tuple[float, float]] = MappingProxyType({
    "warm_from": (0.0, 0.99),
    "wobble_deg": (0.0, 180.0),
    "wobble_hz": (0.0, 10.0),
    "glow_lo": (0.0, 10.0),
    "glow_hi": (0.0, 10.0),
    "gain_lo": (0.0, 4.0),
    "gain_hi": (0.0, 4.0),
})


def from_mapping(d: Mapping[str, Any], base: Policy = Policy()) -> Policy:
    """dict（`--policy` の JSON）で上書きする。**知らない項目と範囲外は全部並べて断る。**

    `warm` は cymatics の `--color` と同じ書式（`#fc8` / `crimson` / `255,176,150`）。
    """
    known = {f.name for f in fields(Policy)}
    bad = ["知らない項目: %s" % k for k in sorted(set(d) - known)]
    vals = dict(d)
    if isinstance(vals.get("warm"), str):
        vals["warm"] = parse_color(vals["warm"])[0]
    elif isinstance(vals.get("warm"), list):            # JSON の配列
        vals["warm"] = tuple(vals["warm"])
    pol = replace(base, **{k: v for k, v in vals.items() if k in known})
    bad += pol.problems()
    if bad:
        raise ValueError("Policy が通らない:\n  " + "\n  ".join(bad))
    return pol


@dataclass(frozen=True)
class Look:
    """1フレームの見た目の差分。"""

    color: RGB
    glow: float      # glow に掛ける倍率
    gain: float      # バンドレベルに掛ける倍率


def _hsv(rgb: RGB) -> tuple[float, float, float]:
    return colorsys.rgb_to_hsv(*(c / 255.0 for c in rgb[:3]))


def _rgb(h: float, s: float, v: float) -> RGB:
    return tuple(int(round(c * 255)) for c in colorsys.hsv_to_rgb(h % 1.0, s, v))


def _hue_step(h0: float, h1: float, turn: int) -> float:
    if turn > 0:
        return (h1 - h0) % 1.0
    if turn < 0:
        return -((h0 - h1) % 1.0)
    return ((h1 - h0 + 0.5) % 1.0) - 0.5


def mix(a: RGB, b: RGB, k: float, turn: int = 0) -> RGB:
    """HSV で a → b へ k だけ寄せる。色相は `turn` の向きに回す。k=0 なら a そのもの。

    **a が灰色に近ければ色相は回さない**（最初から b の色相で、彩度と明度だけ寄せる）。
    灰色の色相には意味が無い——frost（彩度 0.07）から金へ青→紫→赤の向きで回すと、
    途中がピンクになった。白 → 淡い金 → 金、が素直。判定は cymatics の `is_grey`。
    """
    if k <= 0.0:
        return tuple(a)
    (h0, s0, v0), (h1, s1, v1) = _hsv(a), _hsv(b)
    h0 = h1 if palette.is_grey(a) else h0
    return _rgb(h0 + _hue_step(h0, h1, turn) * k, s0 + (s1 - s0) * k, v0 + (v1 - v0) * k)


def rotate(rgb: RGB, deg: float) -> RGB:
    """色相を deg 度回す。0 なら rgb そのもの。"""
    if deg == 0.0:
        return tuple(rgb)
    h, s, v = _hsv(rgb)
    return _rgb(h + deg / 360.0, s, v)


def _lerp(lo: float, hi: float, k: float) -> float:
    return lo + (hi - lo) * k


def look(mood: Mapping[str, float], t: float, base: RGB, pol: Policy = Policy()) -> Look:
    """そのフレームの感情 `mood` と時刻 `t`（秒）から見た目を決める。"""
    v = mood[pol.color_by]
    v = 1.0 - v if pol.color_invert else v
    k = min(1.0, max(0.0, (v - pol.warm_from) / (1.0 - pol.warm_from)))
    col = mix(base, pol.warm, k, pol.turn)
    # 揺れは周期の割り切れない2つの正弦の和。規則的に見えにくい
    ph = 2 * math.pi * pol.wobble_hz * t
    swing = 0.7 * math.sin(ph) + 0.3 * math.sin(2.7 * ph + 1.3)
    col = rotate(col, pol.wobble_deg * mood[pol.wobble_by] * swing)
    return Look(color=col,
                glow=_lerp(pol.glow_lo, pol.glow_hi, mood[pol.glow_by]),
                gain=_lerp(pol.gain_lo, pol.gain_hi, mood[pol.gain_by]))
