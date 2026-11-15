"""手元で開く画面（`emotion-effecter ui`）。HTTP の口だけで、判断は持たない——`desk` を呼ぶ。

    uv run --env-file .env emotion-effecter ui          → http://127.0.0.1:8765

自分の PC で開くためのもの。外から届く場所（0.0.0.0）では開かない——ファイルを書き、
子プロセスを起こすので。画面は `ui.html` の1枚。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from . import desk

PAGE = Path(__file__).with_name("ui.html")


@dataclass
class Desk:
    """曲の置き場所と出力の置き場所、走っている仕事、重いタイムラインの控え。"""

    data: Path
    out: Path
    jobs: desk.Jobs = field(default_factory=desk.Jobs)
    #: (曲, ファイルの更新時刻) → 音の解析（`desk.sound`）。拍の解析に数秒かかる
    timelines: dict[tuple, dict[str, Any]] = field(default_factory=dict)

    def song(self, name: str) -> Path:
        d = (self.data / name).resolve()
        if d.parent != self.data.resolve() or not (d / "song.json").is_file():
            raise HTTPException(404, "曲が無い: %s" % name)
        return d

    def outdir(self, name: str) -> Path:
        return self.out / self.song(name).name


def _guard(fn, *args: Any) -> Any:
    """`desk` の ValueError（書き方の間違い）を 400 に。"""
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def _song_routes(api: FastAPI, dk: Desk) -> None:
    @api.get("/api/songs")
    def songs() -> list[dict[str, Any]]:
        return desk.songs(dk.data, dk.out)

    @api.get("/api/choices")
    def choices() -> dict[str, Any]:
        return desk.choices()

    @api.get("/api/songs/{name}")
    def song(name: str) -> dict[str, Any]:
        d = dk.song(name)
        doc = _guard(desk.doc_of, d)
        return {"doc": doc, "problems": desk.check(d, doc), "files": desk.files_in(d),
                "sections": desk.section_names(d)}

    @api.post("/api/songs/{name}/check")
    def check(name: str, doc: Any = Body(...)) -> list[str]:
        return desk.check(dk.song(name), doc)

    @api.put("/api/songs/{name}")
    def save(name: str, doc: dict[str, Any] = Body(...)) -> list[str]:
        return desk.save(dk.song(name), doc)


def _stamp(dk: Desk, name: str) -> tuple:
    """音の解析の控えの鍵。曲のディレクトリのファイルが変われば変わる。"""
    files = sorted(p for p in dk.song(name).iterdir() if p.is_file())
    return (name, *((p.name, p.stat().st_mtime) for p in files))


def _timeline_routes(api: FastAPI, dk: Desk) -> None:
    @api.get("/api/songs/{name}/timeline")
    def timeline(name: str) -> dict[str, Any]:
        key = _stamp(dk, name)
        if key not in dk.timelines:              # 音の解析は数秒かかるので控える
            dk.timelines[key] = _guard(desk.sound, dk.song(name))
        snd = dk.timelines[key]
        return {**snd, **_guard(desk.words, dk.song(name), dk.outdir(name), snd["duration"])}

    @api.post("/api/songs/{name}/timeline/suggest")
    def suggest(name: str) -> list[dict[str, Any]]:
        return _guard(desk.suggest, dk.song(name))

    @api.put("/api/songs/{name}/timeline")
    def save(name: str, starts: list[float] = Body(..., embed=True)) -> dict[str, str]:
        return {"file": _guard(desk.save_timeline, dk.song(name), dk.outdir(name), starts)}

    @api.put("/api/songs/{name}/timeline/lines")
    def save_lines(name: str,
                   starts: list[list[float]] = Body(..., embed=True)) -> dict[str, str]:
        return {"file": _guard(desk.save_lines, dk.song(name), dk.outdir(name), starts)}

    @api.get("/api/songs/{name}/media/{role}")
    def media(name: str, role: str) -> FileResponse:
        return FileResponse(_guard(desk.file_of, dk.song(name), role))


def _out_routes(api: FastAPI, dk: Desk) -> None:
    @api.get("/api/songs/{name}/out/{file}")
    def output(name: str, file: str) -> FileResponse:
        path = (dk.outdir(name) / file).resolve()
        if path.parent != dk.outdir(name).resolve() or not path.is_file():
            raise HTTPException(404, "出力が無い: %s" % file)
        return FileResponse(path, headers={"Cache-Control": "no-store"})


def _job_routes(api: FastAPI, dk: Desk) -> None:
    @api.post("/api/songs/{name}/jobs")
    def start(name: str, req: dict[str, Any] = Body(...)) -> dict[str, Any]:
        out = dk.outdir(name)
        cmd = _guard(desk.command, dk.song(name), out, req.get("steps", []),
                     req.get("redo", []), bool(req.get("previews")))
        return _guard(dk.jobs.start, name, cmd, out / desk.JOB_LOG).view()

    @api.get("/api/jobs")
    def jobs() -> list[dict[str, Any]]:
        return [j.view(tail=1) for j in dk.jobs.items.values()]

    @api.get("/api/jobs/{job_id}")
    def job(job_id: int) -> dict[str, Any]:
        if job_id not in dk.jobs.items:
            raise HTTPException(404, "仕事が無い: %d" % job_id)
        return dk.jobs.items[job_id].view()

    @api.delete("/api/jobs/{job_id}")
    def stop(job_id: int) -> dict[str, Any]:
        if job_id not in dk.jobs.items:
            raise HTTPException(404, "仕事が無い: %d" % job_id)
        return dk.jobs.stop(job_id).view()


def app(data: Path, out: Path) -> FastAPI:
    api = FastAPI(title="emotion_effecter")
    dk = Desk(data.resolve(), out.resolve())
    for add in (_song_routes, _timeline_routes, _out_routes, _job_routes):
        add(api, dk)

    @api.get("/", response_class=HTMLResponse)
    def page() -> str:
        return PAGE.read_text(encoding="utf-8")

    return api


def serve(data: Path, out: Path, port: int = 8765) -> None:
    import uvicorn

    print("http://127.0.0.1:%d" % port)
    uvicorn.run(app(data, out), host="127.0.0.1", port=port, log_level="warning")
