"""ライブ動画の宣言（`<入力>/live.json`）を読む。**歌詞も音源も絵も要らない。**

    {
      "title": "Ignite @ Zepp",
      "files": {"video": "Live.mp4"},              ← ライブ動画1本。音も絵もここから
      "base": {"effect": "motif", "params": {...}},  ← cymatics の preset か effect と引数
      "overlays": [{"effect": "crowd", ...}],       ← 重ねる層（`overlay.py`）
      "policy": {"glow_lo": 0.6, "glow_hi": 1.6},   ← 写像（`policy.py`）
      "window": {"bars": 8, "bpm": 0, "spread": 2}  ← 採点の区切り（無くてもいい）
    }

- 見た目を動かすのは**動画そのものの盛り上がり（`hype`）だけ**。歌詞が無いので
  受容や昂ぶりの軸は無い。∴ `policy` の `*_by` は既定で全部 `hype` で、ほかの軸を
  書いたら断る（`overlays` の `moods` も同じ）
- `window.bars` 小節ごとに区切って採点する。`bpm` が 0 なら音から推定（倍や半分に
  ずれることがある——ずれたら手で書く）。`spread` は区切りの中ほどの前後何秒からも
  フレームを取るか
- `_` で始まる鍵は注記。**知らない項目・足りない項目・無いファイルは全部並べて断る**
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from . import dims
from . import overlay as overlay_mod
from . import policy as policy_mod
from .manifest import base_of

KEYS = ("title", "files", "base", "overlays", "policy", "window")
WINDOW: Mapping[str, float] = MappingProxyType({"bars": 8, "bpm": 0.0, "spread": 2.0})

#: ライブ動画の写像の既定。軸は全部 `hype`（それしか無い）
POLICY = policy_mod.Policy(color_by="hype", wobble_by="hype", glow_by="hype", gain_by="hype")


@dataclass(frozen=True)
class Live:
    root: Path
    title: str
    video: str
    effect: str
    params: Mapping[str, Any]
    overlays: tuple[overlay_mod.Overlay, ...]
    policy: policy_mod.Policy
    bars: int
    bpm: float
    spread: float


def _window_problems(w: Any) -> list[str]:
    if not isinstance(w, Mapping):
        return ["window は {\"bars\": ..., \"bpm\": ..., \"spread\": ...}"]
    w = overlay_mod.notes_dropped(w)
    bad = ["window の知らない項目: %s" % k for k in sorted(set(w) - set(WINDOW))]
    for k in set(w) & set(WINDOW):
        v = w[k]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
            bad.append("window.%s は 0 以上の数（%r）" % (k, v))
    if "bars" in w and (not isinstance(w["bars"], int) or w["bars"] < 1):
        bad.append("window.bars は 1 以上の整数（%r）" % w["bars"])
    return bad


def _axis_problems(doc: Mapping[str, Any]) -> list[str]:
    """ライブ動画には `hype` しか無い。ほかの軸を使っていたら断る。"""
    pol = overlay_mod.notes_dropped(doc.get("policy", {}))
    bad = ["policy.%s=%s: ライブ動画で使える軸は %s だけ" % (k, v, " / ".join(dims.AUDIENCE))
           for k, v in pol.items() if k in policy_mod.BY and v not in dims.AUDIENCE]
    for i, ov in enumerate(doc.get("overlays", [])):
        moods = overlay_mod.notes_dropped(ov.get("moods", {})) if isinstance(ov, Mapping) else {}
        bad += ["overlays[%d].moods.%s: ライブ動画で使える軸は %s だけ"
                % (i, k, " / ".join(dims.AUDIENCE))
                for k, sw in moods.items()
                if isinstance(sw, Mapping) and sw.get("by") not in dims.AUDIENCE]
    return bad


def _file_problems(root: Path, files: Any) -> list[str]:
    if not isinstance(files, Mapping) or set(overlay_mod.notes_dropped(files)) != {"video"}:
        return ["files は {\"video\": ライブ動画}"]
    path = root / files["video"]
    return [] if path.is_file() else ["video が無い: %s" % path.resolve()]


def problems(doc: Mapping[str, Any], root: Path) -> list[str]:
    """live.json の駄目な理由を全部。空なら通る。"""
    doc = overlay_mod.notes_dropped(doc)
    bad = ["知らない項目: %s" % k for k in sorted(set(doc) - set(KEYS))]
    bad += ["%s が無い" % k for k in ("title", "files", "base") if k not in doc]
    bad += _file_problems(root, doc.get("files", {}))
    try:
        base_of(doc.get("base", {}))
    except (ValueError, KeyError) as e:
        bad.append(str(e))
    bad += overlay_mod.problems(doc.get("overlays", []))
    bad += _window_problems(doc.get("window", {})) + _axis_problems(doc)
    try:
        policy_mod.from_mapping(overlay_mod.notes_dropped(doc.get("policy", {})), POLICY)
    except ValueError as e:
        bad.append("policy: " + str(e).replace("\n  ", " / "))
    return bad


def load(root: str | Path) -> Live:
    root = Path(root)
    path = root / "live.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    bad = problems(doc, root)
    if bad:
        raise ValueError("%s が通らない:\n  %s" % (path, "\n  ".join(bad)))
    doc = overlay_mod.notes_dropped(doc)
    effect, params = base_of(doc["base"])
    w = {**WINDOW, **overlay_mod.notes_dropped(doc.get("window", {}))}
    return Live(root, doc["title"], str((root / doc["files"]["video"]).resolve()), effect,
                params, overlay_mod.from_list(doc.get("overlays", [])),
                policy_mod.from_mapping(overlay_mod.notes_dropped(doc.get("policy", {})),
                                        POLICY),
                int(w["bars"]), float(w["bpm"]), float(w["spread"]))
