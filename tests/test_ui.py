"""手元の画面の口（`ui`）と、その下の操作（`desk`）。合成した短い曲で通す。"""
import json
import shutil
import subprocess
import sys
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from emotion_effecter import desk, lyrics, structure, ui

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")

LYRICS = "[Intro]\n\n[Verse 1]\nあ\nい\n\n[Chorus 1]\nう\n"


@pytest.fixture
def root(tmp_path):
    song = tmp_path / "data" / "S"
    song.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='sin(2*PI*60*t)*lt(mod(t\\,0.5)\\,0.08)':s=44100:d=12",
                    str(song / "a.wav")], check=True)
    Image.fromarray(np.full((72, 128, 3), 40, np.uint8)).save(song / "i.png")
    (song / "l.txt").write_text(LYRICS, encoding="utf-8")
    doc = {"title": "S", "files": {"lyrics": "l.txt", "audio": "a.wav", "image": "i.png"},
           "base": {"preset": "shape"}, "_note": "注記は残る"}
    (song / "song.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return tmp_path


@pytest.fixture
def client(root):
    return TestClient(ui.app(root / "data", root / "out"))


def test_lists_songs_and_reads_one(client):
    rows = client.get("/api/songs").json()
    assert [(r["name"], r["problems"]) for r in rows] == [("S", 0)]
    r = client.get("/api/songs/S").json()
    assert r["files"]["audio"] == ["a.wav"] and r["files"]["lyrics"] == ["l.txt"]
    assert r["sections"] == ["Intro", "Verse 1", "Chorus 1"] and r["problems"] == []
    assert "channel" in client.get("/api/choices").json()["transitions"]


def test_check_lists_problems_and_save_keeps_notes(client, root):
    doc = client.get("/api/songs/S").json()["doc"]
    bad = client.post("/api/songs/S/check", json={**doc, "crt": {"band": 3}}).json()
    assert bad == ["crt.band は 0..1"]
    assert client.post("/api/songs/S/check", json={**doc, "files": 3}).json()  # 落ちない
    assert client.put("/api/songs/S", json={**doc, "clip_xfade": 0.5}).json() == []
    saved = json.loads((root / "data" / "S" / "song.json").read_text(encoding="utf-8"))
    assert saved["_note"] == "注記は残る" and saved["clip_xfade"] == 0.5


def test_unknown_or_escaping_song_is_404(client):
    assert client.get("/api/songs/nope").status_code == 404
    assert client.get("/api/songs/..").status_code == 404
    assert client.get("/api/songs/S/out/..%2Fdata%2FS%2Fsong.json").status_code == 404


def test_timeline_reads_untimed_lyrics_then_saves_to_out(client, root):
    tl = client.get("/api/songs/S/timeline").json()
    assert [s["start"] for s in tl["sections"]] == [None, None, None]
    assert abs(tl["duration"] - 12.0) < 0.05 and len(tl["peaks"]) <= desk.PEAKS
    assert tl["beats"] and tl["saves_to"].endswith("out/S/lyrics.timed.md")
    r = client.put("/api/songs/S/timeline", json={"starts": [0.0, 4.0, 8.5]})
    assert r.status_code == 200
    song = lyrics.load(root / "out" / "S" / "lyrics.timed.md")
    assert [s.start for s in song.sections] == [0.0, 4.0, 8.5]
    assert (root / "data" / "S" / "l.txt").read_text(encoding="utf-8") == LYRICS  # 元は触らない
    again = client.get("/api/songs/S/timeline").json()
    assert [s["start"] for s in again["sections"]] == [0.0, 4.0, 8.5]


def test_timeline_refuses_bad_starts(client):
    assert client.put("/api/songs/S/timeline", json={"starts": [0.0, 5.0, 4.0]}).status_code == 400
    assert client.put("/api/songs/S/timeline", json={"starts": [0.0, 5.0]}).status_code == 400


def test_suggest_gives_one_start_per_section(client, monkeypatch):
    def fake(song, beats):
        return [structure.Boundary(s.name, t, m) for s, t, m in
                zip(song.sections, (0.0, 4.0, 8.0), (float("inf"), 0.001, 1.0))]

    monkeypatch.setattr(desk.structure, "estimate", fake)
    r = client.post("/api/songs/S/timeline/suggest").json()
    assert [x["section"] for x in r] == ["Intro", "Verse 1", "Chorus 1"]
    assert r[0]["margin"] is None and [x["doubtful"] for x in r] == [False, True, False]


def test_suggest_that_cannot_place_says_why(client):
    """12 秒に3つは置けない——推定の断りはそのまま 400 で画面に出す。"""
    r = client.post("/api/songs/S/timeline/suggest")
    assert r.status_code == 400 and "置ききれない" in r.json()["detail"]


def test_audio_is_served_for_the_player(client):
    r = client.get("/api/songs/S/media/audio")
    assert r.status_code == 200 and r.content[:4] == b"RIFF"


def test_command_is_built_from_steps():
    cmd = desk.command(desk.Path("d"), desk.Path("o"), ["emotion"], ["score"])
    assert cmd[-4:] == ["--steps", "emotion", "--redo", "score"]
    assert "--previews" in desk.command(desk.Path("d"), desk.Path("o"), previews=True)
    with pytest.raises(ValueError, match="知らない工程"):
        desk.command(desk.Path("d"), desk.Path("o"), ["nope"])


def test_jobs_run_log_and_stop(tmp_path):
    jobs = desk.Jobs()
    log = tmp_path / "out" / "job.log"
    j = jobs.start("S", [sys.executable, "-c", "print('hi')"], log)
    for _ in range(100):
        if j.view()["state"] != "running":
            break
        time.sleep(0.05)
    v = j.view()
    assert v["state"] == "done" and "hi" in v["tail"]
    slow = jobs.start("S", [sys.executable, "-c", "import time; time.sleep(30)"], log)
    with pytest.raises(ValueError, match="もう書き出している"):
        jobs.start("S", [sys.executable, "-c", "pass"], log)
    assert jobs.stop(slow.id).view()["state"] == "failed"


def test_line_times_need_section_times_then_save(client, root):
    assert client.get("/api/songs/S/timeline").json()["line_spread"] is None
    bad = client.put("/api/songs/S/timeline/lines", json={"starts": [[], [4.0, 5.0], [8.5]]})
    assert bad.status_code == 400 and "セクションの時刻" in bad.json()["detail"]
    client.put("/api/songs/S/timeline", json={"starts": [0.0, 4.0, 8.5]})
    tl = client.get("/api/songs/S/timeline").json()
    assert tl["line_spread"] == [[], [4.0, 6.25], [8.5]] and tl["line_starts"] is None
    assert client.put("/api/songs/S/timeline/lines",
                      json={"starts": [[], [4.2, 5.0], [8.6]]}).status_code == 200
    assert client.get("/api/songs/S/timeline").json()["line_starts"] == [[], [4.2, 5.0], [8.6]]
    assert (root / "out" / "S" / "lines.json").is_file()
