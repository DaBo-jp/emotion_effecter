import pytest

from emotion_effecter import lyrics

TEXT = """<!--
Song
作詞: someone
-->
[Intro]
hello

[Verse 1 @0:18.5]
a
b

[Instrumental Break]
"""


def test_parse_header_sections_and_times():
    song = lyrics.parse(TEXT)
    assert song.title == "Song" and song.meta == {"作詞": "someone"}
    assert [s.name for s in song.sections] == ["Intro", "Verse 1", "Instrumental Break"]
    assert [s.start for s in song.sections] == [None, 18.5, None]
    assert song.sections[2].instrumental and not song.timed


def test_whole_lyrics_keep_tags_for_context():
    assert lyrics.parse(TEXT).lyrics.startswith("[Intro]\nhello\n\n[Verse 1]\na\nb")


def test_time_roundtrip():
    assert lyrics.parse_time("1:23.5") == 83.5
    assert lyrics.fmt_time(83.5) == "1:23.50"


def test_stamp_writes_times_and_keeps_other_lines():
    out = lyrics.stamp(TEXT, [0.0, 20.25, 75.0])
    song = lyrics.parse(out)
    assert [s.start for s in song.sections] == [0.0, 20.25, 75.0] and song.timed
    assert [ln for ln in out.split("\n") if not ln.startswith("[")] == \
           [ln for ln in TEXT.split("\n") if not ln.startswith("[")]


def test_stamp_refuses_a_count_mismatch():
    with pytest.raises(ValueError, match="3 個に対して時刻が 2 個"):
        lyrics.stamp(TEXT, [0.0, 1.0])
