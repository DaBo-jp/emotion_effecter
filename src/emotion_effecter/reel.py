"""背景の区間の並び（song.json の `reel`）→ 背景の動画1本。**effect と歌詞は全部の上に描く。**

    "reel": [
      {"video": "Opening.mp4"},
      {"image": "Ceiling.jpg", "until": "Bridge", "in": {"transition": "fade", "seconds": 1}},
      {"video": "Bridge.mp4", "in": {"transition": "fadeblack", "seconds": 2}},
      {"image": "Ceiling.jpg"},
      {"video": "Closing.mp4", "in": {"transition": "fade", "seconds": 1}}
    ]

Opening → 静止画 → Closing はその1つの書き方にすぎない。区間は mp4 でも画像でも、
何本でも、どの順でも並べられる。`video` はアニメーション GIF でもいい（`video.ANIMATED`）。

- **mp4 はその尺。** 曲の終わりを越える最後の mp4 だけ曲の終わりで切る
- **`"loop": true` の mp4 は繰り返して、画像と同じく `until` まで**
- **画像は `until` まで。** セクション名（その区間が始まった後に最初に終わる、その名前の
  セクションの終わりまで——`Instrumental Break` のように同じ名前が何度あってもいい）か秒。
  `until` を書かない画像は「残り全部」で、並びに1つだけ置ける。その後ろは尺の決まった
  mp4 だけ（曲の終わりから逆に置ける。Closing の形）。ループする mp4・流れ（`flow`）も
  画像と同じく `until` まで、書かなければ残り全部
- **`"effect": false` でその区間だけ effect を描かない**（`Mute`）。背景と歌詞・仕上げは
  そのまま。入り（`in`）のある境目では、その秒数で effect が薄れて消え、戻る
- **`motion` で区間の絵を動く矩形にする**（`motion.py`）。画像・mp4 は画面ぜんたいを
  覆ってから縮んで移る。`{"flow": [素材, ...]}` の区間は、素材が縮んだ矩形になって
  歌詞の帯のように流れる
- **`in` はその区間の入り方。** `transition`（`video.TRANSITIONS`、既定 `fade`）で `seconds`
  秒かけて前の区間から移る。移り終えた時刻が区切りの時刻になる——前の区間はそこまで
  見え、入ってくる区間は `seconds` 秒早く始まる。書かなければ切り替え
- 曲の終わりに届かない並び、尺の足りない区間は**全部並べて断る**。黙って伸ばさない

フレーム f の絵はフレーム番号だけで決まる ∴ 分割書き出しでも同じ絵になる。
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from . import digest, motion, video
from .doc import is_number, notes_dropped
from .lyrics import Song

#: 区間の種類 → 書けるもの
KEYS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "image": ("image", "until", "in", "motion", "effect"),
    "video": ("video", "loop", "until", "in", "motion", "effect"),
    "flow": ("flow", "until", "in", "motion", "effect"),
})
#: `in` に書けるもの
IN_KEYS = ("transition", "seconds")


@dataclass(frozen=True)
class Segment:
    """並びの1区間。`path` は絶対パス。"""

    kind: str                       # "image" / "video" / "flow"
    path: str                       # flow では使わない（""）
    until: str | float | None = None
    transition: str = "fade"
    seconds: float = 0.0
    loop: bool = False              # mp4 を繰り返して until まで
    items: tuple[str, ...] = ()     # flow の素材（絶対パス）
    #: `motion` の中身（既定値で埋めた項目の組）。無ければ動かない
    motion: tuple[tuple[str, Any], ...] | None = None
    effect: bool = True             # false ならこの区間は effect を描かない

    @property
    def fills(self) -> bool:
        """尺を `until`（無ければ残り全部）で決める区間か。尺の決まった mp4 だけ違う。"""
        return self.kind != "video" or self.loop

    @property
    def files(self) -> tuple[str, ...]:
        return self.items if self.kind == "flow" else (self.path,)


@dataclass(frozen=True)
class Span:
    """置いた区間。`f0` から `frames` フレーム。頭の `overlap` は前の区間と重なる。"""

    seg: Segment
    f0: int
    frames: int
    overlap: int

    @property
    def f1(self) -> int:
        return self.f0 + self.frames


def _in_problems(at: str, doc: Any) -> list[str]:
    if not isinstance(doc, Mapping):
        return ['%s.in は {"transition": 切り替え, "seconds": 秒}' % at]
    doc = notes_dropped(doc)
    bad = ["%s.in の知らない項目: %s" % (at, k) for k in sorted(set(doc) - set(IN_KEYS))]
    if not (is_number(doc.get("seconds")) and doc["seconds"] > 0):
        bad.append("%s.in.seconds は 0 より大きい秒数" % at)
    if doc.get("transition", "fade") not in video.TRANSITIONS:
        bad.append("%s.in.transition=%r は知らない切り替え" % (at, doc.get("transition")))
    return bad


def _kind(doc: Mapping[str, Any]) -> str:
    return next(k for k in KEYS if k in doc)


def _files_problems(at: str, kind: str, doc: Mapping[str, Any], root: Path) -> list[str]:
    name = {"image": "画像", "video": "動画", "flow": "素材"}[kind]
    files = doc[kind] if kind == "flow" else [doc[kind]]
    if kind == "flow" and (not isinstance(files, list) or not files):
        return ["%s.flow は流す素材の並び（1つ以上）" % at]
    return ["%s の%sが無い: %s" % (at, name, f) for f in files
            if not isinstance(f, str) or not (root / f).is_file()]


def _segment_problems(i: int, doc: Any, root: Path) -> list[str]:
    at = "reel[%d]" % i
    if not isinstance(doc, Mapping) or len(set(KEYS) & set(doc)) != 1:
        return ['%s は {"image": 画像, "until": ...} か {"video": 動画} か {"flow": [素材, ...]}'
                % at]
    doc = notes_dropped(doc)
    kind = _kind(doc)
    bad = ["%s の知らない項目: %s" % (at, k) for k in sorted(set(doc) - set(KEYS[kind]))]
    bad += _files_problems(at, kind, doc, root)
    bad += ["%s.%s は true / false" % (at, k) for k in ("loop", "effect")
            if k in doc and not isinstance(doc[k], bool)]
    if kind == "video" and "until" in doc and doc.get("loop") is not True:
        bad.append("%s.until は繰り返す動画（\"loop\": true）だけ。mp4 はその尺" % at)
    if "motion" in doc:
        bad += motion.problems(doc["motion"], "flow" if kind == "flow" else "shrink", at)
    until = doc.get("until")
    if until is not None and not isinstance(until, str) and not (is_number(until) and until > 0):
        bad.append("%s.until はセクション名か 0 より大きい秒数" % at)
    if i == 0 and "in" in doc:
        bad.append("%s.in: 最初の区間には前が無い（黒から入るなら fade_in）" % at)
    return bad + (_in_problems(at, doc["in"]) if "in" in doc else [])


def problems(doc: Any, root: Path) -> list[str]:
    """`reel` の駄目な理由を全部。空なら通る。"""
    if not isinstance(doc, list) or not doc:
        return ["reel は区間の並び（1つ以上）"]
    bad = [p for i, d in enumerate(doc) for p in _segment_problems(i, d, root)]
    if bad:
        return bad
    segs = from_list(doc, root)
    rest = [i for i, s in enumerate(segs) if s.fills and s.until is None]
    if len(rest) > 1:
        bad.append("reel: until の無い区間（残り全部）は1つだけ: %s" % rest)
    if rest and any(s.fills for s in segs[rest[0] + 1:]):
        bad.append("reel: 残り全部の区間より後ろは繰り返さない mp4 だけ（尺で曲の終わりから置く）")
    return bad


def from_list(doc: Sequence[Mapping[str, Any]], root: Path) -> tuple[Segment, ...]:
    out = []
    for d in doc:
        d = notes_dropped(d)
        kind = _kind(d)
        cfg = notes_dropped(d.get("in", {}))
        items = tuple(str((root / f).resolve()) for f in d["flow"]) if kind == "flow" else ()
        moves = motion.options(d.get("motion"), "flow" if kind == "flow" else "shrink") \
            if "motion" in d or kind == "flow" else None
        out.append(Segment(kind, "" if kind == "flow" else str((root / d[kind]).resolve()),
                           d.get("until"), cfg.get("transition", "fade"),
                           float(cfg.get("seconds", 0.0)), bool(d.get("loop", False)), items,
                           moves, bool(d.get("effect", True))))
    return tuple(out)


# ------------------------------------------------------------- 置く
def _section_end(song: Song, name: str, after: int, fps: int, song_f: int) -> int | None:
    """`after` フレームより後に終わる、最初の `name` のセクションの終わり。"""
    starts = [int(round(s.start * fps)) for s in song.sections] + [song_f]
    for i, s in enumerate(song.sections):
        if s.name == name and starts[i + 1] > after:
            return starts[i + 1]
    return None


def _end(seg: Segment, f0: int, song: Song, fps: int, song_f: int,
         length: Callable[[str], int]) -> int | str:
    """区間の終わりのフレーム。決められなければ理由。"""
    if not seg.fills:
        return f0 + length(seg.path)
    if isinstance(seg.until, str):
        end = _section_end(song, seg.until, f0, fps, song_f)
        return "until=%r のセクションがこの区間の後に無い" % seg.until if end is None else end
    return int(round(float(seg.until) * fps))


def _backward(tail: Sequence[Segment], song_f: int, fps: int,
              length: Callable[[str], int]) -> list[tuple[int, int]]:
    """残り全部の区間より後ろの mp4 を、曲の終わりから逆に置く → [(f0, f1)]。"""
    out, end = [], song_f
    for seg in reversed(tail):
        f0 = end - length(seg.path)
        out.append((f0, end))
        end = f0 + int(round(seg.seconds * fps))
    return out[::-1]


def place(segs: Sequence[Segment], song: Song, song_f: int, fps: int,
          length: Callable[[str], int] | None = None) -> list[Span]:
    """区間を時間に置く。曲の終わり `song_f` に届かない・尺の足りない区間は全部並べて断る。"""
    length = length or (lambda p: video.frames_of(p, fps))
    rest = next((i for i, s in enumerate(segs) if s.fills and s.until is None), None)
    tail = _backward(segs[rest + 1:], song_f, fps, length) if rest is not None else []
    ends: list[int | str] = []
    cur = 0
    for i, seg in enumerate(segs):
        f0 = cur - int(round(seg.seconds * fps)) if i else 0
        if rest is not None and i > rest:
            f0, end = tail[i - rest - 1]
        elif i == rest:
            end = tail[0][0] + int(round(segs[i + 1].seconds * fps)) if tail else song_f
        else:
            end = _end(seg, f0, song, fps, song_f, length)
        ends.append(end)
        cur = end if isinstance(end, int) else cur
    return _checked(segs, ends, song_f, fps)


def _checked(segs: Sequence[Segment], ends: Sequence[int | str], song_f: int,
             fps: int) -> list[Span]:
    bad = ["reel[%d]: %s" % (i, e) for i, e in enumerate(ends) if isinstance(e, str)]
    if bad:
        raise ValueError("\n".join(bad))
    ovs = [int(round(s.seconds * fps)) if i else 0 for i, s in enumerate(segs)] + [0]
    spans, prev, last = [], 0, len(segs) - 1
    for i, (seg, end) in enumerate(zip(segs, ends)):
        end = min(end, song_f) if i == last else end
        if end - prev <= ovs[i + 1]:
            bad.append("reel[%d]: 区間が短すぎる（%.2f 秒。次の区間の入りより長く要る）"
                       % (i, (end - prev) / fps))
        if i < last and end >= song_f:
            bad.append("reel[%d]: 曲の終わりを越える（後ろの区間が入らない）" % i)
        spans.append(Span(seg, prev - ovs[i], end - prev + ovs[i], ovs[i]))
        prev = end
    if prev < song_f:
        bad.append("reel: 並びが曲の終わりに届かない（%.2f 秒足りない）" % ((song_f - prev) / fps))
    if bad:
        raise ValueError("\n".join(bad))
    return spans


# ------------------------------------------------------------- effect を消す
#: 窓の端を開いたままにする大きなフレーム番号（最後の区間の後ろ）
OPEN_END = 1 << 40


@dataclass(frozen=True)
class Mute:
    """effect を消す窓の並び。窓 (a, b, c, d) は a→b で薄れ、b..c は消え、c→d で戻る。
    フレーム番号だけで決まる（pickle できる）∴ 分割書き出しでも同じ絵。"""

    windows: tuple[tuple[int, int, int, int], ...] = ()

    def gain(self, f: int) -> float:
        """フレーム f の effect の濃さ 0..1（窓が重なれば薄い方）。"""
        return min((_window_gain(w, f) for w in self.windows), default=1.0)

    def to_list(self) -> list[list[int]]:
        return [list(w) for w in self.windows]


def _window_gain(w: tuple[int, int, int, int], f: int) -> float:
    a, b, c, d = w
    if f < a or f >= d:
        return 1.0
    if f < b:
        return 1.0 - (f - a + 1) / (b - a + 1)
    if f < c:
        return 0.0
    return (f - c + 1) / (d - c + 1)


def mute_of(spans: Sequence[Span]) -> Mute:
    """`"effect": false` の区間 → 消す窓。区間の入りで薄れ、次の区間の入りで戻る。"""
    out = []
    for i, s in enumerate(spans):
        if s.seg.effect:
            continue
        nxt = spans[i + 1] if i + 1 < len(spans) else None
        c, d = (s.f1 - nxt.overlap, s.f1) if nxt is not None else (OPEN_END, OPEN_END)
        out.append((s.f0, s.f0 + s.overlap, c, d))
    return Mute(tuple(out))


# ------------------------------------------------------------- 書く
def record(spans: Sequence[Span], frames: int, fps: int,
           size: tuple[int, int]) -> dict[str, Any]:
    """作り直すかを決める記録。ファイルは中身のハッシュで持つ。"""
    sums = {p: digest.sha256(p) for s in spans for p in s.seg.files}
    return {"spans": [[s.seg.kind, [[p, sums[p]] for p in s.seg.files], s.f0, s.frames,
                       s.overlap, s.seg.transition, s.seg.loop, s.seg.effect,
                       dict(s.seg.motion) if s.seg.motion is not None else None]
                      for s in spans],
            "frames": frames, "fps": fps, "size": list(size), "crf": video.CRF,
            "motion_crf": motion.CRF}


def write(dst: str, spans: Sequence[Span], frames: int, fps: int,
          size: tuple[int, int]) -> str:
    """背景の動画を書く。最後の区間は `frames`（曲の尺＋余白）まで伸ばす
    （画像はそのまま、mp4 は最後のフレームで止める）。`motion` のある区間は先に
    動きを描いた動画にしてからつなぐ。"""
    lengths = [s.frames for s in spans]
    lengths[-1] = frames - spans[-1].f0
    with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(dst))) as tmp:
        sources = [_source(s, n, fps, size, os.path.join(tmp, "motion%d.mp4" % i))
                   for i, (s, n) in enumerate(zip(spans, lengths))]
        return video.chain(sources, lengths, [s.overlap for s in spans],
                           [s.seg.transition for s in spans], fps, dst, size)


def _source(span: Span, frames: int, fps: int, size: tuple[int, int],
            tmp: str) -> video.Source:
    """区間1つを `chain` に渡す形に。動くなら先に描く。"""
    seg = span.seg
    if seg.motion is None:
        return video.source(seg.path, seg.kind == "image", fps, frames, size, seg.loop)
    cfg = dict(seg.motion)
    pics = motion.flow_frames(seg.items, cfg, size, fps, frames, span.overlap) \
        if seg.kind == "flow" else \
        motion.shrink_frames(seg.path, cfg, seg.loop, size, fps, frames, span.overlap)
    return video.source(motion.write(tmp, pics, size, fps), False, fps, frames, size)
