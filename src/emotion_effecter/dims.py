"""採点する軸の宣言。**名前はここにだけ書く。**

採点（`mood` / `elements`）はこの名前で Jev に聞き、使う側（`policy` / `casting`）は
この名前で「どの軸で何を決めるか」を選ぶ。両方が同じ一覧を見るので、片方だけ
名前が変わることが無い。
"""
from __future__ import annotations

#: セクションごとの感情（`mood`）。値は 0..1
DIMS: tuple[str, ...] = ("arousal", "valence", "acceptance", "conflict", "dominance")

#: 曲全体の属性（`elements`）。水・地・風・金・火・明・暗。値は 0..1
ELEMENTS: tuple[str, ...] = ("water", "earth", "wind", "metal", "fire", "light", "dark")
