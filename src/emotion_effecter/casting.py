"""属性（水・地・風・金・火・明・暗）と BPM → effect の候補。**選び方はここにだけ書く。**

候補は「effect 名」ではなく **使い方**（effect + 性格を決める引数）。arc は棒を
並べれば後光、粒にすれば火花で、向く曲がまるで違う。

    点 = (1 - TEMPO_SHARE) × 属性の合い方 + TEMPO_SHARE × テンポの合い方

**属性の合い方**は、曲の属性を平均からの偏りにしてから、使い方の重みで加重平均する。
偏りで見るのは、何もかも強い曲（どの属性も 0.6）で全候補が同点にならないため。
**テンポの合い方**は、BPM が使い方の中心から何オクターブ離れているかの釣鐘。

**正解は無い。** 返すのは並べた候補と、どの属性がどれだけ効いたかの内訳まで。
決めるのは人。dB レンジは曲ごとに測るもの（cymatics の `analyze`）なので、ここでは
出さない。
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from . import dims

#: 点のうちテンポが占める割合
TEMPO_SHARE = 0.3
#: テンポの釣鐘の幅（オクターブ）。中心から1オクターブずれると 0.25 倍
TEMPO_WIDTH = 0.6


@dataclass(frozen=True)
class Cast:
    """effect の使い方1つ。"""

    effect: str
    #: その使い方を決める引数（cymatics の Field）
    params: Mapping[str, Any]
    #: 属性 → 重み（0 より大きい）。書かない属性は 0
    weights: Mapping[str, float]
    #: いちばん合う BPM
    tempo: float
    #: なぜその属性に合うか
    note: str


def _cast(effect: str, params: dict, weights: dict, tempo: float, note: str) -> Cast:
    return Cast(effect, MappingProxyType(params), MappingProxyType(weights), tempo, note)


#: 名前 → 使い方。括弧内は公開した曲（cymatics の preset）
CASTS: Mapping[str, Cast] = MappingProxyType({
    "scope": _cast("line", {"mode": "scope"}, {"metal": 1.0, "dark": 0.4}, 120,
                   "走査線。非人間・電子の語り手（Architecture）"),
    "harmonic": _cast("line", {"mode": "harmonic"}, {"water": 0.8, "wind": 0.6}, 85,
                      "滑らかなうねり。水面・風"),
    "halo": _cast("arc", {"gap": 0}, {"light": 1.0, "fire": 0.3}, 100,
                  "閉じた円の後光（Dragon）"),
    "sparks": _cast("arc", {"particles": 5}, {"fire": 1.0, "light": 0.4, "dark": 0.3}, 80,
                    "粒。静かになると消える＝儚い火（線香花火）"),
    "open_arc": _cast("arc", {"gap": 120}, {"wind": 0.7, "earth": 0.5, "light": 0.3}, 100,
                      "欠けた弧。素朴で開けた風景（Aisle）"),
    "smoke": _cast("smoke", {}, {"wind": 1.0, "dark": 0.4, "water": 0.3}, 75,
                   "立ち昇る煙・霧（Felt / Shape）"),
    "rune": _cast("rune", {}, {"dark": 0.8, "earth": 0.5, "metal": 0.3}, 70,
                  "流れる文字。異界・古いもの（イセカイ）"),
    "stave": _cast("stave", {}, {"metal": 0.8, "light": 0.4}, 110,
                   "棒グラフ。画面の中のパネル・計器（Script）"),
    "corona": _cast("corona", {}, {"light": 0.8, "fire": 0.6}, 100,
                    "冠。日食のコロナ・燃える輪"),
    "wreath": _cast("wreath", {}, {"water": 1.0, "wind": 0.3}, 80,
                    "隙間のない波の輪。水紋"),
    "iris": _cast("iris", {}, {"dark": 0.8, "water": 0.4}, 90,
                  "内へ閉じる絞り。瞳・内に溜まるもの"),
    "edge": _cast("edge", {}, {"metal": 0.6, "fire": 0.6}, 140,
                  "枠から内へ伸びる刃"),
    "floor": _cast("floor", {}, {"earth": 1.0, "metal": 0.4}, 130,
                   "奥へ流れる地形。手前が今、奥が過去"),
})

#: 候補にしない effect と理由。**黙って外さない**（テストが全 effect を数える）
EXCLUDED: Mapping[str, str] = MappingProxyType({
    "ring": "公開済み動画の再現のために残してある旧版。新しい曲は arc の halo で足りる",
})


@dataclass(frozen=True)
class Suggestion:
    name: str
    cast: Cast
    score: float
    #: 属性の合い方 -1..1（偏りの加重平均）
    fit: float
    #: テンポの合い方 0..1
    tempo_fit: float
    #: 属性 → この候補の属性の合い方への寄与
    parts: Mapping[str, float]


def problems(casts: Mapping[str, Cast] = CASTS) -> list[str]:
    """宣言の駄目な理由を全部。空なら通る。"""
    bad = []
    for name, c in casts.items():
        bad += ["%s: 知らない属性 %s" % (name, e) for e in sorted(set(c.weights)
                                                              - set(dims.ELEMENTS))]
        bad += ["%s: 重み %s は 0 より大きく" % (name, e) for e, w in c.weights.items()
                if w <= 0]
        bad += ["%s: tempo は 0 より大きく" % name] if c.tempo <= 0 else []
    return bad


def tempo_fit(bpm: float, center: float) -> float:
    return math.exp(-0.5 * (math.log2(bpm / center) / TEMPO_WIDTH) ** 2)


def _parts(scores: Mapping[str, float], weights: Mapping[str, float]) -> dict[str, float]:
    mean = sum(scores[e] for e in dims.ELEMENTS) / len(dims.ELEMENTS)
    total = sum(weights.values())
    return {e: w * (scores[e] - mean) / total for e, w in weights.items()}


def rank(scores: Mapping[str, float], bpm: float,
         casts: Mapping[str, Cast] = CASTS) -> list[Suggestion]:
    """点の高い順。`scores` は属性 → 0..1 で、全属性が要る。"""
    missing = [e for e in dims.ELEMENTS if e not in scores]
    if missing or bpm <= 0:
        raise ValueError("属性が足りない: %s / bpm=%s" % (", ".join(missing) or "-", bpm))
    out = []
    for name, c in casts.items():
        parts = _parts(scores, c.weights)
        fit, tf = sum(parts.values()), tempo_fit(bpm, c.tempo)
        total = (1 - TEMPO_SHARE) * (fit + 1) / 2 + TEMPO_SHARE * tf
        out.append(Suggestion(name, c, total, fit, tf, MappingProxyType(parts)))
    return sorted(out, key=lambda s: -s.score)


def _bar(v: float, width: int = 20) -> str:
    return "█" * round(max(0.0, min(1.0, v)) * width)


def _why(s: Suggestion) -> str:
    top = sorted(s.parts.items(), key=lambda kv: -kv[1])
    return " ".join("%s%+.2f" % (e, v) for e, v in top)


def report(title: str, scores: Mapping[str, float], confidence: Mapping[str, float],
           bpm: float, ranked: list[Suggestion], current: str | None = None) -> str:
    """提案の Markdown。上が属性と BPM、下が候補の表（点・内訳・引数）。"""
    lines = ["# %s — effect の提案" % title, "", "BPM %.1f" % bpm, "", "```"]
    lines += ["%-6s %.2f (%2d%%) %s" % (e, scores[e], round(100 * confidence[e]),
                                        _bar(scores[e])) for e in dims.ELEMENTS]
    lines += ["```", "", "| # | 候補 | effect | 点 | 属性 | テンポ | 内訳 | 引数 | 意図 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for i, s in enumerate(ranked, 1):
        mark = " ◀ 今" if current == s.cast.effect else ""
        args = " ".join("--%s %s" % (k.replace("_", "-"), v) for k, v in s.cast.params.items())
        lines.append("| %d | %s%s | %s | %.2f | %+.2f | %.2f | %s | %s | %s |" % (
            i, s.name, mark, s.cast.effect, s.score, s.fit, s.tempo_fit, _why(s),
            args or "-", s.cast.note))
    return "\n".join(lines + ["", "点 = %.1f × 属性 + %.1f × テンポ。内訳は属性ごとの寄与"
                              "（曲の平均からの偏り × 重み）" % (1 - TEMPO_SHARE, TEMPO_SHARE)])
