"""聴衆の映像と曲の音源の時刻合わせ。**音の立ち上がりの並びを重ねて、ずれを測る。**

会場で撮った映像の音は、曲の音源とは音色が違う（PA・残響・歓声）。波形そのものでは
なく**立ち上がりの並び**（10ms ごとの音量の増え方）を相互相関で重ねる——拍と
歌い出しの位置は会場でも変わらない。

    t_映像 = t_曲 + lead

`lead` は「映像の中で曲が始まる秒」。曲が始まってから撮り始めた映像なら負になる。

山の鋭さ（`strength`：相関の山が、相関全体のばらつきの何倍か）が `MIN_STRENGTH`
を切ったら**黙って使わずに断る**。そのときは song.json の `audience.lead` に手で書く。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import video

#: 立ち上がりを測る音のサンプリング周波数。拍の位置さえ分かればいい
SR = 4000
#: 立ち上がりの刻み（サンプル）。10ms
HOP = 40
#: これより鈍い山は「重なった」と言えない
MIN_STRENGTH = 8.0


@dataclass(frozen=True)
class Sync:
    #: 映像の中で曲が始まる秒。t_映像 = t_曲 + lead
    lead: float
    #: 相関の山が、相関全体のばらつきの何倍か。手で書いた lead なら 0
    strength: float

    def video_time(self, t_song: float) -> float:
        return t_song + self.lead


def onsets(x: np.ndarray) -> np.ndarray:
    """10ms ごとの音量の増え方（対数）。平均 0・標準偏差 1 に揃える。"""
    n = len(x) // HOP
    if n < 2:
        raise ValueError("音が短すぎる（%d サンプル）" % len(x))
    rms = np.sqrt(np.mean(x[:n * HOP].reshape(n, HOP).astype(np.float64) ** 2, axis=1))
    rise = np.maximum(np.diff(np.log(rms + 1e-6)), 0.0)
    sd = rise.std()
    return (rise - rise.mean()) / sd if sd > 0 else rise * 0.0


def measure(song: np.ndarray, clip: np.ndarray) -> Sync:
    """2つの音（どちらも `SR` Hz）のずれ。`clip[i + k] ≈ song[i]` になる k を探す。"""
    a, b = onsets(song), onsets(clip)
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    c = np.fft.irfft(np.fft.rfft(b, n) * np.conj(np.fft.rfft(a, n)), n)
    k = int(np.argmax(c))
    sd = c.std()
    strength = float((c[k] - np.median(c)) / sd) if sd > 0 else 0.0
    lag = k if k < n - len(a) else k - n
    return Sync(lag * HOP / SR, strength)


def align(song_audio: str, clip_video: str) -> Sync:
    """曲の音源と聴衆の映像のずれ。山が鈍ければ理由を添えて断る。"""
    s = measure(video.audio_of(song_audio, SR), video.audio_of(clip_video, SR))
    if s.strength < MIN_STRENGTH:
        raise ValueError(
            "聴衆の映像と曲の音が重ならない（山の鋭さ %.1f < %.1f。いちばん近いのは "
            "lead %.2f 秒）。song.json の audience.lead に手で書く"
            % (s.strength, MIN_STRENGTH, s.lead))
    return s
