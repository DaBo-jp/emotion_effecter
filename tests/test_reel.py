"""背景の区間の並び（`reel`）。置き方は尺を差し替えて、書き出しは ffmpeg で通す。"""
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from emotion_effecter import lyrics, reel, video

FPS = 10
#: 0〜2 / 2〜5 / 5〜8 / 8〜10 秒
SONG = lyrics.parse("[Intro @0:00]\na\n[Instrumental Break @0:02]\n"
                    "[Chorus @0:05]\nb\n[Instrumental Break @0:08]\n")
SONG_F = 100


def _seg(kind, name, until=None, seconds=0.0, transition="fade"):
    return reel.Segment(kind, name, until, transition, seconds)


def _len(lengths):
    return lambda p: lengths[p]


def _spans(segs, lengths=None):
    return [(s.seg.path, s.f0, s.f1, s.overlap)
            for s in reel.place(segs, SONG, SONG_F, FPS, _len(lengths or {}))]


def test_opening_still_closing_is_one_way_to_write_it():
    """mp4 はその尺、残り全部の画像の後ろの mp4 は曲の終わりから逆に置く。"""
    segs = [_seg("video", "open"), _seg("image", "still"),
            _seg("video", "close", seconds=1.0)]
    assert _spans(segs, {"open": 20, "close": 30}) == [
        ("open", 0, 20, 0), ("still", 20, 80, 0), ("close", 70, 100, 10)]


def test_until_takes_the_next_section_of_that_name_and_mp4s_play_anywhere():
    """同じ名前のセクションは、その区間が始まった後に最初に終わるもの。"""
    segs = [_seg("image", "a", until="Instrumental Break"), _seg("video", "m", seconds=0.5),
            _seg("image", "b", until=9.0), _seg("image", "c", until="Instrumental Break")]
    assert _spans(segs, {"m": 25}) == [
        ("a", 0, 50, 0), ("m", 45, 70, 5), ("b", 70, 90, 0), ("c", 90, 100, 0)]


def test_last_mp4_is_cut_at_the_end_of_the_song():
    assert _spans([_seg("image", "a", until=3.0), _seg("video", "m")], {"m": 500}) == [
        ("a", 0, 30, 0), ("m", 30, 100, 0)]


def test_every_placement_problem_is_listed():
    """届かない・短すぎる・無いセクションを全部並べて断る。黙って伸ばさない。"""
    with pytest.raises(ValueError) as e:
        reel.place([_seg("image", "a", until="Bridge"), _seg("image", "b", until=6.0)],
                   SONG, SONG_F, FPS, _len({}))
    assert "until='Bridge'" in str(e.value)
    with pytest.raises(ValueError) as e:
        reel.place([_seg("image", "a", until=1.0), _seg("video", "m", seconds=2.0),
                    _seg("image", "b", until=5.0)], SONG, SONG_F, FPS, _len({"m": 30}))
    msg = str(e.value)
    assert "reel[0]: 区間が短すぎる" in msg and "曲の終わりに届かない" in msg


def test_manifest_problems_are_all_listed(tmp_path):
    for f in ("a.jpg", "m.mp4"):
        (tmp_path / f).write_text("x")
    doc = [{"image": "a.jpg", "in": {"seconds": 1}}, {"image": "a.jpg"},
           {"video": "m.mp4", "until": 3, "in": {"transition": "nope", "seconds": 0}},
           {"image": "gone.jpg"}, {"song": "x"}]
    msg = "\n".join(reel.problems(doc, tmp_path))
    for part in ("reel[0].in: 最初の区間には前が無い", "reel[2].until は繰り返す動画",
                 "reel[2].in.seconds", "reel[2].in.transition='nope'", "reel[3] の画像が無い",
                 "reel[4] は"):
        assert part in msg, part
    msg = "\n".join(reel.problems([{"image": "a.jpg"}, {"image": "a.jpg"}], tmp_path))
    assert "残り全部" in msg and "1つだけ" in msg
    msg = "\n".join(reel.problems([{"image": "a.jpg"}, {"image": "a.jpg", "until": 3}],
                                  tmp_path))
    assert "後ろは繰り返さない mp4 だけ" in msg


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")
def test_background_is_written_frame_exact_with_each_seam_its_own_way(tmp_path):
    """赤い画像 → 青い mp4（切り替え）→ 赤い画像（1秒のクロスフェード）。"""
    red, blue = str(tmp_path / "r.png"), str(tmp_path / "b.mp4")
    Image.new("RGB", (64, 36), (255, 0, 0)).save(red)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=blue:size=48x48:rate=24:duration=2", blue], check=True)
    segs = [_seg("image", red, until=1.0), _seg("video", blue),
            _seg("image", red, seconds=1.0)]
    spans = reel.place(segs, SONG, 50, FPS)
    dst = reel.write(str(tmp_path / "bg.mp4"), spans, 60, FPS, (32, 18))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", dst, "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 18, 32, 3).astype(int)
    assert len(fr) == 60 and video.count_frames(dst) == 60
    assert fr[5, 9, 16, 0] > 200 and fr[15, 9, 16, 2] > 200       # 赤 → 青（切り替え）
    assert 60 < fr[25, 9, 16, 0] < 200 and fr[45, 9, 16, 0] > 200  # 混ざって赤へ、余白まで赤


def test_a_looped_video_runs_until_like_an_image():
    """`loop` の mp4 は尺ではなく until まで。until が無ければ残り全部。"""
    segs = [reel.Segment("video", "loop", "Chorus", loop=True), _seg("image", "still"),
            _seg("video", "close")]
    assert _spans(segs, {"loop": 7, "close": 10}) == [
        ("loop", 0, 80, 0), ("still", 80, 90, 0), ("close", 90, 100, 0)]
    rest = [_seg("video", "open"), reel.Segment("video", "loop", loop=True)]
    assert _spans(rest, {"open": 20, "loop": 7}) == [("open", 0, 20, 0), ("loop", 20, 100, 0)]


def _files(tmp_path, *names):
    for n in names:
        (tmp_path / n).write_bytes(b"x")


def test_loop_flow_and_motion_problems_are_listed(tmp_path):
    _files(tmp_path, "a.jpg", "m.mp4")
    doc = [{"video": "m.mp4", "loop": "yes"},
           {"image": "a.jpg", "until": 3, "motion": {"position": "left_right", "item": 0.5}},
           {"flow": [], "until": 5},
           {"flow": ["a.jpg", "gone.gif"], "until": 6,
            "motion": {"jitter": 2, "back": "mist", "anchor": 0.5}},
           {"image": "a.jpg", "until": 7, "motion": {"width": 0.0, "band": "nope"}},
           {"flow": ["a.jpg"], "motion": {"direction": "left", "loop": 1}}]
    msg = "\n".join(reel.problems(doc, tmp_path))
    for part in ("reel[0].loop は true / false",
                 "reel[1].motion.position='left_right' は right / left / center",
                 "reel[1].motion の知らない項目: item（流れる区間だけ）",
                 "reel[2].flow は流す素材の並び", "reel[3] の素材が無い: gone.gif",
                 "reel[3].motion.jitter=2", "reel[3].motion.back='mist'",
                 "reel[3].motion の知らない項目: anchor（縮む区間だけ）",
                 "reel[4].motion.width=0.0", "reel[4].motion.band='nope'",
                 "reel[5].motion.direction='left'", "reel[5].motion.loop=1"):
        assert part in msg, part


def test_record_hashes_every_file_and_changes_with_motion(tmp_path):
    _files(tmp_path, "a.jpg", "b.jpg")
    doc = [{"flow": ["a.jpg", "b.jpg"]}]
    spans = reel.place(reel.from_list(doc, tmp_path), SONG, SONG_F, FPS)
    rec = reel.record(spans, 100, FPS, (32, 18))
    assert [p.rsplit("/", 1)[-1] for p, _h in rec["spans"][0][1]] == ["a.jpg", "b.jpg"]
    moved = reel.place(reel.from_list([{"flow": ["a.jpg", "b.jpg"], "motion": {"gap": 0.5}}],
                                      tmp_path), SONG, SONG_F, FPS)
    assert reel.record(moved, 100, FPS, (32, 18)) != rec


def _rgb(path, h, w):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(int)


def test_shrink_covers_the_screen_then_moves_into_the_column(tmp_path):
    """白い画像が画面ぜんたいを覆い、1秒止まって1秒で右の列へ縮む。後ろは単色。"""
    white = str(tmp_path / "w.png")
    Image.new("RGB", (40, 40), (255, 255, 255)).save(white)
    cfg = {"position": "right", "width": 0.25, "margin": 0.0, "anchor": 0.5, "hold": 1,
           "seconds": 1, "back": "color", "back_color": "0,0,255"}
    segs = reel.from_list([{"image": "w.png", "motion": cfg}], tmp_path)
    dst = reel.write(str(tmp_path / "bg.mp4"), reel.place(segs, SONG, 40, FPS), 40, FPS,
                     (64, 32))
    fr = _rgb(dst, 32, 64)
    assert fr[5].min() > 230                                      # 画面ぜんたいが白
    end = fr[-1]
    assert end[16, 56].min() > 230                                # 右の列の真ん中は白
    assert end[16, 10, 2] > 200 and end[16, 10, 0] < 40           # 空いたところは青
    assert end[2, 56, 2] > 200                                    # 正方形 16px：上は空く


def test_flow_items_pass_through_the_column_and_jitter_stays_inside():
    from emotion_effecter import motion

    cfg = dict(motion.options({"position": "center", "width": 0.5, "item": 0.5, "gap": 0.0,
                               "jitter": 1.0, "seed": 3}, "flow"))
    size = (100, 100)
    st = motion.Stream([(10, 10), (10, 20)], cfg, size, 10.0)
    assert st.slots(0.0) == []                                    # まだ入っていない
    first = st.slots(0.5)
    assert [s.item for s in first] == [0] and 75 < first[0].rect.y < 100   # 下から入る
    assert all(25 <= s.rect.x and s.rect.x + s.rect.w <= 75
               for t in np.linspace(0, 10, 41) for s in st.slots(float(t)))  # 列の中だけ
    assert st.slots(9.99) and st.slots(10.0) == []                # 区間の尺ちょうどで出きる
    xs = {round(s.rect.x, 3) for t in (2.0, 4.0) for s in st.slots(t)}
    assert len(xs) > 1                                            # 横がばらつく
    alt = motion.Stream([(10, 10)], dict(motion.options(
        {"position": "left_right", "speed": 0.5}, "flow")), size, 10.0)
    assert [alt.side(i) for i in range(3)] == ["left", "right", "left"]
    assert max(s.index for s in alt.slots(8.0)) >= 2             # speed を書けば繰り返す


def test_flow_writes_items_over_a_blurred_back(tmp_path):
    """画像と GIF が流れる。後ろは見えている素材をぼかしたもので、素材が無ければ単色。"""
    red = str(tmp_path / "r.png")
    Image.new("RGB", (20, 20), (255, 0, 0)).save(red)
    frames = [Image.new("RGB", (20, 20), (0, 255, 0)) for _ in range(3)]
    frames[0].save(tmp_path / "g.gif", save_all=True, append_images=frames[1:], duration=100)
    segs = reel.from_list([{"flow": ["r.png", "g.gif"],
                            "motion": {"position": "center", "width": 0.5, "dim": 0.5}}],
                          tmp_path)
    dst = reel.write(str(tmp_path / "bg.mp4"), reel.place(segs, SONG, 40, FPS), 40, FPS,
                     (64, 32))
    fr = _rgb(dst, 32, 64)
    assert len(fr) == 40 and fr[0].max() < 30                     # 入る前は黒
    mid = fr[10]                                                  # 赤が画面の真ん中あたり
    assert mid[:, 32, 0].max() > 200                              # 列に赤
    assert 20 < mid[16, 2, 0] < 200                               # 端はぼかした赤を暗く
    assert fr[30][:, 32, 1].max() > 200                           # 後から緑の GIF


def test_looped_video_repeats_in_the_background(tmp_path):
    """1秒（赤→青）の mp4 を繰り返して 3 秒。"""
    clip = str(tmp_path / "c.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=red:size=32x18:rate=10:duration=0.5", "-f", "lavfi", "-i",
                    "color=c=blue:size=32x18:rate=10:duration=0.5", "-filter_complex",
                    "[0:v][1:v]concat=n=2:v=1", clip], check=True)
    segs = reel.from_list([{"video": "c.mp4", "loop": True}], tmp_path)
    dst = reel.write(str(tmp_path / "bg.mp4"), reel.place(segs, SONG, 30, FPS), 30, FPS,
                     (32, 18))
    fr = _rgb(dst, 18, 32)
    assert [int(fr[f, 9, 16, 0] > 128) for f in (2, 7, 12, 17, 22, 27)] == [1, 0, 1, 0, 1, 0]


def test_motion_options_follow_the_lyrics_band():
    """位置と向きの名前は歌詞の帯（credits）と同じ。"""
    from emotion_effecter import motion, roll

    assert dict(motion.POSITIONS) == dict(roll.POSITIONS)
    assert motion.DIRECTIONS == roll.DIRECTIONS
