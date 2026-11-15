"""歌っている行に合わせて、歌詞を**2行だけ**出す（song.json の `credits` の `mode`）。

- `karaoke` — 横の帯に2段。`position` は `bottom`（既定）か `top`
- `vertical` — 縦書きで2列。`position` は `right`（既定）か `left` の端。右の列から読む

**同期は行の単位。** 行は交互の段（列）に置き、前の行を歌い始めたところで次の行として
出て、自分の次の行を歌い始めるまで残る ∴ いつも「いま歌っている行」と「次の行」の2行。
置いた行は動かない（入れ替わるのは歌い終えた側の段だけ）。セクションの頭の行は前の行を
待たず、歌い出しの `lead` 秒前に出る。文字の色は変えない。

行の時刻は `lines`（タイムラインで置いた lines.json、無ければ文字数で振り分けた仮置き）。
段（列）に収まらない長い行は縮めて収める。

縦書きは縦の字形（`vert`。句読点・括弧・長音が縦になる）で、raqm の入った Pillow が
要る。**欧文（かなも漢字も無い区間）は横倒し**にする（縦書きの中の欧文の慣習。1文字ずつ
縦に積むと読めない）。日本語と混ざった行は区間ごとに、日本語は縦、欧文は横倒しで積む。
文字は `roll` と同じフォントの探し方（fontconfig、入っていなければ断る）。

`Sing` はフレーム番号にも時刻にも依らない配置だけを持つ（pickle できる）。描くのは
`draw()` で、文字の絵は書き出し1回ぶん作り置く（呼ぶ側が渡す辞書）。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from cymatics.model.color import parse as parse_color
from PIL import Image, ImageDraw, ImageFont

from . import roll
from .doc import is_number, notes_dropped
from .lines import Line

#: 出し方 → 置ける位置（最初が既定）
MODES: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "karaoke": ("bottom", "top"), "vertical": ("right", "left")})

#: 書ける項目と既定値（`position` は出し方ごとの既定）
DEFAULTS: Mapping[str, Any] = MappingProxyType({
    "mode": "karaoke",
    "position": "",
    "color": "255,255,255",
    "band": "0,0,0",
    "band_alpha": 0.45,
    "font": "noto-sans",
    "weight": "Bold",
    "size": 0.05,               # 文字の高さ ÷ 画面の高さ
    "margin": 0.04,             # 画面の端から帯（縦書きは列）まで ÷ 画面の高さ
    "line": 1.5,                # 段（縦書きは列）の送り ÷ 文字の高さ
    "lead": 1.0,                # セクションの頭の行を、歌い出しの何秒前から出すか
    "fade": 0.3,                # 浮かぶ・消える秒数
})

#: 数の項目の範囲（両端を含む）
RANGES: Mapping[str, tuple[float, float]] = MappingProxyType({
    "band_alpha": (0.0, 1.0), "size": (0.01, 0.2), "margin": (0.0, 0.4),
    "line": (1.0, 4.0), "lead": (0.0, 10.0), "fade": (0.0, 5.0)})

#: 次の行が来なくても（セクションの最後の行の後ろが長い間奏でも）、歌い出しから
#: 出しておく秒数の目安: HOLD_BASE + 1文字あたり HOLD_PER_CHAR
HOLD_BASE, HOLD_PER_CHAR = 1.5, 0.45
#: 帯が文字からはみ出す幅 ÷ 文字の高さ
PAD = 0.5
#: 段（列）の長さのうち、行が使ってよい割合（はみ出す行は縮める）
FIT = 0.94
#: 縦書きで、横倒しにした欧文の前後の空き ÷ 文字の高さ
RUN_GAP = 0.3
#: 段（列）の数
SLOTS = 2
OPAQUE = 255


@dataclass(frozen=True)
class Sing:
    lines: tuple[Line, ...]
    #: セクションごとの (始まり, 終わり) 秒
    spans: tuple[tuple[float, float], ...]
    size: tuple[int, int]
    px: int
    #: `credits` の中身（既定値で埋めたもの）。pickle できる形
    options: tuple[tuple[str, Any], ...]
    font: tuple[str, int]

    @property
    def cfg(self) -> Mapping[str, Any]:
        return MappingProxyType(dict(self.options))


def _filled(doc: Mapping[str, Any]) -> dict[str, Any]:
    cfg = {**DEFAULTS, **notes_dropped(doc)}
    if not cfg["position"] and cfg["mode"] in MODES:
        cfg["position"] = MODES[cfg["mode"]][0]
    return cfg


def problems(doc: Any, root: Path | None = None) -> list[str]:
    """`credits`（karaoke / vertical）の駄目な理由を全部。"""
    if not isinstance(doc, Mapping):
        return ["credits は {項目: 値}"]
    cfg = _filled(doc)
    bad = ["credits の知らない項目: %s（%s では）" % (k, cfg["mode"])
           for k in sorted(set(notes_dropped(doc)) - set(DEFAULTS))]
    if cfg["position"] not in MODES.get(cfg["mode"], ()):
        bad.append("credits.position=%r は %s のどれか（%s では）"
                   % (cfg["position"], " / ".join(MODES.get(cfg["mode"], ())), cfg["mode"]))
    bad += ["credits.%s=%r は %s..%s の数" % (k, cfg[k], lo, hi)
            for k, (lo, hi) in RANGES.items() if not (is_number(cfg[k]) and lo <= cfg[k] <= hi)]
    for k in ("band", "color"):
        try:
            parse_color(str(cfg[k]))
        except (ValueError, TypeError) as e:
            bad.append("credits.%s=%r（%s）" % (k, cfg[k], e))
    try:
        roll._font(roll.find_font(str(cfg["font"]), str(cfg["weight"]), root), roll.PROBE_PX,
                   str(cfg["weight"]))
    except (OSError, ValueError) as e:
        bad.append("credits.font=%r / weight=%r: %s" % (cfg["font"], cfg["weight"], e))
    return bad


def layout(lines: tuple[Line, ...], spans: tuple[tuple[float, float], ...],
           size: tuple[int, int], cfg: Mapping[str, Any], root: Path | None = None) -> Sing:
    cfg = _filled(cfg)
    where = roll.find_font(str(cfg["font"]), str(cfg["weight"]), root)
    px = max(roll.MIN_PX, int(round(cfg["size"] * size[1])))
    return Sing(lines, spans, size, px, tuple(sorted(cfg.items())), where)


# ------------------------------------------------------------- 時刻
def until(ln: Line) -> float:
    """行を出しておく終わり。次の行の歌い出しか、歌い終えて少し経つまで。"""
    return min(ln.end, ln.start + HOLD_BASE + HOLD_PER_CHAR * len(ln.text))


def span(sg: Sing, i: int) -> tuple[float, float]:
    """行 i を出しておく [始め, 終わり)。同じセクションの前の行の歌い出しから（セクション
    の頭の行は `lead` 秒前から）、`until` まで。"""
    ln = sg.lines[i]
    prev = sg.lines[i - 1] if i > 0 and sg.lines[i - 1].section == ln.section else None
    return (prev.start if prev is not None else ln.start - sg.cfg["lead"]), until(ln)


def shown(sg: Sing, a: float, b: float, t: float) -> float:
    """[a, b) に出すものの、時刻 t の濃さ 0..1（`fade` 秒で浮かび、消える）。"""
    if not a <= t < b:
        return 0.0
    f = sg.cfg["fade"]
    return 1.0 if f <= 0 else min(1.0, (t - a) / f, (b - t) / f)


def on_screen(sg: Sing, t: float) -> list[tuple[int, float]]:
    """時刻 t に出ている行: [(行の番号, 濃さ)]。多くて2行（段が交互なので重ならない）。"""
    return [(i, k) for i in range(len(sg.lines)) for k in [shown(sg, *span(sg, i), t)]
            if k > 0]


# ------------------------------------------------------------- 文字の絵
def _font(sg: Sing) -> ImageFont.FreeTypeFont:
    return roll._font(sg.font, sg.px, sg.cfg["weight"])


def is_cjk(text: str) -> bool:
    """かな・漢字・全角の記号を含むか。"""
    return any("　" <= ch <= "鿿" or "豈" <= ch <= "￯" for ch in text)


def runs(text: str) -> list[tuple[str, bool]]:
    """行を日本語の区間と欧文の区間に分ける: [(文字, 日本語か)]。空白は前の区間に付ける。"""
    out: list[tuple[str, bool]] = []
    for ch in text:
        cjk = is_cjk(ch) if not ch.isspace() else (out[-1][1] if out else False)
        if out and out[-1][1] == cjk:
            out[-1] = (out[-1][0] + ch, cjk)
        else:
            out.append((ch, cjk))
    return [(t, c) for t, c in out if t.strip()]


def _glyphs(sg: Sing, text: str, vertical: bool) -> Image.Image:
    """1区間の文字（RGBA、透明の地）。`vertical` なら縦の字形で上から下へ。"""
    font, rgb = _font(sg), parse_color(str(sg.cfg["color"]))[0]
    kw = {"direction": "ttb", "features": ["vert"]} if vertical else {}
    x0, y0, x1, y1 = font.getbbox(text, **kw)
    img = Image.new("RGBA", (max(1, x1 - min(x0, 0)), max(1, y1 - min(y0, 0))), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((-min(x0, 0), -min(y0, 0)), text, font=font,
                             fill=(*rgb, OPAQUE), **kw)
    return img


def _stacked(sg: Sing, text: str) -> Image.Image:
    """縦書きの1行。日本語の区間は縦の字形、欧文の区間は横に書いて右へ90度倒し、
    上から積む（列の中で中央揃え）。"""
    parts = [_glyphs(sg, t.strip(), True) if cjk else
             _glyphs(sg, t.strip(), False).rotate(-90, expand=True) for t, cjk in runs(text)]
    gap = int(sg.px * RUN_GAP)
    w = max(p.width for p in parts)
    out = Image.new("RGBA", (w, sum(p.height for p in parts) + gap * (len(parts) - 1)),
                    (0, 0, 0, 0))
    y = 0
    for p in parts:
        out.alpha_composite(p, ((w - p.width) // 2, y))
        y += p.height + gap
    return out


def _fit(img: Image.Image, room: float, vertical: bool) -> Image.Image:
    """段（列）の長さ `room` に収まらなければ、縦横比のまま縮める。"""
    long = img.height if vertical else img.width
    if long <= room:
        return img
    k = room / long
    return img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.LANCZOS)


def line_image(sg: Sing, text: str, cache: dict) -> Image.Image:
    """1行の文字の絵。段（列）に収まる大きさで、書き出し1回ぶん作り置く。"""
    vertical = sg.cfg["mode"] == "vertical"
    key = ("line", text)
    if key not in cache:
        w, h = sg.size
        room = (h * (1 - 2 * sg.cfg["margin"]) if vertical else w) * FIT
        img = _stacked(sg, text) if vertical else _glyphs(sg, text, False)
        cache[key] = _fit(img, room, vertical)
    return cache[key]


def faded(img: Image.Image, k: float) -> Image.Image:
    """不透明度を `k` 倍した絵。"""
    if k >= 1:
        return img
    out = img.copy()
    out.putalpha(img.getchannel("A").point(lambda a: int(round(a * max(k, 0.0)))))
    return out


# ------------------------------------------------------------- 置く
def band_box(sg: Sing) -> tuple[int, int, int, int]:
    """裏の帯の (左, 上, 右, 下)。横は画面の幅で2段、縦は画面の高さで2列。"""
    w, h = sg.size
    m, thick = int(h * sg.cfg["margin"]), int(SLOTS * sg.px * sg.cfg["line"] + 2 * sg.px * PAD)
    if sg.cfg["mode"] == "karaoke":
        top = m if sg.cfg["position"] == "top" else h - m - thick
        return 0, top, w, top + thick
    left = m if sg.cfg["position"] == "left" else w - m - thick
    return left, m, left + thick, h - m


def slot_origin(sg: Sing, img: Image.Image, slot: int) -> tuple[int, int]:
    """段（列）`slot` に置く絵の左上。横は中央揃え、縦は上揃えで右の列から。"""
    x0, y0, x1, _ = band_box(sg)
    step, pad = sg.px * sg.cfg["line"], sg.px * PAD
    if sg.cfg["mode"] == "karaoke":
        return int((sg.size[0] - img.width) / 2), int(y0 + pad + slot * step
                                                       + (step - img.height) / 2)
    right = x1 - pad - slot * step
    return int(right - step + (step - img.width) / 2), int(y0 + pad)


def draw(img: Image.Image, t: float, sg: Sing, cache: dict) -> Image.Image:
    """時刻 t の画面に歌詞を描く。`cache` は文字の絵の作り置き。"""
    lit = on_screen(sg, t)
    if not lit:
        return img
    out = img.convert("RGBA")
    layer = Image.new("RGBA", out.size, (0, 0, 0, 0))
    rgb = parse_color(str(sg.cfg["band"]))[0]
    alpha = int(round(OPAQUE * sg.cfg["band_alpha"] * max(k for _, k in lit)))
    ImageDraw.Draw(layer).rectangle(band_box(sg), fill=(*rgb, alpha))
    for i, k in lit:
        pic = faded(line_image(sg, sg.lines[i].text, cache), k)
        layer.alpha_composite(pic, slot_origin(sg, pic, i % SLOTS))
    out.alpha_composite(layer)
    return out.convert("RGB")
