"""ファイルの中身のハッシュ。再現の記録と「作り直すか」の判定に使う。

動画も通るので、**丸ごと読まずに 1MiB ずつ**読む。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

#: 1回に読む大きさ
BLOCK = 1 << 20


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(BLOCK), b""):
            h.update(block)
    return h.hexdigest()
