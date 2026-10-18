"""セクションごとのキー画像 → 背景の動画1本。cymatics の `--image` に動画として渡す。

- キー画像を書いていないセクションは、**前のセクションの画像のまま**。最初の
  セクションより前に書いたものが無ければ曲の `image`
- 同じ名前のセクションが複数あれば全部に当たる（`scenes` と同じ）
- 画像は画面を覆うように拡大して中央で切る（cymatics の動画の背景と同じ）
- **境界は `xfade` フレームかけて混ぜる。** 境界をまたいで半分ずつ——effect の
  置き場所（`scenes`）と同じ窓なので、背景と effect が一緒に移る

フレーム f の絵はフレーム番号だけで決まる ∴ 分割書き出しでも同じ絵になる。
作り直すかは `record()`（入力のハッシュ・切れ目・大きさ）で決める。
"""
from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from .lyrics import Song

#: 背景の動画の画質（x264 の crf）。cymatics がこの上に描くので高めに
CRF = 14


def keyed(song: Song, keys: Mapping[str, str], default: str) -> list[str]:
    """セクションごとの背景の画像。書いていなければ前のセクションの画像のまま。"""
    out, cur = [], default
    for s in song.sections:
        cur = keys.get(s.name, cur)
        out.append(cur)
    return out


def cover(path: str, w: int, h: int) -> np.ndarray:
    """画面 (w, h) を覆うように拡大して中央で切った RGB。"""
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return np.asarray(ImageOps.fit(img, (w, h), Image.LANCZOS), np.float32)


def weights(starts: Sequence[int], images: Sequence[str], f: int,
            xfade: int) -> list[tuple[str, float]]:
    """フレーム f の (画像, 濃さ) の列。境界の前後 `xfade/2` だけ2枚を混ぜる。"""
    i = max(0, int(np.searchsorted(starts, f, side="right")) - 1)
    half = xfade / 2.0
    for j in (i + 1, i):
        if 0 < j < len(images) and images[j] != images[j - 1] and \
                starts[j] - half <= f < starts[j] + half:
            k = (f - (starts[j] - half)) / xfade
            return [(images[j - 1], 1.0 - k), (images[j], k)]
    return [(images[i], 1.0)]


def record(images: Sequence[str], starts: Sequence[int], frames: int, fps: int,
           size: tuple[int, int], xfade: int) -> dict[str, Any]:
    """作り直すかを決める記録。画像は中身のハッシュで持つ。"""
    digest = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in set(images)}
    return {"images": [[p, digest[p]] for p in images], "starts": list(starts),
            "frames": frames, "fps": fps, "size": list(size), "xfade": xfade, "crf": CRF}


def _encoder(dst: str, fps: int, w: int, h: int) -> subprocess.Popen:
    return subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", "%dx%d" % (w, h), "-r", str(fps), "-i", "-", "-c:v", "libx264",
         "-crf", str(CRF), "-tune", "stillimage", "-pix_fmt", "yuv420p", dst],
        stdin=subprocess.PIPE)


def write(dst: str, images: Sequence[str], starts: Sequence[int], frames: int, fps: int,
          size: tuple[int, int], xfade: int) -> str:
    """背景の動画を書く。`starts` はセクションの開始フレーム（`images` と同じ順）。"""
    w, h = size
    pics = {p: cover(p, w, h) for p in set(images)}
    enc = _encoder(dst, fps, w, h)
    try:
        for f in range(frames):
            mix = sum(pics[p] * k for p, k in weights(starts, images, f, xfade))
            enc.stdin.write(np.clip(np.rint(mix), 0, 255).astype(np.uint8).tobytes())
    finally:
        enc.stdin.close()
        if enc.wait() != 0:
            raise RuntimeError("ffmpeg が背景の動画を書けなかった: %s" % dst)
    return dst
