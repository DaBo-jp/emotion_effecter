import numpy as np

from emotion_effecter import lyrics, structure
from emotion_effecter.beats import Beats

# 種類ごとの音色。同じ種類は同じ向き（＋雑音）
FORM = [("Intro", 16, 2, "i"), ("Verse 1", 48, 6, "v"), ("Pre-Chorus 1", 32, 4, "p"),
        ("Chorus 1", 56, 7, "c"), ("Verse 2", 48, 6, "v"), ("Pre-Chorus 2", 32, 4, "p"),
        ("Chorus 2", 56, 7, "c"), ("Outro", 24, 0, "o")]


def _synthetic(rng):
    base = {k: rng.normal(size=32) for k in "ivpco"}
    feats, text, beat = [], [], 0
    starts = []
    for name, n, lines, k in FORM:
        starts.append(beat * 0.5)
        feats += [base[k] + 0.6 * rng.normal(size=32) for _ in range(n)]
        text.append("[%s]\n%s" % (name, "\n".join("x" * (i + 1) for i in range(lines))))
        beat += n
    f = np.array(feats)
    f -= f.mean(0)
    f /= np.linalg.norm(f, axis=1, keepdims=True)
    beats = Beats(np.arange(len(f)) * 0.5, f, len(f) * 0.5, 120.0)
    return lyrics.parse("\n".join(text)), beats, starts


def test_kind_groups_repeated_sections():
    assert {structure.kind(n) for n in ("Chorus 1", "Chorus 2", "Last-Chorus")} == {"chorus"}
    assert structure.kind("Pre-Chorus 2") == "pre-chorus"
    assert structure.kind("Outro - Instrumental") == "outro"


def test_kind_drops_annotations():
    assert structure.kind("Pre-Chorus 1 - high backing vocals") == "pre-chorus"
    assert structure.kind("Last Chorus - key change, ethereal boys choir") == "chorus"
    assert structure.kind("Drop Chorus - ethereal boys choir backing vocals") == "drop chorus"
    assert structure.kind("Instrumental Break - ethereal") == "instrumental break"


def test_recovers_boundaries_of_a_repeating_form(rng):
    song, beats, truth = _synthetic(rng)
    got = [b.start for b in structure.estimate(song, beats)]
    assert np.allclose(got, truth, atol=1.0)        # 2拍以内


def test_novelty_peaks_at_a_block_change():
    f = np.array([[1.0, 0.0]] * 20 + [[0.0, 1.0]] * 20)
    nv = structure.novelty(f @ f.T)
    assert abs(int(np.argmax(nv)) - 20) <= 1


def test_candidates_start_at_zero_and_are_sorted(rng):
    _song, beats, _ = _synthetic(rng)
    sim = beats.similarity()
    c = structure.candidates(structure.novelty(sim), sim)
    assert c[0] == 0 and c == sorted(c) and all(b - a > 2 for a, b in zip(c, c[1:]))
