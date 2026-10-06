"""コマンドの入口。

    song      1曲を最初から最後まで（入力 music_data/<曲>/ → 出力 out/<曲>/）
    suggest   歌詞の属性（水地風金火明暗）と BPM → effect の候補
    score     歌詞 → セクションごとの感情（Jev）
    sections  歌詞 + 音源 → 各セクションの開始時刻を歌詞に書き込む
    render    1回の書き出し（--preview で1枚）
    produce   公開版と同じ三段（Opening / 本編 / Closing）の1本。本編は並列
    compare   2本を上下に並べた1本

入口でやるのは引数の解釈と、下の層の呼び出しだけ。値の検証は下の層の宣言から
出る（Spec は cymatics の Field、Policy は `policy.RANGES`）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import lyrics, mood, policy, structure, timeline, video
from .beats import analyze


# ----------------------------------------------------------------- 各コマンド
def _mood_table(moods: list[mood.Mood]) -> str:
    rows = ["%-14s " % "section" + " ".join("%9s" % c for c in mood.DIMS) + "  emotion"]
    for m in moods:
        cells = " ".join("%5.2f(%2d)" % (m.scores[c], round(100 * m.confidence[c]))
                         for c in mood.DIMS)
        rows.append("%-14s %s  %s %.2f" % (m.section, cells, m.emotion,
                                           m.distributions["emotion"][m.emotion]))
    return "\n".join(rows + ["", "値は 0..1 の期待値、括弧内は confidence(%)"])


def cmd_score(a: argparse.Namespace) -> None:
    song = lyrics.load(a.lyrics)
    moods = mood.score(song)
    print(_mood_table(moods))
    mood.save(a.out, song, moods)
    print("saved:", a.out)


def cmd_sections(a: argparse.Namespace) -> None:
    song = lyrics.load(a.lyrics)
    beats = analyze(a.audio)
    bounds = structure.estimate(song, beats)
    print("%.1f BPM / %.1f 秒" % (beats.bpm, beats.duration))
    for b in bounds:
        print("%-22s %8s  margin %5.2f%s" % (b.section, lyrics.fmt_time(b.start), b.margin,
                                             "  ← 要確認" if b.doubtful else ""))
    text = Path(a.lyrics).read_text(encoding="utf-8")
    Path(a.out).write_text(lyrics.stamp(text, [b.start for b in bounds]), encoding="utf-8")
    print("saved:", a.out)


def _policy(a: argparse.Namespace) -> policy.Policy:
    if not a.policy:
        return policy.Policy()
    return policy.from_mapping(json.loads(Path(a.policy).read_text(encoding="utf-8")))


def _base(a: argparse.Namespace) -> tuple[str, dict]:
    """土台の (effect, 引数)。cymatics の preset か、`--spec` の JSON。"""
    from . import manifest

    if a.preset:
        return manifest.base_of({"preset": a.preset})
    return manifest.base_of(json.loads(Path(a.spec).read_text(encoding="utf-8")))


def _setup(a: argparse.Namespace):
    """(effect, params, timeline, policy)。`--no-mood` なら timeline は None。"""
    from cymatics import effects
    from cymatics.dsp import audio

    effect, params = _base(a)
    params.update(audio=a.audio, image=a.image)
    pol = _policy(a)
    if a.no_mood:
        return effect, params, None, pol
    fps = int(effects.get(effect).spec_from(**params, out=a.out)["fps"])
    tl = timeline.build(lyrics.load(a.lyrics), mood.load(a.mood),
                        audio.duration(a.audio), fps, a.xfade)
    return effect, params, tl, pol


def cmd_render(a: argparse.Namespace) -> None:
    from . import drive

    effect, params, tl, pol = _setup(a)
    params["out"] = a.out
    if a.preview:
        params.update(preview=a.preview, preview_at=a.preview_at)
    drive.render(effect, params, tl, pol)


def cmd_produce(a: argparse.Namespace) -> None:
    from . import production

    effect, params, tl, pol = _setup(a)
    rec = production.produce(effect, params, tl, a.out, opening=a.opening, closing=a.closing,
                             pol=pol, jobs=a.jobs,
                             sources={"lyrics": a.lyrics, "mood": a.mood, "policy": a.policy})
    c = rec["cut"]
    print("done: %s（%d フレーム / 本編 %d-%d）" % (a.out, c["total"], c["body0"], c["body1"]))
    print("plan: %s.plan.json" % a.out)


def cmd_compare(a: argparse.Namespace) -> None:
    video.stack(a.top, a.bottom, a.out, labels=(a.top_label, a.bottom_label))
    print("done:", a.out)


def cmd_song(a: argparse.Namespace) -> None:
    from . import manifest, workflow

    m = manifest.load(a.dir)
    out = a.out or str(Path("out") / Path(a.dir).resolve().name)
    if a.previews:
        o = workflow.Outputs(Path(out))
        o.root.mkdir(parents=True, exist_ok=True)
        moods = workflow.score(m, o, a.redo, print)
        workflow.previews(m, o, workflow.sections(m, o, a.redo, print), moods, print)
        return
    workflow.run(m, out, steps=a.steps, redo=a.redo, jobs=a.jobs)


def cmd_suggest(a: argparse.Namespace) -> None:
    from . import manifest, workflow

    for d in a.dirs:
        m = manifest.load(d)
        o = workflow.Outputs(Path(a.out or "out") / Path(d).resolve().name)
        o.root.mkdir(parents=True, exist_ok=True)
        ranked = workflow.suggest(m, o, a.redo, print)
        print("  %s: %s" % (m.title, "  ".join(
            "%s%s %.2f" % (s.name, "*" if s.cast.effect == m.effect else "", s.score)
            for s in ranked[:a.top])))


# ----------------------------------------------------------------- 引数
def _add_song(sub) -> None:
    from .workflow import STEPS

    p = sub.add_parser("song", help="1曲を最初から最後まで（song.json のあるディレクトリ）")
    p.add_argument("dir", help="入力ディレクトリ（song.json がある）")
    p.add_argument("--out", help="出力ディレクトリ。既定は out/<入力ディレクトリ名>")
    p.add_argument("--steps", nargs="+", choices=STEPS, default=list(STEPS))
    p.add_argument("--redo", nargs="+", choices=STEPS, default=[],
                   help="出力があってもやり直す工程")
    p.add_argument("--jobs", type=int, default=0)
    p.add_argument("--previews", action="store_true",
                   help="動画は作らず、セクションごとの「感情なし｜感情あり」を1枚に")
    p.set_defaults(fn=cmd_song)


def _add_suggest(sub) -> None:
    p = sub.add_parser("suggest", help="歌詞の属性（水地風金火明暗）と BPM → effect の候補")
    p.add_argument("dirs", nargs="+", help="入力ディレクトリ（song.json がある）")
    p.add_argument("--out", help="出力の親ディレクトリ。既定は out（その下に曲名）")
    p.add_argument("--redo", action="store_true", help="属性を Jev で採点し直す")
    p.add_argument("--top", type=int, default=3, help="画面に出す候補の数")
    p.set_defaults(fn=cmd_suggest)


def _add_score(sub) -> None:
    p = sub.add_parser("score", help="歌詞のセクションごとの感情を Jev で採点する")
    p.add_argument("lyrics")
    p.add_argument("--out", required=True, help="採点の保存先（JSON）")
    p.set_defaults(fn=cmd_score)


def _add_sections(sub) -> None:
    p = sub.add_parser("sections", help="音源から各セクションの開始時刻を推定する")
    p.add_argument("lyrics")
    p.add_argument("audio")
    p.add_argument("--out", required=True, help="時刻を書き込んだ歌詞の保存先")
    p.set_defaults(fn=cmd_sections)


def _drive_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("lyrics", help="開始時刻つきの歌詞（sections の出力）")
    p.add_argument("audio")
    p.add_argument("--mood", help="score の出力（--no-mood なら不要）")
    base = p.add_mutually_exclusive_group(required=True)
    base.add_argument("--preset", help="土台にする cymatics の preset")
    base.add_argument("--spec", help='土台の JSON {"effect": ..., "params": {...}}')
    p.add_argument("--image", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--policy", help="写像の上書き（JSON）。項目は policy.Policy")
    p.add_argument("--xfade", type=float, default=2.0, help="セクション間の移り変わり（秒）")
    p.add_argument("--no-mood", action="store_true", help="感情なし（素の cymatics と同じ）")


def _add_render(sub) -> None:
    p = sub.add_parser("render", help="1回の書き出し（--preview で1枚）")
    _drive_args(p)
    p.add_argument("--preview", help="1枚だけ PNG に出す")
    p.add_argument("--preview-at", type=float, default=60.0)
    p.set_defaults(fn=cmd_render)


def _add_produce(sub) -> None:
    p = sub.add_parser("produce", help="Opening / 本編 / Closing の1本（本編は並列）")
    _drive_args(p)
    p.add_argument("--opening", help="前に付けるクリップ")
    p.add_argument("--closing", help="後ろに付けるクリップ")
    p.add_argument("--jobs", type=int, default=0, help="並列数。0=区間の数と CPU の少ない方")
    p.set_defaults(fn=cmd_produce)


def _add_compare(sub) -> None:
    p = sub.add_parser("compare", help="2本を上下に並べる（音は上から）")
    p.add_argument("top")
    p.add_argument("bottom")
    p.add_argument("--out", required=True)
    p.add_argument("--top-label", default="PUBLISHED")
    p.add_argument("--bottom-label", default="EMOTION (Jev)")
    p.set_defaults(fn=cmd_compare)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="emotion-effecter", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for add in (_add_song, _add_suggest, _add_score, _add_sections, _add_render, _add_produce,
                _add_compare):
        add(sub)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = parser()
    a = ap.parse_args(argv)
    if hasattr(a, "no_mood") and not a.no_mood and not a.mood:
        ap.error("--mood が要る（感情なしなら --no-mood）")
    try:
        a.fn(a)
    except ValueError as e:              # 入力の問題は usage と同じく 2 で終える
        print(e)
        return 2
    return 0
