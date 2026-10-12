"""1曲を最初から最後まで回す。入力は `music_data/<曲>/`、出力は `out/<曲>/`。

    score     歌詞 → mood.json（Jev）。**あれば作り直さない**（呼び出しは有料）
    sections  音源 → lyrics.timed.md。あれば作り直さない。歌詞に時刻を手で
              書いてあれば推定しない（手書きが勝つ）
    emotion   emotion.mp4（三段、感情あり）
    base      base.mp4（三段、感情なし）。**公開版の動画が無い曲だけ**——
              ある曲は公開版そのものを比べる。`sections`（流れの向き）は
              感情ではなく振り付けなので base にも入れる ∴ compare の上下の
              違いは Jev の感情だけになる
    compare   compare.mp4（上：公開版 or base / 下：emotion）

song.json に `tempo` がある曲は、気持ちの速さ（Jev）も聞いて pace.json に残す
（あれば作り直さない。`redo` に `pace`）。拍と気持ちから出した流れ・踊りの速さは
**emotion にだけ効く**——Jev の判断なので、base は song.json の速さのまま。

`suggest`（effect の提案）は書き出しとは別に回す。属性（Jev）は elements.json に
残し、あれば作り直さない。

`redo` に工程の名前を入れると、出力があってもやり直す。
"""
from __future__ import annotations

import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from cymatics import effects
from cymatics.dsp import audio

from . import (
    casting,
    drive,
    elements,
    lyrics,
    mood,
    pace,
    policy,
    production,
    scenes,
    structure,
    tempo,
    timeline,
    video,
)
from .beats import analyze
from .manifest import Manifest

STEPS = ("score", "sections", "emotion", "base", "compare")

#: `redo` に入れられるもの。気持ちの速さ（`pace`）は `tempo` のある曲だけが聞く
REDO = STEPS + ("pace",)

Say = Callable[[str], None]


#: 出力の役割 → ファイル名（`out/<曲>/` の中）
NAMES: Mapping[str, str] = MappingProxyType({
    "mood": "mood.json", "timed": "lyrics.timed.md", "emotion": "emotion.mp4",
    "base": "base.mp4", "compare": "compare.mp4", "previews": "previews.png",
    "elements": "elements.json", "suggest": "suggest.md", "pace": "pace.json",
})


@dataclass(frozen=True)
class Outputs:
    root: Path

    def __getitem__(self, role: str) -> str:
        return str(self.root / NAMES[role])


def _fresh(path: str, step: str, redo: Iterable[str]) -> bool:
    """作り直すか。出力が無いか、`redo` に入っていれば作る。"""
    return step in redo or not Path(path).exists()


def score(m: Manifest, o: Outputs, redo: Iterable[str], say: Say) -> list[mood.Mood]:
    if _fresh(o["mood"], "score", redo):
        song = lyrics.load(m.file("lyrics"))
        mood.save(o["mood"], song, mood.score(song))
        say("score: %s" % o["mood"])
    return mood.load(o["mood"])


def paces(m: Manifest, o: Outputs, redo: Iterable[str], say: Say) -> list[pace.Pace]:
    if _fresh(o["pace"], "pace", redo):
        song = lyrics.load(m.file("lyrics"))
        pace.save(o["pace"], song, pace.score(song))
        say("pace: %s" % o["pace"])
    return pace.load(o["pace"])


def song_elements(m: Manifest, o: Outputs, redo: bool, say: Say) -> elements.Elements:
    if redo or not Path(o["elements"]).exists():
        song = lyrics.load(m.file("lyrics"))
        elements.save(o["elements"], song, elements.score(song))
        say("elements: %s" % o["elements"])
    return elements.load(o["elements"])


def suggest(m: Manifest, o: Outputs, redo: bool, say: Say) -> list[casting.Suggestion]:
    """属性（Jev）と BPM → effect の候補を suggest.md に。"""
    el = song_elements(m, o, redo, say)
    bpm = analyze(m.file("audio")).bpm
    ranked = casting.rank(el.scores, bpm)
    Path(o["suggest"]).write_text(casting.report(m.title, el.scores, el.confidence, bpm,
                                                 ranked, (m.effect, m.params)), encoding="utf-8")
    say("suggest: %s" % o["suggest"])
    return ranked


def sections(m: Manifest, o: Outputs, redo: Iterable[str], say: Say) -> lyrics.Song:
    song = lyrics.load(m.file("lyrics"))
    if song.timed:
        say("sections: 歌詞に時刻が書いてあるのでそれを使う")
        return song
    if _fresh(o["timed"], "sections", redo):
        bounds = structure.estimate(song, analyze(m.file("audio")))
        text = Path(m.file("lyrics")).read_text(encoding="utf-8")
        Path(o["timed"]).write_text(lyrics.stamp(text, [b.start for b in bounds]),
                                 encoding="utf-8")
        doubt = [b.section for b in bounds if b.doubtful]
        say("sections: %s%s" % (o["timed"], "（要確認: %s）" % ", ".join(doubt) if doubt else ""))
    return lyrics.load(o["timed"])


def fps_of(m: Manifest) -> int:
    s = effects.get(m.effect).spec_from(**{**m.params, "audio": m.file("audio"),
                                           "image": m.file("image"), "out": "-"})
    return int(s["fps"])


def build_timeline(m: Manifest, song: lyrics.Song, moods: list[mood.Mood],
                   xfade: float = 2.0) -> timeline.Timeline:
    return timeline.build(song, moods, audio.duration(m.file("audio")), fps_of(m), xfade)


def build_scenes(m: Manifest, song: lyrics.Song, xfade: float = 2.0,
                 extra: list[dict] | None = None) -> scenes.Scenes:
    """song.json の `sections` → セクションごとに変える引数。境界は感情と同じ秒数で移る。"""
    return scenes.build(song, m.sections, m.effect, fps_of(m), xfade, extra)


def tempo_extra(m: Manifest, song: lyrics.Song, moods: list[mood.Mood],
                ps: list[pace.Pace], say: Say) -> list[dict]:
    """拍と気持ちから出した、セクションごとの流れ・踊りの速さ（`tempo`）。"""
    bpm = m.tempo.bpm or analyze(m.file("audio")).bpm
    fields = {f.name: f for f in effects.get(m.effect).fields}
    base = fields["speed"].coerce(m.params.get("speed", fields["speed"].default))
    marks = timeline.anchors(song, moods, ps)
    extra = tempo.overrides(marks, bpm, m.tempo, fields, base)
    names = [None if s.instrumental else s.name for s in song.sections]
    say("tempo: %.1f BPM → %s" % (bpm, tempo.summary(names, extra, bpm, m.tempo)))
    return extra


def emotion_scenes(m: Manifest, o: Outputs, song: lyrics.Song, moods: list[mood.Mood],
                   redo: Iterable[str], say: Say) -> scenes.Scenes:
    """emotion 版の `Scenes`。`tempo` が無ければ base と同じ。"""
    if m.tempo is None:
        return build_scenes(m, song)
    extra = tempo_extra(m, song, moods, paces(m, o, redo, say), say)
    return build_scenes(m, song, extra=extra)


def produce(m: Manifest, out: str, tl: timeline.Timeline | None, o: Outputs,
            jobs: int = 0, sc: scenes.Scenes | None = None) -> None:
    params = {**m.params, "audio": m.file("audio"), "image": m.file("image")}
    sources = {"lyrics": m.file("lyrics"), "mood": o["mood"] if tl else None,
               "manifest": str(m.root / "song.json")}
    production.produce(m.effect, params, tl, out, opening=m.file("opening"),
                       closing=m.file("closing"), pol=policy.from_mapping(m.policy),
                       jobs=jobs, sources=sources, scenes=sc)


def compare(m: Manifest, o: Outputs, say: Say) -> None:
    top = m.file("published") or o["base"]
    label = "PUBLISHED" if m.file("published") else "BASE (no mood)"
    video.stack(top, o["emotion"], o["compare"], labels=(label, "EMOTION (Jev)"))
    say("compare: %s" % o["compare"])


def _shot(m: Manifest, tl: timeline.Timeline | None, t: float, png: str,
          sc: scenes.Scenes | None = None) -> str:
    params = {**m.params, "audio": m.file("audio"), "image": m.file("image"),
              "out": png + ".mp4", "preview": png, "preview_at": t}
    drive.render(m.effect, params, tl, policy.from_mapping(m.policy), sc)
    return png


def previews(m: Manifest, o: Outputs, song: lyrics.Song, moods: list[mood.Mood],
             say: Say, redo: Iterable[str] = ()) -> str:
    """歌詞セクションの中ほどで「感情なし｜感情あり」を並べた1枚。

    どちらも `sections` の流れで描く ∴ 左右の違いは感情（と `tempo` の速さ）だけ。
    """
    tl, sc = build_timeline(m, song, moods), build_scenes(m, song)
    sc_mood = emotion_scenes(m, o, song, moods, redo, say)
    ends = [s.start for s in song.sections[1:]] + [audio.duration(m.file("audio"))]
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (sec, end) in enumerate(zip(song.sections, ends)):
            if sec.instrumental:
                continue
            t = (sec.start + end) / 2
            v = tl.frame(int(t * tl.fps))
            label = "%s  %s  %s" % (sec.name.split(" - ")[0], lyrics.fmt_time(t), "  ".join(
                "%s %.2f" % (d[:3], v[d]) for d in mood.DIMS))
            pair = [_shot(m, x, t, "%s/%d_%s.png" % (tmp, i, k), y)
                    for k, x, y in (("base", None, sc), ("mood", tl, sc_mood))]
            rows.append((label, pair))
        video.sheet(rows, o["previews"])
    say("previews: %s" % o["previews"])
    return o["previews"]


def run(m: Manifest, out_dir: str | Path, *, steps: Iterable[str] = STEPS,
        redo: Iterable[str] = (), jobs: int = 0, say: Say = print) -> Outputs:
    o = Outputs(Path(out_dir))
    o.root.mkdir(parents=True, exist_ok=True)
    steps, redo = set(steps), set(redo)
    moods, song = score(m, o, redo, say), sections(m, o, redo, say)
    sc = build_scenes(m, song)
    if "emotion" in steps:
        produce(m, o["emotion"], build_timeline(m, song, moods), o, jobs,
                emotion_scenes(m, o, song, moods, redo, say))
        say("emotion: %s" % o["emotion"])
    if "base" in steps and not m.file("published") and _fresh(o["base"], "base", redo):
        produce(m, o["base"], None, o, jobs, sc)
        say("base: %s" % o["base"])
    if "compare" in steps:
        compare(m, o, say)
    return o
