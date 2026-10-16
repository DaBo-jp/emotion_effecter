"""聴衆の映像 → 時刻合わせ → セクションごとの盛り上がり。映像は合成して作る。"""
import json
import subprocess
import wave
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from emotion_effecter import (
    audience,
    dims,
    lyrics,
    manifest,
    policy,
    sync,
    timeline,
    video,
    workflow,
)
from tests.conftest import make_mood

SR = sync.SR
TEXT = """[Intro @0:00]
[Verse 1 @0:04]
a
[Instrumental Break @0:10]
[Chorus 1 @0:14]
b
"""


def _clicks(seconds: float, seed: int = 0) -> np.ndarray:
    """拍のばらついたクリック列（曲の代わり）。"""
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 0.01, int(seconds * SR))
    t = 0.0
    while t < seconds - 0.1:
        i = int(t * SR)
        x[i:i + 200] += np.hanning(200) * rng.uniform(0.4, 1.0)
        t += rng.uniform(0.18, 0.6)
    return x.astype(np.float32)


def _venue(x: np.ndarray, seed: int = 1) -> np.ndarray:
    """会場で録った音の代わり。こもらせて、歓声の雑音を足す。"""
    soft = np.convolve(x, np.ones(8) / 8, "same")
    return (0.6 * soft + np.random.default_rng(seed).normal(0, 0.03, len(x))).astype(
        np.float32)


def test_measure_finds_a_clip_that_started_before_the_song():
    song = _clicks(20)
    clip = np.concatenate([np.zeros(int(3.25 * SR), np.float32), _venue(song)])
    s = sync.measure(song, clip)
    assert abs(s.lead - 3.25) < 0.02 and s.strength > sync.MIN_STRENGTH


def test_measure_finds_a_clip_that_started_after_the_song():
    song = _clicks(20)
    s = sync.measure(song, _venue(song[int(5.0 * SR):]))
    assert abs(s.lead + 5.0) < 0.02 and s.video_time(7.0) == pytest.approx(2.0, abs=0.02)


# ------------------------------------------------------------------ 合成の映像
def _wav(path, x, sr=SR):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 30000).astype(np.int16).tobytes())
    return str(path)


def _clip(path, wav, seconds, size="640x360"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=%s:rate=10:duration=%s" % (size, seconds), "-i", wav,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(path)], check=True)
    return str(path)


@pytest.fixture
def media(tmp_path):
    song = _clicks(20)
    clip_audio = np.concatenate([np.zeros(int(2.0 * SR), np.float32), _venue(song)])
    s = _wav(tmp_path / "song.wav", song)
    v = _clip(tmp_path / "crowd.mp4", _wav(tmp_path / "venue.wav", clip_audio), 22)
    return s, v, tmp_path


def test_align_reads_the_video_sound(media):
    s, v, _tmp = media
    assert abs(sync.align(s, v).lead - 2.0) < 0.05


def test_align_refuses_an_unrelated_video(media, tmp_path):
    s, _v, _tmp = media
    other = _clip(tmp_path / "other.mp4",
                  _wav(tmp_path / "noise.wav", _clicks(20, seed=9) * 0.0 +
                       np.random.default_rng(3).normal(0, 0.2, 20 * SR)), 20)
    with pytest.raises(ValueError, match="audience.lead"):
        sync.align(s, other)


def test_still_fits_the_image_limits(media, tmp_path):
    _s, v, _tmp = media
    big = _clip(tmp_path / "big.mp4", _wav(tmp_path / "q.wav", np.zeros(SR)), 1, "3200x1800")
    with Image.open(video.still_at(big, 0.5, str(tmp_path / "b.jpg"))) as im:
        assert im.size == (1568, 882)
    small = _clip(tmp_path / "small.mp4", _wav(tmp_path / "q2.wav", np.zeros(SR)), 1,
                  "320x180")
    with pytest.raises(ValueError, match="小さすぎる"):
        video.still_at(small, 0.5, str(tmp_path / "s.jpg"))


# ------------------------------------------------------------------ 取る時刻
def test_plan_takes_three_moments_around_the_middle_of_every_section():
    song = lyrics.parse(TEXT)
    shots = audience.plan(song, 20.0, 2.0, 22.0)
    assert [s.section for s in shots] == [s.name for s in song.sections]
    chorus = shots[-1]
    assert chorus.t == 17.0 and chorus.at == (17.0, 19.0, 21.0)
    intro = shots[0]                                   # 4秒しかない → 中ほど ±1.8
    assert intro.at == pytest.approx((2.2, 4.0, 5.8))


def test_plan_lists_every_section_outside_the_video():
    with pytest.raises(ValueError) as e:
        audience.plan(lyrics.parse(TEXT), 20.0, -3.0, 10.0)
    msg = str(e.value)
    assert "Intro" in msg and "Chorus 1" in msg and "Verse 1" not in msg


# ------------------------------------------------------------------ Jev
class _Client:
    def __init__(self):
        self.calls = []

    async def system_one(self, **kw):
        self.calls.append(kw)
        a = SimpleNamespace(score=3.0, confidence=0.7, probabilities={0: 0.1, 3: 0.8, 4: 0.1})
        return SimpleNamespace(scores={"hype": a})


def test_scoring_sends_the_frames_as_images_with_the_header(tmp_path):
    import asyncio

    paths = []
    for i in range(3):
        Image.new("RGB", (300, 300)).save(tmp_path / ("%d.jpg" % i))
        paths.append(str(tmp_path / ("%d.jpg" % i)))
    shot = audience.Shot("Chorus 1", 17.0, (17.0, 19.0, 21.0))
    c = _Client()
    (cheer,) = asyncio.run(audience.score_shots([shot], [paths], c))
    kw = c.calls[0]
    assert kw["extra_headers"]["TypeSafe-Danger-Zone-Images"] == "true"
    assert len(kw["state"]["frames"]) == 3 and set(kw["questions"]) == {"hype"}
    assert cheer.scores == {"hype": 0.75} and cheer.at == shot.at


def test_questions_are_the_audience_axes():
    assert tuple(audience.QUESTIONS) == dims.AUDIENCE
    assert set(dims.AUDIENCE) <= set(dims.AXES) and not set(dims.AUDIENCE) & set(dims.DIMS)


def _cheers(song, values):
    return [audience.Cheer(s.name, 0.0, (0.0,), {"hype": v}, {"hype": 0.9}, {})
            for s, v in zip(song.sections, values)]


def test_save_load_roundtrip(tmp_path):
    song = lyrics.parse(TEXT)
    cs = _cheers(song, [0.1, 0.3, 0.9, 0.6])
    audience.save(tmp_path / "a.json", "T", {"lead": 2.0, "strength": 30.0}, cs)
    assert audience.load(tmp_path / "a.json") == cs
    (tmp_path / "b.json").write_text("[]")
    with pytest.raises(ValueError, match="形式"):
        audience.load(tmp_path / "b.json")


# ------------------------------------------------------------------ 曲線
def test_hype_has_its_own_value_even_in_the_instrumental_break():
    song = lyrics.parse(TEXT)
    moods = [make_mood("Verse 1", 0.0), make_mood("Chorus 1", 1.0)]
    tl = timeline.build(song, moods, 20.0, 10, xfade=0.0,
                        cheers=_cheers(song, [0.1, 0.3, 0.9, 0.6]))
    assert "hype" in tl.names and "acceptance" in tl.names
    assert tl.at("hype", 120) == pytest.approx(0.9)        # 間奏で沸いている
    assert tl.at("acceptance", 120) == pytest.approx(0.5, abs=0.1)  # 歌詞の軸はつなぐ


def test_timeline_without_cheers_is_unchanged():
    song = lyrics.parse(TEXT)
    moods = [make_mood("Verse 1", 0.0), make_mood("Chorus 1", 1.0)]
    assert "hype" not in timeline.build(song, moods, 20.0, 10).names


def test_cheers_must_match_the_sections():
    song = lyrics.parse(TEXT)
    with pytest.raises(ValueError, match="Instrumental Break"):
        timeline.cheer_marks(song, _cheers(song, [0.1, 0.3, 0.9, 0.6])[:2] +
                             _cheers(song, [0, 0, 0, 0.6])[3:])


# ------------------------------------------------------------------ song.json
def _doc(tmp_path, **extra):
    for f in ("l.md", "a.wav", "i.png", "c.mp4"):
        (tmp_path / f).write_text("x")
    doc = {"title": "T", "files": {"lyrics": "l.md", "audio": "a.wav", "image": "i.png"},
           "base": {"effect": "motif"}, **extra}
    (tmp_path / "song.json").write_text(json.dumps(doc), encoding="utf-8")
    return doc


def test_hype_without_an_audience_video_is_refused(tmp_path):
    _doc(tmp_path, policy={"glow_by": "hype"},
         overlays=[{"effect": "crowd",
                    "moods": {"bounce": {"by": "hype", "lo": 0.0, "hi": 0.1}}}],
         audience={"lead": 1.0, "nope": 2})
    with pytest.raises(ValueError) as e:
        manifest.load(tmp_path)
    msg = str(e.value)
    assert "glow_by" in msg and "moods.bounce" in msg and "nope" in msg
    assert "audience を書いたのに" in msg


def test_audience_video_and_manual_lead_are_read(tmp_path):
    doc = _doc(tmp_path, policy={"glow_by": "hype"}, audience={"lead": -1.5})
    doc["files"]["audience"] = "c.mp4"
    (tmp_path / "song.json").write_text(json.dumps(doc), encoding="utf-8")
    m = manifest.load(tmp_path)
    assert m.file("audience").endswith("c.mp4") and m.lead == -1.5 and m.spread == 2.0
    assert policy.from_mapping(m.policy).glow_by == "hype"


def test_workflow_scores_once_and_uses_the_manual_lead(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(workflow.sync, "align", lambda *a: pytest.fail("音で合わせない"))
    monkeypatch.setattr(workflow.audience, "stills", lambda clip, shots, tmp: [[]] * len(shots))
    monkeypatch.setattr(workflow.audio, "duration", lambda p: 20.0)
    monkeypatch.setattr(workflow.video, "probe_duration", lambda p: 30.0)

    def fake_score(shots, paths):
        calls.append([s.at for s in shots])
        return [audience.Cheer(s.section, s.t, s.at, {"hype": 0.5}, {}, {}) for s in shots]

    monkeypatch.setattr(workflow.audience, "score", fake_score)
    m = SimpleNamespace(file=lambda r: {"audience": "c.mp4", "audio": "a.wav"}.get(r),
                        lead=3.0, spread=2.0, title="T")
    o = workflow.Outputs(tmp_path)
    song = lyrics.parse(TEXT)
    first = workflow.cheers(m, o, song, (), lambda s: None)
    again = workflow.cheers(m, o, song, (), lambda s: None)
    assert len(calls) == 1 and first == again and calls[0][-1] == (18.0, 20.0, 22.0)
    doc = json.loads((tmp_path / "audience.json").read_text())
    assert doc["sync"] == {"lead": 3.0, "strength": 0.0}
