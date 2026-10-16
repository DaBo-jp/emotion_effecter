"""ライブ動画1本 → 盛り上がりに合わせてエフェクトを重ねた1本。入力は `<入力>/live.json`。

    audio    動画の音 → audio.wav。書き出しの音と拍の推定に使う
    score    小節で区切り（`windows`）、区切りごとに中ほどと前後の3枚を動画から
             取って、場面の盛り上がり（`hype`）を Jev で採点 → hype.json。
             **あれば作り直さない**（呼び出しは有料）
    live     live.mp4（毎回書き出す）。背景はライブ動画そのもの（cymatics の動画背景）で、
             エフェクトの強さ・色・重ねた層の動きが盛り上がりの曲線で変わる
    compare  compare.mp4（上：元の動画 / 下：live.mp4）

`redo` に工程の名前を入れると、出力があってもやり直す。拍（`window.bpm`）や
小節数を変えたら区切りが変わるので `score` をやり直す——古い hype.json は
区切りの名前が合わないので読まずに断る。
"""
from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from cymatics import effects
from cymatics.dsp import audio

from . import audience, production, timeline, video, windows
from .beats import analyze
from .livefile import Live
from .lyrics import Song

STEPS = ("audio", "score", "live", "compare")
REDO = ("audio", "score")

Say = Callable[[str], None]

NAMES: Mapping[str, str] = MappingProxyType({
    "audio": "audio.wav", "hype": "hype.json", "live": "live.mp4",
    "compare": "compare.mp4",
})


@dataclass(frozen=True)
class Outputs:
    root: Path

    def __getitem__(self, role: str) -> str:
        return str(self.root / NAMES[role])


def _fresh(path: str, step: str, redo: Iterable[str]) -> bool:
    return step in redo or not Path(path).exists()


def sound(lv: Live, o: Outputs, redo: Iterable[str], say: Say) -> str:
    """動画の音。cymatics には動画ではなくこの WAV を音として渡す。"""
    if _fresh(o["audio"], "audio", redo):
        video.extract_audio(lv.video, o["audio"])
        say("audio: %s" % o["audio"])
    return o["audio"]


def framing(lv: Live, wav: str, say: Say) -> Song:
    """拍から決めた区切りを、セクションにした歌詞の無い曲として。"""
    bpm = lv.bpm or analyze(wav).bpm
    song = windows.song(lv.title, audio.duration(wav), bpm, lv.bars)
    say("window: %.1f BPM × %d 小節 → %d 区切り%s" % (
        bpm, lv.bars, len(song.sections), "" if lv.bpm else "（推定。ずれたら window.bpm）"))
    return song


def cheers(lv: Live, o: Outputs, song: Song, redo: Iterable[str],
           say: Say) -> list[audience.Cheer]:
    """区切りごとの盛り上がり。動画と音は同じ1本なので時刻合わせは要らない。"""
    if _fresh(o["hype"], "score", redo):
        shots = audience.plan(song, audio.duration(o["audio"]), 0.0,
                              video.probe_duration(lv.video), lv.spread)
        with tempfile.TemporaryDirectory() as tmp:
            scored = audience.score(shots, audience.stills(lv.video, shots, tmp),
                                    audience.SCENE)
        audience.save(o["hype"], lv.title, {"lead": 0.0, "strength": 0.0}, scored)
        say("score: %s" % o["hype"])
    return audience.load(o["hype"])


def fps_of(lv: Live, wav: str) -> int:
    s = effects.get(lv.effect).spec_from(**{**lv.params, "audio": wav,
                                            "image": lv.video, "out": "-"})
    return int(s["fps"])


def build_timeline(lv: Live, song: Song, wav: str, cs: list[audience.Cheer],
                   xfade: float = 2.0) -> timeline.Timeline:
    return timeline.build(song, [], audio.duration(wav), fps_of(lv, wav), xfade, cs)


def render(lv: Live, o: Outputs, tl: timeline.Timeline, jobs: int) -> dict:
    """背景はライブ動画、音は抜き出した WAV。隣に再現の記録を置く。"""
    params = {**lv.params, "audio": o["audio"], "image": lv.video}
    sources = {"video": lv.video, "hype": o["hype"],
               "live": str(lv.root / "live.json")}
    return production.produce(lv.effect, params, tl, o["live"], pol=lv.policy, jobs=jobs,
                              sources=sources, overlays=lv.overlays)


def compare(lv: Live, o: Outputs, say: Say) -> None:
    width = int(json.loads(Path(o["live"] + ".plan.json").read_text())["spec"]["width"])
    video.stack(lv.video, o["live"], o["compare"], labels=("LIVE", "EFFECT (Jev hype)"),
                fit=width)
    say("compare: %s" % o["compare"])


def run(lv: Live, out_dir: str | Path, *, steps: Iterable[str] = STEPS,
        redo: Iterable[str] = (), jobs: int = 0, say: Say = print) -> Outputs:
    o = Outputs(Path(out_dir))
    o.root.mkdir(parents=True, exist_ok=True)
    steps, redo = set(steps), set(redo)
    wav = sound(lv, o, redo, say)
    song = framing(lv, wav, say)
    cs = cheers(lv, o, song, redo, say) if steps & {"score", "live"} else None
    if "live" in steps:
        render(lv, o, build_timeline(lv, song, wav, cs), jobs)
        say("live: %s" % o["live"])
    if "compare" in steps:
        compare(lv, o, say)
    return o
