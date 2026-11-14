"""宣言の JSON（song.json / live.json）と保存した採点の JSON の、読み書きの決まりごと。

どの宣言も同じ決まりで読む——`_` で始まる鍵は注記、数は bool を数と見なさない、
感情で動かす項目は `{"by": 軸, "lo": 数, "hi": 数}`。決まりはここにだけ書く
（同じ層どうしは依存できないので、使う側が各々に写すと少しずつずれる）。

採点の保存ファイルは `{"format": 版, ...}`。読めない版は断る。
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: 感情で動かす1項目の書き方（`moods`）
SWING_KEYS: tuple[str, ...] = ("by", "lo", "hi")


def notes_dropped(doc: Mapping[str, Any]) -> dict[str, Any]:
    """`_` で始まる鍵（注記）を落とす。"""
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def is_number(v: Any) -> bool:
    """JSON の数か。`true` / `false` は数ではない（Python では int の仲間）。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def write(path: str | Path, doc: Mapping[str, Any]) -> None:
    """人が読める JSON（日本語はそのまま、字下げ 2）。"""
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def read_versioned(path: str | Path, fmt: int, what: str) -> dict[str, Any]:
    """`{"format": fmt, ...}` の JSON。版が違えば `what` を添えて断る。"""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("format") != fmt:
        raise ValueError("%s: %sの形式が違う（format=%d を期待）" % (path, what, fmt))
    return doc
