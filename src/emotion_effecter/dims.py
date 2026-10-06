"""感情の次元の宣言。**名前はここにだけ書く。**

採点（`mood`）はこの名前で Jev に聞き、写像（`policy`）はこの名前で「どの次元で
何を動かすか」を選ぶ。両方が同じ一覧を見るので、片方だけ名前が変わることが無い。
"""
from __future__ import annotations

#: Score で取る次元。値は 0..1
DIMS: tuple[str, ...] = ("arousal", "valence", "acceptance", "conflict", "dominance")
