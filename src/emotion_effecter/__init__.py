"""emotion_effecter — 歌詞の感情を Jev で数値にして、cymatics のエフェクトを動かす。

    lyrics      歌詞ファイルの読み書き
    mood        Jev でセクションごとの感情を採点
    elements    Jev で曲全体の属性（水地風金火明暗）を採点
    casting     属性 + BPM → effect の候補
    beats       音源 → テンポ・拍・拍ごとの音色
    structure   拍 → セクションの開始時刻
    timeline    採点 → 毎フレームの感情曲線
    policy      感情 → 見た目（写像はここだけ）
    drive       cymatics の effect を包んで動かす
    video       ffmpeg でつなぐ・揃える・並べる
    production  本編を並列に描いてつなぎ、音を乗せる
    workflow    1曲を最初から最後まで（liveflow はライブ動画1本）

全部の一覧と層は `architecture.LAYERS` と README の「構成」。
"""
__version__ = "0.1.0"
