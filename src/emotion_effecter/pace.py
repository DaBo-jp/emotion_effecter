"""セクションごとの「気持ちの速さ」を Jev に聞く。流れる速さを拍に合わせる材料（`tempo`）。

昂ぶり（`mood` の arousal）だけでは足りない——昂ぶっていても陶酔して時間が止まる
セクションもあれば、静かなのに焦って前のめりのセクションもある。∴ 別に聞く。

聞くのは**曲のテンポではなく、言葉から感じる気持ちの歩み**。Jev は音を聞けない。

`mood.json` とは別のファイル（`pace.json`）に持つ。`song.json` に `tempo` を書いた
曲だけが聞く——足しても、他の曲の採点（`mood.json`）を採点し直さなくていい。
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType

from typesafe_sdk import AsyncTypeSafeClient, Choice

from . import dims
from .lyrics import Song, context

#: 保存形式の版。読めない版は断る
FORMAT = 1

_FOCUS = ("`section.text` の歌詞が表している、語り手のその時点の気持ちを判断する。"
          "`song.lyrics` は曲全体、`previous` は直前のセクション。"
          "曲のテンポ（音の速さ）ではなく、言葉から感じる気持ちの歩みで答える。")

#: ラベル → 説明。ラベルは `dims.PACES`
CRITERIA = MappingProxyType({
    "linger": "たゆたう。時間が止まったよう。回想・余韻・陶酔・諦めの中で、"
              "気持ちがその場に留まっている",
    "walk": "歩む。語りかけるような、普段の速さで気持ちが進んでいる",
    "rush": "急く。焦り・衝動・高揚で前のめりになり、気持ちが先へ先へと駆けている",
})

QUESTION = Choice(instructions=[_FOCUS, "語り手の気持ちの時間は、どんな速さで流れているか。"],
                  criteria=dict(CRITERIA))


@dataclass(frozen=True)
class Pace:
    section: str
    #: ラベル → 確率
    probabilities: dict[str, float]
    confidence: float
    #: いちばん確からしいラベル
    choice: str


def from_response(section: str, resp) -> Pace:
    a = resp.choices["pace"]
    return Pace(section, dict(a.probabilities), a.confidence, a.choice)


async def score_song(song: Song, client: AsyncTypeSafeClient) -> list[Pace]:
    """歌詞のあるセクションを全部、並列に聞く。"""
    idx = [i for i, s in enumerate(song.sections) if s.lines]
    resps = await asyncio.gather(*(client.system_one(state=context(song, i),
                                                     questions={"pace": QUESTION})
                                   for i in idx))
    return [from_response(song.sections[i].name, r) for i, r in zip(idx, resps)]


def score(song: Song) -> list[Pace]:
    """同期版。`TYPESAFE_API_KEY` を環境変数から読む。"""
    async def run() -> list[Pace]:
        async with AsyncTypeSafeClient() as client:
            return await score_song(song, client)
    return asyncio.run(run())


def save(path: str | Path, song: Song, paces: list[Pace]) -> None:
    doc = {"format": FORMAT, "title": song.title, "paces": [asdict(p) for p in paces]}
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def load(path: str | Path) -> list[Pace]:
    """**知らないラベルの混じった採点も断る**（`tempo` が倍率を引けない）。"""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ValueError("%s: 気持ちの速さのファイルの形式が違う（format=%d を期待）"
                         % (path, FORMAT))
    paces = [Pace(**p) for p in doc["paces"]]
    bad = ["%s: %s" % (p.section, k) for p in paces for k in p.probabilities
           if k not in dims.PACES]
    if bad:
        raise ValueError("%s: 知らないラベル: %s" % (path, ", ".join(bad)))
    return paces
