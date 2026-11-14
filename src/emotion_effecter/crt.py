"""ブラウン管の画面（song.json の `crt`）。つないだ1本の上に、画面ぜんたいへ重ねる。

    "crt": {"scanlines": 0.15, "band": 0.08, "band_seconds": 8, "band_direction": "down"}

- **走査線**（`scanlines`）: 横の暗い縞をうっすら。0 で無し、1 で縞の芯が真っ黒。
  `pitch` px ごとに1本。縞はなだらか（cos）なので、縮めて見てもちらつきにくい
- **明るい帯**（`band`）: 白っぽい帯が `band_seconds` 秒で画面を上から下へ
  （`band_direction` が `"up"` なら下から上へ）通り過ぎ、それを繰り返す。0 で無し。
  帯の高さは画面の高さに対する割合（`band_height`）

どちらも絵（effect・歌詞・Opening / Closing も）の上に重ねる静止画1枚ずつで、
動くのは帯の位置だけ ∴ 書き出しの時間はほとんど増えない。位置は時刻だけで決まる。
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from PIL import Image

from .doc import is_number, notes_dropped

#: `crt` に書けるもの
KEYS = ("scanlines", "pitch", "band", "band_height", "band_seconds", "band_direction")
#: 帯の向き
DIRECTIONS = ("down", "up")


@dataclass(frozen=True)
class Crt:
    #: 走査線の濃さ 0..1。0 なら引かない
    scanlines: float = 0.15
    #: 走査線の間隔（px）
    pitch: int = 4
    #: 明るい帯の明るさ 0..1。0 なら流さない
    band: float = 0.08
    #: 帯の高さ（画面の高さに対する割合）
    band_height: float = 0.15
    #: 帯が画面を通り過ぎる秒数
    band_seconds: float = 8.0
    #: `"down"`（上から下）か `"up"`（下から上）
    band_direction: str = "down"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _range_problems(doc: Mapping[str, Any]) -> list[str]:
    """数の項目の範囲。"""
    bad = ["crt.%s は 0..1" % k for k in ("scanlines", "band")
           if k in doc and not (is_number(doc[k]) and 0 <= doc[k] <= 1)]
    if "band_height" in doc and not (is_number(doc["band_height"])
                                     and 0 < doc["band_height"] <= 1):
        bad.append("crt.band_height は 0 より大きく 1 以下")
    if "pitch" in doc and not (isinstance(doc["pitch"], int) and is_number(doc["pitch"])
                               and doc["pitch"] >= 2):
        bad.append("crt.pitch は 2 以上の整数（px）")
    if "band_seconds" in doc and not (is_number(doc["band_seconds"])
                                      and doc["band_seconds"] > 0):
        bad.append("crt.band_seconds は 0 より大きい秒数")
    return bad


def problems(doc: Any) -> list[str]:
    """`crt` の駄目な理由を全部。空なら通る。"""
    if not isinstance(doc, Mapping):
        return ['crt は {"scanlines": 0..1, "band": 0..1, ...}（{} で既定）']
    doc = notes_dropped(doc)
    bad = ["crt の知らない項目: %s" % k for k in sorted(set(doc) - set(KEYS))]
    if doc.get("band_direction", "down") not in DIRECTIONS:
        bad.append("crt.band_direction は down / up")
    return bad + _range_problems(doc)


def from_mapping(doc: Mapping[str, Any]) -> Crt:
    return Crt(**notes_dropped(doc))


def _scanlines(c: Crt, size: tuple[int, int], dst: str) -> str:
    """黒の縞の透過 PNG。縞の芯で `scanlines` の濃さ、縞のあいだは透明。"""
    w, h = size
    y = np.arange(h, dtype=np.float64)
    alpha = 255.0 * c.scanlines * (0.5 - 0.5 * np.cos(2.0 * np.pi * y / c.pitch))
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., 3] = np.round(alpha).astype(np.uint8)[:, None]
    Image.fromarray(rgba, "RGBA").save(dst)
    return dst


def _band(c: Crt, size: tuple[int, int], dst: str) -> str:
    """白い帯の透過 PNG。真ん中で `band` の明るさ、上下の端へなだらかに消える。"""
    w, h = size[0], max(2, int(round(size[1] * c.band_height)))
    alpha = 255.0 * c.band * np.sin(np.pi * (np.arange(h) + 0.5) / h) ** 2
    rgba = np.full((h, w, 4), 255, np.uint8)
    rgba[..., 3] = np.round(alpha).astype(np.uint8)[:, None]
    Image.fromarray(rgba, "RGBA").save(dst)
    return dst


def band_y(c: Crt) -> str:
    """帯の上端の位置（ffmpeg の overlay の y の式。`H` は画面、`h` は帯の高さ）。
    画面の外（帯がちょうど隠れる位置）から入って、反対の外へ抜ける。"""
    run = "mod(t/%.6f,1)*(H+h)" % c.band_seconds
    return "%s-h" % run if c.band_direction == "down" else "H-%s" % run


def layers(c: Crt, size: tuple[int, int], tmp: str) -> list[tuple[str, str]]:
    """重ねる (透過 PNG, y の式) の並び。下から順に重ねる。濃さ 0 のものは入れない。"""
    out = []
    if c.scanlines > 0:
        out.append((_scanlines(c, size, os.path.join(tmp, "scanlines.png")), "0"))
    if c.band > 0:
        out.append((_band(c, size, os.path.join(tmp, "band.png")), band_y(c)))
    return out
