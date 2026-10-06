"""公開版と同じ三段（Opening / 静止画に波形 / Closing）で1本を組み立てる。

    Opening   素のクリップ。fps を揃えて尺ぶんのフレームに切る
    本編      cymatics で描く。感情で動かすのはここだけ
    Closing   素のクリップ

本編は区間に分けて並列で描き、Opening・Closing とつないでから音を乗せ直す。
クリップの尺は「fps に揃えたときのフレーム数」で数える（10.005秒 → 300）。

**出力の隣に再現の記録（`<出力>.plan.json`）を置く。** cymatics の Plan と同じ
考え方で、実際に使った Spec・Policy・切れ目・区間と、入力ファイルのハッシュが
入る。∴ 「この動画はどの採点とどの重みで作ったか」が後から追える。
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from importlib.metadata import version
from typing import Any

from cymatics import effects
from cymatics.dsp import audio

from . import drive, video
from .policy import Policy
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


def cut(audio_path: str, fps: int, opening: str | None, closing: str | None) -> Cut:
    total = int(audio.duration(audio_path) * fps)
    head = video.frames_of(opening, fps) if opening else 0
    tail = video.frames_of(closing, fps) if closing else 0
    if head + tail >= total:
        raise ValueError("Opening と Closing だけで曲の尺を超える")
    return Cut(fps, total, head, total - tail)


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def record(spec: Mapping[str, Any], pol: Policy, c: Cut, chunks: list[drive.Chunk],
           sources: Mapping[str, str | None], mood: bool) -> dict[str, Any]:
    """再現の記録。JSON にそのまま落ちる形。"""
    return {
        "versions": {p: version(p) for p in ("emotion_effecter", "cymatics", "typesafe-sdk")},
        "sources": {k: {"path": v, "sha256": sha256(v)} for k, v in sources.items() if v},
        "mood": mood,
        "policy": pol.to_dict(),
        "spec": {k: v for k, v in spec.items() if k not in ("out", "preview")},
        "cut": asdict(c),
        "chunks": [{"f0": ch.f0, "frames": ch.frames} for ch in chunks],
    }


def _assemble(parts: list[str], c: Cut, opening: str | None, closing: str | None,
              tmp: str) -> str:
    """Opening + 本編の区間 + Closing を音なしの1本にする。"""
    if opening:
        parts = [video.conform(opening, os.path.join(tmp, "opening.mp4"), c.fps, c.body0),
                 *parts]
    if closing:
        parts = [*parts, video.conform(closing, os.path.join(tmp, "closing.mp4"),
                                       c.fps, c.total - c.body1)]
    return video.concat(parts, os.path.join(tmp, "video.mp4"))


def produce(effect: str, params: Mapping[str, Any], tl: Timeline | None, out: str, *,
            opening: str | None = None, closing: str | None = None,
            pol: Policy = Policy(), jobs: int = 0, chunk_seconds: int = CHUNK_SECONDS,
            sources: Mapping[str, str | None] | None = None) -> dict[str, Any]:
    """三段の1本を out に書き、隣に再現の記録を置く。戻り値はその記録。"""
    pol.check()
    spec = effects.get(effect).spec_from(**{**params, "out": out})
    c = cut(spec["audio"], int(spec["fps"]), opening, closing)
    size = chunk_seconds * c.fps if drive.chunk_safe(effect) else c.body1 - c.body0
    with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(out))) as tmp:
        chunks = drive.plan_chunks(c.body0, c.body1, size, tmp)
        parts = drive.render_chunks(effect, spec, tl, chunks, pol, jobs)
        silent = _assemble(parts, c, opening, closing, tmp)
        video.mux(silent, spec["audio"], out, c.total / c.fps)
    src = {"audio": spec["audio"], "image": spec["image"], "opening": opening,
           "closing": closing, **(sources or {})}
    rec = record(spec, pol, c, chunks, src, tl is not None)
    with open(out + ".plan.json", "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=2)
    return rec
