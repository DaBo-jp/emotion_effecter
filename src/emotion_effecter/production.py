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


def produce(effect: str, params: Mapping[str, Any], tl: Timeline | None, out: str, *,
            opening: str | None = None, closing: str | None = None,
            pol: Policy = Policy(), jobs: int = 0, chunk_seconds: int = CHUNK_SECONDS,
            sources: Mapping[str, str | None] | None = None,
            scenes: Scenes | None = None,
            overlays: Sequence[Overlay] = (), fade: float = 0.0,
            transition: str = "fade", roll: drive.Lyrics | None = None,
            black: tuple[float, float] | None = None,
            black_out: float | None = None, crt: crt_mod.Crt | None = None) -> dict[str, Any]:
    """三段の1本を out に書き、隣に再現の記録を置く。戻り値はその記録。
    `fade` はつなぎ目のクロスフェード（秒）、`transition` はその切り替え方、
    `black` / `black_out` は黒からの入り（開始秒, 秒数）と黒への落ち（秒数）、
    `crt` はブラウン管の走査線と明るい帯（画面ぜんたいに重ねる）。"""
    pol.check()
    if transition not in video.TRANSITIONS:
        raise ValueError("知らない切り替え: %s" % transition)
    spec = effects.get(effect).spec_from(**{**params, "out": out})
    c = cut(spec["audio"], int(spec["fps"]), opening, closing, fade)
    f0, f1 = c.drawn()
    size = chunk_seconds * c.fps if drive.chunk_safe(effect, overlays) else f1 - f0
    with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(out))) as tmp:
        chunks = drive.plan_chunks(f0, f1, size, tmp)
        parts = drive.render_chunks(effect, spec, tl, chunks, pol, jobs, scenes, overlays, roll)
        lays = crt_mod.layers(crt, (int(spec["width"]), int(spec["height"])), tmp) \
            if crt is not None else []
        silent = _assemble(parts, c, opening, closing, tmp, transition,
                           video.Finish(black, black_out, tuple(lays)))
        video.mux(silent, spec["audio"], out, c.total / c.fps)
    src = {"audio": spec["audio"], "image": spec["image"], "opening": opening,
           "closing": closing, **(sources or {})}
    rec = record(spec, pol, c, chunks, src, tl is not None, scenes, overlays)
    rec["transition"] = transition if c.fade else None
    rec["credits"] = dict(roll.cfg) if roll is not None else None
    rec["black"] = {"in": list(black) if black is not None else None, "out": black_out}
    rec["crt"] = crt.to_dict() if crt is not None else None
    with open(out + ".plan.json", "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=2)
    return rec
