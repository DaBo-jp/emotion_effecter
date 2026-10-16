"""ffmpeg で動画をつなぐ・揃える・並べる。描画は持たない。

尺はすべてフレーム数で扱う。秒で切ると端数の切り捨てで1フレームずれ、
つないだ動画が音より短くなる。
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def probe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def count_frames(path: str) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True).stdout.strip()
    return int(out)


def frames_of(path: str, fps: int) -> int:
    """その動画を fps に揃えたときのフレーム数（切り捨て）。10.005秒 → 300。"""
    return int(probe_duration(path) * fps)


def audio_of(path: str, sr: int) -> np.ndarray:
    """動画（か音源）の音を、モノラル float32 の `sr` Hz で。音が無ければ落ちる。"""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sr),
         "-f", "f32le", "-"], capture_output=True, check=True).stdout
    if not raw:
        raise ValueError("音が無い: %s" % path)
    return np.frombuffer(raw, np.float32)


def extract_audio(src: str, dst: str) -> str:
    """動画の音を WAV に（44.1kHz）。書き出しの音はこれを乗せる。"""
    _ff("-i", src, "-vn", "-ar", "44100", "-c:a", "pcm_s16le", dst)
    return dst


#: Jev が読める画像の辺の長さ（px、両端を含む）。外れる画像は縮めずに断られる
IMAGE_SIDE = (280, 1568)


def still_at(path: str, t: float, dst: str) -> str:
    """t 秒のフレームを JPEG に。長い辺を `IMAGE_SIDE` の上限まで縮める。

    短い辺が下限に届かない映像は断る——引き伸ばしても見えるものは増えない。
    """
    lo, hi = IMAGE_SIDE
    _ff("-ss", "%.3f" % t, "-i", path, "-frames:v", "1", "-vf",
        "scale='min(%d,iw)':'min(%d,ih)':force_original_aspect_ratio=decrease" % (hi, hi),
        "-q:v", "3", dst)
    with Image.open(dst) as im:
        if min(im.size) < lo:
            raise ValueError("%s: 映像が小さすぎる（%dx%d、短い辺 %dpx 以上が要る）"
                             % (path, im.size[0], im.size[1], lo))
    return dst


def conform(src: str, dst: str, fps: int, frames: int) -> str:
    """fps を揃えて、ちょうど frames フレームに切る。音は捨てる（後で乗せ直す）。"""
    _ff("-i", src, "-vf", "fps=%d" % fps, "-frames:v", str(frames), "-an",
        "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", dst)
    return dst


def concat(parts: Sequence[str], dst: str) -> str:
    """同じ形式の動画を再エンコードせずにつなぐ。"""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.writelines("file '%s'\n" % os.path.abspath(p) for p in parts)
    try:
        _ff("-f", "concat", "-safe", "0", "-i", fh.name, "-c", "copy", dst)
    finally:
        os.remove(fh.name)
    return dst


def mux(video: str, audio: str, dst: str, seconds: float) -> str:
    """音を乗せる。`-shortest` は AAC のフレーム境界で音を削るので `-t` で切る。"""
    _ff("-i", video, "-i", audio, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "256k", "-t", "%.3f" % seconds, dst)
    return dst


def label(text: str, dst: str, size: int = 22) -> str:
    """半透明の地に白文字の札（PNG）。"""
    font = ImageFont.truetype(FONT, size)
    w = int(font.getlength(text)) + 24
    im = Image.new("RGBA", (w, size + 16), (0, 0, 0, 150))
    ImageDraw.Draw(im).text((12, 6), text, font=font, fill=(255, 255, 255, 235))
    im.save(dst)
    return dst


def stack(top: str, bottom: str, dst: str, labels: tuple[str, str] | None = None,
          audio_from: int = 0, fit: int | None = None) -> str:
    """上下に並べた1本。音は `audio_from`（0=上 / 1=下）から。尺は短い方に合わせる。

    `fit` を渡すと両方をその幅に揃えてから並べる（元の映像と書き出しで大きさが違うとき）。
    """
    seconds = min(probe_duration(top), probe_duration(bottom))
    pre = "" if fit is None else "[0:v]scale=%d:-2[t];[1:v]scale=%d:-2[u];" % (fit, fit)
    a, b = ("[0:v]", "[1:v]") if fit is None else ("[t]", "[u]")
    with tempfile.TemporaryDirectory() as tmp:
        if labels:
            tags = [label(t, os.path.join(tmp, "l%d.png" % i)) for i, t in enumerate(labels)]
            inputs = ["-i", top, "-i", bottom, "-i", tags[0], "-i", tags[1]]
            graph = pre + ("%s[2:v]overlay=14:14[a];%s[3:v]overlay=14:14[b];"
                           "[a][b]vstack=inputs=2[v]" % (a, b))
        else:
            inputs = ["-i", top, "-i", bottom]
            graph = pre + "%s%svstack=inputs=2[v]" % (a, b)
        _ff(*inputs, "-filter_complex", graph, "-map", "[v]", "-map", "%d:a" % audio_from,
            "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-t", "%.3f" % seconds, dst)
    return dst


def sheet(rows: Sequence[tuple[str, Sequence[str]]], dst: str, width: int = 480) -> str:
    """見出しつきの行を縦に積んだ1枚。行は (見出し, 横に並べる画像)。"""
    font = ImageFont.truetype(FONT, 14)
    tiles = [[Image.open(p).convert("RGB") for p in ims] for _label, ims in rows]
    w, h = width, int(width * tiles[0][0].height / tiles[0][0].width)
    cols = max(len(t) for t in tiles)
    out = Image.new("RGB", (w * cols, (h + 22) * len(rows)), (0, 0, 0))
    draw = ImageDraw.Draw(out)
    for r, ((label, _), ims) in enumerate(zip(rows, tiles)):
        y = r * (h + 22)
        draw.text((6, y + 3), label, font=font, fill=(255, 255, 255))
        for c, im in enumerate(ims):
            out.paste(im.resize((w, h)), (c * w, y + 22))
    out.save(dst)
    return dst
