"""stem のフック: リードボーカルの見つけ方・書き起こしの使い回し・歌詞への当てはめ。"""
import wave
import zipfile

import numpy as np
import pytest

from emotion_effecter import lyrics, stems, vocals

SONG = lyrics.parse("""[Intro]
how could I have protected you
最後の涙を 覚えているから

[Instrumental Break]

[Verse 1]
君の髪を撫でた 届けたかったから
I couldn't figure out how to keep you safe
ただ隣にいること それがすべてだった
""")


def _words(*rows):
    """(秒, 文字) の並び → 1語 0.4 秒の単語に分けた書き起こし。"""
    out = []
    for t, text in rows:
        for k, w in enumerate(text.split()):
            out.append((t + 0.4 * k, t + 0.4 * k + 0.4, w))
    return out


def test_align_matches_loosely_and_fills_what_was_not_heard():
    heard = _words((4.5, "最後の涙を覚えているから"),          # 1行目は聞き落とし
                   (40.0, "君の髪を撫でた 届けたかったから"),
                   (44.0, "I couldn't figure out how to keep you safe"),
                   (52.0, "ただ隣にいること それが全てだった"))  # 「すべて」→「全て」
    t = vocals.align(SONG, heard, first=2.5)
    assert t.lines[0] == (2.5, 4.5)                     # 聞き落とした最初の行は声の立ち上がり
    assert t.lines[2] == (40.0, 44.0, 52.0)
    assert t.filled == ((0, 0),)
    assert t.sections[0] == 0.0                         # 最初のセクションは 0
    assert t.sections[1] == pytest.approx(4.9)          # 間奏 = 前の行の歌い終わり
    assert t.sections[2] == pytest.approx(40.0 - vocals.LEAD)


def test_align_fills_a_missing_middle_line_between_its_neighbours():
    heard = _words((2.0, "how could I have protected you"), (6.0, "最後の涙を覚えているから"),
                   (40.0, "君の髪を撫でた"), (52.0, "ただ隣にいること"))
    t = vocals.align(SONG, heard)
    assert 40.0 < t.lines[2][1] < 52.0
    assert t.filled == ((2, 1),)
    flat = [x for r in t.lines for x in r]
    assert flat == sorted(flat)


def test_align_refuses_when_nothing_matches():
    with pytest.raises(ValueError, match="どの行とも合わない"):
        vocals.align(SONG, _words((1.0, "zzz qqq")))


def test_onset_cuts_at_a_threshold_below_the_loudest():
    sr = 1000
    x = np.concatenate([np.full(2000, 0.001), np.full(1000, 0.5)]).astype(np.float32)
    assert vocals.onset(x, sr) == pytest.approx(2.0)    # 小さな音（-54dB）は声ではない
    assert vocals.onset(np.zeros(1000, np.float32), sr) is None


def _wav(path, seconds=0.5, sr=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.sin(np.arange(int(sr * seconds)) / 5) * 8000).astype("<i2").tobytes())


def test_find_prefers_lead_vocals_in_a_folder_then_a_zip(tmp_path):
    assert stems.find(tmp_path) is None
    z = tmp_path / "Song Stems.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for n in ("1 Backing Vocals.mp3", "2 Drums.mp3", "0 Lead Vocals.mp3"):
            zf.writestr(n, b"x")
    assert stems.find(tmp_path) == stems.Stem(z, "0 Lead Vocals.mp3")
    (tmp_path / "stems").mkdir()
    for n in ("Backing Vocals.wav", "Vocals.wav", "Bass.wav"):
        (tmp_path / "stems" / n).write_bytes(b"x")
    assert stems.find(tmp_path) == stems.Stem(tmp_path / "stems" / "Vocals.wav")


def test_words_are_cached_by_stem_hash_and_model(tmp_path, monkeypatch):
    _wav(tmp_path / "Vocals.wav")
    calls = []
    monkeypatch.setattr(stems, "transcribe",
                        lambda x, model=stems.MODEL: calls.append(model) or [(0.1, 0.3, "a")])
    stem, cache = stems.Stem(tmp_path / "Vocals.wav"), tmp_path / "vocals.json"
    ws, x = stems.words(stem, cache)
    assert ws == [(0.1, 0.3, "a")] and len(x) == pytest.approx(8000, abs=50)
    assert stems.words(stem, cache)[0] == ws and len(calls) == 1      # 使い回す
    stems.words(stem, cache, redo=True)
    stems.words(stem, cache, model="small")
    assert calls == [stems.MODEL, stems.MODEL, "small"]                # やり直し・別のモデル
