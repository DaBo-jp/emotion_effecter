"""曲の宣言（`<入力>/song.json`）を読む。**曲ごとの決めごとはここに1つだけ書く。**

    {
      "title": "Shape",
      "genre": "...",                       ← 曲ごとに人が入れる（effect の提案で使う）
      "files": {"lyrics": "歌詞_Shape.md", "audio": "Shape.wav", "image": "shape.jpg",
                "opening": "Shape_Opening.mp4", "closing": "Shape_Closing.mp4",
                "published": "Shape.mp4"},
      "base": {"preset": "shape"},          ← cymatics の preset か
              {"effect": "rune", "params": {...}},   ← effect と引数
      "policy": {"warm": "255,120,56", "turn": 0},
      "sections": {"Chorus 1": {"flow": "in"}},  ← セクションごとの流れの向き（`scenes.py`）
      "tempo": {"bars_calm": 8},            ← 書けば流れる速さを拍と気持ちで変える（`tempo.py`）
      "overlays": [{"effect": "crowd", ...}]  ← 主役の上や下に重ねる層（`overlay.py`）
    }

ファイル名は song.json からの相対。`opening` / `closing` / `published` は無くてもいい。
`_` で始まる鍵は注記として読み飛ばす。**知らない項目・足りない項目・無いファイルは
全部並べて断る**（cymatics の Spec と同じ）。effect の引数の検証は cymatics の
Field がする。
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import overlay as overlay_mod
from . import policy as policy_mod
from . import scenes as scenes_mod
from . import tempo as tempo_mod

FILES_REQUIRED = ("lyrics", "audio", "image")
FILES_OPTIONAL = ("opening", "closing", "published")
KEYS = ("title", "genre", "files", "base", "policy", "sections", "tempo", "overlays")


@dataclass(frozen=True)
class Manifest:
    root: Path
    title: str
    genre: str | None
    #: 役割 → 絶対パス。無いものは入らない
    files: Mapping[str, str]
    effect: str
    params: Mapping[str, Any]
    policy: Mapping[str, Any] = field(default_factory=dict)
    #: セクション名 → 変える引数。名前の照合は歌詞と合わせる `scenes.build()` で
    sections: Mapping[str, Any] = field(default_factory=dict)
    #: 流れる速さを拍と気持ちで変えるか。None なら変えない（`tempo` を書いていない）
    tempo: tempo_mod.Tempo | None = None
    #: 主役の上や下に重ねる層。書いていなければ空（素の1枚）
    overlays: tuple[overlay_mod.Overlay, ...] = ()

    def file(self, role: str) -> str | None:
        return self.files.get(role)


def _notes_dropped(doc: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def base_of(doc: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """`{"preset": ...}` か `{"effect": ..., "params": {...}}` → (effect, 引数)。"""
    from cymatics import presets

    doc = _notes_dropped(doc)
    if set(doc) == {"preset"}:
        return presets.get(doc["preset"])
    if "effect" in doc and set(doc) <= {"effect", "params"}:
        return doc["effect"], overlay_mod.flat(doc.get("params", {}))
    raise ValueError('base は {"preset": 名前} か {"effect": 名前, "params": {...}}（%s）'
                     % ", ".join(sorted(doc)))


def _files(root: Path, files: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    bad = ["files に %s が無い" % r for r in FILES_REQUIRED if r not in files]
    bad += ["files の知らない役割: %s" % r
            for r in sorted(set(files) - set(FILES_REQUIRED) - set(FILES_OPTIONAL))]
    out = {r: str((root / n).resolve()) for r, n in files.items()}
    bad += ["%s が無い: %s" % (r, p) for r, p in out.items() if not Path(p).is_file()]
    return out, bad


def _tempo_problems(doc: Mapping[str, Any], effect: str) -> list[str]:
    """`tempo` の駄目な理由。effect が `speed` を持たなければ速さを変えようが無い。"""
    if "tempo" not in doc:
        return []
    from cymatics import effects

    bad = [] if any(f.name == "speed" for f in effects.get(effect).fields) else [
        "tempo: %s は speed を持たない" % effect]
    try:
        tempo_mod.from_mapping(_notes_dropped(doc["tempo"]))
    except (ValueError, AttributeError) as e:
        bad.append("tempo: " + str(e).replace("\n  ", " / "))
    return bad


def problems(doc: Mapping[str, Any], root: Path) -> list[str]:
    """song.json の駄目な理由を全部。空なら通る。"""
    doc = _notes_dropped(doc)
    bad = ["知らない項目: %s" % k for k in sorted(set(doc) - set(KEYS))]
    bad += ["%s が無い" % k for k in ("title", "files", "base") if k not in doc]
    bad += _files(root, doc.get("files", {}))[1]
    try:
        effect = base_of(doc.get("base", {}))[0]
        bad += ["sections: " + p for p in scenes_mod.problems(doc.get("sections", {}), effect)]
        bad += _tempo_problems(doc, effect)
    except (ValueError, KeyError) as e:
        bad.append(str(e))
    bad += overlay_mod.problems(doc.get("overlays", []))
    try:
        policy_mod.from_mapping(_notes_dropped(doc.get("policy", {})))
    except ValueError as e:
        bad.append("policy: " + str(e).replace("\n  ", " / "))
    return bad


def load(root: str | Path) -> Manifest:
    root = Path(root)
    path = root / "song.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    bad = problems(doc, root)
    if bad:
        raise ValueError("%s が通らない:\n  %s" % (path, "\n  ".join(bad)))
    files, _ = _files(root, doc["files"])
    effect, params = base_of(doc["base"])
    return Manifest(root, doc["title"], doc.get("genre") or None, files, effect, params,
                _notes_dropped(doc.get("policy", {})),
                _notes_dropped(doc.get("sections", {})),
                tempo_mod.from_mapping(_notes_dropped(doc["tempo"])) if "tempo" in doc else None,
                overlay_mod.from_list(doc.get("overlays", [])))
