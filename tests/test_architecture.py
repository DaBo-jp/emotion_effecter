"""層の宣言（`emotion_effecter/architecture.py`）と実際のコードを突き合わせる。

守るのは3つ——**関数の外の可変メモリ禁止 / 関数を区切る / 同層の横依存禁止**。
どれも「そう書いた」では足りないので、AST で実測して落とす。
"""
import ast
import pathlib

import pytest

import emotion_effecter
from emotion_effecter.architecture import LAYERS, MAX_FUNCTION_LINES

ROOT = pathlib.Path(emotion_effecter.__file__).parent


def _files():
    return [f for f in sorted(ROOT.rglob("*.py")) if "__pycache__" not in f.parts]


def _modname(f: pathlib.Path) -> str:
    parts = list(f.relative_to(ROOT).parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def _resolve(f: pathlib.Path, level: int, module: str | None) -> str:
    """相対 import を `emotion_effecter.` を除いたモジュール名に直す。"""
    parts = list(f.relative_to(ROOT).parts)
    base = parts[:-1] if parts[-1] != "__init__.py" else parts[:-1]
    up = level - 1
    if up:
        base = base[:len(base) - up] if up <= len(base) else []
    return ".".join([*base, module] if module else base)


def _imports(f: pathlib.Path) -> set[str]:
    out = set()
    for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
        if isinstance(n, ast.ImportFrom) and n.level:
            t = _resolve(f, n.level, n.module)
            # `from . import a, b` は個々の名前がモジュールでもありうる
            if n.module is None:
                # `from . import color` — 見ているのは中身であって facade ではない
                for a in n.names:
                    out.add("%s.%s" % (t, a.name) if t else a.name)
            else:
                # `from ..dsp import audio` は dsp も dsp.audio も見ている
                out.add(t)
                for a in n.names:
                    out.add("%s.%s" % (t, a.name))
        elif isinstance(n, ast.ImportFrom) and (n.module or "").startswith("emotion_effecter."):
            out.add((n.module or "")[len("emotion_effecter."):])
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith("emotion_effecter."):
                    out.add(a.name[len("emotion_effecter."):])
    return {x for x in out if x}


def _known(name: str) -> str | None:
    """宣言にある一番長い接頭辞。`model.color.NAMED` → `model.color`。"""
    while name:
        if name in LAYERS:
            return name
        if "." not in name:
            return None
        name = name.rsplit(".", 1)[0]
    return None


# ------------------------------------------------- 1. 層の宣言
def test_every_module_declares_its_layer():
    """新しいモジュールは**層を宣言してから**置く。"""
    missing = sorted(_modname(f) for f in _files() if _modname(f) not in LAYERS)
    assert not missing, ("architecture.py の LAYERS に無い: %s" % ", ".join(missing))


def test_no_stale_entries_in_the_layer_table():
    have = {_modname(f) for f in _files()}
    assert not sorted(set(LAYERS) - have - {"__main__"}), \
        "LAYERS に無いモジュールが残っている"


@pytest.mark.parametrize("path", _files(), ids=_modname)
def test_imports_go_strictly_downward(path):
    """**import は必ず下の層へ。** 同じ層どうしは依存できない。

    依存が要るなら同じ層ではない——下に置き直す。`architecture.py` を直して
    初めて通る。
    """
    me = _modname(path)
    mine = LAYERS[me]
    bad = []
    for target in sorted(_imports(path)):
        key = _known(target)
        if key is None or key == me:
            continue
        theirs = LAYERS[key]
        if theirs > mine:
            bad.append("%s(層%d) ← 上を見ている" % (key, theirs))
        elif theirs == mine:
            bad.append("%s(層%d) ← **同層の横依存**" % (key, theirs))
    assert not bad, "%s(層%d) から:\n  %s" % (me, mine, "\n  ".join(bad))


def test_the_graph_has_no_cycle():
    g = {_modname(f): {k for k in (_known(t) for t in _imports(f)) if k}
         for f in _files()}
    seen, stack, cyc = set(), [], []

    def walk(n):
        if n in stack:
            cyc.append(stack[stack.index(n):] + [n])
            return
        if n in seen:
            return
        seen.add(n)
        stack.append(n)
        for m in sorted(g.get(n, ())):
            walk(m)
        stack.pop()

    for n in sorted(g):
        walk(n)
    assert not cyc, "\n".join(" → ".join(c) for c in cyc)


# ------------------------------------------------- 2. 関数の外のメモリ
_MUTABLE = (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)
_FROZEN_CALLS = {"MappingProxyType", "frozenset", "tuple"}


@pytest.mark.parametrize("path", _files(), ids=_modname)
def test_no_mutable_state_outside_functions(path):
    """**モジュール直下に可変なコンテナを置かない。**

    置いた瞬間に「誰がいつ書き換えたか」が追えなくなる。読むだけのデータなら
    `MappingProxyType` か `tuple` で固める。`__all__` は Python の約束事なので除く。
    """
    bad = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        tgt = node.targets[0] if isinstance(node, ast.Assign) else node.target
        name = getattr(tgt, "id", "")
        if name.startswith("__") and name.endswith("__"):
            continue
        v = node.value
        if isinstance(v, _MUTABLE):
            bad.append("%s 行%d %s" % (path.name, node.lineno, name))
        elif isinstance(v, ast.Call):
            fn = getattr(v.func, "id", getattr(v.func, "attr", ""))
            if fn in ("dict", "list", "set"):
                bad.append("%s 行%d %s" % (path.name, node.lineno, name))
    assert not bad, "可変なまま置かれている: " + ", ".join(bad)


@pytest.mark.parametrize("path", _files(), ids=_modname)
def test_import_has_no_side_effects(path):
    """**import しただけで何も起きない。** 呼び出しもループもモジュール直下に置かない。"""
    bad = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            fn = getattr(node.value.func, "id",
                         getattr(node.value.func, "attr", "?"))
            bad.append("行%d %s(...)" % (node.lineno, fn))
        elif isinstance(node, (ast.For, ast.While, ast.With, ast.Try)):
            bad.append("行%d %s" % (node.lineno, type(node).__name__))
    assert not bad, "%s: import 時に走る: %s" % (path.name, ", ".join(bad))


@pytest.mark.parametrize("path", _files(), ids=_modname)
def test_no_global_statement(path):
    """`global` / `nonlocal` で外を書き換えない。"""
    bad = [type(n).__name__ for n in ast.walk(ast.parse(path.read_text()))
           if isinstance(n, (ast.Global, ast.Nonlocal))]
    assert not bad, "%s: %s" % (path.name, bad)


# ------------------------------------------------- 3. 関数を区切る
def _functions():
    out = []
    for f in _files():
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = [x for x in n.body
                    if not (isinstance(x, ast.Expr)
                            and isinstance(x.value, ast.Constant)
                            and isinstance(x.value.value, str))]
            if not body:
                continue
            lines = max(x.end_lineno for x in body) - min(x.lineno for x in body) + 1
            out.append((f.name, n.name, lines))
    return out


@pytest.mark.parametrize("fname,func,lines", _functions(),
                         ids=lambda v: v if isinstance(v, str) else str(v))
def test_functions_stay_short(fname, func, lines):
    """**1つの関数が長いなら、2つ以上のことをしている。**"""
    assert lines <= MAX_FUNCTION_LINES, (
        "%s の %s() が %d 行（上限 %d）。区切る"
        % (fname, func, lines, MAX_FUNCTION_LINES))
