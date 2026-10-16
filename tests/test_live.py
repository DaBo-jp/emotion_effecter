"""ライブ動画1本 → 盛り上がりに合わせたエフェクト。動画は合成して作り、Jev は差し替える。"""
import json
import subprocess

import numpy as np
import pytest
from PIL import Image

from emotion_effecter import audience, livefile, liveflow, timeline, windows


# ------------------------------------------------------------------ 区切り
def test_windows_are_bars_long():
    assert windows.starts(40.0, 120.0, 8) == [0.0, 16.0, 32.0]


def test_a_tail_shorter_than_a_bar_joins_the_previous_window():
    assert windows.starts(33.0, 120.0, 8) == [0.0, 16.0]   # 最後の 1秒は 1小節(2秒)未満


def test_windows_refuse_nonsense():
    with pytest.raises(ValueError):
        windows.starts(10.0, 0.0, 8)


def test_window_song_has_no_lyrics_so_the_timeline_has_only_hype():
    song = windows.song("T", 40.0, 120.0, 8)
    assert [s.name for s in song.sections] == ["W01 0:00.00", "W02 0:16.00", "W03 0:32.00"]
    cs = [audience.Cheer(s.name, 0.0, (0.0,), {"hype": v}, {}, {})
          for s, v in zip(song.sections, (0.2, 0.9, 0.4))]
    tl = timeline.build(song, [], 40.0, 10, xfade=0.0, cheers=cs)
    assert tl.names == ("hype",) and tl.at("hype", 200) == pytest.approx(0.9)


# ------------------------------------------------------------------ live.json
def _write(root, **doc):
    (root / "Live.mp4").write_text("x")
    base = {"title": "T", "files": {"video": "Live.mp4"}, "base": {"effect": "motif"}}
    (root / "live.json").write_text(json.dumps({**base, **doc}), encoding="utf-8")


def test_live_json_defaults_every_axis_to_hype(tmp_path):
    _write(tmp_path)
    lv = livefile.load(tmp_path)
    assert (lv.policy.color_by, lv.policy.glow_by, lv.policy.gain_by) == ("hype",) * 3
    assert (lv.bars, lv.bpm, lv.spread) == (8, 0.0, 2.0) and lv.video.endswith("Live.mp4")


def test_live_json_lists_every_problem(tmp_path):
    _write(tmp_path, files={"video": "nope.mp4"}, policy={"glow_by": "arousal"},
           window={"bars": 0, "fps": 3}, extra=1,
           overlays=[{"effect": "crowd",
                      "moods": {"bounce": {"by": "valence", "lo": 0.0, "hi": 0.1}}}])
    with pytest.raises(ValueError) as e:
        livefile.load(tmp_path)
    msg = str(e.value)
    for word in ("extra", "nope.mp4", "glow_by=arousal", "window.bars", "fps",
                 "moods.bounce"):
        assert word in msg, word


# ------------------------------------------------------------------ 通し
def _live_video(path, seconds=12):
    """拍の入った音と、時間で絵が変わる映像。"""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=512x288:rate=30:duration=%d" % seconds, "-f", "lavfi",
                    "-i", "aevalsrc='sin(2*PI*60*t)*lt(mod(t\\,0.5)\\,0.08)':s=44100:d=%d"
                    % seconds, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(path)], check=True)


def test_run_end_to_end(tmp_path, monkeypatch):
    src = tmp_path / "in"
    src.mkdir()
    _live_video(src / "Live.mp4")
    (src / "live.json").write_text(json.dumps({
        "title": "T", "files": {"video": "Live.mp4"},
        "base": {"effect": "motif", "params": {"width": 320, "height": 180, "rate": 6}},
        "overlays": [{"effect": "crowd", "params": {"db_floor": -40, "db_ceil": 0},
                      "moods": {"bounce": {"by": "hype", "lo": 0.0, "hi": 0.2}}}],
        "window": {"bars": 2, "bpm": 120, "spread": 1}}), encoding="utf-8")
    seen = []

    def fake_score(shots, paths, questions):
        seen.append((questions is audience.SCENE, [len(p) for p in paths]))
        for ps in paths:
            for p in ps:
                assert Image.open(p).size == (512, 288)
        return [audience.Cheer(s.section, s.t, s.at, {"hype": i / len(shots)}, {}, {})
                for i, s in enumerate(shots)]

    monkeypatch.setattr(liveflow.audience, "score", fake_score)
    o = liveflow.run(livefile.load(src), tmp_path / "out", say=lambda s: None)
    assert seen == [(True, [3, 3, 3])]                    # 12秒 ÷ 4秒（2小節）
    plan = json.loads((tmp_path / "out" / "live.mp4.plan.json").read_text())
    assert plan["overlays"][0]["effect"] == "crowd" and plan["policy"]["glow_by"] == "hype"
    frames = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams",
                             "v:0", "-show_entries", "stream=nb_read_frames", "-of",
                             "csv=p=0", o["live"]], capture_output=True, text=True).stdout
    assert int(frames) == 360
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", o["compare"], "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    assert len(np.frombuffer(raw, np.uint8)) == 320 * 360 * 3     # 上下とも幅 320
    liveflow.run(livefile.load(src), tmp_path / "out", steps=["score"], say=lambda s: None)
    assert len(seen) == 1                                 # 採点はあれば作り直さない
