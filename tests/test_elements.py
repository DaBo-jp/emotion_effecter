from types import SimpleNamespace

import pytest

from emotion_effecter import dims, elements, lyrics


def test_one_question_per_element():
    assert set(elements.questions()) == set(dims.ELEMENTS) == set(elements.IMAGERY)


def test_state_carries_whole_song():
    song = lyrics.parse("[Verse 1]\na\n[Chorus 1]\nb\n")
    assert "[Chorus 1]\nb" in elements.state(song)["song"]["lyrics"]


def test_score_is_normalised_by_top_level():
    a = SimpleNamespace(score=2.0, confidence=0.6, probabilities={0: 0.0, 2: 1.0, 4: 0.0})
    el = elements.from_response(SimpleNamespace(scores={"fire": a}))
    assert el.scores == {"fire": 0.5} and el.confidence == {"fire": 0.6}


def test_save_load_roundtrip(tmp_path, song):
    el = elements.Elements({e: 0.1 for e in dims.ELEMENTS}, {e: 0.9 for e in dims.ELEMENTS})
    elements.save(tmp_path / "e.json", song, el)
    assert elements.load(tmp_path / "e.json") == el


def test_load_rejects_other_formats(tmp_path):
    (tmp_path / "e.json").write_text("{}")
    with pytest.raises(ValueError):
        elements.load(tmp_path / "e.json")
