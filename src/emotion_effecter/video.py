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

#: 揃え直す・混ぜるときの画質（x264 の crf）。この後 cymatics の絵とつなぐので高めに
CRF = "16"


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
        "-c:v", "libx264", "-crf", CRF, "-pix_fmt", "yuv420p", dst)
    return dst


def _quoted(path: str) -> str:
    """concat の一覧に書くパス。`'` を含む曲名でも切れないよう、ffmpeg の書き方で囲む。"""
    return "'%s'" % path.replace("'", "'\\''")


def concat(parts: Sequence[str], dst: str) -> str:
    """同じ形式の動画を再エンコードせずにつなぐ。"""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.writelines("file %s\n" % _quoted(os.path.abspath(p)) for p in parts)
    try:
        _ff("-f", "concat", "-safe", "0", "-i", fh.name, "-c", "copy", dst)
    finally:
        os.remove(fh.name)
    return dst


#: つなぎ目の切り替え方（ffmpeg の xfade の transition）。`fade` が重ねて入れ替える
#: オーバーラップ。`custom`（数式で書く）は除く。最後の `channel` は ffmpeg に無い、
#: ここで式を書いた切り替え（`channel_expr`）
TRANSITIONS: tuple[str, ...] = (
    "fade", "wipeleft", "wiperight", "wipeup", "wipedown", "slideleft", "slideright",
    "slideup", "slidedown", "circlecrop", "rectcrop", "distance", "fadeblack", "fadewhite",
    "radial", "smoothleft", "smoothright", "smoothup", "smoothdown", "circleopen",
    "circleclose", "vertopen", "vertclose", "horzopen", "horzclose", "dissolve",
    "pixelize", "diagtl", "diagtr", "diagbl", "diagbr", "hlslice", "hrslice", "vuslice",
    "vdslice", "hblur", "fadegrays", "wipetl", "wipetr", "wipebl", "wipebr", "squeezeh",
    "squeezev", "zoomin", "fadefast", "fadeslow", "hlwind", "hrwind", "vuwind", "vdwind",
    "coverleft", "coverright", "coverup", "coverdown", "revealleft", "revealright",
    "revealup", "revealdown", "channel",
)


def _rand(v: str) -> str:
    """式 `v` → 0..1 の擬似乱数（GLSL でよく使う sin のハッシュ）。同じ入力なら同じ値。"""
    return "((sin(%s)*43758.5453)-floor(sin(%s)*43758.5453))" % (v, v)


def channel_expr() -> str:
    """`channel`：ダイヤル式のブラウン管テレビでチャンネルを回したときの乱れ。xfade の
    custom の式（yuv444p の 8bit で評価する）。

    重なりの真ん中に向かって乱れが強まり、真ん中で前の映像から次の映像へ移る。
    走査線ごとに横へ裂け（`dx`）、絵が縦に流れ（`sy`）、色が抜け、真ん中あたりは砂嵐。
    乱れはフレームの位置だけで決まる ∴ 何度書き出しても同じ絵。
    """
    q = "(1-P)"                                   # 0 → 1 に進む
    e = "sin(PI*%s)" % q                          # 乱れの強さ。両端 0、真ん中 1
    fr = "floor(%s*24)" % q                       # 乱れの模様が変わる刻み
    line = _rand("floor(Y/4)*12.9898+%s*78.233" % fr)
    dx = "(%s)*W*(0.05*sin(Y*14/H+%s*40)+0.45*(%s-0.5)*gt(%s,0.4))" % (e, q, line, e)
    sx, sy = "mod(X+%s+4*W,W)" % dx, "mod(Y+H*%s*%s*0.45+4*H,H)" % (e, e)

    def src(p: int) -> str:
        return "if(lt(%s,0.5),a%d(%s,%s),b%d(%s,%s))" % (q, p, sx, sy, p, sx, sy)

    snow = _rand("X*12.9898+Y*78.233+%s*37.719" % fr)
    s = "clip((%s-0.55)*2.2,0,0.9)" % e           # 砂嵐の濃さ
    luma = "(%s*(1-0.35*%s*%s)*(1-%s)+%s*255*%s)" % (src(0), e, line, s, snow, s)
    chroma = ["(128+(%s-128)*(1-%s))" % (src(p), e) for p in (1, 2)]
    return "if(eq(PLANE,0),%s,if(eq(PLANE,1),%s,%s))" % (luma, *chroma)


def _xfade(a: str, b: str, transition: str, frames: int, offset: int, fps: int,
           out: str) -> str:
    """`a` から `b` へ `frames` フレームで移る xfade（`offset` フレーム目から）。
    `channel` は数式の切り替え（custom）。式は 8bit の 4:4:4 で書いてあるので揃えて渡す。"""
    tail = "duration=%.6f:offset=%.6f%s" % (frames / fps, offset / fps, out)
    if transition != "channel":
        return "%s%sxfade=transition=%s:%s" % (a, b, transition, tail)
    tag = out.strip("[]")
    return ("%sformat=yuv444p[%sa];%sformat=yuv444p[%sb];[%sa][%sb]xfade=transition=custom:"
            "expr='%s':%s" % (a, tag, b, tag, tag, tag, channel_expr(), tail))


def crossfade(parts: Sequence[str], frames: Sequence[int], overlap: int, fps: int,
              dst: str, transition: str = "fade") -> str:
    """動画をつなぐ。つなぎ目ごとに `overlap` フレーム重ねて `transition` で切り替える
    （音なし）。

    `frames` は各動画のフレーム数。重ねたぶん短くなる——呼ぶ側が重なりのぶん
    長く用意する。オフセットはフレームで数えるので1フレームもずれない。
    """
    if transition not in TRANSITIONS:
        raise ValueError("知らない切り替え: %s" % transition)
    pre = ";".join("[%d:v]settb=AVTB,setpts=PTS-STARTPTS[v%d]" % (i, i)
                   for i in range(len(parts)))
    chain, cur, length = [], "[v0]", frames[0]
    for i in range(1, len(parts)):
        nxt = "[x%d]" % i
        chain.append(_xfade(cur, "[v%d]" % i, transition, overlap, length - overlap, fps, nxt))
        cur, length = nxt, length + frames[i] - overlap
    inputs = [x for p in parts for x in ("-i", p)]
    _ff(*inputs, "-filter_complex", ";".join([pre, *chain]), "-map", cur,
        "-frames:v", str(length), "-an", "-c:v", "libx264", "-crf", CRF,
        "-pix_fmt", "yuv420p", dst)
    return dst


def source(src: str, still: bool, fps: int, frames: int,
           size: tuple[int, int]) -> tuple[list[str], str]:
    """`chain` に渡す1本：(入力の引数, フィルタ)。画面 `size` を覆うように拡大して中央で
    切り、ちょうど `frames` フレームに。動画が足りなければ最後のフレームで止める。"""
    w, h = size
    fit = "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1" % (w, h, w, h)
    if still:
        # 1回だけ縮めて、そのフレームを繰り返す（毎フレーム読み直すと14倍遅い）
        return ["-i", src], "%s,loop=loop=%d:size=1:start=0,setpts=N/%d/TB,fps=%d" % (
            fit, frames - 1, fps, fps)
    return ["-i", src], "fps=%d,%s,tpad=stop_mode=clone:stop=-1,trim=end_frame=%d" % (
        fps, fit, frames)


def chain(sources: Sequence[tuple[list[str], str]], frames: Sequence[int],
          overlaps: Sequence[int], transitions: Sequence[str], fps: int, dst: str) -> str:
    """`source` の並びを1回の書き出しでつなぐ（音なし）。つなぎ目 i ごとに `overlaps[i]`
    フレーム重ねて `transitions[i]` で移る。0 なら切り替え。`overlaps[0]` は使わない。"""
    pre = ";".join("[%d:v]%s,settb=AVTB,setpts=PTS-STARTPTS[v%d]" % (i, vf, i)
                   for i, (_args, vf) in enumerate(sources))
    links, cur, length = [], "[v0]", frames[0]
    for i in range(1, len(sources)):
        nxt, ov = "[x%d]" % i, overlaps[i]
        if ov:
            links.append(_xfade(cur, "[v%d]" % i, transitions[i], ov, length - ov, fps, nxt))
        else:
            links.append("%s[v%d]concat=n=2:v=1:a=0%s" % (cur, i, nxt))
        cur, length = nxt, length + frames[i] - ov
    inputs = [x for args, _vf in sources for x in args]
    _ff(*inputs, "-filter_complex", ";".join([pre, *links]), "-map", cur,
        "-frames:v", str(length), "-an", "-c:v", "libx264", "-crf", CRF,
        "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", str(fps), dst)
    return dst


def finish(src: str, dst: str, frames: int, fps: int,
           black_in: tuple[float, float] | None = None,
           black_out: float | None = None,
           layers: Sequence[tuple[str, str]] = ()) -> str:
    """つないだ1本の仕上げ（音なし）。画面ぜんたい（絵・effect・歌詞）にかかる。

    `layers`＝(透過 PNG, y の式) の並び：下から順に、左端そろえで y の位置に重ねる
    （y は overlay の式。`t` 秒・`H` 画面の高さ・`h` 重ねる絵の高さが使える）。
    `black_in`＝(開始秒, 秒数)：開始秒までは真っ黒、そこから秒数で元の絵へ。
    `black_out`＝秒数：最後のその秒数で黒へ落ち、最後のフレームが真っ黒。
    黒は重ねたものごと落とす。フレーム数は変えない。
    """
    vf = []
    if black_in is not None:
        vf.append("fade=t=in:st=%.6f:d=%.6f" % black_in)
    if black_out is not None:
        vf.append("fade=t=out:st=%.6f:d=%.6f" % (frames / fps - black_out, black_out))
    graph, cur = [], "[0:v]"
    for i, (_png, y) in enumerate(layers, 1):
        graph.append("%s[%d:v]overlay=x=0:y='%s':eval=frame[l%d]" % (cur, i, y, i))
        cur = "[l%d]" % i
    graph.append("%s%s[out]" % (cur, ",".join(vf) or "null"))
    inputs = [x for png, _y in layers for x in ("-loop", "1", "-framerate", str(fps), "-i", png)]
    _ff("-i", src, *inputs, "-filter_complex", ";".join(graph), "-map", "[out]",
        "-frames:v", str(frames), "-an", "-c:v", "libx264", "-crf", CRF,
        "-pix_fmt", "yuv420p", dst)
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
