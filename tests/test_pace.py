from types import SimpleNamespace

import pytest

from emotion_effecter import dims, pace


def test_labels_are_the_declared_paces():
    assert tuple(pace.CRITERIA) == dims.PACES


def test_from_response_keeps_the_distribution():
    a = SimpleNamespace(choice="rush", confidence=0.6,
                        probabilities={"linger": 0.1, "walk": 0.3, "rush": 0.6})
    p = pace.from_response("Chorus 1", SimpleNamespace(choices={"pace": a}))
    assert p == pace.Pace("Chorus 1", {"linger": 0.1, "walk": 0.3, "rush": 0.6}, 0.6, "rush")


def test_save_load_roundtrip(tmp_path, song):
    ps = [pace.Pace("Verse 1", {"walk": 1.0}, 0.9, "walk")]
    pace.save(tmp_path / "p.json", song, ps)
    assert pace.load(tmp_path / "p.json") == ps


def test_load_refuses_unknown_labels(tmp_path, song):
    pace.save(tmp_path / "p.json", song, [pace.Pace("Verse 1", {"crawl": 1.0}, 0.9, "crawl")])
    with pytest.raises(ValueError, match="crawl"):
        pace.load(tmp_path / "p.json")


def test_load_rejects_other_formats(tmp_path):
    (tmp_path / "p.json").write_text("[]")
    with pytest.raises(ValueError):
        pace.load(tmp_path / "p.json")
