"""`reel` の区間の動き（`motion`）。区間の絵を、背景の上で動く矩形にする。

    {"image": "a.jpg", "until": "Chorus 1",
     "motion": {"position": "right", "width": 0.4, "anchor": 0.5, "hold": 1, "seconds": 1.5}}
    {"flow": ["a.jpg", "b.gif", "c.mp4"], "until": "Bridge",
     "motion": {"position": "left_right", "direction": "up", "item": 0.8, "jitter": 1}}

- **縮む（`image` / `video` の区間）。** 区間の絵はまず画面ぜんたいを覆い（cymatics の背景と
  同じ、拡大して中央で切った見え方）、`hold` 秒そのまま、`seconds` 秒かけて比率を保った
  まま縮みながら、列（`position` / `width` / `margin`）の中の高さ `anchor` へ移る
- **流れる（`flow` の区間）。** 並べた素材（画像・動画・GIF、何本でも）が縮んだ矩形になり、
  歌詞の `roll` のように列の中を間（`gap`）をあけて次々に流れる。`speed`（画面の高さ／秒）が
  0 なら、最初の素材が画面の端から入り、最後の素材が反対の端から出きるまでで区間の尺
  ちょうど。`speed` を書けば並びを繰り返して区間を埋める。`jitter` で、流れる向きと
  直交する向き（横）の位置を列の中でばらつかせる（`seed` ごとに同じばらつき）
- 時刻は**前の区間からの入り（`in`）が終わったところ**から数える
- 空いたところ（`back`）は、`blur`＝自分（流れなら見えている素材を見えている量で混ぜる）を
  画面いっぱいにぼかして `dim` だけ暗くしたもの、`color`＝`back_color` の単色
- 項目は歌詞の帯（`credits`）に準じる: `position`（`left_right` / `right_left` は流れの
  素材ごとに左右を入れ替える）・`width` 列の幅・`margin` 端からの余白・`anchor`・
  `direction`・`gap`・`edge_fade` 上下の端で薄れる幅・`band` / `band_alpha` 列の裏の帯
- 透けた素材（PNG・GIF）は透けたまま重ねる

フレーム f の絵は区間の頭からのフレーム番号だけで決まる ∴ 何度書き出しても同じ絵。
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np
from cymatics.model.color import parse as parse_color
from PIL import Image, ImageFilter, ImageOps

from . import video
from .doc import is_number, notes_dropped

#: 位置の名前 → 左右（交互は最初の側）。歌詞の帯（`roll.POSITIONS`）と同じ値
POSITIONS: Mapping[str, str] = MappingProxyType({
    "right": "right", "left": "left", "center": "center",
    "left_right": "left", "right_left": "right"})
#: 流れる向き。歌詞の帯（`roll.DIRECTIONS`）と同じ
DIRECTIONS: tuple[str, ...] = ("up", "down")

#: 縮む・流れるの両方に書ける項目と既定値
COMMON: Mapping[str, Any] = MappingProxyType({
    "position": "right",
    "width": 0.32,           # 列の幅 ÷ 画面の幅
    "margin": 0.04,          # 画面の端から列まで ÷ 画面の幅
    "band": "0,0,0",         # 列の裏の帯（上から下まで）の色
    "band_alpha": 0.0,
    "back": "blur",          # 空いたところ: blur / color
    "back_color": "0,0,0",
    "blur": 0.03,            # ぼかしの半径 ÷ 画面の高さ
    "dim": 0.4,              # ぼかした背景を暗くする量 0..1
})
#: 縮むときだけの項目
SHRINK: Mapping[str, Any] = MappingProxyType({
    "anchor": 0.5,           # 縮んだ矩形の真ん中の高さ ÷ 画面の高さ
    "hold": 0.0,             # 画面ぜんたいのまま止まる秒数
    "seconds": 1.0,          # 縮む秒数
})
#: 流れるときだけの項目
FLOW: Mapping[str, Any] = MappingProxyType({
    "direction": "up",
    "item": 1.0,             # 素材の幅 ÷ 列の幅
    "gap": 0.1,              # 素材の間 ÷ 画面の高さ
    "speed": 0.0,            # 画面の高さ／秒。0 で区間の尺に合わせる（繰り返さない）
    "jitter": 0.0,           # 横のばらつき 0..1（列の空きのどれだけを使うか）
    "seed": 0,
    "edge_fade": 0.0,        # 上下の端で薄れる幅 ÷ 画面の高さ
    "loop": False,           # 動画の素材を繰り返すか（しなければ最後のコマで止まる）
})
#: 数の項目の範囲（両端を含む）
RANGES: Mapping[str, tuple[float, float]] = MappingProxyType({
    "width": (0.05, 1.0), "margin": (0.0, 0.45), "band_alpha": (0.0, 1.0),
    "blur": (0.0, 0.2), "dim": (0.0, 1.0), "anchor": (0.0, 1.0), "hold": (0.0, 600.0),
    "seconds": (0.0, 600.0), "item": (0.05, 1.0), "gap": (0.0, 2.0), "speed": (0.0, 10.0),
    "jitter": (0.0, 1.0), "edge_fade": (0.0, 0.5)})
#: 空いたところの埋め方
BACKS: tuple[str, ...] = ("blur", "color")
#: ぼかした背景を作る解像度 ÷ 画面（ぼかすので粗くていい）
BACK_SCALE = 8
#: 背景の動画の画質（x264 の crf）。この後 chain で書き直すので高めに
CRF = 14
#: 不透明（8bit のアルファ）
OPAQUE = 255
#: 0 で割らないための下限
EPS = 1e-9


def defaults(mode: str) -> Mapping[str, Any]:
    """`mode`（shrink / flow）で書ける項目と既定値。"""
    return MappingProxyType({**COMMON, **(SHRINK if mode == "shrink" else FLOW)})


def _choice_problems(cfg: Mapping[str, Any], mode: str, at: str) -> list[str]:
    """名前で選ぶ項目と、true / false・整数の項目。"""
    choices = {"position": POSITIONS if mode == "flow" else ("right", "left", "center"),
               "back": BACKS, **({"direction": DIRECTIONS} if mode == "flow" else {})}
    bad = ["%s.motion.%s=%r は %s のどれか" % (at, k, cfg[k], " / ".join(v))
           for k, v in choices.items() if cfg[k] not in v]
    if mode == "flow" and not isinstance(cfg["loop"], bool):
        bad.append("%s.motion.loop=%r は true / false" % (at, cfg["loop"]))
    if mode == "flow" and (not isinstance(cfg["seed"], int) or isinstance(cfg["seed"], bool)):
        bad.append("%s.motion.seed=%r は整数" % (at, cfg["seed"]))
    return bad


def problems(doc: Any, mode: str, at: str) -> list[str]:
    """`motion` の駄目な理由を全部。`mode` は区間の種類で決まる（flow なら flow）。"""
    if not isinstance(doc, Mapping):
        return ["%s.motion は {項目: 値}" % at]
    doc = notes_dropped(doc)
    keys = defaults(mode)
    bad = ["%s.motion の知らない項目: %s%s" % (at, k, "（流れる区間だけ）" if k in FLOW else
                                         "（縮む区間だけ）" if k in SHRINK else "")
           for k in sorted(set(doc) - set(keys))]
    cfg = {**keys, **doc}
    bad += _choice_problems(cfg, mode, at)
    for k, (lo, hi) in RANGES.items():
        if k in keys and not (is_number(cfg[k]) and lo <= cfg[k] <= hi):
            bad.append("%s.motion.%s=%r は %s..%s の数" % (at, k, cfg[k], lo, hi))
    for k in ("band", "back_color"):
        try:
            parse_color(str(cfg[k]))
        except (ValueError, TypeError) as e:
            bad.append("%s.motion.%s=%r（%s）" % (at, k, cfg[k], e))
    return bad


def options(doc: Mapping[str, Any] | None, mode: str) -> tuple[tuple[str, Any], ...]:
    """既定値で埋めた `motion`。区間（frozen）に持たせるので項目の組の tuple。"""
    return tuple(sorted({**defaults(mode), **notes_dropped(doc or {})}.items()))


# ------------------------------------------------------------- 形
@dataclass(frozen=True)
class Rect:
    """画面の上の矩形（px、小数のまま）。"""

    x: float
    y: float
    w: float
    h: float

    def lerp(self, other: Rect, k: float) -> Rect:
        return Rect(*(a + (b - a) * k for a, b in zip(
            (self.x, self.y, self.w, self.h), (other.x, other.y, other.w, other.h))))


def smooth(k: float) -> float:
    """0..1 の進みを、出だしと終わりがなめらかな進みに（smoothstep）。外は端に張りつく。"""
    k = min(max(k, 0.0), 1.0)
    return k * k * (3 - 2 * k)


def column(cfg: Mapping[str, Any], side: str, size: tuple[int, int]) -> tuple[float, float]:
    """列の左右の端（px）。歌詞の列（`roll.column`）と同じ置き方。"""
    w = size[0]
    cw, m = cfg["width"] * w, cfg["margin"] * w
    x0 = {"left": m, "right": w - m - cw, "center": (w - cw) / 2}[side]
    return x0, x0 + cw


def cover_rect(src: tuple[int, int], size: tuple[int, int]) -> Rect:
    """画面を覆うように拡大して中央に置いたときの矩形（はみ出したぶんは画面の外）。"""
    (sw, sh), (w, h) = src, size
    s = max(w / sw, h / sh)
    return Rect((w - sw * s) / 2, (h - sh * s) / 2, sw * s, sh * s)


def fitted(src: tuple[int, int], width: float, height: float) -> tuple[float, float]:
    """比率を保って幅 `width` に。高さが `height` を越えるなら高さに合わせる。"""
    sw, sh = src
    w, h = width, width * sh / sw
    return (w, h) if h <= height else (height * sw / sh, height)


def shrunk_rect(src: tuple[int, int], cfg: Mapping[str, Any], size: tuple[int, int]) -> Rect:
    """縮み終えた矩形。列の幅に合わせ（画面より高くはしない）、列の中で横は真ん中、
    縦は真ん中が `anchor` の高さ。"""
    x0, x1 = column(cfg, POSITIONS[cfg["position"]], size)
    w, h = fitted(src, x1 - x0, size[1])
    return Rect(x0 + (x1 - x0 - w) / 2, cfg["anchor"] * size[1] - h / 2, w, h)


def shrink_at(src: tuple[int, int], cfg: Mapping[str, Any], size: tuple[int, int],
              t: float) -> Rect:
    """時刻 t（入りが終わってからの秒）の矩形。"""
    k = smooth((t - cfg["hold"]) / max(cfg["seconds"], EPS)) if cfg["seconds"] > 0 else \
        float(t >= cfg["hold"])
    return cover_rect(src, size).lerp(shrunk_rect(src, cfg, size), k)


@dataclass(frozen=True)
class Slot:
    """流れの1つ。`index` は並びの通し番号（繰り返しも数える）、`item` は素材の番号。"""

    index: int
    item: int
    rect: Rect


class Stream:
    """流れる素材の並びの置き方。並びの中の位置（流れる向きに px）と、時刻の進み。"""

    def __init__(self, sizes: Sequence[tuple[int, int]], cfg: Mapping[str, Any],
                 size: tuple[int, int], seconds: float) -> None:
        if not sizes:
            raise ValueError("流れる素材が無い")
        self._cfg, self._size = cfg, size
        w, h = size
        x0, x1 = column(cfg, "left", size)
        self._dims = [fitted(s, (x1 - x0) * cfg["item"], h) for s in sizes]
        self._gap = cfg["gap"] * h
        self._starts = list(np.cumsum([0.0] + [d[1] + self._gap for d in self._dims]))
        self._period = self._starts[-1]           # 並び1周の長さ（最後の後ろの間を含む）
        length = self._period - self._gap         # 最初の頭から最後のお尻まで
        self._speed = cfg["speed"] * h if cfg["speed"] > 0 else \
            (h + length) / max(seconds, EPS)
        self._repeat = cfg["speed"] > 0
        self._sides = self._sides_of(cfg["position"])

    @staticmethod
    def _sides_of(position: str) -> tuple[str, ...]:
        first = POSITIONS[position]
        if position in ("left_right", "right_left"):
            return (first, "right" if first == "left" else "left")
        return (first,)

    def side(self, index: int) -> str:
        return self._sides[index % len(self._sides)]

    def _x(self, index: int, w: float) -> float:
        x0, x1 = column(self._cfg, self.side(index), self._size)
        free = x1 - x0 - w
        u = float(np.random.default_rng([int(self._cfg["seed"]), index]).random())
        return x0 + free / 2 + self._cfg["jitter"] * (u - 0.5) * free

    def slots(self, t: float) -> list[Slot]:
        """時刻 t に画面にかかる素材。"""
        h, n = self._size[1], len(self._dims)
        off = self._speed * max(t, 0.0)           # 並びの頭が画面の端からどれだけ入ったか
        rounds = range(int(off // self._period) + 1) if self._repeat else range(1)
        out = []
        for r in rounds:
            for j, (iw, ih) in enumerate(self._dims):
                along = off - (r * self._period + self._starts[j])  # 素材の頭が入った量
                if along <= 0 or along >= h + ih:
                    continue
                y = h - along if self._cfg["direction"] == "up" else along - ih
                idx = r * n + j
                out.append(Slot(idx, j, Rect(self._x(idx, iw), y, iw, ih)))
        return out


# ------------------------------------------------------------- 素材のコマ
def source_size(path: str) -> tuple[int, int]:
    """素材の大きさ（画像は向きを直した後）。"""
    if Path(path).suffix.lower() in IMAGES:
        with Image.open(path) as im:
            return ImageOps.exif_transpose(im).size
    return video.size_of(path)


#: 画像として読む拡張子（ほかは ffmpeg で動画として読む）
IMAGES = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


class Frames:
    """素材のコマを1枚ずつ、大きさ `size` の RGBA で出す。画像はいつも同じ絵。動画は
    尽きたら最後のコマのまま（`loop` なら頭から）。"""

    def __init__(self, path: str, size: tuple[int, int], fps: int, loop: bool) -> None:
        self._size = (max(1, int(round(size[0]))), max(1, int(round(size[1]))))
        self._last: Image.Image | None = None
        self._proc: subprocess.Popen | None = None
        if Path(path).suffix.lower() in IMAGES:
            with Image.open(path) as im:
                self._last = ImageOps.exif_transpose(im).convert("RGBA").resize(
                    self._size, Image.LANCZOS)
            return
        w, h = self._size
        self._proc = subprocess.Popen(
            ["ffmpeg", "-v", "error", *(["-stream_loop", "-1"] if loop else []), "-i", path,
             "-vf", "fps=%d,scale=%d:%d,setsar=1" % (fps, w, h), "-an", "-f", "rawvideo",
             "-pix_fmt", "rgba", "-"], stdout=subprocess.PIPE)

    def next(self) -> Image.Image:
        if self._proc is not None:
            n = self._size[0] * self._size[1] * 4
            raw = self._proc.stdout.read(n)
            if len(raw) == n:
                self._last = Image.frombuffer("RGBA", self._size, raw, "raw", "RGBA", 0, 1)
            else:
                self.close()
        if self._last is None:
            raise RuntimeError("素材からコマが読めなかった")
        return self._last

    def close(self) -> None:
        if self._proc is not None:
            self._proc.kill()                     # 先に止める（読み口を閉じると ffmpeg が騒ぐ）
            self._proc.wait()
            self._proc.stdout.close()
            self._proc = None


# ------------------------------------------------------------- 描く
def _opaque(im: Image.Image) -> Image.Image:
    """透けたところを黒にした RGB。"""
    base = Image.new("RGB", im.size, (0, 0, 0))
    base.paste(im, (0, 0), im)
    return base


def blurred(frame: Image.Image, size: tuple[int, int], cfg: Mapping[str, Any]) -> np.ndarray:
    """画面を覆うようにぼかして `dim` だけ暗くした背景（float32、画面の 1/BACK_SCALE）。"""
    w, h = (max(1, size[0] // BACK_SCALE), max(1, size[1] // BACK_SCALE))
    small = ImageOps.fit(_opaque(frame), (w, h), Image.BILINEAR)
    radius = cfg["blur"] * size[1] / BACK_SCALE
    if radius > 0:
        small = small.filter(ImageFilter.GaussianBlur(radius))
    return np.asarray(small, np.float32) * (1.0 - cfg["dim"])


class Canvas:
    """1フレームの下地（空いたところ・列の帯）と、矩形の貼りつけ。"""

    def __init__(self, cfg: Mapping[str, Any], size: tuple[int, int]) -> None:
        self._cfg, self._size = cfg, size
        self._color = np.array(parse_color(str(cfg["back_color"]))[0], np.float32)
        self._band = parse_color(str(cfg["band"]))[0]

    def back(self, layers: Sequence[tuple[np.ndarray, float]]) -> Image.Image:
        """`layers`＝(ぼかした背景, 重み)。重みの和が 1 に届かないぶんは `back_color`。"""
        w, h = self._size
        if self._cfg["back"] == "color" or not layers:
            return Image.new("RGB", self._size, tuple(int(c) for c in self._color))
        total = sum(k for _b, k in layers)
        mix = sum(b * (k / max(total, EPS)) for b, k in layers)
        cover = min(1.0, total)
        mix = mix * cover + self._color * (1 - cover)
        small = Image.fromarray(np.clip(np.rint(mix), 0, 255).astype(np.uint8))
        return small.resize((w, h), Image.BILINEAR)

    def band(self, img: Image.Image, side: str, k: float = 1.0) -> None:
        """列の裏の帯（上から下まで）。`k` は濃さの倍率。"""
        a = self._cfg["band_alpha"] * k
        if a <= 0:
            return
        x0, x1 = column(self._cfg, side, self._size)
        box = (int(round(x0)), 0, int(round(x1)), self._size[1])
        layer = Image.new("RGBA", (box[2] - box[0], box[3]), (*self._band, int(round(OPAQUE * a))))
        img.paste(layer, box[:2], layer)

    @staticmethod
    def put(img: Image.Image, im: Image.Image, rect: Rect,
            fade: Callable[[int, int], np.ndarray] | None = None) -> None:
        """`im` を矩形 `rect` に貼る（透けたまま）。`fade(y0, h)` があれば行ごとの濃さを掛ける。"""
        w, h = max(1, int(round(rect.w))), max(1, int(round(rect.h)))
        x, y = int(round(rect.x)), int(round(rect.y))
        if x >= img.width or y >= img.height or x + w <= 0 or y + h <= 0:
            return
        im = im if im.size == (w, h) else im.resize((w, h), Image.BILINEAR, reducing_gap=2.0)
        mask = im.getchannel("A")
        if fade is not None:
            a = np.asarray(mask, np.float32) * fade(y, h)[:, None]
            mask = Image.fromarray(np.clip(np.rint(a), 0, 255).astype(np.uint8))
        img.paste(im.convert("RGB"), (x, y), mask)


def edge_alpha(height: int, frac: float) -> Callable[[int, int], np.ndarray]:
    """画面の上下の端で `frac`（画面の高さに対する比）かけて薄れる、行ごとの濃さ。"""
    ramp = frac * height

    def fade(y0: int, h: int) -> np.ndarray:
        ys = np.arange(y0, y0 + h, dtype=np.float32) + 0.5
        return np.clip(np.minimum(ys, height - ys) / max(ramp, EPS), 0.0, 1.0)
    return fade


def shrink_frames(path: str, cfg: Mapping[str, Any], loop: bool, size: tuple[int, int],
                  fps: int, frames: int, lead: int) -> Iterator[Image.Image]:
    """縮む区間のコマ。`lead` は前の区間からの入りのフレーム数（時刻はその後から）。"""
    src = source_size(path)
    full = cover_rect(src, size)
    frm, cv = Frames(path, (full.w, full.h), fps, loop), Canvas(cfg, size)
    side = POSITIONS[cfg["position"]]
    try:
        for f in range(frames):
            im = frm.next()
            img = cv.back([(blurred(im, size, cfg), 1.0)] if cfg["back"] == "blur" else [])
            rect = shrink_at(src, cfg, size, (f - lead) / fps)
            t = (f - lead) / fps - cfg["hold"]
            cv.band(img, side, smooth(t / cfg["seconds"]) if cfg["seconds"] > 0 else float(t >= 0))
            cv.put(img, im, rect)
            yield img
    finally:
        frm.close()


def _visible(rect: Rect, h: int) -> float:
    return max(0.0, min(rect.y + rect.h, h) - max(rect.y, 0.0))


def flow_frames(paths: Sequence[str], cfg: Mapping[str, Any], size: tuple[int, int],
                fps: int, frames: int, lead: int) -> Iterator[Image.Image]:
    """流れる区間のコマ。素材の動画は画面に入ったところから再生する。"""
    sizes = [source_size(p) for p in paths]
    stream = Stream(sizes, cfg, size, (frames - lead) / fps)
    cv, fade = Canvas(cfg, size), edge_alpha(size[1], cfg["edge_fade"])
    playing: dict[int, Frames] = {}
    h = size[1]
    try:
        for f in range(frames):
            slots = stream.slots((f - lead) / fps)
            for idx in set(playing) - {s.index for s in slots}:
                playing.pop(idx).close()
            shots = []
            for s in slots:
                if s.index not in playing:
                    playing[s.index] = Frames(paths[s.item], (s.rect.w, s.rect.h), fps,
                                              cfg["loop"])
                shots.append((s, playing[s.index].next()))
            backs = [(blurred(im, size, cfg), _visible(s.rect, h) / (h / 2))
                     for s, im in shots] if cfg["back"] == "blur" else []
            img = cv.back(backs)
            for side in set(stream.side(i) for i in range(2)):
                seen = sum(_visible(s.rect, h) for s in slots if stream.side(s.index) == side)
                tallest = max((s.rect.h for s in slots), default=1.0)
                fixed = cfg["position"] in ("right", "left", "center")
                cv.band(img, side, 1.0 if fixed else min(1.0, seen / max(tallest, EPS)))
            for s, im in shots:
                cv.put(img, im, s.rect, fade if cfg["edge_fade"] > 0 else None)
            yield img
    finally:
        for p in playing.values():
            p.close()


def write(dst: str, pictures: Iterator[Image.Image], size: tuple[int, int], fps: int) -> str:
    """コマの並びを動画に（音なし）。"""
    w, h = size
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", "%dx%d" % (w, h), "-r", str(fps), "-i", "-", "-c:v", "libx264",
         "-crf", str(CRF), "-pix_fmt", "yuv420p", dst], stdin=subprocess.PIPE)
    try:
        for img in pictures:
            enc.stdin.write(img.tobytes())
    finally:
        enc.stdin.close()
        if enc.wait() != 0:
            raise RuntimeError("ffmpeg が動きの区間を書けなかった: %s" % dst)
    return dst
