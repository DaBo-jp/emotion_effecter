"""キー画像 → Jev（Box / Noul / Choice）。effect を**どこに置くか**の材料。

Jev には「どこに置けば良いか」の座標を作らせない。聞くのは2つだけ：

1. **目印の場所**（Box）と、その目印が本当にあるか（Noul）。Box は無いものにも
   箱を返すので、必ず有無と組で聞く
2. その曲の effect を**どの目印に添えると絵になるか**（Choice）。effect の説明
   （cymatics の SUMMARY と、曲の宣言の引数）と、その画像を使うセクションの歌詞も見せる

座標への直し方（半径・箱・顔を避ける穴）は `placement` がコードで決める。
目印も置き場所の選択肢も曲を選ばない形にしてある。

Box は Jev 1.14 から（`jev-preview`）。画像は1辺 280〜1568 px でないと断られる
ので、縮めてから送る。EXIF の向きは向こうで適用されないので、こちらで起こす。
"""
from __future__ import annotations

import asyncio
import io
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType

from PIL import Image as PILImage
from PIL import ImageOps
from typesafe_sdk import AsyncTypeSafeClient, Box, Choice, Image, Noul

#: 保存形式の版。読めない版は断る
FORMAT = 1

#: Jev に送る質問の版。目印や置き場所の言い回しを変えたら上げる（保存した採点を使わなくなる）
ASKED = 3

#: Box を聞けるモデルと、画像を送るのに要るヘッダ
MODEL = "jev-preview"
HEADERS: Mapping[str, str] = MappingProxyType({"TypeSafe-Danger-Zone-Images": "true"})

#: Jev が受け取れる1辺の長さ（px）
MIN_SIDE, MAX_SIDE = 280, 1568

#: 目印 → 有無（Noul）で Jev に見せる説明
LANDMARKS: Mapping[str, str] = MappingProxyType({
    "face": "主人公（いちばん目立つ人物）の顔",
    "person": "主人公（いちばん目立つ人物）",
    "sky": "空（雲や夕焼けを含む）",
    "ground": "地面・道・床",
    "light": "目を引く光源（太陽・夕日・街灯・窓の灯りなど）",
})

#: 目印 → Box の指示。**短く、物の名前で。** 長い日本語の説明（「顔と髪を含む頭部」
#: など）では箱が人物の全身に広がった（Downburst、2026-10-18）。「空いた場所」の
#: ような物でないものは箱にならない（confidence 0.03）∴ 聞かずに `placement` で出す
BOX_TARGETS: Mapping[str, str] = MappingProxyType({
    "face": "the face of the main person in `picture`",
    "person": "the main person in `picture`",
    "sky": "the visible sky in `picture`",
    "ground": "the road or ground surface in `picture`",
    "light": "the brightest light source in `picture`",
})

#: 置き場所のラベル → 説明。`whole` 以外は `LANDMARKS` の目印に添える（`open` は人物の脇）
ANCHORS: Mapping[str, str] = MappingProxyType({
    "face": "主人公の頭を囲むように（後光・頭上の輪のように）",
    "sky": "空に（空を舞う・空に浮かぶように）",
    "ground": "地面・道に（足元から湧く・地を這うように）",
    "light": "光源に重ねて（光から放たれるように）",
    "open": "人物の脇の空いた場所に（人物と並べて別に）",
    "whole": "画面いっぱいに（人物の顔だけは避けて、全体に散らす）",
})

_LOOK = ("`picture` は曲のそのセクションの背景（キー画像）。この上に、音に合わせて動く"
         "光のエフェクト `effect` を重ねて曲の映像にする。`lyrics` はこの画像を背景にする"
         "セクションの歌詞。")


@dataclass(frozen=True)
class Scenery:
    #: 送った画像の大きさ（px）。箱は 0..1 なので大きさに依らない
    size: tuple[int, int]
    #: 目印 → (left, top, right, bottom)。どれも 0..1
    boxes: dict[str, tuple[float, float, float, float]]
    #: 目印 → 箱の confidence
    box_confidence: dict[str, float]
    #: 目印 → その目印が画像にある確率
    present: dict[str, float]
    #: 置き場所 → 確率
    anchors: dict[str, float]


def prepare(path: str | Path) -> bytes:
    """Jev に送れる JPEG。向きを起こし、1辺が 280〜1568 px に収まるよう縮める。"""
    img = ImageOps.exif_transpose(PILImage.open(path)).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    if min(img.size) < MIN_SIDE:
        raise ValueError("%s: 画像が小さすぎる %dx%d（1辺 %d px 以上）"
                         % (path, *img.size, MIN_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def boxes() -> dict[str, Box]:
    """目印ごとの Box。**画像だけの state で別に聞く**——歌詞や他の質問と同じ
    リクエストに入れると、顔の箱が人物の全身に広がった（Downburst、2026-10-18）。"""
    return {"box:" + k: Box(instructions=BOX_TARGETS[k]) for k in LANDMARKS}


def questions() -> dict[str, Noul | Choice]:
    """目印ごとの有無（Noul）と、置き場所の Choice。名前は Jev には送られない。"""
    out: dict[str, Noul | Choice] = {}
    for k, what in LANDMARKS.items():
        out["has:" + k] = Noul(instructions=[_LOOK, "`picture` に、%s はあるか。" % what])
    out["at"] = Choice(
        instructions=[_LOOK, "`effect` を重ねるなら、`picture` のどこに置くといちばん"
                      "絵になるか。構図と、人物の顔を隠さないことも考える。"],
        criteria=dict(ANCHORS))
    return out


def from_response(size: tuple[int, int], boxed, resp) -> Scenery:
    """`boxed` は `boxes()` の応答、`resp` は `questions()` の応答。"""
    bx = {k: boxed.boxes["box:" + k] for k in LANDMARKS}
    return Scenery(
        size=size,
        boxes={k: (b.box.left, b.box.top, b.box.right, b.box.bottom) for k, b in bx.items()},
        box_confidence={k: b.confidence or 0.0 for k, b in bx.items()},
        present={k: resp.nouls["has:" + k].noul for k in LANDMARKS},
        anchors=dict(resp.choices["at"].probabilities))


def state(data: bytes, effect: str, lyrics: str) -> dict:
    return {"picture": Image(data), "effect": effect, "lyrics": lyrics}


def look(path: str | Path, effect: str, lyrics: str) -> Scenery:
    """1枚を聞く。`effect` は effect の説明、`lyrics` はその画像を使うセクションの歌詞。
    `TYPESAFE_API_KEY` を環境変数から読む。"""
    data = prepare(path)

    async def run() -> Scenery:
        async with AsyncTypeSafeClient() as client:
            ask = dict(model=MODEL, extra_headers=dict(HEADERS))
            boxed, resp = await asyncio.gather(
                client.system_one(state={"picture": Image(data)}, questions=boxes(), **ask),
                client.system_one(state=state(data, effect, lyrics), questions=questions(),
                                  **ask))
            return from_response(PILImage.open(io.BytesIO(data)).size, boxed, resp)
    return asyncio.run(run())


def save(path: str | Path, key: Mapping[str, str], sc: Scenery) -> None:
    """`key` は何を聞いたか（画像のハッシュ・effect の説明・歌詞）。`load()` で照合する。"""
    doc = {"format": FORMAT, "asked": ASKED, "key": dict(key), **asdict(sc)}
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def load(path: str | Path, key: Mapping[str, str] | None = None) -> Scenery | None:
    """保存した採点。**聞いたものが `key` と違えば None**（採点し直す）。"""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ValueError("%s: キー画像の解析ファイルの形式が違う（format=%d を期待）"
                         % (path, FORMAT))
    if key is not None and (doc.get("asked") != ASKED or doc.get("key") != dict(key)):
        return None
    return Scenery(tuple(doc["size"]), {k: tuple(v) for k, v in doc["boxes"].items()},
                   doc["box_confidence"], doc["present"], doc["anchors"])
