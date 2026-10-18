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
  pace.json                 気持ちの速さ（Jev）。song.json に tempo がある曲だけ
  elements.json, suggest.md 属性（Jev）と effect の候補。suggest のときだけ
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
  （`{"effect": "rune", "params": {...}}`）。濃さのカーブ（`mask_curve` / motif の
  `alpha_curve`）は**オブジェクトのまま書ける**——`"mask_curve": {"points": [[0, 1],
  [0.5, 0.2], [1, 1]], "interp": "smooth"}`。cymatics へは JSON の文字列で渡る
- `opening` / `closing` / `published` は無くてもいい
- `sections` で**セクションごとに流れの向きを変えられる**（cymatics の `--flow` を持つ
  effect＝motif / smoke / rune）。書かないセクションは `base` のまま。境界は2秒かけて
  入れ替わる——古い流れは薄れながら流れ続け、新しい流れが濃くなる（粒が瞬間移動しない）。
  変えられるのは `flow` / `flow_x` / `flow_y` / `flow_twist` と、motif の落下
  `gravity`（火花。経過時間の2乗で効くので、外へ散らす区間でだけ立てる——集まる・
  ゆっくり渡る区間で立てると真下へ落ちるだけになる）、図形 `shape` と向き `align`
  （星で集まり、火花で弾ける）、湧く数の倍率 `density`（`rate` を手で書くと `tempo`
  が拍から出した数を潰すが、倍率ならその上に掛かる）。感情ではなく振り付けなので
  **base.mp4 にも効く**——compare の上下（previews の左右）の違いは Jev の感情だけになる

  ```json
  "sections": {"Chorus 1": {"flow": "in", "flow_x": 0.55, "flow_y": 0.3},
               "Last-Chorus": {"flow": "out", "flow_twist": 180}}
  ```
- `tempo` を書くと、**流れる速さ・湧く数・踊り（揺れ・首振り）を拍と気持ちで変える**
  （`speed` を持つ effect＝motif / rune）。昂ぶり（arousal）と、Jev に別に聞く
  「気持ちの速さ」（たゆたう／歩む／急く → `pace.json`）から、画面を渡りきる小節数を
  決める。昂ぶりは曲の最小〜最大へ引き伸ばし（`stretch`）、小節数は1オクターブを
  `snap` 段に刻んで丸める。湧く数は、急くほど画面に居る数が増えるように変える
  （`density_gain`）。揺れと首振りは拍の周波数に合わせる。Jev の判断なので
  **emotion.mp4 にだけ効く**。`sections` に手で書いた `speed` などが勝つ

  ```json
  "tempo": {"bpm": 98, "bars_calm": 4, "bars_wild": 1, "rock_beats": 1, "sway_beats": 2}
  ```

  | 項目 | 既定 | |
  |---|---|---|
  | `bpm` | 0 | 0 なら音源から推定（倍・半分にずれることがある——Irrational は 198 と出た） |
  | `bars_calm` / `bars_wild` | 8 / 2 | 昂ぶり 0 / 1 で渡りきる小節数 |
  | `stretch` | 1 | 昂ぶりを曲の最小〜最大へ引き伸ばす割合。0 で生の値 |
  | `snap` | 2 | 1オクターブの刻み。1 で2のべき、2 で √2 刻み |
  | `density_gain` | 1 | 気持ちの速さ1段で、画面に居る数を何オクターブ増減するか |
  | `beats_per_bar` / `sway_beats` / `rock_beats` | 4 / 4 / 2 | 拍子、揺れ・首振りの1往復の拍数 |

  いま使っているのは Irrational_hearts（motif のハート）だけ。上の設定でこう出る:

  ```
  tempo: 98.0 BPM → Intro 2小節 / Verse1 1.414小節 / Pre-Chorus1 0.707小節 /
    Chorus1 1.414小節 / Verse2 2小節 / Pre-Chorus2 0.5小節 / Chorus2 2.828小節 /
    Bridge 1小節 / Drop-Chorus 1小節 / Last-Chorus 2.828小節 / Outro 8小節
  ```

  急くサビ前で速く・数多く、サビで陶酔してゆっくりになる。写像の定数（8 / 2 小節、
  気持ちの速さ1段で1オクターブ）は仮置き
- `overlays` で**主役の effect の上や下に層を重ねられる**（cymatics の重ね合わせ）。
  たとえば cymatics の `crowd`（観客の影）を手前に置けば、中央でモチーフが踊る
  ライブ会場になる。`moods` に書いた項目は、その軸の値 0..1 で `lo` → `hi` へ動く
  （小数の項目だけ）。**emotion.mp4 にだけ効き**、base.mp4 は `params` のまま。
  音源・絵・尺・明滅は主役が持つので層には書けない。フェードは主役から引き継ぐ。
  `sections` と `tempo` は主役にだけ効く

  ```json
  "overlays": [{"effect": "crowd", "place": "over",
                "params": {"db_floor": 10, "db_ceil": 40},
                "moods": {"bounce": {"by": "arousal", "lo": 0.02, "hi": 0.09},
                          "arms":   {"by": "arousal", "lo": 0.15, "hi": 0.7}}}]
  ```

  `place` は `under`（主役の下）か `over`（上、既定）。写像の値（跳ねる高さ・手を
  挙げる割合）は仮置き
- `files.audience` に**聴衆の映像**を置くと、聴衆の盛り上がり（`hype`）で見た目を
  動かせる。映像と曲は**音で時刻を合わせ**（会場の音と音源の立ち上がりの並びを
  重ねる）、セクションごとに中ほどと前後2秒の3枚を取って Jev の画像入力で採点する
  （`audience.json`。あれば作り直さない、`--redo audience`）。**間奏も採点する**——
  聴衆は間奏でこそ沸く。`hype` は歌詞の軸と同じに選べる

  ```json
  "files": {..., "audience": "Audience.mp4"},
  "policy": {"glow_by": "hype", "gain_by": "hype"},
  "overlays": [{"effect": "crowd", "moods": {"bounce": {"by": "hype", "lo": 0.02, "hi": 0.1}}}],
  "audience": {"lead": 12.3, "spread": 2}
  ```

  音で合わないとき（山が鈍いとき）は理由を添えて断るので、`audience.lead`（映像の
  中で曲が始まる秒）を手で書く。映像は短い辺 280px 以上。Jev の画像入力は
  TypeSafe で「dreamer-ready」（試作向け）の扱い
- `keys` に**セクションごとのキー画像**を書くと、背景がセクションごとにその画像へ
  切り替わり（境界は2秒のクロスフェード）、effect もその画像に合わせて置かれる。
  書いていないセクションは前のセクションの画像のまま（最初は `files.image`）

  ```json
  "base": {"effect": "arc", "params": {"beam": 0}},
  "keys": {"Verse 1": "verse.jpg", "Chorus 1": "chorus.jpg", "Bridge": "bridge.jpg"}
  ```

  キー画像ごとに Jev の画像入力で2つ聞く（`scenery/` に残す。画像・effect・歌詞が
  同じなら聞き直さない、`--redo scenery`）——**目印の箱**（顔・人物・空・地面・光源、
  Box）と有無（Noul）、それから**その曲の effect をどの目印に添えるか**（Choice:
  頭を囲む / 空 / 地面 / 光源 / 人物の脇 / 画面いっぱい）。座標は Jev に作らせず、
  `placement` がコードで出す:

  | effect が持つ引数 | 出すもの |
  |---|---|
  | `cx` / `cy` / `radius`（arc・iris・wreath・corona） | 円の中心と半径。頭なら顔を囲む大きさ |
  | `flow_x` / `flow_y`（motif・smoke・rune） | 流れの中心 |
  | `holes` | **主人公の顔を透かす円**（頭を囲むとき以外は必ず） |

  置き場所は振り付けなので **base.mp4 にも効く**。`sections` に手で書いた値が勝つ。
  背景が動画になるので明滅（`beam`）は使えない（書いていなければ断る）。
  Box は短い物の名前で聞き、歌詞などとは別のリクエストにする——長い日本語の説明や
  同じリクエストの他の質問があると、顔の箱が全身に広がった。「空いた場所」は箱に
  ならない（confidence 0.03）ので、人物の箱の左右の広い方をコードで出す
- `_` で始まる鍵は注記。**知らない項目・足りない項目・無いファイルは全部並べて断る**

```
uv sync
uv run --env-file .env emotion-effecter song music_data/Shape              # 全部
uv run --env-file .env emotion-effecter song music_data/Shape --previews   # 静止画で確かめる
uv run emotion-effecter song music_data/Shape --steps emotion compare      # 書き出しだけ
uv run --env-file .env emotion-effecter song music_data/Shape --redo score # 採点し直す
uv run --env-file .env emotion-effecter suggest music_data/*               # effect の候補
```

採点（有料）と開始時刻は、**出力があれば作り直さない**。`--redo` で指定したものだけ
やり直す。歌詞に `@分:秒` を手で書いておけば推定しない（手書きが勝つ）。
`produce` は出力の隣に再現の記録 `<出力>.plan.json` を置く。

工程ごとのコマンド（`score` / `sections` / `render` / `produce` / `compare`）も
そのまま使える。`emotion-effecter --help` を参照。

### ライブ動画1本から

歌詞も音源も絵も無く、**ライブ動画1本**だけでも回せる。動画そのものを背景にして
（cymatics の動画背景）、場面の盛り上がり（`hype`）に合わせてエフェクトを重ねる。

```
music_data/<ライブ>/live.json   入力
out/<ライブ>/
  audio.wav                     動画の音（書き出しの音と拍の推定に使う）
  hype.json                     区切りごとの盛り上がり（Jev の画像入力）
  live.mp4 (+.plan.json)        エフェクトを重ねた1本
  compare.mp4                   上：元の動画 / 下：live.mp4
```

```json
{
  "title": "Ignite @ Zepp",
  "files": {"video": "Live.mp4"},
  "base": {"effect": "motif", "params": {"shape": "heart,star,note", "flow": "out"}},
  "overlays": [{"effect": "crowd",
                "moods": {"bounce": {"by": "hype", "lo": 0.02, "hi": 0.09}}}],
  "policy": {"glow_lo": 0.6, "glow_hi": 1.6},
  "window": {"bars": 8, "bpm": 0, "spread": 2}
}
```

- 歌詞が無いので、**拍から決めた `window.bars` 小節ごと**に区切って採点する。
  区切りごとに中ほどと前後 `spread` 秒の3枚を取り、演者・客席・照明を合わせた
  場面の盛り上がりを聞く。`bpm` が 0 なら音から推定（倍や半分にずれたら手で書く）
- 見た目を動かす軸は `hype` だけ。`policy` の `*_by` は既定で全部 `hype` で、ほかの
  軸を書いたら断る
- 採点（有料）は**出力があれば作り直さない**（`--redo score`）。拍や小節数を変えたら
  区切りが変わるので `--redo score`——古い hype.json は区切りが合わないので断る

```
uv run --env-file .env emotion-effecter live music_data/<ライブ>
```

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
 10  policy / mood / elements / pace / tempo / casting / structure / scenes
                                  ← 互いに知らない
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
pace        Jev でセクションごとの気持ちの速さを採点（tempo のある曲だけ）
tempo       昂ぶり + 気持ちの速さ + BPM → 流れる速さ・湧く数・踊りの速さ。純粋な計算
scenes      セクションごとに変える層の引数（流れの向き・速さ・数）
elements    Jev で曲全体の属性（水地風金火明暗）を採点
casting     属性 + BPM → effect の候補。純粋な計算
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

1セクション = 1リクエストで、Score 12 個と Choice 1つを並列に投げる。

| 質問 | 型 | 中身 |
|---|---|---|
| arousal | Score 5段階 | 昂ぶり（静まりかえる → 抑えきれない） |
| valence | Score 5段階 | 快・不快（苦しい → 満ちている） |
| acceptance | Score 5段階 | 受容（拒む → 受け入れる）。相手・世界・自分の状況のどれでもいい |
| conflict | Score 4段階 | 葛藤（定まっている → 引き裂かれている） |
| dominance | Score 5段階 | 主導権（支配されている → 委ねる → 対等 → 主導 → 支配） |
| love | Score 5段階 | 愛（無関心 → 冷めている → 惹かれる → 想う → 愛している）。憎しみは hate で別に聞く |
| hate | Score 5段階 | 憎しみ（無関心 → 疎ましい → 反感 → 恨む → 憎んでいる）。love と両方高ければ愛憎 |
| tense | Score 5段階 | 時制（過去 → 過去寄り → 現在 → 未来寄り → 未来）。0.5 が現在 |
| spring / summer / autumn / winter | Score 4段階 ×4 | 季節をそれぞれ（感じられない → 強く感じる）。巡るので1本の軸にしない |
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
| 画面の灰色（`gray_by`） | valence | `gray_lo` 〜 `gray_hi`（0=今の彩度、1=グレースケール）。既定は動かさない |
| 画面のセピア（`sepia_by`） | tense | `sepia_lo` 〜 `sepia_hi`（0=そのまま、1=セピア）。既定は動かさない |

灰色とセピアは**画面ぜんたい**（背景も重ねた層も）に掛かる。cymatics の `finish`
（重ね終えた画面を仕上げる口）に渡す。過去を振り返るほどセピアなら
`"sepia_by": "tense", "sepia_lo": 0.8, "sepia_hi": 0`。

**どの次元で何を動かすかは曲ごとに選ぶ**（`song.json` の `policy`）。曲によって
物語の軸が違う——Script / イセカイ / Shape は受容、Architecture は主導権。
`color_invert` で向きを返せる。

- **色相は既定で青 → 紫 → 赤の向きに回す。** ice（シアン）から暖色へ近い方を回ると
  黄緑を通り、開いていく気持ちの色に見えなかった
- **元の色が灰色に近ければ色相は回さない**（cymatics の `is_grey`）。frost から金へ
  回すと途中がピンクになった。白 → 淡い金 → 金、が素直

重みを変えても Jev を呼び直す必要はない（採点は JSON に残っている）。

**写像は曲ごとに手で決めている**（Script / イセカイ / Architecture / Shape /
Irrational）——効く次元も色の行き先も曲ごとに違う。effect の選び方は下の `suggest`
で提案させ始めたところ。色と「どの次元を何に割り当てるか」の提案はまだ無い。

### effect の提案（`elements` → `casting`、作りかけ）

`emotion-effecter suggest <dir>...` は、曲全体の歌詞を Jev に7つの属性（水・地・風・
金・火・明・暗、比喩も含む）で採点させ、BPM と合わせて effect の**使い方**を並べる
（`out/<曲>/suggest.md`）。使い方は effect 名ではなく effect + 性格を決める引数——
arc は棒なら後光、粒なら火花。

    点 = 0.7 × 属性の合い方 + 0.3 × テンポの合い方

属性の合い方は「曲の平均からの偏り × 使い方の重み」、テンポは BPM が使い方の中心から
何オクターブ離れているかの釣鐘。今の土台には `◀ 今` が付く。今の土台の順位は
Architecture の scope が1位、イセカイの rune が2位、Shape の smoke が6位、Script の
stave が7位——外れる曲もある。

**正解は返さない。** 並べた候補と内訳まで出して、決めるのは人。重み（`casting.CASTS`）
は公開済みの曲から手で置いたもので、motif の5つ（hearts / night / spring / rain /
music）は仮置き。dB レンジは曲ごとに測るもの（cymatics の `analyze`）なので出さない。
`genre` と絵はまだ使っていない。

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
