"""主役の effect の上や下に重ねる層（song.json の `overlays`）。

    "overlays": [
      {"effect": "crowd", "place": "over",
       "params": {"people": 22, "db_floor": 10, "db_ceil": 40},
       "moods": {"bounce": {"by": "arousal", "lo": 0.02, "hi": 0.09},
                 "arms":   {"by": "arousal", "lo": 0.15, "hi": 0.7}}}
    ]

- `place` は `under`（主役の下）か `over`（上）。既定は `over`。並びは書いた順
- `params` はその層の項目だけ。**音源・絵・尺・出口・明滅は主役（`base`）が持つ**
  ので書けない（cymatics の重ね合わせと同じ決まり）
- `moods` は**感情で動かす項目**。その軸の値 0..1 で `lo` → `hi` へ動く。動かせるのは
  小数の項目だけ——人数や列の数が毎フレーム変わると並びが崩れる
- `moods` は emotion 版にだけ効く。感情なしの版（base.mp4）は `params` のまま
  ∴ 上下に並べたときの違いは感情だけになる

`sections` と `tempo` は主役にだけ効く。知らない effect・項目・軸、範囲外の値は
**全部並べて断る**。
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import dims

PLACES = ("under", "over")
KEYS = ("effect", "place", "params", "moods")
SWING_KEYS = ("by", "lo", "hi")


@dataclass(frozen=True)
class Swing:
    """感情で動かす1項目。軸 `by` の値 0..1 で `lo` → `hi`。"""

    key: str
    by: str
    lo: float
    hi: float

    def value(self, mood: Mapping[str, float]) -> float:
        return self.lo + (self.hi - self.lo) * mood[self.by]


@dataclass(frozen=True)
class Overlay:
    """重ねる層1枚。"""

    effect: str
    #: その層の項目だけ（入れ子の値は JSON の文字列にしてある）
    params: Mapping[str, Any]
    place: str = "over"
    swings: tuple[Swing, ...] = ()

    def at(self, mood: Mapping[str, float]) -> dict[str, float]:
        """そのフレームの感情で動かした項目。"""
        return {sw.key: sw.value(mood) for sw in self.swings}

    def to_dict(self) -> dict[str, Any]:
        return {"effect": self.effect, "place": self.place, "params": dict(self.params),
                "moods": {sw.key: {"by": sw.by, "lo": sw.lo, "hi": sw.hi}
                          for sw in self.swings}}


def notes_dropped(doc: Mapping[str, Any]) -> dict[str, Any]:
    """`_` で始まる鍵（注記）を落とす。"""
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def flat(params: Mapping[str, Any]) -> dict[str, Any]:
    """入れ子の値（`mask_curve` のカーブなど）は JSON の文字列にして渡す。

    cymatics はカーブを JSON の文字列で受ける。song.json ではフロントが書き出した
    オブジェクトをそのまま置けるように、ここで文字列へ寄せる。
    """
    return {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
            for k, v in params.items()}


def _fields(effect: str):
    from cymatics import effects

    return {f.name: f for f in effects.get(effect).fields}


def _layer_only(fields) -> set[str]:
    """層ごとに書ける項目の名前。共通の項目（音源・絵・尺…）は入らない。"""
    from cymatics.model import scope

    return {n for n, f in fields.items() if scope.scope_of(f.group) != "shared"}


def _param_problems(effect: str, params: Mapping[str, Any]) -> list[str]:
    from cymatics.model import validate

    fields = _fields(effect)
    bad = ["知らない項目: %s" % k for k in sorted(set(params) - set(fields))]
    bad += ["%s は主役（base）が持つ項目なので書けない" % k
            for k in sorted(set(params) & set(fields) - _layer_only(fields))]
    known = {k: v for k, v in params.items() if k in fields}
    try:
        coerced = {k: fields[k].coerce(v) for k, v in known.items()}
    except (TypeError, ValueError) as e:
        return [*bad, str(e)]
    return bad + validate(list(fields.values()), coerced)


def _swing_problems(effect: str, key: str, doc: Any) -> list[str]:
    from cymatics.model import validate

    fields = _fields(effect)
    if key not in fields or key not in _layer_only(fields):
        return ["%s: 動かせる項目ではない" % key]
    if fields[key].type is not float:
        return ["%s: 小数の項目だけ動かせる（%s）" % (key, fields[key].type.__name__)]
    if not isinstance(doc, Mapping) or set(notes_dropped(doc)) != set(SWING_KEYS):
        return ["%s: {\"by\": 軸, \"lo\": 数, \"hi\": 数} で書く" % key]
    bad = [] if doc["by"] in dims.AXES else [
        "%s: 知らない軸 %s（%s）" % (key, doc["by"], ", ".join(dims.AXES))]
    for end in ("lo", "hi"):
        v = doc[end]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            bad.append("%s.%s: 数ではない" % (key, end))
        else:
            bad += ["%s.%s: %s" % (key, end, p)
                    for p in validate([fields[key]], {key: float(v)})]
    return bad


def _item_problems(item: Any) -> list[str]:
    from cymatics import effects

    if not isinstance(item, Mapping):
        return ["{\"effect\": ..., \"params\": {...}} で書く"]
    item = notes_dropped(item)
    bad = ["知らない項目: %s" % k for k in sorted(set(item) - set(KEYS))]
    if item.get("place", "over") not in PLACES:
        bad.append("place は %s のどれか（%s）" % (" / ".join(PLACES), item["place"]))
    if item.get("effect") not in effects.names():
        return [*bad, "知らない effect: %s" % item.get("effect")]
    bad += _param_problems(item["effect"], flat(notes_dropped(item.get("params", {}))))
    for key, doc in notes_dropped(item.get("moods", {})).items():
        bad += ["moods." + p for p in _swing_problems(item["effect"], key, doc)]
    return bad


def problems(items: Any) -> list[str]:
    """`overlays` の駄目な理由を全部。空なら通る。"""
    if not isinstance(items, Sequence) or isinstance(items, str):
        return ["overlays は層のリスト"]
    return ["overlays[%d]: %s" % (i, p)
            for i, item in enumerate(items) for p in _item_problems(item)]


def _one(item: Mapping[str, Any]) -> Overlay:
    item = notes_dropped(item)
    swings = tuple(Swing(k, d["by"], float(d["lo"]), float(d["hi"]))
                   for k, d in notes_dropped(item.get("moods", {})).items())
    return Overlay(item["effect"], flat(notes_dropped(item.get("params", {}))),
                   item.get("place", "over"), swings)


def from_list(items: Sequence[Mapping[str, Any]]) -> tuple[Overlay, ...]:
    """`overlays` → 層のタプル。駄目なら理由を全部並べて落とす。"""
    bad = problems(items)
    if bad:
        raise ValueError("overlays が通らない:\n  " + "\n  ".join(bad))
    return tuple(_one(item) for item in items)
