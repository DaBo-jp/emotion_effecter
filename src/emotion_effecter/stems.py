"""曲のフォルダの stem（パートごとの音源）から、リードボーカルを書き起こす。

**stem があるときだけ動くフック。** 曲のフォルダ（`music_data/<曲>/`）に

    stems/              パートごとの音源を並べたフォルダ
    *Stems*.zip         Suno などが書き出す stem の zip（大文字小文字は問わない）

のどちらかがあれば、その中のリードボーカル（名前に `lead vocal` → `vocal` / `vox`。
`backing` は除く）を Whisper（faster-whisper）で単語ごとの時刻つきで書き起こす。

書き起こしは重い（CPU で 5 分の曲に数分）ので `out/<曲>/vocals.json` に置き、**同じ
stem（ハッシュ）と同じモデルなら書き起こし直さない**。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

#: 書き起こしのモデル。small だと日本語の行を落とす（Tin で試した）
MODEL = "medium"
#: 書き起こしに渡す音のサンプリング周波数（Whisper の入力）
SR = 16000
#: vocals.json の版
FORMAT = 1
#: 音源の拡張子
AUDIO = (".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac")

#: 1語 = (歌い始め秒, 歌い終わり秒, 文字)
Word = tuple[float, float, str]


@dataclass(frozen=True)
class Stem:
    """リードボーカルの stem。zip の中なら `member` に名前。"""

    path: Path
    member: str | None = None

    @property
    def name(self) -> str:
        return self.member or self.path.name

    def read(self) -> bytes:
        if self.member is None:
            return self.path.read_bytes()
        with zipfile.ZipFile(self.path) as z:
            return z.read(self.member)


def _rank(name: str) -> int | None:
    """リードボーカルらしさ（小さいほど）。ボーカルでなければ None。"""
    n = Path(name).name.lower()
    if Path(n).suffix not in AUDIO or "backing" in n or "back vocal" in n:
        return None
    if re.search(r"lead\s*vocal", n):
        return 0
    return 1 if re.search(r"vocal|vox", n) else None


def _best(names: list[str]) -> str | None:
    ranked = sorted((r, n) for n in names if (r := _rank(n)) is not None)
    return ranked[0][1] if ranked else None


def find(root: str | Path) -> Stem | None:
    """曲のフォルダのリードボーカルの stem。無ければ None。`stems/` が zip より先。"""
    root = Path(root)
    folder = root / "stems"
    if folder.is_dir():
        best = _best([p.name for p in folder.iterdir() if p.is_file()])
        if best is not None:
            return Stem(folder / best)
    for z in sorted(p for p in root.iterdir() if p.suffix.lower() == ".zip"
                    and "stem" in p.name.lower()):
        with zipfile.ZipFile(z) as zf:
            best = _best([i.filename for i in zf.infolist() if not i.is_dir()])
        if best is not None:
            return Stem(z, best)
    return None


def decode(data: bytes, sr: int = SR) -> np.ndarray:
    """音源のバイト列 → モノラル float32（`sr` Hz）。"""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(sr),
                          "-f", "f32le", "pipe:1"], input=data, capture_output=True, check=True)
    return np.frombuffer(out.stdout, np.float32)


def transcribe(x: np.ndarray, model: str = MODEL) -> list[Word]:
    """Whisper で単語ごとに。言語は日本語に固定（英語の行も英字で返る）。"""
    from faster_whisper import WhisperModel  # 重いので使うときだけ読む

    m = WhisperModel(model, device="cpu", compute_type="int8")
    segs, _ = m.transcribe(x, language="ja", word_timestamps=True,
                           condition_on_previous_text=False)
    return [(float(w.start), float(w.end), w.word) for s in segs for w in (s.words or [])]


def words(stem: Stem, cache: str | Path, redo: bool = False,
          model: str = MODEL) -> tuple[list[Word], np.ndarray]:
    """書き起こし（`cache` にあれば読む）と、声の大きさを測る音（`SR` Hz）。"""
    data = stem.read()
    sha = hashlib.sha256(data).hexdigest()
    x = decode(data)
    cache = Path(cache)
    if not redo and cache.is_file():
        doc = json.loads(cache.read_text(encoding="utf-8"))
        if doc.get("format") == FORMAT and doc.get("sha256") == sha and doc.get("model") == model:
            return [tuple(w) for w in doc["words"]], x
    ws = transcribe(x, model)
    cache.write_text(json.dumps({"format": FORMAT, "stem": stem.name, "sha256": sha,
                                 "model": model, "words": ws}, ensure_ascii=False),
                     encoding="utf-8")
    return ws, x
