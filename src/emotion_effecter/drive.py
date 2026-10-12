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
"""
from __future__ import annotations

import contextlib
import os
import types
from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from cymatics import effects
from cymatics.render import pipeline

from .policy import Look, Policy, look
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


def in_scenes(m, img, ctx, fr, parts):
    """セクションの引数ごとに描き重ねる。濃さは `fr.wa` に掛けて分け合う。"""
    for over, k in parts:
        f = fr if k == 1.0 else replace(fr, wa=fr.wa * k)
        img = m.draw(img, variant(m, ctx, over), f) or img
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


def chunk_safe(effect: str) -> bool:
    """区間に分けて書き出しても通しと同じ絵になる effect か。"""
    return effects.get(effect).module.ENVELOPE == "precomputed"


def render(effect: str, params: Mapping[str, Any], tl: Timeline | None,
           pol: Policy = Policy(), sc: Scenes | None = None):
    """平らな Spec 1つで書き出す。`tl=None` かつ `sc=None` なら素の cymatics と同じ。

    Spec の検証は cymatics の `pipeline.render()` が、Policy の検証はここがする。
    """
    pol.check()
    eff = effects.get(effect)
    s = eff.spec_from(**params)
    if sc is not None and sc.is_plain:
        sc = None
    return pipeline.render(wrap(eff, tl, pol, sc) if tl or sc else eff, s)


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
    effect, params, tl, pol, sc, chunk = job
    fps = int(params["fps"])
    p = {**params, **chunk.window(fps), "out": chunk.path, "no_audio": True}
    with open(os.devnull, "w") as quiet, contextlib.redirect_stdout(quiet), \
            contextlib.redirect_stderr(quiet):
        render(effect, p, tl, pol, sc)
    return chunk.path


def render_chunks(effect: str, params: Mapping[str, Any], tl: Timeline | None,
                  chunks: list[Chunk], pol: Policy = Policy(), jobs: int = 0,
                  sc: Scenes | None = None) -> list[str]:
    """区間ごとに並列で書き出す（音なし）。戻り値は区間の動画、順番どおり。

    precomputed の包絡は初回にキャッシュへ書かれるので、先に1枚描いて温めておく
    ——並列で同時に書くと壊れたキャッシュを読みかねない。
    """
    params = effects.get(effect).spec_from(**params)
    with open(os.devnull, "w") as quiet, contextlib.redirect_stdout(quiet), \
            contextlib.redirect_stderr(quiet):
        render(effect, {**params, "preview": chunks[0].path + ".warm.png",
                        "preview_at": chunks[0].f0 / int(params["fps"])}, tl, pol, sc)
    os.remove(chunks[0].path + ".warm.png")
    work = [(effect, params, tl, pol, sc, c) for c in chunks]
    with ProcessPoolExecutor(max_workers=jobs or min(len(chunks), os.cpu_count() or 1)) as ex:
        return list(ex.map(_render_chunk, work))
