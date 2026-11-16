"""Jev（TypeSafe System One）の呼び方と、応答の読み方。**質問は持たない。**

質問を持つ側（`mood` / `pace` / `elements` / `audience` / `scenery`）が、
同じ読み方を各々に写さずに済むように:

- `level()` — Score の期待値を 0..1 に。段階は 0 から数えるので最上段で割る
- `scores()` — Score の応答を (0..1 の値, confidence, 分布) に
- `run()` — 非同期のクライアントを開いて1回の仕事を回す同期版。`TYPESAFE_API_KEY` を
  環境変数から読む。`EMOTION_EFFECTER_OFFLINE` が立っていれば呼ばずに断る（Cloud Run
  Jobs の render / finalize。Jev への質問は prepare で済んでいるはず）
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from typesafe_sdk import AsyncTypeSafeClient


def level(answer: Any) -> float:
    """Score の答え → 0..1。分布の鍵は段階 0..n−1 ∴ 最上段 n−1 で割る。"""
    return answer.score / max(answer.probabilities)


def scores(answers: Mapping[str, Any]
           ) -> tuple[dict[str, float], dict[str, float], dict[str, dict[str, float]]]:
    """Score の答えの束 → (値 0..1, confidence, 段階 → 確率)。分布の鍵は JSON に
    落ちるよう文字列にする。"""
    vals = {k: level(a) for k, a in answers.items()}
    conf = {k: a.confidence for k, a in answers.items()}
    dist = {k: {str(s): p for s, p in a.probabilities.items()} for k, a in answers.items()}
    return vals, conf, dist


#: これが立っていれば Jev を呼ばない（呼ぼうとしたら断る）
OFFLINE = "EMOTION_EFFECTER_OFFLINE"


class Offline(RuntimeError):
    """Jev を呼ばない段で、Jev への質問が要った（出力が残っていない）。"""


def run[T](job: Callable[[AsyncTypeSafeClient], Awaitable[T]]) -> T:
    """`job(client)` を回す同期版。クライアントは1回ぶん開いて閉じる。"""
    if os.environ.get(OFFLINE):
        raise Offline("Jev を呼ばない段（%s）で Jev への質問が要った——前の段の出力"
                      "（mood.json など）が無い" % OFFLINE)
    async def go() -> T:
        async with AsyncTypeSafeClient() as client:
            return await job(client)
    return asyncio.run(go())
