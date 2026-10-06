"""歌詞ファイルの読み書き。

形式は作詞メモそのまま:

    <!--
    Script
    完成: 2026-09-30 01:11
    作詞: みじんこきなこ
    -->
    [Intro]
    ...
    [Verse 1 @0:13.35]
    ...

ヘッダーのコメントは1行目がタイトル、残りが `キー: 値`。セクションタグには
`@分:秒` で開始時刻を書き足せる（`sections` コマンドが書き込む）。歌詞の無い
セクション（`[Instrumental Break]` など）も1区間として残す。
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

_HEADER = re.compile(r"\A\s*<!--(.*?)-->", re.S)
_TAG = re.compile(r"^\[(?P<name>[^\]@]+?)\s*(?:@\s*(?P<at>[\d:.]+))?\s*\]$")


@dataclass(frozen=True)
class Section:
    name: str
    lines: tuple[str, ...]
    #: 開始時刻（秒）。タグに `@` が無ければ None
    start: float | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def instrumental(self) -> bool:
        return not self.lines


@dataclass(frozen=True)
class Song:
    title: str
    sections: tuple[Section, ...]
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def lyrics(self) -> str:
        """タグつきの全文。Jev に曲全体の流れを渡すときに使う。"""
        return "\n\n".join(
            "[%s]\n%s" % (s.name, s.text) if s.lines else "[%s]" % s.name
            for s in self.sections)

    @property
    def timed(self) -> bool:
        return all(s.start is not None for s in self.sections)


def parse_time(text: str) -> float:
    """`1:23.5` / `83.5` → 秒。"""
    secs = 0.0
    for part in text.split(":"):
        secs = secs * 60 + float(part)
    return secs


def fmt_time(secs: float) -> str:
    """秒 → `1:23.50`。"""
    return "%d:%05.2f" % divmod(secs, 60)


def _header(text: str) -> tuple[str, dict[str, str], str]:
    m = _HEADER.match(text)
    if not m:
        return "", {}, text
    rows = [r.strip() for r in m.group(1).strip().splitlines() if r.strip()]
    pairs = (r.split(":", 1) for r in rows[1:] if ":" in r)
    meta = {k.strip(): v.strip() for k, v in pairs}
    return (rows[0] if rows else ""), meta, text[m.end():]


def _sections(body: str) -> tuple[Section, ...]:
    out: list[Section] = []
    name, at, lines = None, None, []
    for raw in body.splitlines():
        line = raw.strip()
        tag = _TAG.match(line)
        if tag:
            if name is not None:
                out.append(Section(name, tuple(lines), at))
            name, lines = tag.group("name").strip(), []
            at = parse_time(tag.group("at")) if tag.group("at") else None
        elif line and name is not None:
            lines.append(line)
    if name is not None:
        out.append(Section(name, tuple(lines), at))
    return tuple(out)


def parse(text: str) -> Song:
    title, meta, body = _header(text)
    return Song(title=title, sections=_sections(body), meta=meta)


def load(path: str | Path) -> Song:
    """読む。ヘッダーにタイトルが無ければファイル名をタイトルにする。"""
    path = Path(path)
    song = parse(path.read_text(encoding="utf-8"))
    return song if song.title else Song(path.stem, song.sections, song.meta)


def stamp(text: str, starts: Sequence[float]) -> str:
    """セクションタグに、出てくる順に `@分:秒` を書き込む。

    既に時刻があるタグは書き換える。タグ以外の行は1文字も触らない。
    **時刻の数とタグの数が合わなければ断る**（余りを黙って捨てない）。
    """
    tags = sum(1 for line in text.split("\n") if _TAG.match(line.strip()))
    if tags != len(starts):
        raise ValueError("タグが %d 個に対して時刻が %d 個" % (tags, len(starts)))
    it = iter(starts)

    def tag(m: re.Match) -> str:
        return "[%s @%s]" % (m.group("name").strip(), fmt_time(next(it)))

    return "\n".join(_TAG.sub(tag, line.strip()) if _TAG.match(line.strip()) else line
                     for line in text.split("\n"))
