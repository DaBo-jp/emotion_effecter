"""セクションごとの感情を Jev（TypeSafe System One）で数値にする。

1セクション = 1リクエスト。質問はすべて同じ state に対して並列に投げる。
state には**曲全体の歌詞**と**直前のセクション**も入れる——Chorus の繰り返しは
文面がほぼ同じで（「心までは 渡さない」「心まで 渡したい」「心まで 渡したから」）、
違いは曲の流れの中でしか読めないため。

質問は曲を選ばない形にしてある。受容（acceptance）の相手は「相手・世界・自分の
置かれた状況」のどれでもいい——Script は恋の相手、イセカイは来てしまった世界。
最初は「相手に心を開くか（openness）」で聞いていて、相手のいない曲では
confidence が 15〜65% まで落ちた。

歌詞の無いセクションは採点しない（前後からつなぐのは `timeline`）。
結果は JSON に保存する。∴ 写像の重みを変えるたびに Jev を呼び直さなくていい。
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType

from typesafe_sdk import AsyncTypeSafeClient, Choice, Score

from . import dims
from .lyrics import Song

#: Score で取る次元（宣言は `dims`）。値は 0..1 に正規化して持つ
DIMS = dims.DIMS

#: 保存形式の版。読めない版は断る。
#: 2: openness（相手に心を開く）→ acceptance（向き合うものを受け入れる）に一般化。
#:    質問の意味が変わったので、1 の採点は読まずに採点し直す
#: 3: dominance（主導権）を足した。PAD モデル（快・覚醒・支配）の支配だけが抜けていて、
#:    主導権の移り変わりが物語の軸の曲（Architecture）で何も動かなかった
FORMAT = 3

_FOCUS = ("`section.text` の歌詞が表している、語り手のその時点の気持ちを判断する。"
          "`song.lyrics` は曲全体、`previous` は直前のセクションで、"
          "同じ言い回しの繰り返しでも曲の流れの中で意味が変わることに注意する。")

#: 質問の名前 → 質問。名前はコードのためのもので Jev には送られない
QUESTIONS: Mapping[str, Score | Choice] = MappingProxyType({
    "arousal": Score(
        instructions=[_FOCUS, "語り手の気持ちの昂ぶり（覚醒度）はどの程度か。"],
        criteria=[
            "静まりかえっている。淡々と独り言のように距離を置いて語っている",
            "落ち着いている。気持ちはあるが抑えて語っている",
            "心が動いている。迷いや期待で気持ちがざわついている",
            "強く昂ぶっている。衝動や欲求が言葉に出ている",
            "抑えきれない。感情や身体の反応が言葉を押し流している",
        ]),
    "valence": Score(
        instructions=[_FOCUS, "語り手の気持ちは快・不快のどちら寄りか。"],
        criteria=[
            "苦しい。痛み・喪失・拒絶の感情が中心にある",
            "やや苦い。警戒や諦めが混じって素直に喜べない",
            "どちらとも言えない。快と不快が拮抗している",
            "やや甘い。惹かれる気持ちや期待が前に出ている",
            "満ちている。受け入れる喜びや幸福感が中心にある",
        ]),
    "acceptance": Score(
        instructions=[_FOCUS,
                      "語り手は、向き合っているもの（相手・世界・自分の置かれた状況）を"
                      "どこまで受け入れているか。"],
        criteria=[
            "拒んでいる。向き合っているものを否定し、受け入れる余地が無い",
            "身構えている。心が動いても、受け入れまいとしている",
            "揺れている。拒む気持ちと受け入れたい気持ちが行き来している",
            "傾いている。受け入れたいと願い始めている",
            "受け入れている。向き合っているものを受け入れ、委ねている",
        ]),
    "conflict": Score(
        instructions=[_FOCUS, "語り手の中にある葛藤（矛盾した気持ちの同居）はどの程度か。"],
        criteria=[
            "葛藤は無い。気持ちが一つに定まっている",
            "わずかな引っかかりがあるが、大筋の気持ちは決まっている",
            "相反する気持ちがはっきり同居している",
            "相反する気持ちに引き裂かれ、自分でも分からなくなっている",
        ]),
    "dominance": Score(
        instructions=[_FOCUS,
                      "語り手は、向き合っているもの（相手・世界・状況）に対して"
                      "どれだけ主導権を握っているか。"],
        criteria=[
            "支配されている。相手や状況に振り回され、自分では何も決められない",
            "委ねている。主導権を自分から相手に渡している",
            "対等。主導権を分け合い、互いに作用し合っている",
            "主導している。自分から働きかけ、相手を動かそうとしている",
            "支配している。相手や状況を思いどおりにしている、あるいは奪いに行っている",
        ]),
    "emotion": Choice(
        instructions=[_FOCUS, "語り手の中心にある感情はどれか。"],
        criteria={
            "defiance": "拒絶・反発。相手や状況を受け入れまいとしている",
            "desire": "渇望・欲情。身体や心が相手を求めている",
            "doubt": "疑い・迷い。相手の言葉や自分の気持ちを信じきれない",
            "fear": "恐れ。傷つくことを避けようとしている",
            "longing": "切望。ここには無いもの・届かないものを求めている",
            "resignation": "諦め・悲しみ。どうにもならないと感じて沈んでいる",
            "hope": "希望。まだ変わりうると信じて前を向き始めている",
            "surrender": "受容・陶酔。相手や状況を受け入れ、満たされている",
        }),
})


@dataclass(frozen=True)
class Mood:
    """1セクションの採点。生の分布も持つ（写像の側で使える）。"""

    section: str
    #: 次元 → 0..1 の期待値
    scores: dict[str, float]
    #: 質問 → confidence（分布の集中度）
    confidence: dict[str, float]
    #: 質問 → {段階 or ラベル: 確率}
    distributions: dict[str, dict[str, float]]
    #: 中心の感情（Choice の答え）
    emotion: str


def state(song: Song, i: int) -> dict:
    """i 番目のセクションを採点するときに Jev に渡すもの。"""
    sec = song.sections[i]
    prev = next((s for s in reversed(song.sections[:i]) if s.lines), None)
    return {
        "song": {"title": song.title, "lyrics": song.lyrics},
        "section": {"name": sec.name,
                    "position": "%d / %d" % (i + 1, len(song.sections)),
                    "text": sec.text},
        "previous": ({"name": prev.name, "text": prev.text} if prev
                     else "（曲の最初のセクション）"),
    }


def from_response(section: str, resp) -> Mood:
    """System One の応答 → Mood。Score は最上段で割って 0..1 にする。"""
    scores, conf, dist = {}, {}, {}
    for name, a in resp.scores.items():
        scores[name] = a.score / max(a.probabilities)
        conf[name] = a.confidence
        dist[name] = {str(k): v for k, v in a.probabilities.items()}
    emo = resp.choices["emotion"]
    conf["emotion"], dist["emotion"] = emo.confidence, dict(emo.probabilities)
    return Mood(section, scores, conf, dist, emo.choice)


async def score_song(song: Song, client: AsyncTypeSafeClient) -> list[Mood]:
    """歌詞のあるセクションを全部、並列に採点する。"""
    idx = [i for i, s in enumerate(song.sections) if s.lines]
    resps = await asyncio.gather(
        *(client.system_one(state=state(song, i), questions=QUESTIONS) for i in idx))
    return [from_response(song.sections[i].name, r) for i, r in zip(idx, resps)]


def score(song: Song) -> list[Mood]:
    """同期版。`TYPESAFE_API_KEY` を環境変数から読む。"""
    async def run() -> list[Mood]:
        async with AsyncTypeSafeClient() as client:
            return await score_song(song, client)
    return asyncio.run(run())


def save(path: str | Path, song: Song, moods: list[Mood]) -> None:
    doc = {"format": FORMAT, "title": song.title, "moods": [asdict(m) for m in moods]}
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def load(path: str | Path) -> list[Mood]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ValueError("%s: 採点ファイルの形式が違う（format=%d を期待）" % (path, FORMAT))
    return [Mood(**m) for m in doc["moods"]]
