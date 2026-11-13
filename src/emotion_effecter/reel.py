"""背景の区間の並び（song.json の `reel`）→ 背景の動画1本。**effect と歌詞は全部の上に描く。**

    "reel": [
      {"video": "Opening.mp4"},
      {"image": "Ceiling.jpg", "until": "Bridge", "in": {"transition": "fade", "seconds": 1}},
      {"video": "Bridge.mp4", "in": {"transition": "fadeblack", "seconds": 2}},
      {"image": "Ceiling.jpg"},
      {"video": "Closing.mp4", "in": {"transition": "fade", "seconds": 1}}
    ]

Opening → 静止画 → Closing はその1つの書き方にすぎない。区間は mp4 でも画像でも、
何本でも、どの順でも並べられる。

- **mp4 はその尺。** 曲の終わりを越える最後の mp4 だけ曲の終わりで切る
- **画像は `until` まで。** セクション名（その区間が始まった後に最初に終わる、その名前の
  セクションの終わりまで——`Instrumental Break` のように同じ名前が何度あってもいい）か秒。
  `until` を書かない画像は「残り全部」で、並びに1つだけ置ける。その後ろは mp4 だけ
  （尺が決まっているので、曲の終わりから逆に置ける。Closing の形）
- **`in` はその区間の入り方。** `transition`（`video.TRANSITIONS`、既定 `fade`）で `seconds`
  秒かけて前の区間から移る。移り終えた時刻が区切りの時刻になる——前の区間はそこまで
  見え、入ってくる区間は `seconds` 秒早く始まる。書かなければ切り替え
- 曲の終わりに届かない並び、尺の足りない区間は**全部並べて断る**。黙って伸ばさない

フレーム f の絵はフレーム番号だけで決まる ∴ 分割書き出しでも同じ絵になる。
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import video
from .lyrics import Song

#: 区間に書けるもの
IMAGE_KEYS = ("image", "until", "in")
VIDEO_KEYS = ("video", "in")
#: `in` に書けるもの
IN_KEYS = ("transition", "seconds")


@dataclass(frozen=True)
class Segment:
    """並びの1区間。`path` は絶対パス。"""

    kind: str                       # "image" / "video"
    path: str
    until: str | float | None = None
    transition: str = "fade"
    seconds: float = 0.0


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


def _notes_dropped(doc: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _in_problems(at: str, doc: Any) -> list[str]:
    if not isinstance(doc, Mapping):
        return ['%s.in は {"transition": 切り替え, "seconds": 秒}' % at]
    doc = _notes_dropped(doc)
    bad = ["%s.in の知らない項目: %s" % (at, k) for k in sorted(set(doc) - set(IN_KEYS))]
    if not (_number(doc.get("seconds")) and doc["seconds"] > 0):
        bad.append("%s.in.seconds は 0 より大きい秒数" % at)
    if doc.get("transition", "fade") not in video.TRANSITIONS:
        bad.append("%s.in.transition=%r は知らない切り替え" % (at, doc.get("transition")))
    return bad


def _segment_problems(i: int, doc: Any, root: Path) -> list[str]:
    at = "reel[%d]" % i
    if not isinstance(doc, Mapping) or len({"image", "video"} & set(doc)) != 1:
        return ['%s は {"image": 画像, "until": ...} か {"video": 動画}' % at]
    doc = _notes_dropped(doc)
    kind = "image" if "image" in doc else "video"
    keys = IMAGE_KEYS if kind == "image" else VIDEO_KEYS
    bad = ["%s の知らない項目: %s" % (at, k) for k in sorted(set(doc) - set(keys))]
    if not isinstance(doc[kind], str) or not (root / doc[kind]).is_file():
        bad.append("%s の%sが無い: %s" % (at, "画像" if kind == "image" else "動画", doc[kind]))
    until = doc.get("until")
    if until is not None and not isinstance(until, str) and not (_number(until) and until > 0):
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
    rest = [i for i, s in enumerate(segs) if s.kind == "image" and s.until is None]
    if len(rest) > 1:
        bad.append("reel: until の無い画像（残り全部）は1つだけ: %s" % rest)
    if rest and any(s.kind != "video" for s in segs[rest[0] + 1:]):
        bad.append("reel: 残り全部の画像より後ろは mp4 だけ（尺で曲の終わりから置く）")
    return bad


def from_list(doc: Sequence[Mapping[str, Any]], root: Path) -> tuple[Segment, ...]:
    out = []
    for d in doc:
        d = _notes_dropped(d)
        kind = "image" if "image" in d else "video"
        cfg = _notes_dropped(d.get("in", {}))
        out.append(Segment(kind, str((root / d[kind]).resolve()), d.get("until"),
                           cfg.get("transition", "fade"), float(cfg.get("seconds", 0.0))))
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
    if seg.kind == "video":
        return f0 + length(seg.path)
    if isinstance(seg.until, str):
        end = _section_end(song, seg.until, f0, fps, song_f)
        return "until=%r のセクションがこの区間の後に無い" % seg.until if end is None else end
    return int(round(float(seg.until) * fps))


def _backward(tail: Sequence[Segment], song_f: int, fps: int,
              length: Callable[[str], int]) -> list[tuple[int, int]]:
    """残り全部の画像より後ろの mp4 を、曲の終わりから逆に置く → [(f0, f1)]。"""
    out, end = [], song_f
    for seg in reversed(tail):
        f0 = end - length(seg.path)
        out.append((f0, end))
        end = f0 + int(round(seg.seconds * fps))
    return out[::-1]


def place(segs: Sequence[Segment], song: Song, song_f: int, fps: int,
          length: Callable[[str], int] = None) -> list[Span]:
    """区間を時間に置く。曲の終わり `song_f` に届かない・尺の足りない区間は全部並べて断る。"""
    length = length or (lambda p: video.frames_of(p, fps))
    rest = next((i for i, s in enumerate(segs) if s.kind == "image" and s.until is None), None)
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


# ------------------------------------------------------------- 書く
def record(spans: Sequence[Span], frames: int, fps: int,
           size: tuple[int, int]) -> dict[str, Any]:
    """作り直すかを決める記録。ファイルは中身のハッシュで持つ。"""
    digest = {s.seg.path: hashlib.sha256(Path(s.seg.path).read_bytes()).hexdigest()
              for s in spans}
    return {"spans": [[s.seg.kind, s.seg.path, digest[s.seg.path], s.f0, s.frames, s.overlap,
                       s.seg.transition] for s in spans],
            "frames": frames, "fps": fps, "size": list(size), "crf": video.CRF}


def write(dst: str, spans: Sequence[Span], frames: int, fps: int,
          size: tuple[int, int]) -> str:
    """背景の動画を書く。最後の区間は `frames`（曲の尺＋余白）まで伸ばす
    （画像はそのまま、mp4 は最後のフレームで止める）。"""
    lengths = [s.frames for s in spans]
    lengths[-1] = frames - spans[-1].f0
    sources = [video.source(s.seg.path, s.seg.kind == "image", fps, n, size)
               for s, n in zip(spans, lengths)]
    return video.chain(sources, lengths, [s.overlap for s in spans],
                       [s.seg.transition for s in spans], fps, dst)
