"""歌詞を映画のエンドロールのように流す、またはオープニングクレジットのように出す。
重ね終えた画面（cymatics の `finish`）に描く。

出し方（`mode`）は `roll`（流れる、既定）か `card`（流れない）。`card` はいま歌っている
セクションの歌詞を、位置（`position`）の列で基準の高さ（`anchor`）を中心に出し、文字の
裏だけに `band` の色を不透明度 `band_alpha` で敷く。セクションの頭で `fade` 秒かけて
浮かび、終わりで `fade` 秒かけて消える。間奏では何も出さない。以下は `roll` の話。

**流れる速さはセクションの開始時刻で決める。** 各セクションの最初の行が、その
セクションの開始時刻に基準の高さ（`anchor`、画面の高さに対する比）を通る。間は
一定の速さ ∴ セクションの中の行は、歌の進みにだいたい合って通り過ぎる（行ごとの
時刻は持っていない）。間奏は、歌詞のある区間の平均の速さぶんの空白として流れる。

流れる向き（`direction`）は `up`（下から上、既定）か `down`（上から下）。`down` では
後のセクションほど上に積み、塊の下の端が開始時刻に基準の高さを通る（塊の中の行は
上から読む順のまま）。

フォント（`font`）は**入っているフォントのファミリー名**（fontconfig で探す。例
`Noto Sans CJK JP`）か、`FONTS` の別名か、フォントファイルのパス（song.json からの相対も
可）。太さ（`weight`）は `WEIGHTS` の名前（Regular / Bold など）で、fontconfig の太さの
数で探す。fc-match は無いフォントを頼まれても似たものを黙って返すので、**返ってきた
ファミリーと太さが頼んだものでなければ断る**（Light を頼んで ExtraLight、も断る）。
動く環境は Linux のコンテナ——Debian なら `fontconfig` と `fonts-noto-cjk` を入れる
（OS 固有の場所のフォントを前提にしない）。

位置（`position`）:

| 値 | 流れる場所 |
|---|---|
| `right` / `left` / `center` | その列に固定 |
| `left_right` / `right_left` | セクションごとに左右を入れ替える（最初が左 / 右） |

裏の帯は**列の上から下までの縦の帯**。固定の位置では常に、交互では歌詞が見えている
側だけに敷く——文字が入ってくるにつれて濃くなり、出ていくにつれて薄くなる
（見えている文字が `band_fade` 行ぶんで濃さいっぱい）。`card` は文字の裏の箱。

`edge_fade` を書くと、流れる文字が画面の上下の端でその幅（画面の高さに対する比）を
かけて薄れて消える・浮かんでくる。帯は薄れない。

帯は `band` の色を不透明度 `band_alpha` で敷く。文字は列の中で中央揃え、列に
収まらない行は折り返す（空白があれば語の切れ目で、無ければ文字で）。

`Roll` はフレーム番号にも時刻にも依らない配置だけを持つ（pickle できる）。描くのは
`draw()` で、文字の塊の絵は書き出し1回ぶん作り置く（呼ぶ側が渡す辞書）。
"""
from __future__ import annotations

import subprocess
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np
from cymatics.model.color import parse as parse_color
from PIL import Image, ImageChops, ImageDraw, ImageFont

from .lyrics import Song

#: 位置の名前 → 左右（交互は最初の側）
POSITIONS: Mapping[str, str] = MappingProxyType({
    "right": "right", "left": "left", "center": "center",
    "left_right": "left", "right_left": "right"})

#: フォントの別名 → ファミリー名（Debian の fonts-noto-cjk に入っているもの）
FONTS: Mapping[str, str] = MappingProxyType({
    "noto-sans": "Noto Sans CJK JP", "noto-serif": "Noto Serif CJK JP"})

#: 太さの名前 → fontconfig の太さの数
WEIGHTS: Mapping[str, int] = MappingProxyType({
    "Thin": 0, "ExtraLight": 40, "Light": 50, "DemiLight": 55, "Book": 75, "Regular": 80,
    "Medium": 100, "SemiBold": 180, "Bold": 200, "ExtraBold": 205, "Black": 210})

#: 出し方
MODES: tuple[str, ...] = ("roll", "card")

#: 流れる向き
DIRECTIONS: tuple[str, ...] = ("up", "down")

#: 書ける項目と既定値
DEFAULTS: Mapping[str, Any] = MappingProxyType({
    "mode": "roll",
    "position": "right",
    "direction": "up",
    "fade": 0.5,             # card の浮かぶ・消える秒数
    "band_fade": 2.0,        # 交互の縦の帯が濃くなりきるまでの、見えている文字の行数
    "edge_fade": 0.0,        # roll の文字が上下の端で薄れる幅 ÷ 画面の高さ。0 で薄れない
    "band": "0,0,0",
    "band_alpha": 0.4,
    "color": "255,255,255",
    "font": "noto-sans",
    "weight": "Regular",
    "size": 0.04,            # 文字の高さ ÷ 画面の高さ
    "width": 0.32,           # 列の幅 ÷ 画面の幅
    "margin": 0.04,          # 画面の端から列まで ÷ 画面の幅
    "anchor": 0.5,           # セクションの頭が開始時刻に通る高さ ÷ 画面の高さ
    "gap": 1.5,              # セクションの間の空き（行数）
    "line": 1.5,             # 行の送り ÷ 文字の高さ
})

#: 文字の裏の帯が文字からはみ出す幅 ÷ 文字の高さ
PAD = 0.6
#: 文字の高さの下限（px）。これより小さいと読めない
MIN_PX = 8
#: フォントが開けるかを確かめるときの大きさ（px）
PROBE_PX = 20
#: 不透明（8bit のアルファ）
OPAQUE = 255
#: 0 で割らないための下限
EPS = 1e-9

#: 数の項目の範囲（両端を含む）
RANGES: Mapping[str, tuple[float, float]] = MappingProxyType({
    "band_alpha": (0.0, 1.0), "size": (0.005, 0.2), "width": (0.05, 1.0),
    "margin": (0.0, 0.45), "anchor": (0.0, 1.0), "gap": (0.0, 20.0), "line": (1.0, 4.0),
    "fade": (0.0, 5.0), "band_fade": (0.0, 20.0), "edge_fade": (0.0, 0.5)})


@dataclass(frozen=True)
class Block:
    """セクション1つぶんの文字の塊。歌詞の無いセクションは `lines` が空。"""

    lines: tuple[str, ...]
    #: 塊の頭の、流れる帯の中での高さ（px）
    y: float
    #: 塊の高さ（px、セクションの間の空きを含む）
    height: float
    side: str


@dataclass(frozen=True)
class Roll:
    blocks: tuple[Block, ...]
    #: 流れる量の節目: (時刻 秒, 帯の中の高さ px)。画面の基準の高さに来るもの
    keys: tuple[tuple[float, float], ...]
    size: tuple[int, int]
    px: int                  # 文字の高さ
    step: float              # 行の送り
    #: `credits` の中身（既定値で埋めたもの）。並列の書き出しで別プロセスへ渡すので
    #: pickle できる形（項目の組の tuple）で持つ——MappingProxyType は pickle できない
    options: tuple[tuple[str, Any], ...]
    #: 使うフォントのファイルと、その中の番号（.ttc）
    font: tuple[str, int]

    @property
    def cfg(self) -> Mapping[str, Any]:
        return MappingProxyType(dict(self.options))

    def offset(self, t: float) -> float:
        """時刻 t に、帯の中のどの高さが画面の基準の高さにあるか。節目の間は直線、
        外は端の速さで伸ばす。"""
        ts = [k[0] for k in self.keys]
        i = min(max(bisect_right(ts, t) - 1, 0), len(ts) - 2)
        (t0, y0), (t1, y1) = self.keys[i], self.keys[i + 1]
        return y0 + (y1 - y0) * (t - t0) / max(t1 - t0, EPS)


def problems(doc: Any, root: Path | None = None) -> list[str]:
    """`credits` の駄目な理由を全部。"""
    if not isinstance(doc, Mapping):
        return ["credits は {項目: 値}"]
    doc = {k: v for k, v in doc.items() if not k.startswith("_")}
    bad = ["credits の知らない項目: %s" % k for k in sorted(set(doc) - set(DEFAULTS))]
    cfg = {**DEFAULTS, **doc}
    if cfg["position"] not in POSITIONS:
        bad.append("credits.position=%r は %s のどれか" % (cfg["position"], " / ".join(POSITIONS)))
    if cfg["mode"] not in MODES:
        bad.append("credits.mode=%r は %s のどれか" % (cfg["mode"], " / ".join(MODES)))
    if cfg["direction"] not in DIRECTIONS:
        bad.append("credits.direction=%r は %s のどれか"
                   % (cfg["direction"], " / ".join(DIRECTIONS)))
    for k, (lo, hi) in RANGES.items():
        v = cfg[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
            bad.append("credits.%s=%r は %s..%s の数" % (k, v, lo, hi))
    for k in ("band", "color"):
        try:
            parse_color(str(cfg[k]))
        except (ValueError, TypeError) as e:
            bad.append("credits.%s=%r（%s）" % (k, cfg[k], e))
    try:
        _font(find_font(str(cfg["font"]), str(cfg["weight"]), root), PROBE_PX,
              str(cfg["weight"]))
    except (OSError, ValueError) as e:
        bad.append("credits.font=%r / weight=%r: %s" % (cfg["font"], cfg["weight"], e))
    return bad


def _is_path(font: str) -> bool:
    return "/" in font or font.lower().endswith((".ttf", ".otf", ".ttc"))


def find_font(font: str, weight: str, root: Path | None = None) -> tuple[str, int]:
    """(ファイル, 番号)。パスならそのまま、それ以外は fontconfig で探す。
    **頼んだファミリーとスタイルが返らなければ断る**（fc-match は黙って似たものを返す）。"""
    if _is_path(font):
        p = Path(font) if Path(font).is_absolute() or root is None else root / font
        if not p.is_file():
            raise ValueError("フォントのファイルが無い: %s" % p)
        if weight != "Regular" and not _variable(str(p)):
            raise ValueError("可変フォントではないので太さ %s は選べない（別の太さのファイルを"
                             "指定する）" % weight)
        return str(p.resolve()), 0
    if weight not in WEIGHTS:
        raise ValueError("太さ %s は %s のどれか" % (weight, " / ".join(WEIGHTS)))
    family = FONTS.get(font, font)
    out = subprocess.run(["fc-match", "-f", "%{family}\t%{weight}\t%{file}\t%{index}",
                          "%s:weight=%d" % (family, WEIGHTS[weight])],
                         capture_output=True, text=True, check=True).stdout.split("\t")
    fams = {x.strip().lower() for x in out[0].split(",")}
    if family.lower() not in fams or int(float(out[1])) != WEIGHTS[weight]:
        raise ValueError("%s %s が入っていない（fc-match は %s 太さ %s を返した。別名は %s）"
                         % (family, weight, out[0], out[1], " / ".join(FONTS)))
    return out[2], int(out[3])


def _variable(path: str) -> bool:
    try:
        ImageFont.truetype(path, PROBE_PX).get_variation_names()
    except OSError:
        return False
    return True


def _font(where: tuple[str, int], px: int, weight: str) -> ImageFont.FreeTypeFont:
    """フォント。可変フォントなら太さを名前で選ぶ（既定のままだと Thin になるものがある）。"""
    f = ImageFont.truetype(where[0], px, index=where[1])
    if where[1] >> 16:
        return f                 # 可変フォントの太さは fontconfig が番号で選んである
    try:
        names = [n.decode() if isinstance(n, bytes) else n for n in f.get_variation_names()]
    except OSError:
        return f                 # 太さは fontconfig がファイルで選んである
    if weight not in names:
        raise OSError("太さ %s が無い（%s）" % (weight, " / ".join(names)))
    f.set_variation_by_name(weight)
    return f


def wrap(text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
    """列の幅に収まるよう折り返す。空白があれば語の切れ目で、無ければ文字で。"""
    units = text.split(" ") if " " in text.strip() else list(text)
    sep = " " if " " in text.strip() else ""
    out, cur = [], ""
    for u in units:
        nxt = cur + sep + u if cur else u
        if cur and font.getlength(nxt) > width:
            out.append(cur)
            nxt = u
        cur = nxt
    return out + ([cur] if cur else [])


def _sides(song: Song, position: str) -> list[str]:
    """セクションごとの左右。交互なら歌詞のあるセクションごとに入れ替える。"""
    first = POSITIONS[position]
    if position not in ("left_right", "right_left"):
        return [first] * len(song.sections)
    other = {"left": "right", "right": "left"}[first]
    out, n = [], 0
    for s in song.sections:
        out.append(first if n % 2 == 0 else other)
        n += 1 if s.lines else 0
    return out


def layout(song: Song, duration: float, size: tuple[int, int], cfg: Mapping[str, Any],
           root: Path | None = None) -> Roll:
    """開始時刻つきの歌詞と曲の尺から、流れる配置を作る。`cfg` は `credits`。"""
    cfg = {**DEFAULTS, **{k: v for k, v in cfg.items() if not k.startswith("_")}}
    where = find_font(str(cfg["font"]), str(cfg["weight"]), root)
    w, h = size
    px = max(MIN_PX, int(round(cfg["size"] * h)))
    step, font = px * cfg["line"], _font(where, px, cfg["weight"])
    lines = [[x for ln in s.lines for x in wrap(ln, font, cfg["width"] * w)]
             for s in song.sections]
    ends = [s.start for s in song.sections[1:]] + [duration]
    sung = [((len(ls) + cfg["gap"]) * step, e - s.start)
            for ls, s, e in zip(lines, song.sections, ends) if ls]
    speed = sum(a for a, _ in sung) / max(sum(b for _, b in sung), EPS)
    blocks, y = [], 0.0
    for ls, s, e, side in zip(lines, song.sections, ends, _sides(song, cfg["position"])):
        hgt = (len(ls) + cfg["gap"]) * step if ls else speed * (e - s.start)
        blocks.append(Block(tuple(ls), y, hgt, side))
        y += hgt
    keys = [(s.start, b.y) for s, b in zip(song.sections, blocks)] + [(duration, y)]
    return Roll(tuple(blocks), tuple(keys), size, px, step, tuple(sorted(cfg.items())), where)


def column(roll: Roll, side: str) -> tuple[int, int]:
    """列の左右の端（px）。"""
    w = roll.size[0]
    cw, m = int(roll.cfg["width"] * w), int(roll.cfg["margin"] * w)
    x0 = {"left": m, "right": w - m - cw, "center": (w - cw) // 2}[side]
    return x0, x0 + cw


def _block_image(roll: Roll, b: Block) -> Image.Image:
    """文字の塊の絵（RGBA、列の幅）。行は列の中で中央揃え。"""
    cw = column(roll, b.side)[1] - column(roll, b.side)[0]
    img = Image.new("RGBA", (cw, int(len(b.lines) * roll.step) + 1), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = _font(roll.font, roll.px, roll.cfg["weight"])
    col = parse_color(str(roll.cfg["color"]))[0]
    for i, ln in enumerate(b.lines):
        d.text(((cw - font.getlength(ln)) / 2, i * roll.step), ln, font=font,
               fill=(*col, OPAQUE))
    return img


def _band(roll: Roll, k: float = 1.0) -> tuple[int, int, int, int]:
    """裏の帯の色。`k` は濃さの倍率（0..1）。"""
    rgb = parse_color(str(roll.cfg["band"]))[0]
    return (*rgb, int(round(OPAQUE * roll.cfg["band_alpha"] * k)))


def presence(roll: Roll, side: str, shown: list[tuple[Block, int]]) -> float:
    """その側の帯の濃さの倍率 0..1。画面に見えている文字の高さが `band_fade` 行ぶんで
    1 ——文字が入ってくるにつれて濃くなり、出ていくにつれて薄くなる。"""
    h = roll.size[1]
    seen = sum(max(0, min(top + len(b.lines) * roll.step, h) - max(top, 0))
               for b, top in shown if b.side == side)
    full = roll.cfg["band_fade"] * roll.step
    return 1.0 if full <= 0 and seen > 0 else min(1.0, seen / max(full, EPS))


def _bands(roll: Roll, layer: Image.Image, shown: list[tuple[Block, int]]) -> None:
    """裏の帯。**列の上から下までの縦の帯。** 固定の位置は常に、交互は歌詞が見えて
    いる側だけ（`presence()` で出入りする）。"""
    d, pad = ImageDraw.Draw(layer), int(roll.px * PAD)
    fixed = roll.cfg["position"] in ("right", "left", "center")
    for side in ({roll.blocks[0].side} if fixed else ("left", "right")):
        k = 1.0 if fixed else presence(roll, side, shown)
        if k > 0:
            x0, x1 = column(roll, side)
            d.rectangle((x0 - pad, 0, x1 + pad, roll.size[1]), fill=_band(roll, k))


def _top(roll: Roll, b: Block, t: float) -> int:
    """時刻 t の、文字の塊の上の端（画面の px）。"""
    a, off = roll.cfg["anchor"] * roll.size[1], roll.offset(t)
    if roll.cfg["direction"] == "down":
        return int(round(a - (b.y + len(b.lines) * roll.step - off)))
    return int(round(a + (b.y - off)))


def _card(roll: Roll, t: float, cache: dict) -> tuple[Image.Image, tuple[int, int]] | None:
    """`card` の時刻 t の札（RGBA、裏の帯つき、浮かび・消えの濃さ込み）と置く位置。"""
    ts = [k[0] for k in roll.keys]
    i = bisect_right(ts, t) - 1
    if not 0 <= i < len(roll.blocks) or not roll.blocks[i].lines:
        return None
    b, fade = roll.blocks[i], roll.cfg["fade"]
    k = 1.0 if fade <= 0 else min(1.0, (t - ts[i]) / fade, (ts[i + 1] - t) / fade)
    if b not in cache:
        cache[b] = _block_image(roll, b)
    pad = int(roll.px * PAD)
    card = Image.new("RGBA", (cache[b].width + 2 * pad, cache[b].height + 2 * pad), _band(roll))
    card.alpha_composite(cache[b], (pad, pad))
    card.putalpha(card.getchannel("A").point(lambda a: int(round(a * max(k, 0.0)))))
    top = int(round(roll.cfg["anchor"] * roll.size[1] - card.height / 2))
    return card, (column(roll, b.side)[0] - pad, top)


def draw(img: Image.Image, t: float, roll: Roll, cache: dict) -> Image.Image:
    """時刻 t の画面に歌詞を描く。`cache` は文字の塊の絵の作り置き。"""
    if roll.cfg["mode"] == "card":
        got = _card(roll, t, cache)
        if got is None:
            return img
        out = img.convert("RGBA")
        out.alpha_composite(got[0], (max(got[1][0], 0), max(got[1][1], 0)))
        return out.convert("RGB")
    w, h = roll.size
    shown = [(b, top) for b in roll.blocks if b.lines
             for top in [_top(roll, b, t)] if top < h and top + len(b.lines) * roll.step > 0]
    bands, text = (Image.new("RGBA", (w, h), (0, 0, 0, 0)) for _ in range(2))
    _bands(roll, bands, shown)
    for b, top in shown:
        if b not in cache:
            cache[b] = _block_image(roll, b)
        text.alpha_composite(cache[b], (column(roll, b.side)[0], top)) if top >= 0 else \
            text.alpha_composite(cache[b].crop((0, -top, cache[b].width, cache[b].height)),
                                 (column(roll, b.side)[0], 0))
    if roll.cfg["edge_fade"] > 0:
        text.putalpha(ImageChops.multiply(text.getchannel("A"), _edges(roll, cache)))
    out = Image.alpha_composite(img.convert("RGBA"), bands)
    return Image.alpha_composite(out, text).convert("RGB")


def edge_ramp(h: int, frac: float) -> np.ndarray:
    """高さ h の濃さの倍率 0..1。上下の端から `frac × h` の間で 0 から 1 へ上がる。"""
    y = np.arange(h) + 0.5
    band = max(frac * h, EPS)
    return np.clip(np.minimum(y, h - y) / band, 0.0, 1.0)


def _edges(roll: Roll, cache: dict) -> Image.Image:
    """上下のフェードの濃さ（画面の大きさの L）。書き出し1回ぶん作り置く。"""
    if "edges" not in cache:
        w, h = roll.size
        ramp = np.rint(edge_ramp(h, roll.cfg["edge_fade"]) * OPAQUE).astype(np.uint8)
        cache["edges"] = Image.fromarray(np.repeat(ramp[:, None], w, axis=1), "L")
    return cache["edges"]
