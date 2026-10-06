import numpy as np
import pytest

from emotion_effecter import lyrics, mood

SONG_TEXT = """<!--
Song
作詞: someone
-->
[Verse 1 @0:00]
a
[Instrumental Break @0:10]
[Chorus 1 @0:20]
b
"""


def make_mood(name: str, acceptance: float) -> mood.Mood:
    scores = {k: 0.5 for k in mood.DIMS} | {"acceptance": acceptance}
    return mood.Mood(name, scores, {k: 0.9 for k in scores},
                     {"emotion": {"doubt": 1.0 - acceptance, "surrender": acceptance}},
                     "surrender" if acceptance > 0.5 else "doubt")


@pytest.fixture
def song():
    return lyrics.parse(SONG_TEXT)


@pytest.fixture
def moods():
    return [make_mood("Verse 1", 0.0), make_mood("Chorus 1", 1.0)]


@pytest.fixture
def rng():
    return np.random.default_rng(0)
