# emotion_effecter

歌詞の感情を **Jev**（[TypeSafe](https://docs.typesafe.ai) の System One モデル）で
数値にして、[cymatics](https://github.com/DaBo-jp/cymatics) の波形エフェクトを
曲の流れに合わせて動かす。

cymatics の preset は、人が曲の雰囲気から決めた**1曲で1つの固定値**だった。
ここではそれを土台にしたまま、**セクションごとに変わる気持ち**で色・揺れ・にじみを
毎フレーム動かす。

```
Script（2026-10）: サビは3回とも同じ形で、変わるのは一文字ずつ
  Chorus 1     心までは 渡さない    acceptance 0.26   ice のまま
  Chorus 2     心まで 渡したい      acceptance 0.56   紫〜ピンクへ
  Bridge       is it just a script?  conflict   0.97   色相が揺れる
  Last-Chorus  心まで 渡したから    acceptance 0.99   暖色、にじみ最大

イセカイ（2026-10）: 受容の相手は恋人ではなく「来てしまった世界」
  Chorus 1/2   帰してほしい              acceptance 0.02   longing
  Drop Chorus  何も救われない 世界なら    acceptance 0.14   resignation 0.86
  Last Chorus  このセカイに まだ生きてみるよ acceptance 0.69 hope 1.00

Architecture（2026-10）: 軸は受容ではなく主導権
  Chorus 1     hunting for your admin rights     dominance 0.95   scarlet、鋭く
  Chorus 2     can you become my dominant?       dominance 0.39   藤色へ、にじむ
  Last-Chorus  now we've become the dominant     dominance 0.96   scarlet に戻る
```

> **依存の cymatics は非公開リポジトリ。** `uv sync` には DaBo-jp の GitHub 認証
> （`gh auth login` → `gh auth setup-git`）が要る。

## 使い方

Python 3.14+ と ffmpeg。`TYPESAFE_API_KEY` を `.env` に置く（.gitignore 済み）。

**入力と出力は曲ごとのディレクトリ。**

```
music_data/<曲>/            入力。人が置くもの（元のファイル名のまま）
  song.json                 曲の宣言：タイトル・ジャンル・ファイル・土台・写像
  歌詞_Shape.md, Shape.wav, shape.jpg, Shape_Opening.mp4 ...
out/<曲>/                   出力。全部作り直せるもの
  mood.json                 採点（Jev）
  lyrics.timed.md           開始時刻つきの歌詞
  emotion.mp4 (+.plan.json) 感情版（Opening / 本編 / Closing）
  base.mp4                  公開版の動画が無い曲だけ：土台の設定で感情なし
  compare.mp4               上：公開版（無ければ base）/ 下：感情版
  previews.png              セクションごとの「感情なし｜感情あり」
```

```json
{
  "title": "Architecture",
  "genre": "",
  "files": {"lyrics": "歌詞_Architecture.md", "audio": "Architecture.wav",
            "image": "Architecture.jpg", "opening": "Architecture_Opening.mp4",
            "closing": "Architecture_Closing.mp4", "published": "Architecture.mp4"},
  "base": {"preset": "architecture"},
  "policy": {"color_by": "dominance", "color_invert": true, "warm": "200,140,255",
             "turn": 0, "glow_by": "dominance", "glow_lo": 2.2, "glow_hi": 0.8}
}
```

- `base` は cymatics の preset（`{"preset": ...}`）か、effect と引数
  （`{"effect": "rune", "params": {...}}`）
- `opening` / `closing` / `published` は無くてもいい
- `_` で始まる鍵は注記。**知らない項目・足りない項目・無いファイルは全部並べて断る**

```
uv sync
uv run --env-file .env emotion-effecter song music_data/Shape              # 全部
uv run --env-file .env emotion-effecter song music_data/Shape --previews   # 静止画で確かめる
uv run emotion-effecter song music_data/Shape --steps emotion compare      # 書き出しだけ
uv run --env-file .env emotion-effecter song music_data/Shape --redo score # 採点し直す
```

採点（有料）と開始時刻は、**出力があれば作り直さない**。`--redo` で指定したものだけ
やり直す。歌詞に `@分:秒` を手で書いておけば推定しない（手書きが勝つ）。
`produce` は出力の隣に再現の記録 `<出力>.plan.json` を置く。

工程ごとのコマンド（`score` / `sections` / `render` / `produce` / `compare`）も
そのまま使える。`emotion-effecter --help` を参照。

### 歌詞ファイル

作詞メモそのまま。ヘッダーのコメントの1行目がタイトル。

```
<!--
Script
作詞: みじんこきなこ
-->
[Intro]
Every time we lock eyes, my body just takes over
心までは渡さない

[Verse 1]
...
```

`sections` がタグに `@分:秒` を書き込む（`[Verse 1 @0:13.35]`）。手で書いてもいい。

## 設計方針 — cymatics と同じ

`src/emotion_effecter/architecture.py` に書いてあって、`tests/test_architecture.py` が
AST で実測する。**「そう書いた」では足りないので、破ったら落ちる。**

1. **関数の外に、副作用を伴うメモリを置かない。** モジュール直下の可変コンテナも、
   import 時に走る処理も、`global` / `nonlocal` も無し。読むだけのデータは
   `MappingProxyType` と `tuple`。感情曲線（`Timeline`）も読み取り専用の配列で持つ
2. **関数はきちんと区切る。** 実行行 30 行が上限
3. **同じ層の横依存は禁止。** 層は順位として宣言し、import は必ず下へ向かう

```
  0  architecture / dims / lyrics / beats / video
 10  policy / mood / structure    ← 互いに知らない
 20  manifest / timeline
 30  drive                        ← cymatics の描画とつなぐのはここだけ
 40  production
 50  workflow
 60  cli / emotion_effecter
 70  __main__
```

ほかにも cymatics から引き継いでいるもの:

- **値の検証は宣言から出る。** Spec は cymatics の `Field`、Policy は `policy.RANGES`。
  **最初の1つで止めず全部並べる**
- **黙って捨てない。** 歌詞と採点が対応しない、時刻とタグの数が合わない、知らない
  Policy の項目——どれも並べて断る
- **既定の書き出しは画素が1ビットも変わらない。** 中立な Policy で包んだ effect は
  素の cymatics と画素まで一致する。`tests/test_conformance.py` が全 effect で実測する
  （動かさないときは色を HSV に開かない。開いて閉じると丸めで1ずれうる）
- **出力の隣に再現の記録を置く。** Spec・Policy・切れ目・区間・入力のハッシュ・版

## 構成

```
architecture  層の宣言
dims        感情の次元の名前（採点と写像が同じ一覧を見る）
lyrics      歌詞ファイルの読み書き
mood        Jev でセクションごとの感情を採点。JSON に保存
beats       音源 → テンポ・拍・拍ごとの音色
structure   拍 → セクションの開始時刻（音源を知らない。合成データでテストできる）
timeline    採点 → 毎フレームの感情曲線
policy      感情 → 見た目。**写像はここだけ**。cymatics を知らない純粋な計算
drive       cymatics の effect の draw() を包んで動かす。区間ごとの並列書き出し
video       ffmpeg でつなぐ・揃える・並べる
production  Opening / 本編 / Closing の三段
manifest    song.json（曲の宣言）を読んで検証する
workflow    1曲を最初から最後まで
cli         入口
```

### 採点（`mood`）

1セクション = 1リクエストで、Score 5つと Choice 1つを並列に投げる。

| 質問 | 型 | 中身 |
|---|---|---|
| arousal | Score 5段階 | 昂ぶり（静まりかえる → 抑えきれない） |
| valence | Score 5段階 | 快・不快（苦しい → 満ちている） |
| acceptance | Score 5段階 | 受容（拒む → 受け入れる）。相手・世界・自分の状況のどれでもいい |
| conflict | Score 4段階 | 葛藤（定まっている → 引き裂かれている） |
| dominance | Score 5段階 | 主導権（支配されている → 委ねる → 対等 → 主導 → 支配） |
| emotion | Choice | defiance / desire / doubt / fear / longing / resignation / hope / surrender |

質問は曲を選ばない。受容の相手は「相手・世界・自分の状況」のどれでもよく、
最初の「相手に心を開くか（openness）」は相手のいないイセカイで confidence が
15〜65% まで落ちた。主導権は PAD モデル（快・覚醒・支配）の支配で、これが無いと
主導権の移り変わりが軸の Architecture で何も動かなかった。

state には**曲全体の歌詞と直前のセクション**も入れる。サビの繰り返しは文面が
ほぼ同じで、違いは曲の流れの中でしか読めない。セクション単体だと「は」の有無と
「たい」の違いしか見えない。

### 開始時刻の推定（`beats` → `structure`）

1. テンポと拍を取り、拍ごとの音色（対数32帯域）を作る
2. 拍どうしの自己類似から切れ目らしさ（novelty）の山を取り、**繰り返しの間隔
   だけずらした位置**も候補に足す。Verse → Pre-Chorus のようになだらかな境界は
   山が立たないが、2番の同じ位置に山があれば拾える
3. 歌詞のセクション列を候補に割り当てる（ビームサーチ）。良さは
   - 境界の novelty
   - **同じ種類のセクション（Chorus 1 / 2 / Last）が音として似ていること**
   - 同じ種類のセクションの長さが揃っていること
   - **1行あたりの長さが揃っていること**——これが無いと Verse と Pre-Chorus を
     取り違えた

境界ごとに次点との差（margin）を出し、0.2 未満は「要確認」と表示する。
**ボーカルの有無は見ていない。** 中央成分（cymatics の `beam_center`）は EBM では
シンセやベースも乗るので、声の目印にならなかった。

Script での実測：Pre-Chorus の margin 7.19 に対して、間奏・Bridge・間奏の
境界は 0.3 前後。感情はセクション間を2秒でならすので、数秒のずれは絵に出にくい。

### 写像（`policy`）

| 見た目 | 既定で動かす次元 | 動き |
|---|---|---|
| 色（`color_by`） | acceptance | `--color` から `warm`（255,176,150）へ。**0.3 以下は動かさない** |
| 色相の揺れ（`wobble_by`） | conflict | 最大 ±28°、周期の割り切れない2つの正弦 |
| glow（`glow_by`） | valence | ×0.5 〜 ×1.8 |
| バンドレベル（`gain_by`） | arousal | ×0.9 〜 ×1.1（歌詞から読んだ昂ぶりなので控えめ） |

**どの次元で何を動かすかは曲ごとに選ぶ**（`song.json` の `policy`）。曲によって
物語の軸が違う——Script / イセカイ / Shape は受容、Architecture は主導権。
`color_invert` で向きを返せる。

- **色相は既定で青 → 紫 → 赤の向きに回す。** ice（シアン）から暖色へ近い方を回ると
  黄緑を通り、開いていく気持ちの色に見えなかった
- **元の色が灰色に近ければ色相は回さない**（cymatics の `is_grey`）。frost から金へ
  回すと途中がピンクになった。白 → 淡い金 → 金、が素直

重みを変えても Jev を呼び直す必要はない（採点は JSON に残っている）。

**4曲とも写像を手で決めた**——効く次元も色の行き先も曲ごとに違う。次は、ジャンル・
歌詞・BPM から effect と色と「どの次元を何に割り当てるか」を**提案**させる。

### cymatics は改造しない（`drive`）

cymatics の pipeline は effect を外から受け取る（`pipeline.render(eff, spec)`）。
そこへ**`draw()` だけ包んだ effect** を渡し、毎フレーム `ctx`（色・glow）と
`fr`（バンドのレベル）を差し替えてから元の `draw()` を呼ぶ。

- 宣言・`stage()`・導出値・包絡は元のまま ∴ Spec の検証も preset もそのまま使える
- 差し替えは曲頭からのフレーム番号だけで決まる ∴ 区間に分けても同じ絵
- `--no-mood` は包まない ∴ 素の cymatics と同じ（公開版 Script と平均画素差 4.2、
  圧縮誤差の範囲）

### 並列の書き出し（`production`）

本編を25秒（750フレーム）ずつに割って並列に描き、Opening・Closing とつないで
から音を乗せ直す。

- **尺はフレーム数で扱う。** Opening の 10.005秒は 30fps で 300 フレーム。
  cymatics は `int(秒 * fps)` で切り捨てるので、区間の秒数は少しだけ足して渡す
- precomputed の包絡は初回にキャッシュへ書かれる。並列で同時に書かないよう、
  先に1枚描いて温める
- 包絡が streaming の effect（arc / ring / line）は cymatics 側が区間依存なので、
  本編を割らずに1本で描く
- 音は `-shortest` ではなく `-t` で切る（cymatics の README と同じ理由）

## 開発

```
uv run pytest
uv run ruff check src tests
```

## License

MIT
