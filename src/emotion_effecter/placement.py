"""キー画像の解析（`scenery`）→ effect の置き場所の引数。**座標の決め方はここにだけ書く。**

Jev が選んだ置き場所（`ANCHORS`）の目印の箱から、effect が持っている引数だけを出す：

| effect が持つ引数 | 出すもの |
|---|---|
| `cx` と `cy`（円の effect） | 円の中心。`radius` も持てば半径（px）も |
| `flow_x` と `flow_y`（流れる effect） | 流れの中心（集まる・散る先） |
| `cx` だけ（floor） / `cy` だけ（line・rune） | その向きの中心 |
| `holes` | **主人公の顔を透かす円。** 頭に添えるとき以外は必ず |

- `open`（人物の脇）は Jev に箱を聞かない（物でないものは箱にならない）。人物の
  箱の左右で広い方の帯。人物がいなければ画面ぜんたい
- 置き場所の目印が画像に無い（有無の確率が `PRESENT` 未満）なら、次に確からしい
  置き場所へ。どれも無ければ `whole`（画面の中央）
- `holes` は**セクションごとに必ず出す**（無ければ空）。前のセクションの穴が
  残らないように
- 頭を囲む円の半径は顔の大きさから、それ以外の円は目印の箱に収まる大きさ

出した値は song.json の `sections` に手で書いた値に負ける（`scenes` の `extra`）。
"""
from __future__ import annotations

from collections.abc import Collection, Mapping
from types import MappingProxyType
from typing import Any

from .scenery import ANCHORS, Scenery

#: 目印が「ある」とみなす確率
PRESENT = 0.5

#: 頭を囲む円の半径 ÷ 頭の箱の長辺
HALO = 0.75
#: 目印に収める円の半径 ÷ 目印の箱の短辺
FIT = 0.45
#: 半径の下限 ÷ 画面の高さ
MIN_RADIUS = 0.06
#: 顔を透かす円の直径 ÷ 頭の箱の高さ
HOLE = 1.3

Box = tuple[float, float, float, float]

#: 置き場所 → 目印。`whole` は画面ぜんたい、`open` は人物（の脇）
REGION: Mapping[str, str | None] = MappingProxyType(
    {a: {"whole": None, "open": "person"}.get(a, a) for a in ANCHORS})


def anchor(sc: Scenery) -> str:
    """置き場所。Jev の確率の高い順に、目印が画像にあるものを選ぶ。"""
    for a in sorted(sc.anchors, key=lambda a: -sc.anchors[a]):
        lm = REGION.get(a)
        if lm is None or a == "open" or sc.present.get(lm, 0.0) >= PRESENT:
            return a
    return "whole"


def _center(b: Box) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def region(sc: Scenery, a: str) -> Box:
    """置き場所の箱（0..1）。"""
    lm = REGION[a]
    if lm is None or (a == "open" and sc.present.get(lm, 0.0) < PRESENT):
        return (0.0, 0.0, 1.0, 1.0)
    b = sc.boxes[lm]
    if a != "open":
        return b
    return (0.0, 0.0, b[0], 1.0) if b[0] >= 1.0 - b[2] else (b[2], 0.0, 1.0, 1.0)


def _radius(a: str, b: Box, w: int, h: int) -> float:
    bw, bh = (b[2] - b[0]) * w, (b[3] - b[1]) * h
    r = HALO * max(bw, bh) if a == "face" else FIT * min(bw, bh)
    return round(max(r, MIN_RADIUS * h), 1)


def _hole(sc: Scenery, a: str) -> list:
    """顔を透かす円（`holes_unit` は fraction）。頭に添えるか、顔が無ければ空。"""
    if a == "face" or sc.present.get("face", 0.0) < PRESENT:
        return []
    b = sc.boxes["face"]
    x, y = _center(b)
    return [[[round(x, 3), round(y, 3)], round(HOLE * (b[3] - b[1]), 3)]]


def params(sc: Scenery, fields: Collection[str], w: int, h: int) -> dict[str, Any]:
    """effect の引数の名前 `fields` と画面の大きさ（px）→ 置き場所の引数。"""
    a = anchor(sc)
    b = region(sc, a)
    x, y = (round(v, 3) for v in _center(b))
    out: dict[str, Any] = {}
    if "cx" in fields:
        out["cx"] = x
    if "cy" in fields:
        out["cy"] = y
    if "radius" in fields:
        out["radius"] = 0.0 if a == "whole" else _radius(a, b, w, h)
    if "flow_x" in fields and "flow_y" in fields:
        out.update(flow_x=x, flow_y=y)
    if "holes" in fields:
        out.update(holes=_hole(sc, a), holes_unit="fraction")
    return out


def summary(sc: Scenery, a: str) -> str:
    """1行の説明。置き場所と、その確率と、目印の箱の確からしさ。"""
    lm = REGION[a]
    tail = "" if lm is None else " 箱 %.0f%%" % (100 * sc.box_confidence[lm])
    return "%s %.0f%%%s" % (a, 100 * sc.anchors.get(a, 0.0), tail)
