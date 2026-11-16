"""Cloud Run Jobs の3段（`job`）を、合成した短い曲で最後まで通す。ffmpeg が要る。

**3段に割っても、通し（`workflow.run`）と1フレームずつ同じ絵になる**ことを見る。
"""
import json
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from emotion_effecter import jev, job, lyrics, manifest, mood, workflow
from tests.conftest import make_mood

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")

LYRICS = """<!--
Song
作詞: someone
-->
[Verse 1 @0:00]
a
[Chorus 1 @0:04]
b
"""


def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def _frames(path):
    """動画の絵の、1フレームずつのハッシュ（入れ物の違いは見ない）。"""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v", "-f",
                          "framemd5", "-"], check=True, capture_output=True, text=True)
    return [line.split(",")[-1].strip() for line in out.stdout.splitlines()
            if not line.startswith("#")]


@pytest.fixture
def song_dir(tmp_path, monkeypatch):
    """8秒の曲（Opening / Closing つき、公開版なし ∴ base も作る）。"""
    monkeypatch.setenv("CYMATICS_CACHE_DIR", str(tmp_path / "cache"))
    root = tmp_path / "Song"
    root.mkdir()
    _ff("-f", "lavfi", "-i", "sine=frequency=220:duration=8", "-ac", "2", str(root / "a.wav"))
    Image.fromarray(np.full((72, 128, 3), 40, np.uint8)).save(root / "i.png")
    for name in ("open", "close"):
        _ff("-f", "lavfi", "-i", "testsrc=size=128x72:rate=24:duration=1.02",
            str(root / ("%s.mp4" % name)))
    (root / "l.md").write_text(LYRICS, encoding="utf-8")
    doc = {"title": "Song", "files": {"lyrics": "l.md", "audio": "a.wav", "image": "i.png",
                                      "opening": "open.mp4", "closing": "close.mp4"},
           "base": {"effect": "stave", "params": {"width": 128, "height": 72, "fps": 10,
                                                  "bands": 8}}}
    (root / "song.json").write_text(json.dumps(doc), encoding="utf-8")
    return root


def _scored(out):
    """採点を先に置く（Jev を呼ばない）。"""
    out.mkdir(parents=True, exist_ok=True)
    song = lyrics.parse(LYRICS)
    mood.save(str(out / "mood.json"), song,
              [make_mood("Verse 1", 0.0), make_mood("Chorus 1", 1.0)])


def _small_chunks(monkeypatch):
    """区間を1秒に（8秒の曲が何区間にも割れるように）。"""
    real = workflow.order
    monkeypatch.setattr(workflow, "order", lambda *a, **k: _with_chunks(real(*a, **k), 1))


def _with_chunks(order, seconds):
    from dataclasses import replace
    return replace(order, chunk_seconds=seconds)


def test_three_stages_match_the_single_run_frame_by_frame(tmp_path, song_dir, monkeypatch):
    _small_chunks(monkeypatch)
    m = manifest.load(song_dir)
    single, split = tmp_path / "single", tmp_path / "split"
    for out in (single, split):
        _scored(out)
    workflow.run(m, single, say=lambda *_: None)

    counts = job.prepare(m, split, say=lambda *_: None)
    assert counts == {"emotion": 6, "base": 6}                # 本編 6 秒を 1 秒ずつ
    drawn = [job.render(m, split, job.Task(i, 3), say=lambda *_: None) for i in range(3)]
    assert sorted(len(d) for d in drawn) == [4, 4, 4]          # 12 区間を 3 タスクで
    job.finalize(m, split, say=lambda *_: None)

    for role in ("emotion", "base"):
        assert _frames(split / ("%s.mp4" % role)) == _frames(single / ("%s.mp4" % role))
    assert (split / "compare.mp4").exists()
    assert not (split / job.WORK).exists()                     # 共有の作業場所は消える


def test_render_never_asks_jev(tmp_path, song_dir, monkeypatch):
    """render の段で採点が無ければ、Jev を呼ばずに断る。"""
    m = manifest.load(song_dir)
    out = tmp_path / "out"
    _scored(out)
    job.prepare(m, out, say=lambda *_: None)
    (out / "mood.json").unlink()
    with pytest.raises(jev.Offline, match="mood.json"):
        job.render(m, out, say=lambda *_: None)
    assert jev.OFFLINE not in __import__("os").environ       # 抜けたら元に戻る


def test_finalize_refuses_when_a_chunk_is_missing(tmp_path, song_dir, monkeypatch):
    _small_chunks(monkeypatch)
    m = manifest.load(song_dir)
    out = tmp_path / "out"
    _scored(out)
    job.prepare(m, out, say=lambda *_: None)
    job.render(m, out, job.Task(0, 2), say=lambda *_: None)    # 半分だけ描く
    with pytest.raises(FileNotFoundError, match="render が描いていない区間"):
        job.finalize(m, out, say=lambda *_: None)


def test_stages_refuse_without_prepare_or_with_a_changed_plan(tmp_path, song_dir):
    m = manifest.load(song_dir)
    out = tmp_path / "out"
    _scored(out)
    with pytest.raises(FileNotFoundError, match="prepare"):
        job.render(m, out, say=lambda *_: None)
    job.prepare(m, out, say=lambda *_: None)
    (out / job.WORK / "plan.json").write_text(json.dumps({"chunks": {"emotion": 99}}),
                                              encoding="utf-8")
    with pytest.raises(ValueError, match="prepare の数え"):
        job.render(m, out, say=lambda *_: None)


def test_task_comes_from_cloud_run_env_and_is_checked():
    assert job.Task.from_env({}) == job.Task(0, 1)
    t = job.Task.from_env({"CLOUD_RUN_TASK_INDEX": "2", "CLOUD_RUN_TASK_COUNT": "3"})
    assert t.mine(10) == [2, 5, 8]
    # 本をまたいで通し番号: 13 区間の本が2つなら、3タスクに 9 / 9 / 8
    per_task = [len(job.Task(i, 3).mine(13)) + len(job.Task(i, 3).mine(13, 13))
                for i in range(3)]
    assert per_task == [9, 9, 8]
    for bad in ((3, 3), (-1, 2), (0, 0)):
        with pytest.raises(ValueError, match="タスクの番号"):
            job.Task(*bad)
