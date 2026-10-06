"""層の宣言。**ここが依存の唯一の正。** cymatics と同じ3つを守る。

`tests/test_architecture.py` がこの表と実際のコードを AST で突き合わせる。

1. **関数の外に、副作用を伴うメモリを置かない。** モジュール直下の可変な
   コンテナも、import 時に走る処理も、`global` / `nonlocal` も無し。
   読むだけのデータは `MappingProxyType` と `tuple` で固める。
2. **関数はきちんと区切る。** 実行行 30 行が上限。超えたら2つ以上のことをしている。
3. **同じ層の横依存は禁止。例外なし。** 依存が要るなら同じ層ではない——下に置き直す。
   「ディレクトリ＝層」ではなく、層は順位として宣言し、import は必ず下へ向かう。

cymatics は外の部品なので層を持たない（どの層からも見てよい）。ただし cymatics の
中身を書き換えたり、内部を前提に分岐したりはしない——effect を包んで外から渡すだけ。
"""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

#: モジュール名（`emotion_effecter.` を除く）→ 層の順位。小さいほど下。
#: **import は必ず小さい方へ向かう。同じ数字どうしは依存できない。**
LAYERS: Mapping[str, int] = MappingProxyType({
    # 0 — 何も知らない。値の形と純粋な計算、外部コマンドの包み
    "architecture": 0,
    "dims": 0,            # 感情の次元の名前
    "lyrics": 0,          # 歌詞ファイル
    "beats": 0,           # 音源 → 拍（cymatics の decode だけ使う）
    "video": 0,           # ffmpeg

    # 10 — 次元や歌詞を使う判断。互いに知らない
    "policy": 10,         # 感情 → 見た目。描画を知らない
    "mood": 10,           # lyrics → Jev（区間ごとの感情）
    "elements": 10,       # lyrics → Jev（曲全体の属性）
    "casting": 10,        # 属性 + BPM → effect の候補。描画を知らない
    "structure": 10,      # lyrics + beats → 開始時刻

    # 20 — 判断を束ねる。互いに知らない
    "manifest": 20,       # song.json（曲の宣言）。policy で写像を検証する
    "timeline": 20,       # 採点を時間に敷く

    # 30 — cymatics とつなぐ
    "drive": 30,

    # 40 — 三段の組み立てと再現の記録
    "production": 40,

    # 50 — 1曲を最初から最後まで
    "workflow": 50,

    # 60 — 入口。互いに知らない
    "cli": 60,
    "": 60,               # emotion_effecter/__init__.py（facade は中身より上）

    # 70 — 実行
    "__main__": 70,
})

#: 1つの関数の実行行の上限。超えたら2つ以上のことをしている
MAX_FUNCTION_LINES = 30
