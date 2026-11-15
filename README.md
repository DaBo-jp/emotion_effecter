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

Python 3.14+ と ffmpeg。歌詞を流す（`credits`）なら fontconfig と日本語フォント（Debian なら
`fonts-noto-cjk`）。`TYPESAFE_API_KEY` を `.env` に置く（.gitignore 済み）。

### 手元の画面

```
uv run --env-file .env emotion-effecter ui        → http://127.0.0.1:8765 をブラウザで
```

動画編集ソフトと同じ並び：左上に素材、右上にプレビュー、下にタイムライン（仕切りは
ドラッグで動かせる）。曲は上の帯で選ぶ（`?song=名前` でも開ける）。

- **素材**（左上）: 曲のディレクトリのファイルと、出力（`out/<曲>/`）。クリックで
  プレビューに出す（画像・動画・音・歌詞・JSON）。右の選択で song.json の `files` の
  役割（audio / image / opening ...）を付け替える
- **設定**（左上のタブ）: song.json をフォームで書く。書いたそばから検証して問題を全部
  並べる（`_note` は残る）。込み入った項目（policy / overlays / reel など）は JSON の欄
- **書き出し**（左上のタブ）: プレビュー（previews.png）か書き出しを子プロセスで回し、
  記録（`out/<曲>/ui-job.log`）を見る。止められる。終わるとプレビューが新しい動画になる
- **プレビュー**（右上）: タイムラインと一緒に動く「番組」——書き出した emotion.mp4
  （compare / base、まだ無ければ音だけ）。いま歌っている行と次の行を下に重ねる
- **タイムライン**（下）: 上から 目盛り・セクション・歌詞行・音（波形と拍）。
  見出しをクリックした方（セクションか歌詞行）の印を動かす。歌詞の `[ ]` の行が
  セクション。「自動で置く」は `sections` と同じ推定で、自信の無い境界に ？ が付く。
  印をドラッグ（セクションは拍に吸着、Shift で外す）、再生しながら `M` で今の位置に
  置いて次へ、`←` `→` で 0.05 秒（Shift で 0.01 秒）ずらす、`T` でトラックを切り替え、
  `Ctrl`＋ホイールで拡大。セクションの保存先は `out/<曲>/lyrics.timed.md`（歌詞に時刻を
  手で書いてあれば、その歌詞）、歌詞行は `out/<曲>/lines.json`（`credits` の karaoke /
  vertical が使う。セクションの時刻を保存してから置ける）

自分の PC で開くためのもの（127.0.0.1 だけで待つ）。中身は `desk.py`（操作）と
`ui.py`（HTTP の口）で、判断は今のモジュールに任せる。

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
  変えられるのは `flow` / `flow_x` / `flow_y` / `flow_twist` と、にじみ `glow` /
  `glow_blur`（感情の倍率はその上に掛かる）、motif の落下
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
- `moods` で**主役の effect の引数をセクションごとの感情で動かせる**。その軸の値 0..1 で
  `lo` → `hi` へ動き、境界は `sections` と同じく2秒で入れ替わる（毎フレームではない——
  湧く数をその場で変えると粒が全部瞬間移動する）。動かせるのは `sections` で変えられる
  小数の項目と、湧く数の倍率 `density`、**届く割合 `reach`**（motif の図形が流れの
  その割合まで進んだところで消える。`alpha_curve` をそこで 0 にするカーブに書き換える
  ので、base の `alpha_curve` は使わない）。Jev の判断なので **emotion.mp4 にだけ効く**。
  `sections` に手で書いた値が勝つ。軸は歌詞の採点の軸だけ（`hype` は使えない）

  ```json
  "moods": {"density": {"by": "distance", "lo": 2.5, "hi": 0.5},
            "reach":   {"by": "distance", "lo": 1.0, "hi": 0.2}}
  ```

  Virga（地面に届く前に消える雨）で、心が近いほど雨が多く画面の下まで届き、遠いほど
  まばらに上の方で消える。写像の値は仮置き
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
- `credits` で**歌詞を流す**（セクションの見出しは出さず、歌詞の行だけ）。`mode` は
  `roll`（映画のエンドロールのように流れる。各セクションの最初の行がそのセクションの
  開始時刻に基準の高さ `anchor` を通る）か `card`（オープニングクレジットのように、
  いま歌っているセクションを流さずに出し、`fade` 秒で浮かび・消える）

  ```json
  "credits": {"mode": "roll", "position": "left_right", "direction": "up",
              "band": "20,20,30", "band_alpha": 0.4, "font": "noto-sans", "weight": "Regular"}
  ```

  | 項目 | 値 |
  |---|---|
  | `position` | `right` / `left` / `center`（固定）、`left_right` / `right_left`（セクションごとに左右を入れ替え） |
  | `direction` | `up`（下から上）/ `down`（上から下）。`roll` だけ |
  | `edge_fade` | `roll` の文字が画面の上下の端で薄れる幅（画面の高さに対する比）。0 で薄れない。帯は薄れない |
  | `pace` / `bpm` | `pace: true` で Jev の気持ちの速さ（pace.json、`tempo` と同じ質問）と BPM から、セクションごとに行の送り・拍ごとの刻み・フェードの幅を変える（`roll.PACE_*`、仮置き）。各セクションの頭の時刻は変わらない。`bpm` を書かなければ `tempo.bpm` → 推定 |
  | `band` / `band_alpha` | 裏の帯の色と不透明度。固定の位置は列の上から下まで、交互と `card` は文字の裏だけ |
  | `font` / `weight` | fontconfig のファミリー名か別名（`noto-sans` / `noto-serif`）かファイル。太さは Regular / Bold など |
  | `size` / `width` / `margin` / `anchor` / `gap` / `line` / `color` | 文字の高さ・列の幅・端からの余白（比）、基準の高さ、セクションの間の行数、行の送り、文字の色 |

  文字は色調（セピアなど）の後に描くので染まらない。`base_plain` の base には入れない。
  **フォントは OS の場所を前提にしない**——頼んだファミリーと太さが fontconfig から返らな
  ければ断る（似たものを黙って使わない）。コンテナ（Debian）には `fontconfig` と
  `fonts-noto-cjk` を入れる
- `credits` の `mode` を `karaoke` / `vertical` にすると、**歌詞を2行だけ、行の単位で
  歌に合わせて**出す（`sing.py`）。行は交互の段（列）に置き、前の行を歌い始めたところで
  次の行として出て、自分の次の行を歌い始めるまで残る ∴ いつも「いま歌っている行」と
  「次の行」の2行。置いた行は動かない。セクションの頭の行は `lead` 秒前に出る。文字の
  色は変えない。行の歌い出しは `out/<曲>/lines.json`——手元の画面のタイムラインの「歌詞行」で、
  再生しながら `M` で置く。置いていなければ、セクションの長さを行の文字数で振り分けた
  仮置き（頭は合うが中の行は目安）。歌詞が変わると lines.json は読まない（置き直す）

  ```json
  "credits": {"mode": "karaoke", "position": "bottom"}
  "credits": {"mode": "vertical", "position": "right"}
  ```

  | 項目 | 値 |
  |---|---|
  | `mode` | `karaoke`：横の帯に2段。`vertical`：縦書きで2列（右の列から読む） |
  | `position` | karaoke は `bottom`（既定）/ `top`。vertical は `right`（既定）/ `left` |
  | `lead` / `fade` | セクションの頭の行を歌い出しの何秒前から出すか / 浮かぶ・消える秒数 |
  | `color` / `band` / `band_alpha` / `font` / `weight` / `size` / `margin` / `line` | 文字の色、帯の色と不透明度、フォント（`roll` と同じ探し方。既定は Bold）、文字の高さ・端からの余白（画面の高さに対する比）、段・列の送り |

  段（列）に収まらない長い行は縮めて収める。縦書きは縦の字形（句読点・括弧・長音が縦に
  なる）。**欧文（かなも漢字も無い区間）は横倒し**にする——日本語と混ざった行は区間ごとに、
  日本語は縦、欧文は横倒しで上から積む
- `"clip_xfade": 0.3` で **Opening / Closing と本編のつなぎ目をクロスフェード**にする（秒）。
  曲の尺も切れ目も変わらない——Opening の最後の 0.3 秒に本編を重ねながら入り、Closing の
  最初の 0.3 秒で本編から移る（重なるぶん本編を前後に余分に描く）。書かなければ切り替え
  切り替え方は `clip_transition` で ffmpeg の xfade の 58 種類から選べる（既定 `fade` が
  重ねて入れ替えるオーバーラップ。`fadeblack` / `fadewhite` / `dissolve` / `wipeleft` /
  `circleopen` など。一覧は `video.TRANSITIONS`）。ffmpeg に無い **`channel`** も選べる——
  ダイヤル式のブラウン管テレビでチャンネルを回したときのように、走査線ごとに横へ裂け、
  絵が縦に流れ、真ん中で砂嵐を挟んで次の映像へ移る。`reel` の `in.transition` でも使える。
  数式で1画素ずつ作るので、1080p で 1 フレーム 1 秒ほどかかる（0.5 秒なら 15 秒ほど）
- `"fade_in": {"after": "Intro", "seconds": 2}` で **Opening の代わりに黒から入る**。
  `after` のセクションが終わるまで画面は真っ黒で、次のセクションの頭から `seconds` 秒で
  黒から明ける。画面ぜんたい（絵・effect・歌詞）にかかり、曲の尺は変わらない。
  振り付けなので base.mp4 にも効く。`files.opening` とは一緒に使えない（Ceiling で、
  Opening の動画がうまく作れなかったとき、歌入りの Intro のあいだを黒にした）
- `reel` で**背景を区間の並びで書く**。mp4 も画像も何本でも、どの順でも並べられ、
  **effect と歌詞は全部の上に描く**（Opening → 静止画 → Closing はその1つの書き方）。
  区間をつないだ背景の動画（`backdrop.mp4`）を cymatics に渡す

  ```json
  "reel": [{"video": "Opening.mp4"},
           {"image": "main.jpg", "until": "Bridge", "in": {"transition": "fade", "seconds": 1}},
           {"video": "Bridge.mp4", "in": {"transition": "fadeblack", "seconds": 2}},
           {"image": "main.jpg"},
           {"video": "Closing.mp4", "in": {"transition": "fade", "seconds": 1}}]
  ```

  | 項目 | |
  |---|---|
  | `video` | mp4 はその尺。曲の終わりを越える最後の mp4 だけ曲の終わりで切る |
  | `image` + `until` | 画像はセクション名（その区間が始まった後に最初に終わる、その名前のセクションの終わり。`Instrumental Break` のように何度あってもいい）か秒まで |
  | `image`（`until` なし） | 残り全部。並びに1つだけで、後ろは mp4 だけ（尺で曲の終わりから逆に置く） |
  | `in` | その区間の入り方。`transition`（`clip_transition` と同じ 58 種類、既定 `fade`）で `seconds` 秒。移り終えた時刻が区切りになり、入ってくる区間は `seconds` 秒早く始まる。書かなければ切り替え。最初の区間には書けない（黒から入るなら `fade_in`） |

  曲の終わりに届かない並び・短すぎる区間・無いセクションは全部並べて断る（黙って伸ばさ
  ない）。`keys` と `files.opening` / `closing` とは一緒に使えない（どれも背景か頭と
  終わりを決める）。背景が動画になるので明滅（`beam`）は使えない
- `"fade_out": {"seconds": 3}` で **最後のその秒数で画面ぜんたいが黒へ落ちる**（Closing が
  あれば Closing ごと）。最後のフレームが真っ黒になる。曲の尺は変わらず、base.mp4 にも効く
- `"crt": {}` で **ブラウン管の画面**にする。うっすらした走査線と、上から下（か下から上）へ
  繰り返し通り過ぎる明るい帯を、画面ぜんたい（Opening / Closing・歌詞も）に重ねる。
  base.mp4 にも効く。previews.png には出ない（つないだ1本に重ねるため）

  | 項目 | 意味（既定） |
  |---|---|
  | `scanlines` | 走査線の濃さ 0..1（0.15）。0 で引かない |
  | `pitch` | 走査線の間隔 px（4） |
  | `band` | 明るい帯の明るさ 0..1（0.08）。0 で流さない |
  | `band_height` | 帯の高さ。画面の高さに対する割合（0.15） |
  | `band_seconds` | 帯が画面を通り過ぎる秒数（8） |
  | `band_direction` | `down`（上から下）/ `up`（下から上） |
- `"base_plain": true` で **base.mp4 を素の cymatics** にする（`base` の引数と
  `files.image` だけ。`sections`・キー画像・置き場所も入れない）。書かなければ base にも
  振り付けが入り、compare の上下の違いは感情だけになる
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
  0  architecture / dims / lyrics / beats / video / grade / doc / digest / jev
 5   lines                        ← 歌詞の行の時刻
 10  policy / mood / elements / pace / tempo / casting / structure / scenes / overlay
     sync / windows / audience / scenery / backdrop / reel / roll / crt
                                  ← 互いに知らない
 15  sing                         ← 歌う行に合わせた歌詞。フォントは roll の探し方
 20  manifest / timeline / placement
 25  livefile
 30  drive                        ← cymatics の描画とつなぐのはここだけ
 40  production
 50  workflow / liveflow          ← 互いに知らない
 55  desk                         ← 手元の画面から呼ぶ操作。HTTP を知らない
 57  ui                           ← 手元の画面の HTTP の口
 60  cli / emotion_effecter
 70  __main__
```

同じ層の2つが同じ下ごしらえを要るなら、それは下の層に置く（`doc` の注記の落とし方、
`digest` のハッシュ、`jev` の Score の読み方、`lyrics.held` の間奏の埋め方）

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
doc         宣言と保存の JSON の決まりごと（`_` の注記・bool でない数・保存の版）
digest      ファイルの中身のハッシュ（動画も通るので少しずつ読む）
jev         Jev の呼び方と、Score の応答の読み方。質問は持たない
lyrics      歌詞ファイルの読み書き
mood        Jev でセクションごとの感情を採点。JSON に保存
pace        Jev でセクションごとの気持ちの速さを採点（tempo / credits.pace のある曲だけ）
tempo       昂ぶり + 気持ちの速さ + BPM → 流れる速さ・湧く数・踊りの速さ。純粋な計算
scenes      セクションごとに変える層の引数（流れの向き・速さ・数・置き場所・moods）
overlay     主役の上や下に重ねる層と、感情で動かす項目
elements    Jev で曲全体の属性（水地風金火明暗）を採点
casting     属性 + BPM → effect の候補。純粋な計算
beats       音源 → テンポ・拍・拍ごとの音色
structure   拍 → セクションの開始時刻（音源を知らない。合成データでテストできる）
sync        聴衆の映像と曲の音源の時刻合わせ
audience    聴衆の映像 → Jev（セクションごとの盛り上がり）
scenery     キー画像 → Jev（目印の箱と、effect をどこに添えるか）
placement   キー画像の解析 → effect の置き場所の引数
backdrop    セクションごとのキー画像 → 背景の動画
reel        背景の区間の並び（mp4 / 画像）→ 背景の動画
roll        歌詞をエンドロール / クレジットのように流す
grade       画面ぜんたいの色調（灰色・セピア）
crt         ブラウン管の走査線と、上下へ流れる明るい帯
lines       歌詞の行ごとの歌い出し（lines.json）。無ければ文字数で振り分け
sing        歌詞を2行だけ、行の単位で歌に合わせて出す（横の帯・縦書き）
desk        手元の画面から呼ぶ操作（曲の一覧・検証・タイムライン・書き出しの仕事）
ui          手元の画面の HTTP の口（ui.html の1枚）
timeline    採点 → 毎フレームの感情曲線
policy      感情 → 見た目。**写像はここだけ**。cymatics を知らない純粋な計算
drive       cymatics の effect の draw() を包んで動かす。区間ごとの並列書き出し
video       ffmpeg でつなぐ・揃える・並べる
production  本編を並列に描き、Opening / Closing とつなぎ、黒の入り・落ちと音を乗せる
manifest    song.json（曲の宣言）を読んで検証する
workflow    1曲を最初から最後まで
windows     歌詞の無いライブ動画を小節で区切る
livefile    live.json（ライブ動画1本の宣言）を読んで検証する
liveflow    ライブ動画1本を最初から最後まで
cli         入口
```

### 採点（`mood`）

1セクション = 1リクエストで、Score 13 個と Choice 1つを並列に投げる。

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
| distance | Score 5段階 | 心の距離（溶け合う → 近い → 隔たり → 遠い → 届かない）。体が触れていても心が離れていれば遠い |
| poignancy | Score 5段階 | 切なさ（切なくない → かすかに → 切ない → とても → 張り裂けそう）。想いと、叶わない・届かない痛みの同居。ただの悲しさとは違い、想いが無ければ切なくない |
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
| glow の広がり（`blur_by`） | valence | `blur_lo` 〜 `blur_hi` 倍。既定は ×1（動かさない） |
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
Architecture の scope が2位、イセカイの rune が2位、Shape の smoke が6位、Script の
stave が8位——外れる曲もある。

**正解は返さない。** 並べた候補と内訳まで出して、決めるのは人。重み（`casting.CASTS`）
は公開済みの曲から手で置いたもので、motif の5つ（hearts / night / spring / rain /
music）と cipher / ripple は仮置き。dB レンジは曲ごとに測るもの（cymatics の `analyze`）なので出さない。
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
- **曲ぜんたいを書き出すのは1回だけ。** つなぎ目を重ねる（`clip_xfade`）ときは、黒の
  入り・落ちと crt の重ねも同じ ffmpeg の1回でかける（`video.Finish`）。1080p の x264
  medium は1フレーム約 50ms の CPU で、絵を描くのと同じくらい重い。preset は medium の
  まま（veryfast は CPU が半分だが、同じ crf で画質が目に見えて落ちる）
- 重ねる PNG は1回だけ読んで使い回す（`-loop 1` の読み直しは2枚で1フレーム約 50ms）。
  20秒の 1080p で、つなぎ・黒・crt の書き出しの CPU が 109 → 45秒。絵は前と画素まで同じ
- **`channel` のつなぎ目は別に描いて差し込む**（`video.channel_seam`）。ffmpeg の数式
  （`channel_expr`）で描くと 1080p で1フレーム約 5秒かかるので、前後のフレームを取り出して
  cymatics の `render.channel`（C++、無ければ numpy）で同じ式を描き、ffv1 の短い動画に
  してつなぐ。15フレームのつなぎ目1つで CPU 80 → 11秒。素材が短くてつなぎ目どうしが
  重なるときだけ数式で描く

## 開発

```
uv run pytest
uv run ruff check src tests
```

## License

MIT
