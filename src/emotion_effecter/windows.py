"""歌詞の無いライブ動画を、拍から決めた一定の長さ（既定 8小節）で区切る。

歌詞のある曲はセクション（Verse / Chorus）ごとに採点するが、ライブ動画単独には
その区切りが無い。∴ 小節で刻んだ窓をセクションの代わりにする——名前は
`W01 0:00` のような通し番号と開始時刻。どの窓も歌詞を持たない（`timeline` が
歌詞の軸を作らない）。

**最後の窓が1小節に満たなければ、ひとつ前の窓に足す。** 数秒の窓を1つ採点しても
曲線の端が揺れるだけ。
"""
from __future__ import annotations

from .lyrics import Section, Song, fmt_time

#: 1小節の拍数
BEATS_PER_BAR = 4


def starts(duration: float, bpm: float, bars: int,
           beats_per_bar: int = BEATS_PER_BAR) -> list[float]:
    """窓の開始時刻（秒）。先頭は 0。"""
    if bpm <= 0 or bars <= 0 or duration <= 0:
        raise ValueError("bpm・小節数・尺は正の数（%s / %s / %s）" % (bpm, bars, duration))
    bar = beats_per_bar * 60.0 / bpm
    step = bars * bar
    out = [i * step for i in range(int(duration // step) + 1) if i * step < duration]
    if len(out) > 1 and duration - out[-1] < bar:
        out.pop()
    return out


def song(title: str, duration: float, bpm: float, bars: int,
         beats_per_bar: int = BEATS_PER_BAR) -> Song:
    """窓をセクションにした、歌詞の無い曲。"""
    ts = starts(duration, bpm, bars, beats_per_bar)
    return Song(title, tuple(Section("W%02d %s" % (i + 1, fmt_time(t)), (), t)
                             for i, t in enumerate(ts)))
