"""聴衆の映像 → セクションごとの盛り上がり（Jev の画像入力）。

1. 曲と映像の時刻を音で合わせる（`sync`。ここは結果の `lead` だけを受け取る）
2. セクションごとに、中ほどの時刻と前後 `spread` 秒の**3枚**を映像から取る
   ——1枚だけだと、カメラの揺れや手前の人で塞がった瞬間を拾う
3. 3枚を1リクエストで Jev に見せて、盛り上がり（`hype`）を Score で聞く

**間奏も採点する。** 歌詞の感情（`mood`）と違い、聴衆は間奏でこそ沸く。

結果は JSON に保存する（`audience.json`）。∴ 写像を変えるたびに Jev を呼び直さない。
画像は TypeSafe で「dreamer-ready」（試作向け）の扱い——リクエストごとに
`TypeSafe-Danger-Zone-Images: true` を送る。
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType

from typesafe_sdk import AsyncTypeSafeClient, Image, Score

from . import video
from .lyrics import Song

#: 保存形式の版。読めない版は断る
FORMAT = 1

#: 中ほどの時刻の前後、何秒からも取るか（セクションの中に収まる範囲で）
SPREAD = 2.0

#: 画像を使うリクエストに要るヘッダー
HEADERS: Mapping[str, str] = MappingProxyType({"TypeSafe-Danger-Zone-Images": "true"})

QUESTIONS: Mapping[str, Score] = MappingProxyType({
    "hype": Score(
        instructions=["`frames` はライブ会場の聴衆を、同じ数秒のあいだに撮った写真。",
                      "写っている聴衆はどれだけ盛り上がっているか。手の挙がり方・"
                      "跳ねているか・体の向き・揃い方から判断する。照明や演出ではなく"
                      "聴衆そのものを見る。"],
        criteria=[
            "静まっている。座っているか立ち尽くし、ほとんど動いていない",
            "聴き入っている。体は揺れているが、手はほとんど挙がっていない",
            "乗っている。手を挙げる人や手拍子が目立ち、体が拍に乗っている",
            "沸いている。多くの手が挙がり、跳ねる人が多い",
            "熱狂している。ほぼ全員が手を挙げて跳ね、会場が一体になっている",
        ]),
})


#: ライブ映像そのもの（ステージも客席も映る）を採点するときの問い。軸は同じ `hype`
SCENE: Mapping[str, Score] = MappingProxyType({
    "hype": Score(
        instructions=["`frames` はライブ映像の同じ数秒から取った写真。",
                      "このライブの場面はどれだけ盛り上がっているか。演者の動き・"
                      "客席の様子・照明や演出の激しさを合わせて判断する。"],
        criteria=[
            "静か。MC や静かな曲の入りで、演者も客席もほとんど動いていない",
            "穏やか。演者は歌い始めているが、客席は聴き入っている",
            "乗っている。演者が動き、客席の手や体が拍に乗っている",
            "盛り上がっている。演者が煽り、照明が激しく、多くの手が挙がっている",
            "最高潮。演者も客席も全力で、照明や演出が一斉に弾けている",
        ]),
})


@dataclass(frozen=True)
class Shot:
    """1セクションで映像から取る時刻。"""

    section: str
    #: 曲の時刻（中ほど）
    t: float
    #: 映像の時刻（取る3枚ぶん）
    at: tuple[float, ...]


@dataclass(frozen=True)
class Cheer:
    """1セクションの聴衆の採点。"""

    section: str
    t: float
    at: tuple[float, ...]
    #: 軸 → 0..1
    scores: dict[str, float]
    confidence: dict[str, float]
    distributions: dict[str, dict[str, float]]


def plan(song: Song, duration: float, lead: float, clip_len: float,
         spread: float = SPREAD) -> list[Shot]:
    """セクションごとに取る時刻。`lead` は映像の中で曲が始まる秒。

    **映像の外に出るセクションは全部並べて断る。**
    """
    if not song.timed:
        raise ValueError("開始時刻の無いセクションがある（sections コマンドで推定する）")
    ends = [s.start for s in song.sections[1:]] + [duration]
    shots, bad = [], []
    for sec, end in zip(song.sections, ends):
        mid = (sec.start + end) / 2
        half = min(spread, (end - sec.start) / 2 * 0.9)
        at = tuple(t + lead for t in (mid - half, mid, mid + half))
        if at[0] < 0 or at[-1] >= clip_len:
            bad.append("%s（映像の %.1f〜%.1f 秒。映像は %.1f 秒）"
                       % (sec.name, at[0], at[-1], clip_len))
        shots.append(Shot(sec.name, mid, at))
    if bad:
        raise ValueError("聴衆の映像に収まらないセクション:\n  " + "\n  ".join(bad))
    return shots


def stills(clip: str, shots: Sequence[Shot], tmp: str) -> list[list[str]]:
    """セクションごとの画像のパス。"""
    return [[video.still_at(clip, t, "%s/%03d_%d.jpg" % (tmp, i, j))
             for j, t in enumerate(s.at)] for i, s in enumerate(shots)]


def from_response(shot: Shot, resp) -> Cheer:
    """System One の応答 → Cheer。Score は最上段で割って 0..1 にする。"""
    scores, conf, dist = {}, {}, {}
    for name, a in resp.scores.items():
        scores[name] = a.score / max(a.probabilities)
        conf[name] = a.confidence
        dist[name] = {str(k): v for k, v in a.probabilities.items()}
    return Cheer(shot.section, shot.t, shot.at, scores, conf, dist)


async def score_shots(shots: Sequence[Shot], paths: Sequence[Sequence[str]],
                      client: AsyncTypeSafeClient,
                      questions: Mapping[str, Score] = QUESTIONS) -> list[Cheer]:
    resps = await asyncio.gather(*(
        client.system_one(state={"frames": [Image(Path(p)) for p in ps]},
                          questions=questions, extra_headers=HEADERS)
        for ps in paths))
    return [from_response(s, r) for s, r in zip(shots, resps)]


def score(shots: Sequence[Shot], paths: Sequence[Sequence[str]],
          questions: Mapping[str, Score] = QUESTIONS) -> list[Cheer]:
    """`questions` は聴衆を見る `QUESTIONS` か、ライブ映像そのものを見る `SCENE`。"""
    async def run() -> list[Cheer]:
        async with AsyncTypeSafeClient() as client:
            return await score_shots(shots, paths, client, questions)
    return asyncio.run(run())


def save(path: str | Path, title: str, sync: Mapping[str, float],
         cheers: Sequence[Cheer]) -> None:
    """`sync` は時刻合わせの記録（`lead` と山の鋭さ）。採点と一緒に残す。"""
    doc = {"format": FORMAT, "title": title, "sync": dict(sync),
           "cheers": [asdict(c) for c in cheers]}
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def load(path: str | Path) -> list[Cheer]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ValueError("%s: 聴衆の採点ファイルの形式が違う（format=%d を期待）"
                         % (path, FORMAT))
    return [Cheer(**{**c, "at": tuple(c["at"])}) for c in doc["cheers"]]
