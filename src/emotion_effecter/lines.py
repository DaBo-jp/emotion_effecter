"""歌詞の行ごとの歌い出しの時刻（`out/<曲>/lines.json`）。歌詞のファイルには書かない。

    {"format": 1,
     "sections": [{"name": "Verse 1", "lines": ["夜明けの街で", ...], "starts": [43.9, ...]}]}

**歌詞が変わったら断る。** セクションの名前と行の文字がそのまま一致しないと読まない
（ずれた時刻で黙って歌わせない）。置き直すのはタイムライン（手元の画面）。

置いていない曲は `spread()` で仮に置く——セクションの頭から次のセクションの頭まで
（最後は曲の終わりまで）を、行の文字数の割合で分ける。歌い出しの頭は合うが、
中の行は目安。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .doc import read_versioned, write
from .lyrics import Song

FORMAT = 1


@dataclass(frozen=True)
class Line:
    """歌う1行。`end` は次の行の歌い出し（セクションの最後の行はセクションの終わり）。"""

    section: int
    index: int
    text: str
    start: float
    end: float


def _check(song: Song, starts: Sequence[Sequence[float]]) -> None:
    if len(starts) != len(song.sections) or any(
            len(st) != len(s.lines) for st, s in zip(starts, song.sections)):
        raise ValueError("行の時刻の数が歌詞の行の数と合わない")
    flat = [t for st in starts for t in st]
    if any(b < a for a, b in zip(flat, flat[1:])) or (flat and flat[0] < 0):
        raise ValueError("行の時刻は 0 以上で、前から順に増えていく")


def build(song: Song, starts: Sequence[Sequence[float]], duration: float) -> tuple[Line, ...]:
    """セクションごとの行の歌い出し → 行の並び（終わりつき）。歌詞には時刻が要る。"""
    _check(song, starts)
    ends = [s.start for s in song.sections[1:]] + [duration]
    out = []
    for i, (s, st, sec_end) in enumerate(zip(song.sections, starts, ends)):
        for j, (text, t) in enumerate(zip(s.lines, st)):
            nxt = st[j + 1] if j + 1 < len(st) else sec_end
            out.append(Line(i, j, text, float(t), float(max(nxt, t))))
    return tuple(out)


def spread(song: Song, duration: float) -> list[list[float]]:
    """仮の歌い出し。セクションの長さを行の文字数の割合で分ける。"""
    ends = [s.start for s in song.sections[1:]] + [duration]
    out = []
    for s, end in zip(song.sections, ends):
        sizes = [max(len(ln), 1) for ln in s.lines]
        total, at, row = sum(sizes), 0, []
        for n in sizes:
            row.append(round(s.start + (end - s.start) * at / total, 3))
            at += n
        out.append(row)
    return out


def save(path: str | Path, song: Song, starts: Sequence[Sequence[float]]) -> None:
    _check(song, starts)
    write(path, {"format": FORMAT, "sections": [
        {"name": s.name, "lines": list(s.lines), "starts": [round(float(t), 3) for t in st]}
        for s, st in zip(song.sections, starts)]})


def load(path: str | Path, song: Song) -> list[list[float]]:
    """保存した歌い出し。歌詞と1文字でも違えば断る。"""
    doc = read_versioned(path, FORMAT, "行の時刻")
    secs = doc.get("sections", [])
    same = len(secs) == len(song.sections) and all(
        d.get("name") == s.name and d.get("lines") == list(s.lines)
        for d, s in zip(secs, song.sections))
    if not same:
        raise ValueError("%s: 歌詞が変わったので行の時刻が使えない（タイムラインで置き直す）"
                         % path)
    starts = [[float(t) for t in d["starts"]] for d in secs]
    _check(song, starts)
    return starts
