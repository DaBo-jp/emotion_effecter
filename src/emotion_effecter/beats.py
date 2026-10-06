"""音源 → テンポ・拍・拍ごとの音色。

1. 100fps の対数スペクトル（60Hz-12kHz を32帯域）を作る
2. スペクトルの増分（onset）の自己相関からテンポ（60-200 BPM）を、
   拍の櫛を当てて位相を取る
3. 拍ごとにスペクトルを平均し、曲平均を引いて単位ベクトルにする

ボーカルの有無は見ていない——中央成分（cymatics の `beam_center`）は EBM では
シンセやベースも乗るので、声の目印にならなかった。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from cymatics.dsp import audio

HOP = 441            # 44.1kHz で 100fps
FFT = 2048
N_BANDS = 32
BPM_RANGE = (60, 200)


@dataclass(frozen=True)
class Beats:
    #: 拍の時刻（秒）
    times: np.ndarray
    #: 拍ごとの音色 (n, N_BANDS)。曲平均を引いた単位ベクトル
    feats: np.ndarray
    #: 音源の尺（秒）
    duration: float
    bpm: float

    def similarity(self) -> np.ndarray:
        """拍どうしのコサイン類似度 (n, n)。"""
        return self.feats @ self.feats.T


def _filterbank() -> np.ndarray:
    f = np.fft.rfftfreq(FFT, 1 / audio.SR)
    edges = np.geomspace(60, 12000, N_BANDS + 1)
    fb = np.zeros((len(f), N_BANDS), np.float32)
    for i in range(N_BANDS):
        m = (f >= edges[i]) & (f < edges[i + 1])
        if not m.any():                       # 低域はビンより帯域が細い
            m[np.argmin(abs(f - edges[i]))] = True
        fb[m, i] = 1 / m.sum()
    return fb


def log_spectrum(x: np.ndarray, block: int = 2000) -> np.ndarray:
    """モノラル → (フレーム, N_BANDS) の対数振幅。メモリを抑えるため block ずつ。"""
    n = (len(x) - FFT) // HOP + 1
    win, fb, out = np.hanning(FFT).astype(np.float32), _filterbank(), []
    for i in range(0, n, block):
        idx = np.arange(FFT)[None, :] + HOP * np.arange(i, min(n, i + block))[:, None]
        out.append(np.log(np.abs(np.fft.rfft(x[idx] * win, axis=1)) @ fb + 1e-6))
    return np.vstack(out)


def _onset(spec: np.ndarray) -> np.ndarray:
    on = np.r_[0, np.maximum(0, np.diff(spec, axis=0)).sum(1)]
    return np.maximum(on - np.convolve(on, np.ones(50) / 50, "same"), 0)


def beat_grid(spec: np.ndarray, fps: float) -> tuple[float, float]:
    """(拍の周期, 位相)。単位はスペクトルのフレーム。"""
    on = _onset(spec)
    o = on - on.mean()
    ac = np.correlate(o, o, "full")[len(o) - 1:]
    lo, hi = int(fps * 60 / BPM_RANGE[1]), int(fps * 60 / BPM_RANGE[0])
    k = lo + int(np.argmax(ac[lo:hi]))
    a, b, c = ac[k - 1:k + 2]
    period = k + 0.5 * (a - c) / (a - 2 * b + c)     # 放物線で山の頂点を補う
    grid = np.arange(len(on))
    phases = np.arange(0, period, 0.25)
    sums = [np.interp(np.arange(p, len(on) - 1, period), grid, on).sum() for p in phases]
    return float(period), float(phases[int(np.argmax(sums))])


def analyze(path: str) -> Beats:
    x = audio.decode(path, 1)
    spec, fps = log_spectrum(x), audio.SR / HOP
    period, phase = beat_grid(spec, fps)
    starts = np.arange(phase, len(spec) - period, period)
    b = np.stack([spec[int(s):int(s + period)].mean(0) for s in starts])
    b -= b.mean(0)
    b /= np.linalg.norm(b, axis=1, keepdims=True) + 1e-9
    return Beats(starts / fps, b, len(x) / audio.SR, 60 * fps / period)
