"""画面ぜんたいの色調。重ね終えた1枚（cymatics の `finish`）に掛ける。描画は知らない。

- **灰色へ**（`gray`）: 0 で今の彩度のまま、1 でグレースケール。輝度は BT.601
- **セピアへ**（`sepia`）: 0 でそのまま、1 で古い写真の茶色。灰色にしてから
  掛けるのではなく、今の絵（灰色へ寄せたあと）に掛ける

**どちらも 0 なら絵に触らない。** 配列に開いて閉じるだけでも丸めは起きないが、
既定が素の cymatics と画素まで同じことを、触らないことで保証する。
"""
from __future__ import annotations

import numpy as np
from PIL import Image

#: 輝度（BT.601）
LUMA = np.array([0.299, 0.587, 0.114], np.float32)

#: セピアの色行列（行が出力の R / G / B）
SEPIA = np.array([[0.393, 0.769, 0.189],
                  [0.349, 0.686, 0.168],
                  [0.272, 0.534, 0.131]], np.float32)


def apply(img: Image.Image, gray: float, sepia: float) -> Image.Image:
    """`img` を灰色へ `gray`、セピアへ `sepia` だけ寄せた絵。どちらも 0..1。"""
    if gray <= 0.0 and sepia <= 0.0:
        return img
    a = np.asarray(img.convert("RGB"), np.float32)
    if gray > 0.0:
        a = a + ((a @ LUMA)[..., None] - a) * min(gray, 1.0)
    if sepia > 0.0:
        a = a + (a @ SEPIA.T - a) * min(sepia, 1.0)
    return Image.fromarray(np.clip(np.rint(a), 0, 255).astype(np.uint8))
