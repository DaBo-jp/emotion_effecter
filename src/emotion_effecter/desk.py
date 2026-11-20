"""手元の UI から呼ぶ操作。**HTTP も画面も知らない**——`ui` はこれを呼んで返すだけ。

- 曲の一覧と、出力の有無（`songs`）。素材の一覧（`materials`：曲のファイルと出力）
- song.json を読む・検証する・書く（`doc_of` / `check` / `save`）。書けるものの候補
  （preset・effect・切り替え・ファイル）は `choices` / `files_in`
- タイムライン（`timeline` / `suggest` / `save_timeline`）。波形の山・拍・セクションの
  開始時刻を返し、自動の推定（`structure`）を出し、決めた時刻を歌詞のタグに書き込む
- 書き出しの仕事（`Jobs`）。`emotion-effecter song` を子プロセスで回し、記録を
  `out/<曲>/ui-job.log` に残す。止められる

song.json が壊れていても開けるよう、タイムラインは manifest を通さず `files` だけ読む。
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from . import crt, lines, lyrics, manifest, roll, sing, structure, video
from .beats import analyze
from .doc import write
from .workflow import NAMES, REDO, STEPS

#: ファイルの種類 → 拡張子（song.json の `files` の候補に出す）
KINDS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "audio": (".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"),
    "image": (".jpg", ".jpeg", ".png", ".webp"),
    "video": (".mp4", ".mov", ".mkv", ".webm", ".gif"),
    "lyrics": (".md", ".txt"),
})

#: 波形の山の数（画面の幅より多ければ足りる）
PEAKS = 4000
#: 波形を読むときの標本化周波数（山を出すだけなので低くていい）
PEAK_SR = 8000
#: 書き出しの記録（`out/<曲>/` の中）
JOB_LOG = "ui-job.log"


# ------------------------------------------------------------- 曲
def _outputs(out: Path) -> dict[str, float]:
    """出力の役割 → 更新時刻（UNIX 秒）。無いものは入らない。"""
    have = {k: out / n for k, n in NAMES.items()}
    return {k: p.stat().st_mtime for k, p in have.items() if p.exists()}


def songs(data: Path, out: Path) -> list[dict[str, Any]]:
    """`data` の下の song.json のある曲。名前・題・問題の数・出力。"""
    rows = []
    for d in sorted(p for p in data.iterdir() if (p / "song.json").is_file()):
        try:
            doc = doc_of(d)
            title, bad = doc.get("title", d.name), check(d, doc)
        except (ValueError, OSError) as e:
            title, bad = d.name, [str(e)]
        rows.append({"name": d.name, "title": title, "problems": len(bad),
                     "outputs": _outputs(out / d.name)})
    return rows


def doc_of(song_dir: Path) -> dict[str, Any]:
    doc = json.loads((song_dir / "song.json").read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("song.json がオブジェクトでない")
    return doc


def check(song_dir: Path, doc: Any) -> list[str]:
    """song.json の駄目な理由を全部（`manifest.problems`）。"""
    if not isinstance(doc, Mapping):
        return ["song.json は {...}（オブジェクト）"]
    try:
        return manifest.problems(doc, song_dir)
    except (TypeError, AttributeError, KeyError) as e:   # 型の違う項目で検証ごと落ちる
        return ["検証できない書き方がある: %s" % e]


def save(song_dir: Path, doc: Mapping[str, Any]) -> list[str]:
    """書く。問題があっても書く（書きかけを残せるように）。戻り値は問題。"""
    write(song_dir / "song.json", doc)
    return check(song_dir, doc)


def files_in(song_dir: Path) -> dict[str, list[str]]:
    """種類 → 曲のディレクトリの中のファイル（song.json からの相対）。"""
    paths = sorted(p for p in song_dir.rglob("*") if p.is_file())
    return {k: [str(p.relative_to(song_dir)) for p in paths if p.suffix.lower() in exts]
            for k, exts in KINDS.items()}


#: 素材の一覧に出す、出力の拡張子（`out/<曲>/` の中）。種類は KINDS ＋ data
OUT_KINDS: Mapping[str, tuple[str, ...]] = MappingProxyType({**KINDS, "data": (".json",)})


def _kind(path: Path, kinds: Mapping[str, tuple[str, ...]]) -> str | None:
    return next((k for k, exts in kinds.items() if path.suffix.lower() in exts), None)


def _rows(base: Path, paths: Sequence[Path], kinds: Mapping[str, tuple[str, ...]],
          roles: Mapping[str, str], where: str) -> list[dict[str, Any]]:
    out = []
    for p in paths:
        kind, rel = _kind(p, kinds), str(p.relative_to(base))
        if kind is not None and p.is_file():
            st = p.stat()
            out.append({"where": where, "path": rel, "kind": kind, "size": st.st_size,
                        "mtime": st.st_mtime,
                        "roles": sorted(r for r, v in roles.items() if v == rel)})
    return out


def materials(song_dir: Path, out: Path) -> list[dict[str, Any]]:
    """素材の一覧：曲のディレクトリのファイル（`where="song"`、song.json の `files` の
    役割つき）と、出力（`where="out"`、`out/<曲>/` の直下）。"""
    try:
        files = doc_of(song_dir).get("files", {})
    except ValueError:
        files = {}
    roles = {r: v for r, v in files.items() if isinstance(v, str)} \
        if isinstance(files, Mapping) else {}
    rows = _rows(song_dir, sorted(song_dir.rglob("*")), KINDS, roles, "song")
    if out.is_dir():
        rows += _rows(out, sorted(out.iterdir()), OUT_KINDS, {}, "out")
    return rows


def inside(base: Path, rel: str) -> Path:
    """`base` の中のファイル。外へ出る道（`..` や絶対パス）は断る。"""
    path = (base / rel).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        raise ValueError("ファイルが無い: %s" % rel)
    return path


def choices() -> dict[str, Any]:
    """画面の選択肢。preset・effect・切り替え・crt の既定・工程。"""
    from cymatics import effects, presets

    return {"presets": sorted(presets.names()), "effects": sorted(effects.names()),
            "transitions": list(video.TRANSITIONS), "crt": crt.Crt().to_dict(),
            "steps": list(STEPS), "redo": list(REDO), "credits": credit_positions()}


def credit_positions() -> dict[str, list[str]]:
    """歌詞の出し方（`credits.mode`）→ 置ける位置（最初が既定）。"""
    return {**{m: list(roll.POSITIONS) for m in roll.MODES},
            **{m: list(ps) for m, ps in sing.MODES.items()}}


def section_names(song_dir: Path) -> list[str]:
    """歌詞のセクション名（`fade_in.after` の候補）。読めなければ空。"""
    try:
        return [s.name for s in lyrics.load(file_of(song_dir, "lyrics")).sections]
    except (ValueError, OSError):
        return []


# ------------------------------------------------------------- タイムライン
def file_of(song_dir: Path, role: str) -> Path:
    files = doc_of(song_dir).get("files", {})
    if not isinstance(files, Mapping) or not isinstance(files.get(role), str):
        raise ValueError("song.json の files.%s が無い" % role)
    path = song_dir / files[role]
    if not path.is_file():
        raise ValueError("files.%s のファイルが無い: %s" % (role, files[role]))
    return path


def lyrics_file(song_dir: Path, out: Path) -> Path:
    """時刻を読み書きする歌詞。歌詞に時刻を手で書いてあればそれ（書き出しもそれを
    使う）、無ければ `out/<曲>/lyrics.timed.md`（`sections` の出力）。"""
    src = file_of(song_dir, "lyrics")
    if lyrics.load(src).timed:
        return src
    return out / NAMES["timed"]


def peaks(path: Path, n: int = PEAKS) -> tuple[list[float], float]:
    """音の絶対値の山を `n` 個（0..1）と、尺（秒）。"""
    x = np.abs(video.audio_of(str(path), PEAK_SR))
    dur = len(x) / PEAK_SR
    edges = np.linspace(0, len(x), min(n, len(x)) + 1).astype(int)
    top = np.maximum.reduceat(x, edges[:-1]) if len(x) else np.zeros(0)
    scale = float(top.max()) if len(top) and top.max() > 0 else 1.0
    return [round(float(v) / scale, 4) for v in top], dur


def sound(song_dir: Path) -> dict[str, Any]:
    """音の側: 尺・波形の山・拍・BPM。拍の解析に数秒かかる（呼ぶ側が控える）。"""
    audio = file_of(song_dir, "audio")
    pk, dur = peaks(audio)
    b = analyze(str(audio))
    return {"duration": dur, "peaks": pk, "beats": [round(float(t), 4) for t in b.times],
            "bpm": round(float(b.bpm), 2)}


def words(song_dir: Path, out: Path, duration: float) -> dict[str, Any]:
    """歌詞の側: セクション（名前・開始秒・行）と行の歌い出し。時刻の無い歌詞なら
    開始秒は None。軽いので毎回読む。"""
    timed = lyrics_file(song_dir, out)
    src = timed if timed.is_file() else file_of(song_dir, "lyrics")
    song = lyrics.load(src)
    return {"file": str(src), "saves_to": str(timed),
            "sections": [{"name": s.name, "start": s.start, "lines": len(s.lines),
                          "texts": list(s.lines)} for s in song.sections],
            **line_starts(song, out, duration)}


def timeline(song_dir: Path, out: Path) -> dict[str, Any]:
    """`sound` と `words` を合わせたもの。"""
    snd = sound(song_dir)
    return {**snd, **words(song_dir, out, snd["duration"])}


def line_starts(song: lyrics.Song, out: Path, duration: float) -> dict[str, Any]:
    """行の歌い出し（lines.json）と、無いときの仮置き（文字数で振り分け）。セクションの
    時刻が無ければどちらも None。歌詞が変わって読めなければ理由を `line_note` に。"""
    if not song.timed:
        return {"line_starts": None, "line_spread": None, "line_note": "セクションの時刻が先"}
    path, note, got = out / NAMES["lines"], "", None
    if path.is_file():
        try:
            got = lines.load(path, song)
        except ValueError as e:
            note = str(e)
    return {"line_starts": got, "line_spread": lines.spread(song, duration), "line_note": note}


def save_lines(song_dir: Path, out: Path, starts: Sequence[Sequence[float]]) -> str:
    """行の歌い出しを `out/<曲>/lines.json` に。セクションの時刻を置いた歌詞が要る。"""
    src = lyrics_file(song_dir, out)
    if not src.is_file() or not lyrics.load(src).timed:
        raise ValueError("先にセクションの時刻を保存する")
    dst = out / NAMES["lines"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    lines.save(dst, lyrics.load(src), starts)
    return str(dst)


def suggest(song_dir: Path) -> list[dict[str, Any]]:
    """自動の推定（`structure.estimate`）。`doubtful` は人が見るべき境界。"""
    song = lyrics.load(file_of(song_dir, "lyrics"))
    bounds = structure.estimate(song, analyze(str(file_of(song_dir, "audio"))))
    return [{"section": x.section, "start": round(x.start, 3), "doubtful": x.doubtful,
             "margin": None if x.margin == float("inf") else round(x.margin, 4)}
            for x in bounds]


def save_timeline(song_dir: Path, out: Path, starts: Sequence[float]) -> str:
    """開始秒をタグに書き込む。並びが逆転していたら断る。書いたファイルを返す。"""
    if any(b <= a for a, b in zip(starts, starts[1:])) or (starts and starts[0] < 0):
        raise ValueError("開始秒は 0 以上で、前から順に増えていく")
    dst = lyrics_file(song_dir, out)
    src = dst if dst.is_file() else file_of(song_dir, "lyrics")
    text = lyrics.stamp(src.read_text(encoding="utf-8"), list(starts))
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")
    return str(dst)


# ------------------------------------------------------------- 書き出し
def command(song_dir: Path, out: Path, steps: Sequence[str] = (),
            redo: Sequence[str] = (), previews: bool = False) -> list[str]:
    """`emotion-effecter song` の引数。知らない工程は断る。"""
    bad = [s for s in steps if s not in STEPS] + [r for r in redo if r not in REDO]
    if bad:
        raise ValueError("知らない工程: %s" % ", ".join(bad))
    cmd = [sys.executable, "-u", "-m", "emotion_effecter", "song", str(song_dir),
           "--out", str(out)]
    cmd += ["--previews"] if previews else (["--steps", *steps] if steps else [])
    return cmd + (["--redo", *redo] if redo else [])


@dataclass
class Job:
    id: int
    song: str
    cmd: list[str]
    log: str
    started: float
    proc: subprocess.Popen | None = None
    ended: float | None = None
    code: int | None = None

    def poll(self) -> None:
        if self.proc is not None and self.code is None and self.proc.poll() is not None:
            self.code, self.ended = self.proc.returncode, time.time()

    def view(self, tail: int = 60) -> dict[str, Any]:
        self.poll()
        lines = Path(self.log).read_text(encoding="utf-8", errors="replace").splitlines() \
            if Path(self.log).exists() else []
        state = "running" if self.code is None else ("done" if self.code == 0 else "failed")
        return {"id": self.id, "song": self.song, "cmd": self.cmd, "log": self.log,
                "started": self.started, "ended": self.ended, "code": self.code,
                "state": state, "tail": lines[-tail:]}


@dataclass
class Jobs:
    """書き出しの仕事。同じ曲は1度に1つだけ（出力を取り合わないように）。"""

    items: dict[int, Job] = field(default_factory=dict)

    def start(self, song: str, cmd: list[str], log: Path) -> Job:
        if any(j.song == song and j.view()["state"] == "running" for j in self.items.values()):
            raise ValueError("%s はもう書き出している" % song)
        log.parent.mkdir(parents=True, exist_ok=True)
        job = Job(len(self.items) + 1, song, cmd, str(log), time.time())
        with open(log, "w", encoding="utf-8") as fh:
            fh.write("$ %s\n" % " ".join(cmd))
            fh.flush()
            job.proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                        env={**os.environ, "PYTHONUNBUFFERED": "1"},
                                        start_new_session=True)
        self.items[job.id] = job
        return job

    def stop(self, job_id: int) -> Job:
        job = self.items[job_id]
        if job.proc is not None and job.proc.poll() is None:
            os.killpg(job.proc.pid, signal.SIGTERM)      # ffmpeg ごと止める
            job.proc.wait()
        job.poll()
        return job
