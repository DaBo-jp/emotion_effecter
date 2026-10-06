"""曲全体の歌詞を7つの属性（水・地・風・金・火・明・暗）で Jev に採点させる。

effect を選ぶ材料（`casting`）。区間ごとの感情（`mood`）と違い、**曲で1回**しか
聞かない——effect は1曲で1つなので、曲の流れではなく曲全体の像を見ればいい。

属性は字義どおりの語（「雨」「炎」）だけでなく、比喩も含めて聞く。Architecture の
「functions」「admin rights」は金属を一度も言わないが、金（機械・論理）の曲である。

点数は「その属性のイメージがどれだけ強いか」で、属性どうしは排他ではない
（火と暗が両方強い曲はある）。∴ Choice ではなく属性ごとの Score で取る。
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType

from typesafe_sdk import AsyncTypeSafeClient, Score

from . import dims
from .lyrics import Song

#: 保存形式の版。読めない版は断る
FORMAT = 1

#: 属性 → Jev に見せるイメージ。名前は `dims.ELEMENTS`
IMAGERY: Mapping[str, str] = MappingProxyType({
    "water": "水。涙・雨・海・川・流れ・溺れる・揺らぎ・冷たさ・洗い流す",
    "earth": "地。大地・身体・肌・重さ・根・故郷・現実に留まる",
    "wind": "風。息・空・声・漂う・移ろい・自由・届かない遠さ",
    "metal": "金。機械・金属・電子・コード・論理・刃・硬さ・冷たい精密さ",
    "fire": "火。炎・熱・情熱・欲望・怒り・燃え尽きる・火花",
    "light": "明。光・朝・希望・救い・神聖・まぶしさ",
    "dark": "暗。闇・夜・孤独・秘密・死・影・沈む",
})

_FOCUS = ("`song.lyrics` は曲全体の歌詞。字義どおりの語だけでなく、比喩や"
          "語り手・相手の在り方（人間か機械か、どこにいるか）も含めて、"
          "曲全体から立ち上がるイメージを判断する。")

_LEVELS = (
    "無い。このイメージは歌詞から感じられない",
    "かすか。言葉の端に少し出るだけ",
    "ある。いくつかの場面ではっきり感じられる",
    "強い。曲の主要なイメージの一つ",
    "支配的。曲全体がこのイメージに染まっている",
)


def questions() -> dict[str, Score]:
    """属性 → 質問。名前はコードのためのもので Jev には送られない。"""
    return {e: Score(instructions=[_FOCUS, "次の属性のイメージはどれだけ強いか: "
                                   + IMAGERY[e]], criteria=list(_LEVELS))
            for e in dims.ELEMENTS}


@dataclass(frozen=True)
class Elements:
    #: 属性 → 0..1 の期待値
    scores: dict[str, float]
    #: 属性 → confidence（分布の集中度）
    confidence: dict[str, float]


def state(song: Song) -> dict:
    return {"song": {"title": song.title, "lyrics": song.lyrics}}


def from_response(resp) -> Elements:
    """System One の応答 → Elements。Score は最上段で割って 0..1 にする。"""
    scores = {e: a.score / max(a.probabilities) for e, a in resp.scores.items()}
    return Elements(scores, {e: a.confidence for e, a in resp.scores.items()})


def score(song: Song) -> Elements:
    """同期版。`TYPESAFE_API_KEY` を環境変数から読む。"""
    async def run() -> Elements:
        async with AsyncTypeSafeClient() as client:
            return from_response(await client.system_one(state=state(song),
                                                         questions=questions()))
    return asyncio.run(run())


def save(path: str | Path, song: Song, el: Elements) -> None:
    doc = {"format": FORMAT, "title": song.title, **asdict(el)}
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def load(path: str | Path) -> Elements:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ValueError("%s: 属性ファイルの形式が違う（format=%d を期待）" % (path, FORMAT))
    return Elements(doc["scores"], doc["confidence"])
