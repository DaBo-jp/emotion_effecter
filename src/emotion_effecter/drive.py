"""感情曲線で cymatics の effect を毎フレーム動かす。**cymatics は改造しない。**

cymatics の pipeline は effect を外から受け取る（`pipeline.render(eff, spec)`）。
そこへ「`draw()` だけ包んだ effect」を渡す。包んだ `draw()` は、そのフレームの
`Look` で `ctx`（色・glow）と `fr`（バンドのレベル）を差し替えてから元の
`draw()` を呼ぶ。

- 宣言・stage()・導出値・包絡は元の effect のまま ∴ Spec の検証も同じ
- 差し替えはフレーム番号だけで決まる ∴ 分割書き出しでも同じ絵
- セクションごとに変える引数（`scenes.Scenes`）があれば、その引数で `stage()` と
  導出値を作り直した ctx で描く。境界では古い引数と新しい引数で2回描き、
  濃さ（`fr.wa`）を分け合う
  （ただし包絡が streaming の effect は cymatics 側が区間依存。`chunk_safe()`）
- 重ねる層（`overlay.Overlay`）があれば cymatics の重ね合わせで描く。主役の層は
  上と同じ包み方、重ねる層は感情で動かす項目（`moods`）だけを差し替える。
  無ければ今までと同じ1枚の道を通る ∴ 画素は変わらない
- 画面の色調（灰色・セピア）は層ではなく、重ね終えた画面に掛ける（cymatics の
  `finish`）。動かさない Policy なら `finish` を渡さない ∴ 画素は変わらない
"""
from __future__ import annotations

import contextlib
import os
import types
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from cymatics import effects
from cymatics.model import holes as holes_mod
from cymatics.render import pipeline
from PIL import Image

from . import grade
from .overlay import Overlay
from .policy import Look, Policy, look, tone, toned
from .scenes import Scenes
from .timeline import Timeline


def apply(ctx, fr, lk: Look):
    """`Look` を cymatics の (ctx, fr) に当てる。dtype は保つ（画素が変わるため）。"""
    s = {**ctx.s, "glow": ctx.s.get("glow", 0.0) * lk.glow}
    levels = fr.levels
    if levels.size and lk.gain != 1.0:
        levels = np.clip(levels * lk.gain, 0.0, 1.0).astype(levels.dtype)
    return replace(ctx, col=lk.color, s=s), replace(fr, levels=levels)


def variant(m, ctx, over: Mapping[str, Any]):
    """引数を `over` で差し替えた ctx。`derive()` と `stage()` を作り直す。"""
    if not over:
        return ctx
    s = {**ctx.s, **over}
    fn = getattr(m, "derive", None)
    d = {**ctx.derived, **(fn(s, ctx.w, ctx.h, {}) if fn else {})}
    c = replace(ctx, s=s, derived=d)
    return replace(c, work=m.stage(c))


def section_holes(ctx, over: Mapping[str, Any]) -> np.ndarray | None:
    """そのセクションの透かす円の濃さ（画面の大きさ）。円が無ければ None。

    cymatics の円は画面の座標なので、**箱も回しも無い層だけ**に掛けられる。
    """
    if not over.get("holes"):
        return None
    if ctx.quad is not None or not ctx.box.is_full:
        raise ValueError("セクションごとの holes は、箱（box_*）も回し・台形も無い層だけ")
    unit = over.get("holes_unit", ctx.s.get("holes_unit", "px"))
    return holes_mod.of(over["holes"], unit, ctx.plan.width, ctx.plan.height)


def _holed(m, img, ctx, fr, k: np.ndarray):
    """描く前との差を `k` 倍にして描く（cymatics の pipeline の円と同じ式）。"""
    before = np.array(img, np.float32)
    after = np.asarray(m.draw(img, ctx, fr) or img, np.float32)
    out = before + (after - before) * k[..., None]
    return Image.fromarray(np.clip(np.rint(out), 0, 255).astype(np.uint8))


def in_scenes(m, img, ctx, fr, parts):
    """セクションの引数ごとに描き重ねる。濃さは `fr.wa` に掛けて分け合う。
    セクションに透かす円があれば、その層の絵だけを円で薄める。"""
    for over, k in parts:
        f = fr if k == 1.0 else replace(fr, wa=fr.wa * k)
        holes = section_holes(ctx, over)
        c = variant(m, ctx, over)
        img = m.draw(img, c, f) or img if holes is None else _holed(m, img, c, f, holes)
    return img


def wrap(eff: effects.Effect, tl: Timeline | None, pol: Policy,
         sc: Scenes | None = None) -> effects.Effect:
    """`draw()` だけ包んだ effect。他の属性は元のモジュールのものをそのまま持つ。"""
    mod = types.ModuleType("mood_" + eff.name)
    mod.__dict__.update({k: v for k, v in vars(eff.module).items()
                         if not k.startswith("__")})
    inner = eff.module

    def draw(img, ctx, fr):
        if tl is not None:
            ctx, fr = apply(ctx, fr, look(tl.frame(fr.f), fr.t, ctx.col, pol))
        if sc is None:
            return inner.draw(img, ctx, fr)
        return in_scenes(inner, img, ctx, fr, sc.at(fr.f))

    mod.draw = draw
    return replace(eff, module=mod)


def wrap_overlay(eff: effects.Effect, ov: Overlay, tl: Timeline | None) -> effects.Effect:
    """重ねる層の `draw()` を包む。そのフレームの感情で `moods` の項目を差し替える。"""
    if tl is None or not ov.swings:
        return eff
    mod = types.ModuleType("mood_" + eff.name)
    mod.__dict__.update({k: v for k, v in vars(eff.module).items()
                         if not k.startswith("__")})
    inner = eff.module

    def draw(img, ctx, fr):
        return inner.draw(img, variant(inner, ctx, ov.at(tl.frame(fr.f))), fr)

    mod.draw = draw
    return replace(eff, module=mod)


def finisher(tl: Timeline | None, pol: Policy):
    """重ね終えた画面の仕上げ（cymatics の `finish`）。色調を動かさないなら None。"""
    if tl is None or not toned(pol):
        return None

    def finish(img, f):
        return grade.apply(img, *tone(tl.frame(f), pol))

    return finish


def chunk_safe(effect: str, ovs: Sequence[Overlay] = ()) -> bool:
    """区間に分けて書き出しても通しと同じ絵になるか。**重ねる層も全部見る。**"""
    return all(effects.get(e).module.ENVELOPE == "precomputed"
               for e in (effect, *(ov.effect for ov in ovs)))


def _overlay_layer(key: str, ov: Overlay, main: Mapping[str, Any]):
    """重ねる層1枚の Layer。**フェードは主役から引き継ぐ**（書けば層の値が勝つ）。"""
    from cymatics.model import scope
    from cymatics.model.compose import Layer

    eff = effects.get(ov.effect)
    both = {f.name for f in eff.fields if scope.scope_of(f.group) == "both"}
    own = {f.name for f in eff.fields if scope.scope_of(f.group) != "shared"}
    fill = {f.name: "-" for f in eff.fields if f.required}
    s = eff.spec_from(**{**fill, **{k: main[k] for k in both if k in main},
                         **ov.params})
    return Layer(key, {k: v for k, v in s.items() if k in own})


def _stacked(main: effects.Effect, s: Mapping[str, Any], ovs: Sequence[Overlay],
             tl: Timeline | None):
    """(Composition, 層の名前 → effect)。層は下から under・主役・over の順。"""
    from cymatics.model.compose import Composition, from_spec

    base = from_spec("base", list(main.fields), s)
    keys = ["overlay%d" % i for i in range(len(ovs))]
    lay = {k: _overlay_layer(k, ov, s) for k, ov in zip(keys, ovs)}
    under = [lay[k] for k, ov in zip(keys, ovs) if ov.place == "under"]
    over = [lay[k] for k, ov in zip(keys, ovs) if ov.place == "over"]
    get = {"base": main, **{k: wrap_overlay(effects.get(ov.effect), ov, tl)
                            for k, ov in zip(keys, ovs)}}
    return Composition(base.shared, [*under, *base.layers, *over]), get


def render(effect: str, params: Mapping[str, Any], tl: Timeline | None,
           pol: Policy = Policy(), sc: Scenes | None = None,
           ovs: Sequence[Overlay] = ()):
    """平らな Spec 1つで書き出す。`tl=None` かつ `sc=None` で重ねる層が無ければ
    素の cymatics と同じ。

    Spec の検証は cymatics の `pipeline` が、Policy の検証はここがする。
    """
    pol.check()
    eff = effects.get(effect)
    s = eff.spec_from(**params)
    if sc is not None and sc.is_plain:
        sc = None
    main = wrap(eff, tl, pol, sc) if tl or sc else eff
    finish = finisher(tl, pol)
    if not ovs:
        return pipeline.render(main, s, finish)
    comp, get = _stacked(main, s, ovs, tl)
    return pipeline.render_composition(comp, get.__getitem__, finish)


# ------------------------------------------------------------- 区間に分けて書く
@dataclass(frozen=True)
class Chunk:
    path: str
    f0: int        # 開始フレーム（曲頭から）
    frames: int

    def window(self, fps: int) -> dict[str, float]:
        """cymatics の start / duration。`int(秒 * fps)` で切り捨てられるので
        少しだけ足して、必ずこのフレーム数になるようにする。"""
        return {"start": (self.f0 + 1e-6) / fps, "duration": (self.frames + 1e-6) / fps}


def plan_chunks(f0: int, f1: int, size: int, workdir: str) -> list[Chunk]:
    """[f0, f1) を size フレームずつに割る。"""
    return [Chunk(os.path.join(workdir, "chunk_%03d.mp4" % i), a, min(size, f1 - a))
            for i, a in enumerate(range(f0, f1, size))]


def _render_chunk(job) -> str:
    effect, params, tl, pol, sc, ovs, chunk = job
    fps = int(params["fps"])
    p = {**params, **chunk.window(fps), "out": chunk.path, "no_audio": True}
    with open(os.devnull, "w") as quiet, contextlib.redirect_stdout(quiet), \
            contextlib.redirect_stderr(quiet):
        render(effect, p, tl, pol, sc, ovs)
    return chunk.path


def render_chunks(effect: str, params: Mapping[str, Any], tl: Timeline | None,
                  chunks: list[Chunk], pol: Policy = Policy(), jobs: int = 0,
                  sc: Scenes | None = None, ovs: Sequence[Overlay] = ()) -> list[str]:
    """区間ごとに並列で書き出す（音なし）。戻り値は区間の動画、順番どおり。

    precomputed の包絡は初回にキャッシュへ書かれるので、先に1枚描いて温めておく
    ——並列で同時に書くと壊れたキャッシュを読みかねない。
    """
    params = effects.get(effect).spec_from(**params)
    with open(os.devnull, "w") as quiet, contextlib.redirect_stdout(quiet), \
            contextlib.redirect_stderr(quiet):
        render(effect, {**params, "preview": chunks[0].path + ".warm.png",
                        "preview_at": chunks[0].f0 / int(params["fps"])}, tl, pol, sc, ovs)
    os.remove(chunks[0].path + ".warm.png")
    work = [(effect, params, tl, pol, sc, ovs, c) for c in chunks]
    with ProcessPoolExecutor(max_workers=jobs or min(len(chunks), os.cpu_count() or 1)) as ex:
        return list(ex.map(_render_chunk, work))
