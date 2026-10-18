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
      "keys": {"Verse 1": "verse.jpg", "Chorus 1": "chorus.jpg"},
                                            ← セクションごとのキー画像。背景がその画像に
                                              切り替わり、effect もその画像に合わせて置く
      "tempo": {"bars_calm": 8},            ← 書けば流れる速さを拍と気持ちで変える（`tempo.py`）
      "overlays": [{"effect": "crowd", ...}],  ← 主役の上や下に重ねる層（`overlay.py`）
      "audience": {"lead": 12.3, "spread": 2}  ← 聴衆の映像の時刻合わせと取り方（無くてもいい）
    }

`files.audience`（聴衆の映像）があれば、聴衆の盛り上がり（`hype`）で見た目を
動かせる。無いのに `hype` を使っていたら断る。

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

from . import dims
from . import overlay as overlay_mod
from . import policy as policy_mod
from . import scenes as scenes_mod
from . import tempo as tempo_mod

FILES_REQUIRED = ("lyrics", "audio", "image")
FILES_OPTIONAL = ("opening", "closing", "published", "audience")
KEYS = ("title", "genre", "files", "base", "policy", "sections", "tempo", "overlays",
        "audience", "keys")
#: `audience` に書けるもの。`lead` は手で書いた時刻合わせ（書けば音で合わせない）
AUDIENCE_KEYS = ("lead", "spread")


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
    #: 聴衆の映像の時刻合わせ（秒）。None なら音で合わせる
    lead: float | None = None
    #: 聴衆の映像から、セクションの中ほどの前後何秒からも取るか
    spread: float = 2.0
    #: セクション名 → キー画像の絶対パス。名前の照合は歌詞と合わせる `workflow` で
    keys: Mapping[str, str] = field(default_factory=dict)

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


def _keys(root: Path, doc: Any) -> tuple[dict[str, str], list[str]]:
    """`keys`（セクション名 → キー画像）。書き方の駄目と、無いファイルを全部。"""
    if not isinstance(doc, Mapping):
        return {}, ["keys は {セクション名: 画像のファイル名}"]
    doc = _notes_dropped(doc)
    bad = ["keys.%s は画像のファイル名" % k for k, v in doc.items() if not isinstance(v, str)]
    out = {k: str((root / v).resolve()) for k, v in doc.items() if isinstance(v, str)}
    bad += ["keys.%s の画像が無い: %s" % (k, p) for k, p in out.items() if not Path(p).is_file()]
    return out, bad


def _keys_problems(doc: Mapping[str, Any], effect: str, params: Mapping[str, Any]) -> list[str]:
    """キー画像の背景は動画になる。cymatics は動画の背景で明滅（beam）を使えない。"""
    if not _notes_dropped(doc.get("keys", {})):
        return []
    from cymatics import effects

    beam = {f.name: f.default for f in effects.get(effect).fields}.get("beam", 0)
    if float(params.get("beam", beam)) > 0:
        return ["keys: キー画像の背景は動画になるので明滅は使えない"
                "（base の params に \"beam\": 0 と書く）"]
    return []


def _audience_problems(doc: Mapping[str, Any]) -> list[str]:
    """`audience` の書き方と、聴衆の軸を映像なしで使っていないか。"""
    cfg = _notes_dropped(doc.get("audience", {}))
    bad = ["audience の知らない項目: %s" % k for k in sorted(set(cfg) - set(AUDIENCE_KEYS))]
    bad += ["audience.%s は数" % k for k in AUDIENCE_KEYS
            if k in cfg and (not isinstance(cfg[k], (int, float)) or isinstance(cfg[k], bool))]
    if "spread" in cfg and not bad and cfg["spread"] < 0:
        bad.append("audience.spread は 0 以上")
    if "audience" in doc.get("files", {}):
        return bad
    used = [k for k, v in _notes_dropped(doc.get("policy", {})).items()
            if k in policy_mod.BY and v in dims.AUDIENCE]
    used += ["overlays の moods.%s" % k for ov in doc.get("overlays", [])
             if isinstance(ov, Mapping)
             for k, sw in _notes_dropped(ov.get("moods", {})).items()
             if isinstance(sw, Mapping) and sw.get("by") in dims.AUDIENCE]
    bad += ["%s が聴衆の軸を使っているのに files.audience（聴衆の映像）が無い" % u
            for u in used]
    return bad + (["audience を書いたのに files.audience が無い"] if cfg else [])


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
    bad += _keys(root, doc.get("keys", {}))[1]
    try:
        effect, params = base_of(doc.get("base", {}))
        bad += _keys_problems(doc, effect, params)
        bad += ["sections: " + p for p in scenes_mod.problems(doc.get("sections", {}), effect)]
        bad += _tempo_problems(doc, effect)
    except (ValueError, KeyError) as e:
        bad.append(str(e))
    bad += overlay_mod.problems(doc.get("overlays", []))
    bad += _audience_problems(doc)
    try:
        policy_mod.from_mapping(_notes_dropped(doc.get("policy", {})))
    except ValueError as e:
        bad.append("policy: " + str(e).replace("\n  ", " / "))
    return bad


def _audience_of(doc: Mapping[str, Any]) -> tuple[float | None, float]:
    cfg = _notes_dropped(doc.get("audience", {}))
    lead = cfg.get("lead")
    return (None if lead is None else float(lead)), float(cfg.get("spread", 2.0))


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
                overlay_mod.from_list(doc.get("overlays", [])),
                *_audience_of(doc), _keys(root, doc.get("keys", {}))[0])
