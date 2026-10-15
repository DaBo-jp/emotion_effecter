"""セクションごとに層の引数を変える。**変えられるのは流れの向き（`--flow` など）と
流れ・踊りの速さと湧く数（`--speed` / `--rate` / `--sway-hz` / `--rock-hz`）と
落下（motif の `--gravity`）と、図形と向き（motif の `--shape` / `--align`。
星で集まり、火花で弾ける）。**

落下は経過時間の2乗で効く ∴ 集まる（in）・ゆっくり渡る区間では 0 にしないと
真下へ落ちるだけになる——火花を外へ散らす区間でだけ立てる。

song.json に書く:

    "sections": {
      "Chorus 1":    {"flow": "in", "flow_x": 0.4, "flow_y": 0.35},
      "Last-Chorus": {"flow": "out", "flow_twist": 180}
    }

- 書いていないセクションは `base` の引数のまま
- 同じ名前のセクションが複数あれば全部に当たる（`Instrumental Break` が2回など）
- **境界は `xfade` 秒かけて入れ替える。** 古い流れは濃さを落としながら流れ続け、
  新しい流れが濃くなっていく。引数をその場で差し替えると、流れている途中の粒が
  一斉に瞬間移動する——位置は「今の向き」で経過時間から解析的に出しているから
- 知らないセクション名・変えられない項目・範囲外の値は**全部並べて断る**
- `build()` の `extra` で、セクションごとの引数を外から足せる（`tempo` が拍から
  出した速さ）。**song.json に手で書いた値が勝つ**
- **倍率で書ける項目がある**（`SCALES`）。`"density": 2` は湧く数（`rate`）を2倍に
  する——手で `rate` を書くと `tempo` が拍から出した数を潰すが、倍率ならその上に
  掛かる（無ければ `base` の値に掛かる）。火花の区間だけ密にする、など

変えられる項目を `KEYS` の外へ広げるときは、包絡や帯域を作り直さずに描けるか
（`stage()` と `derive()` の作り直しだけで済むか）を確かめてから足す。

**フレーム番号だけで決まる** ∴ 分割書き出しでも同じ絵になる。
"""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from cymatics import effects

from .lyrics import Song

#: セクションごとに変えられる項目
KEYS: tuple[str, ...] = ("flow", "flow_x", "flow_y", "flow_twist",
                         "speed", "rate", "sway_hz", "rock_hz", "gravity",
                         "shape", "align")

#: 倍率で書ける項目 → 掛ける先の項目
SCALES: Mapping[str, str] = MappingProxyType({"density": "rate"})

Override = tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class Scenes:
    """セクションの開始フレームと、そこで変える引数。pickle できる形で持つ。"""

    starts: tuple[int, ...]
    overrides: tuple[Override, ...]
    #: 入れ替えにかけるフレーム数。境界をまたいで半分ずつ
    xfade: int

    def at(self, f: int) -> tuple[tuple[dict[str, Any], float], ...]:
        """そのフレームで描くもの: (変える引数, 濃さの倍率) の列。**描く順。**

        境界の前後 `xfade/2` では古いものと新しいものの2つ、それ以外は1つ。
        """
        i = max(0, bisect_right(self.starts, f) - 1)
        half, ov = self.xfade / 2.0, self.overrides
        if i + 1 < len(ov) and ov[i + 1] != ov[i] and f >= self.starts[i + 1] - half:
            return self._blend(ov[i], ov[i + 1], f, self.starts[i + 1])
        if i > 0 and ov[i - 1] != ov[i] and f < self.starts[i] + half:
            return self._blend(ov[i - 1], ov[i], f, self.starts[i])
        return ((dict(ov[i]), 1.0),)

    def _blend(self, old: Override, new: Override, f: int, edge: int):
        k = (f - (edge - self.xfade / 2.0)) / self.xfade
        return ((dict(old), 1.0 - k), (dict(new), k))

    @property
    def is_plain(self) -> bool:
        """どのセクションでも何も変えないか。"""
        return not any(self.overrides)

    def to_dict(self) -> dict[str, Any]:
        """記録用。"""
        return {"xfade_frames": self.xfade,
                "sections": [{"f0": f, "set": dict(o)}
                             for f, o in zip(self.starts, self.overrides)]}


def _notes_dropped(d: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def _value_problems(name: str, over: Mapping[str, Any], fields) -> list[str]:
    """1セクションぶんの引数の駄目な理由。"""
    bad = []
    for k, v in _notes_dropped(over).items():
        if k in SCALES:
            bad += _scale_problems(name, k, v, fields)
        elif k not in KEYS:
            bad.append("%s: %s は変えられない（%s）"
                       % (name, k, " / ".join((*KEYS, *SCALES))))
        elif k not in fields:
            bad.append("%s: この effect は %s を持たない" % (name, k))
        else:
            try:
                bad += ["%s: %s" % (name, p) for p in fields[k].problems(fields[k].coerce(v))]
            except (TypeError, ValueError) as e:
                bad.append("%s: %s=%r（%s）" % (name, k, v, e))
    return bad


def problems(doc: Mapping[str, Any], effect: str) -> list[str]:
    """`sections` の駄目な理由を全部。セクション名の照合は歌詞が要るので `build()` で。"""
    if not isinstance(doc, Mapping):
        return ["sections は {セクション名: {項目: 値}}"]
    fields = {f.name: f for f in effects.get(effect).fields}
    bad = []
    for name, over in _notes_dropped(doc).items():
        if not isinstance(over, Mapping):
            bad.append("%s: {項目: 値} で書く" % name)
            continue
        bad += _value_problems(name, over, fields)
    return bad


def _scale_problems(name: str, k: str, v: Any, fields) -> list[str]:
    if SCALES[k] not in fields:
        return ["%s: この effect は %s を持たない（%s は %s の倍率）"
                % (name, SCALES[k], k, SCALES[k])]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        return ["%s: %s=%r は 0 より大きい数" % (name, k, v)]
    return []


def _scaled(over: Mapping[str, Any], base: Mapping[str, Any], fields) -> dict[str, Any]:
    """倍率（`SCALES`）を掛ける先の値に直す。先はセクションの値、無ければ `base`。"""
    out = dict(over)
    for k, target in SCALES.items():
        if k in out:
            f = fields[target]
            ref = f.coerce(out.get(target, base.get(target, f.default)))
            out[target] = ref * float(out.pop(k))
    return out


def _override(over: Mapping[str, Any], fields) -> Override:
    return tuple(sorted((k, fields[k].coerce(v)) for k, v in _notes_dropped(over).items()))


def _merged(song: Song, doc: Mapping[str, Any],
            extra: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """セクションごとの引数。`extra` の上に song.json の値を重ねる（手書きが勝つ）。
    倍率はまだ掛けない（検証のあとで `_scaled()`）。"""
    if extra is not None and len(extra) != len(song.sections):
        raise ValueError("extra が %d 個に対してセクションが %d 個"
                         % (len(extra), len(song.sections)))
    extra = extra if extra is not None else [{}] * len(song.sections)
    return [{**e, **_notes_dropped(doc.get(s.name, {}))}
            for s, e in zip(song.sections, extra)]


def build(song: Song, doc: Mapping[str, Any], effect: str, fps: int,
          xfade: float = 2.0, extra: Sequence[Mapping[str, Any]] | None = None,
          base: Mapping[str, Any] | None = None) -> Scenes:
    """`song` は開始時刻つきであること。**知らないセクション名も一緒に並べて断る。**

    `extra` はセクションの順に並べた、足す引数（`doc` と同じく検証する）。
    `base` は effect の元の引数（倍率を掛ける先が、セクションにも `extra` にも無いとき）。
    """
    if not song.timed:
        raise ValueError("開始時刻の無いセクションがある（sections コマンドで推定する）")
    doc = _notes_dropped(doc)
    names = {s.name for s in song.sections}
    merged = _merged(song, doc, extra)
    fields = {f.name: f for f in effects.get(effect).fields}
    bad = problems(doc, effect) + ["歌詞に無いセクション: %s" % n
                                   for n in doc if n not in names]
    bad += [p for s, e in zip(song.sections, extra or ()) for p in
            _value_problems(s.name, e, fields)]
    if bad:
        raise ValueError("sections が通らない:\n  " + "\n  ".join(bad))
    return Scenes(tuple(int(round(s.start * fps)) for s in song.sections),
                  tuple(_override(_scaled(o, base or {}, fields), fields) for o in merged),
                  int(round(xfade * fps)))
