"""公開版と同じ三段（Opening / 静止画に波形 / Closing）で1本を組み立てる。

    Opening   素のクリップ。fps を揃えて尺ぶんのフレームに切る
    本編      cymatics で描く。感情で動かすのはここだけ
    Closing   素のクリップ

本編は区間に分けて並列で描き、Opening・Closing とつないでから音を乗せ直す。
クリップの尺は「fps に揃えたときのフレーム数」で数える（10.005秒 → 300）。

`fade`（秒）を渡すと、つなぎ目をクロスフェードにする。**曲の尺も切れ目も変えない**——
Opening の最後の `fade` 秒に本編を重ねながら入り、Closing の最初の `fade` 秒で本編から
移る。重なるぶん本編を前後に余分に描く。0（既定）なら今までどおりの切り替え。
切り替え方は `transition`（`video.TRANSITIONS`。既定は重ねて入れ替える `fade`）。

`crt`（`crt.Crt`）を渡すと、つないだ1本の上にブラウン管の走査線と、上下へ流れる
明るい帯を重ねる（Opening / Closing にも）。

`black`（(開始秒, 秒数)）を渡すと、つないだ1本の頭を開始秒まで真っ黒にし、そこから
秒数で黒から入る（Opening の代わり）。`black_out`（秒数）は最後のその秒数で黒へ
落ちる。どちらも画面ぜんたい（絵・effect・歌詞、Closing も）にかかる。

**出力の隣に再現の記録（`<出力>.plan.json`）を置く。** cymatics の Plan と同じ
考え方で、実際に使った Spec・Policy・切れ目・区間と、入力ファイルのハッシュが
入る。∴ 「この動画はどの採点とどの重みで作ったか」が後から追える。
"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from importlib.metadata import version
from typing import Any

from cymatics import effects
from cymatics.dsp import audio

from . import crt as crt_mod
from . import digest, drive, video
from .overlay import Overlay
from .policy import Policy
from .scenes import Scenes
from .timeline import Timeline

#: 区間1つの長さ（秒）。fps を掛けて整数になる長さにする
CHUNK_SECONDS = 25


@dataclass(frozen=True)
class Cut:
    """三段の切れ目（フレーム）。本編は [body0, body1)。"""

    fps: int
    total: int
    body0: int
    body1: int
    #: つなぎ目で重ねるフレーム数。0 なら切り替え
    fade: int = 0

    def drawn(self) -> tuple[int, int]:
        """本編として描く範囲 [f0, f1)。重ねるぶんクリップの側へはみ出す。"""
        return (self.body0 - (self.fade if self.body0 else 0),
                self.body1 + (self.fade if self.body1 < self.total else 0))


def cut(audio_path: str, fps: int, opening: str | None, closing: str | None,
        fade: float = 0.0) -> Cut:
    total = int(audio.duration(audio_path) * fps)
    head = video.frames_of(opening, fps) if opening else 0
    tail = video.frames_of(closing, fps) if closing else 0
    if head + tail >= total:
        raise ValueError("Opening と Closing だけで曲の尺を超える")
    n = int(round(fade * fps))
    if n < 0 or (opening and n > head) or (closing and n > tail):
        raise ValueError("クロスフェード %.2f 秒が Opening / Closing より長い（か負）" % fade)
    return Cut(fps, total, head, total - tail, n)


def record(spec: Mapping[str, Any], pol: Policy, c: Cut, chunks: list[drive.Chunk],
           sources: Mapping[str, str | None], mood: bool,
           sc: Scenes | None = None, ovs: Sequence[Overlay] = ()) -> dict[str, Any]:
    """再現の記録。JSON にそのまま落ちる形。"""
    return {
        "versions": {p: version(p) for p in ("emotion_effecter", "cymatics", "typesafe-sdk")},
        "sources": {k: {"path": v, "sha256": digest.sha256(v)} for k, v in sources.items() if v},
        "mood": mood,
        "policy": pol.to_dict(),
        "scenes": sc.to_dict() if sc is not None else None,
        "overlays": [ov.to_dict() for ov in ovs],
        "spec": {k: v for k, v in spec.items() if k not in ("out", "preview")},
        "cut": asdict(c),
        "chunks": [{"f0": ch.f0, "frames": ch.frames} for ch in chunks],
    }


def _assemble(parts: list[str], c: Cut, opening: str | None, closing: str | None,
              tmp: str, transition: str = "fade", fin: video.Finish = video.Finish()) -> str:
    """Opening + 本編の区間 + Closing を音なしの1本にして、仕上げ `fin` をかける。

    **書き出しは1回だけ**（1080p の x264 medium は1フレーム約 50ms の CPU で、絵を描く
    のと同じくらい重い）。重ねるならつなぐときに仕上げも、重ねないならつないでから。
    """
    if c.fade:
        return _blended(parts, c, opening, closing, tmp, transition, fin)
    if opening:
        parts = [video.conform(opening, os.path.join(tmp, "opening.mp4"), c.fps, c.body0),
                 *parts]
    if closing:
        parts = [*parts, video.conform(closing, os.path.join(tmp, "closing.mp4"),
                                       c.fps, c.total - c.body1)]
    silent = video.concat(parts, os.path.join(tmp, "video.mp4"))
    if fin.empty():
        return silent
    return video.finish(silent, os.path.join(tmp, "finish.mp4"), c.total, c.fps,
                        fin.black_in, fin.black_out, fin.layers)


def _blended(parts: list[str], c: Cut, opening: str | None, closing: str | None,
             tmp: str, transition: str, fin: video.Finish) -> str:
    """つなぎ目を `c.fade` フレーム重ねて混ぜる。本編の区間は重なりのぶん長く描いてある。"""
    f0, f1 = c.drawn()
    clips = [(video.concat(parts, os.path.join(tmp, "body.mp4")), f1 - f0)]
    if opening:
        clips.insert(0, (video.conform(opening, os.path.join(tmp, "opening.mp4"), c.fps,
                                       c.body0), c.body0))
    if closing:
        clips.append((video.conform(closing, os.path.join(tmp, "closing.mp4"), c.fps,
                                    c.total - c.body1), c.total - c.body1))
    return video.crossfade([p for p, _ in clips], [n for _, n in clips], c.fade, c.fps,
                           os.path.join(tmp, "video.mp4"), transition, fin)


@dataclass(frozen=True)
class Order:
    """1本の書き出しの注文。**区間に分けても通しでも同じ注文を使う**（Cloud Run Jobs の
    各タスクが同じ注文から同じ区間を出せるように）。"""

    effect: str
    params: Mapping[str, Any]
    tl: Timeline | None = None
    opening: str | None = None
    closing: str | None = None
    pol: Policy = Policy()
    chunk_seconds: int = CHUNK_SECONDS
    sources: Mapping[str, str | None] | None = None
    scenes: Scenes | None = None
    overlays: Sequence[Overlay] = ()
    #: つなぎ目のクロスフェード（秒）とその切り替え方
    fade: float = 0.0
    transition: str = "fade"
    roll: drive.Lyrics | None = None
    #: 黒からの入り（開始秒, 秒数）と黒への落ち（秒数）
    black: tuple[float, float] | None = None
    black_out: float | None = None
    #: ブラウン管の走査線と明るい帯（画面ぜんたいに重ねる）
    crt: crt_mod.Crt | None = None

    def check(self) -> None:
        self.pol.check()
        if self.transition not in video.TRANSITIONS:
            raise ValueError("知らない切り替え: %s" % self.transition)


@dataclass(frozen=True)
class Plan:
    """注文から決まる書き出しの段取り。区間の動画は `workdir` に置く。"""

    spec: Mapping[str, Any]
    cut: Cut
    chunks: tuple[drive.Chunk, ...]


def plan(order: Order, out: str, workdir: str) -> Plan:
    """注文 → 段取り。同じ注文と同じ入力なら、どこで計算しても同じ区間になる。"""
    order.check()
    spec = effects.get(order.effect).spec_from(**{**order.params, "out": out})
    c = cut(spec["audio"], int(spec["fps"]), order.opening, order.closing, order.fade)
    f0, f1 = c.drawn()
    safe = drive.chunk_safe(order.effect, order.overlays)
    size = order.chunk_seconds * c.fps if safe else f1 - f0
    return Plan(spec, c, tuple(drive.plan_chunks(f0, f1, size, workdir)))


def draw(order: Order, p: Plan, which: Sequence[int], jobs: int = 0) -> list[str]:
    """段取りの区間のうち `which`（番号）だけを描く。戻り値は描いた区間の動画。"""
    chosen = [p.chunks[i] for i in which]
    if not chosen:
        return []
    return drive.render_chunks(order.effect, p.spec, order.tl, chosen, order.pol, jobs,
                               order.scenes, order.overlays, order.roll)


def finish(order: Order, p: Plan, parts: Sequence[str], out: str) -> dict[str, Any]:
    """描いた区間（順番どおり）をつなぎ、仕上げと音を乗せて out に書く。隣に再現の記録。"""
    spec, c = p.spec, p.cut
    with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(out))) as tmp:
        lays = crt_mod.layers(order.crt, (int(spec["width"]), int(spec["height"])), tmp) \
            if order.crt is not None else []
        silent = _assemble(list(parts), c, order.opening, order.closing, tmp,
                           order.transition,
                           video.Finish(order.black, order.black_out, tuple(lays)))
        video.mux(silent, spec["audio"], out, c.total / c.fps)
    rec = _recorded(order, p)
    with open(out + ".plan.json", "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=2)
    return rec


def _recorded(order: Order, p: Plan) -> dict[str, Any]:
    spec, c = p.spec, p.cut
    src = {"audio": spec["audio"], "image": spec["image"], "opening": order.opening,
           "closing": order.closing, **(order.sources or {})}
    rec = record(spec, order.pol, c, list(p.chunks), src, order.tl is not None, order.scenes,
                 order.overlays)
    rec["transition"] = order.transition if c.fade else None
    rec["credits"] = dict(order.roll.cfg) if order.roll is not None else None
    rec["black"] = {"in": list(order.black) if order.black is not None else None,
                    "out": order.black_out}
    rec["crt"] = order.crt.to_dict() if order.crt is not None else None
    return rec


def run(order: Order, out: str, jobs: int = 0) -> dict[str, Any]:
    """注文を通しで: 段取り → 全部の区間を並列に描く → つなぐ。戻り値は再現の記録。"""
    order.check()
    with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(out))) as tmp:
        p = plan(order, out, tmp)
        parts = draw(order, p, range(len(p.chunks)), jobs)
        return finish(order, p, parts, out)


def produce(effect: str, params: Mapping[str, Any], tl: Timeline | None, out: str, *,
            jobs: int = 0, **options: Any) -> dict[str, Any]:
    """三段の1本を out に書き、隣に再現の記録を置く。戻り値はその記録。
    `options` は `Order` の項目（opening / closing / pol / fade / transition / roll /
    black / black_out / crt / chunk_seconds / sources / scenes / overlays）。"""
    return run(Order(effect, params, tl, **options), out, jobs)
