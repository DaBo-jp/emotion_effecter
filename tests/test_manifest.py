import json

import pytest

from emotion_effecter import manifest


def _write(root, doc, files=("l.md", "a.wav", "i.png")):
    for f in files:
        (root / f).write_text("x")
    (root / "song.json").write_text(json.dumps(doc), encoding="utf-8")


DOC = {"title": "T", "genre": "pop",
       "files": {"lyrics": "l.md", "audio": "a.wav", "image": "i.png"},
       "base": {"preset": "shape"},
       "policy": {"_note": "注記は読み飛ばす", "warm": "crimson"}}


def test_loads_and_resolves_paths(tmp_path):
    _write(tmp_path, DOC)
    m = manifest.load(tmp_path)
    assert m.effect == "smoke" and m.genre == "pop" and m.policy == {"warm": "crimson"}
    assert m.file("audio") == str((tmp_path / "a.wav").resolve()) and m.file("opening") is None


def test_effect_and_params_base(tmp_path):
    _write(tmp_path, {**DOC, "base": {"_note": "n", "effect": "rune", "params": {"size": 80}}})
    m = manifest.load(tmp_path)
    assert (m.effect, m.params) == ("rune", {"size": 80})


def test_every_problem_is_listed(tmp_path):
    """黙って捨てない。最初の1つで止めない。"""
    doc = {**DOC, "colour": "red", "base": {"preset": "nope"},
           "files": {"lyrics": "l.md", "audio": "missing.wav", "cover": "c.png"},
           "policy": {"turn": 5}}
    _write(tmp_path, doc)
    with pytest.raises(ValueError) as e:
        manifest.load(tmp_path)
    msg = str(e.value)
    for part in ("知らない項目: colour", "files に image が無い", "知らない役割: cover",
                 "audio が無い", "nope", "turn"):
        assert part in msg, part
