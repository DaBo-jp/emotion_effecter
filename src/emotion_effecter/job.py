"""Cloud Run Jobs の3段で1曲を書き出す。`workflow.run` を3つに割ったもの。

    prepare   tasks=1   Jev への質問・セクションの時刻・背景の動画（`workflow.targets`）。
                        書き出す本と区間の数を `job/plan.json` に
    render    tasks=N   N 個のタスクの index 番目が、区間の通し番号（本をまたぐ）i で
                        i % N == index のものを描いて `job/<役割>/` に置く
    finalize  tasks=1   区間を全部つなぎ、Opening / Closing・仕上げ・音を乗せる。compare も。
                        終われば `job/` を消す

**出力のディレクトリ（`out/<曲>/`）はタスクどうしで共有する**（Cloud Storage をそのまま
差す想定）。区間はまずタスクの手元に描き、書き終えてから共有の場所へ写す——途中の
ファイルを他のタスクが読まないように。

**render と finalize は Jev を呼ばない**（`jev.OFFLINE`）。prepare の残した出力を読む
だけで、無ければ断る。∴ どの段も同じ注文（`workflow.targets`）から同じ区間を出す。
prepare の数え（本と区間の数）と違えば断る。

タスクの番号と数は Cloud Run の `CLOUD_RUN_TASK_INDEX` / `CLOUD_RUN_TASK_COUNT`
（無ければ 0 / 1。手元では1つで全部描く）。
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from . import jev, production, workflow
from .manifest import Manifest

STAGES = ("prepare", "render", "finalize")

#: 共有の作業場所（`out/<曲>/` の中）
WORK = "job"

#: 書き出しの工程（compare は finalize がつないだ後に）
STEPS = ("emotion", "base")


@dataclass(frozen=True)
class Task:
    """Cloud Run のタスク。`index` 番目（0 から）／全部で `count` 個。"""

    index: int = 0
    count: int = 1

    def __post_init__(self) -> None:
        if self.count < 1 or not 0 <= self.index < self.count:
            raise ValueError("タスクの番号 %d / 数 %d がおかしい（0 <= 番号 < 数）"
                             % (self.index, self.count))

    @staticmethod
    def from_env(env: Mapping[str, str]) -> Task:
        return Task(int(env.get("CLOUD_RUN_TASK_INDEX", "0")),
                    int(env.get("CLOUD_RUN_TASK_COUNT", "1")))

    def mine(self, n: int, offset: int = 0) -> list[int]:
        """n 個の区間のうち、このタスクが描く番号。`offset` は前の本までの区間の数——
        本をまたいで通し番号で配る（本ごとに配ると、前の方のタスクに偏る）。"""
        return [i for i in range(n) if (offset + i) % self.count == self.index]


def _work(o: workflow.Outputs, role: str = "") -> Path:
    return o.root / WORK / role if role else o.root / WORK


@contextlib.contextmanager
def _offline() -> Iterator[None]:
    """この中では Jev を呼ばない（呼ぼうとしたら `jev.Offline`）。抜けたら元に戻す。"""
    before = os.environ.get(jev.OFFLINE)
    os.environ[jev.OFFLINE] = "1"
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(jev.OFFLINE, None)
        else:
            os.environ[jev.OFFLINE] = before


def _counts(o: workflow.Outputs, ts: list[workflow.Target]) -> dict[str, int]:
    """役割 → 区間の数。"""
    return {t.role: len(production.plan(t.order, t.out, str(_work(o, t.role))).chunks)
            for t in ts}


def prepare(m: Manifest, out_dir: str | Path, say: workflow.Say = print) -> dict[str, int]:
    """Jev への質問と下ごしらえを全部済ませ、書き出す本と区間の数を残す。"""
    o = workflow.Outputs(Path(out_dir))
    o.root.mkdir(parents=True, exist_ok=True)
    counts = _counts(o, workflow.targets(m, o, STEPS, (), say))
    _work(o).mkdir(parents=True, exist_ok=True)
    (_work(o) / "plan.json").write_text(json.dumps({"chunks": counts}, indent=2),
                                        encoding="utf-8")
    say("prepare: %s" % ", ".join("%s %d 区間" % kv for kv in counts.items()))
    return counts


def _targets(m: Manifest, o: workflow.Outputs, say: workflow.Say) -> list[workflow.Target]:
    """prepare と同じ注文。数え（本と区間の数）が prepare と違えば断る。"""
    plan = _work(o) / "plan.json"
    if not plan.exists():
        raise FileNotFoundError("%s が無い——先に prepare を回す" % plan)
    want = json.loads(plan.read_text(encoding="utf-8"))["chunks"]
    with _offline():
        ts = workflow.targets(m, o, STEPS, (), say)
    got = _counts(o, ts)
    if got != want:
        raise ValueError("prepare の数え %s と違う: %s（入力が変わった？）" % (want, got))
    return ts


def _publish(part: str, shared: Path) -> str:
    """手元に描いた区間を共有の場所へ。書き終えてから名前を付ける。"""
    dst = shared / Path(part).name
    tmp = dst.with_name(dst.name + ".part")
    shutil.copyfile(part, tmp)
    os.replace(tmp, dst)
    return str(dst)


def render(m: Manifest, out_dir: str | Path, task: Task = Task(), jobs: int = 0,
           say: workflow.Say = print) -> list[str]:
    """このタスクの区間を描いて共有の場所に置く。戻り値は置いた区間。"""
    o = workflow.Outputs(Path(out_dir))
    done, offset = [], 0
    for t in _targets(m, o, say):
        shared = _work(o, t.role)
        shared.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp, _offline():
            p = production.plan(t.order, t.out, tmp)
            parts = production.draw(t.order, p, task.mine(len(p.chunks), offset), jobs)
            done += [_publish(part, shared) for part in parts]
        offset += len(p.chunks)
    say("render: タスク %d / %d が %d 区間" % (task.index, task.count, len(done)))
    return done


def _finish(t: workflow.Target, o: workflow.Outputs) -> dict:
    p = production.plan(t.order, t.out, str(_work(o, t.role)))
    missing = [Path(c.path).name for c in p.chunks if not Path(c.path).exists()]
    if missing:
        raise FileNotFoundError("%s: render が描いていない区間: %s"
                                % (t.role, ", ".join(missing)))
    return production.finish(t.order, p, [c.path for c in p.chunks], t.out)


def finalize(m: Manifest, out_dir: str | Path, say: workflow.Say = print) -> list[dict]:
    """区間を全部つないで書き出し、compare も作る。終われば共有の作業場所を消す。"""
    o = workflow.Outputs(Path(out_dir))
    recs = []
    for t in _targets(m, o, say):
        with _offline():
            recs.append(_finish(t, o))
        say("%s: %s" % (t.role, t.out))
    workflow.compare(m, o, say)
    shutil.rmtree(_work(o))
    return recs
