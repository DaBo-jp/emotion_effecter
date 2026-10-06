from types import SimpleNamespace

import pytest

from emotion_effecter import lyrics, mood

TEXT = """[Verse 1]
a
[Instrumental Break]
[Chorus 1]
b
"""


def test_state_carries_whole_song_and_previous_lyric_section():
    s = mood.state(lyrics.parse(TEXT), 2)
    assert s["section"] == {"name": "Chorus 1", "position": "3 / 3", "text": "b"}
    assert s["previous"] == {"name": "Verse 1", "text": "a"}   # 間奏は飛ばす
    assert "[Chorus 1]\nb" in s["song"]["lyrics"]


def test_first_section_has_no_previous():
    assert isinstance(mood.state(lyrics.parse(TEXT), 0)["previous"], str)


def test_score_is_normalised_by_top_level():
    score = SimpleNamespace(score=3.0, confidence=0.8, probabilities={0: 0.0, 3: 1.0, 4: 0.0})
    emo = SimpleNamespace(choice="doubt", confidence=0.7, probabilities={"doubt": 0.7})
    resp = SimpleNamespace(scores={"acceptance": score}, choices={"emotion": emo})
    m = mood.from_response("Bridge", resp)
    assert m.scores["acceptance"] == 0.75 and m.emotion == "doubt"
    assert m.distributions["acceptance"] == {"0": 0.0, "3": 1.0, "4": 0.0}


def test_save_load_roundtrip(tmp_path, song, moods):
    path = tmp_path / "m.json"
    mood.save(path, song, moods)
    assert mood.load(path) == moods


def test_load_rejects_other_formats(tmp_path):
    path = tmp_path / "m.json"
    path.write_text("[]")
    with pytest.raises(ValueError):
        mood.load(path)


def test_questions_cover_every_dimension():
    assert set(mood.DIMS) | {"emotion"} == set(mood.QUESTIONS)
