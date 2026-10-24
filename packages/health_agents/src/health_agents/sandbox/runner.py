"""Child-process entrypoint of the sandbox. Started as `python -s -P -X utf8 runner.py`.

Reads {"code", "bundle"} as JSON on stdin and prints one JSON line on stdout:
{"ok": true, "result": ..., "stdout": "..."} or {"ok": false, "error": "...", "stdout": "..."}.

Order matters: the libraries are imported first (they open their own files), then the
audit hook goes in, then the user code runs with a restricted set of builtins. After the
hook is installed, the process can't open a socket, start a process, load ctypes, delete
or rename files, write a file, or read one outside the interpreter's own library paths.
"""
from __future__ import annotations

import datetime
import importlib.util
import io
import json
import math
import os
import statistics
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd

_policy_spec = importlib.util.spec_from_file_location("_policy", Path(__file__).with_name("policy.py"))
assert _policy_spec and _policy_spec.loader
_policy = importlib.util.module_from_spec(_policy_spec)
_policy_spec.loader.exec_module(_policy)

MODULES = {"pandas": pd, "numpy": np, "math": math, "statistics": statistics,
           "datetime": datetime, "json": json}

DENY_PREFIXES = ("socket.", "subprocess.", "os.system", "os.exec", "os.spawn", "os.posix_spawn",
                 "os.fork", "os.forkpty", "os.kill", "os.remove", "os.unlink", "os.rename",
                 "os.replace", "os.mkdir", "os.rmdir", "os.chmod", "os.chown", "os.truncate",
                 "os.symlink", "os.link", "os.putenv", "os.unsetenv", "shutil.", "ctypes.",
                 "winreg.", "_winapi.", "msvcrt.", "urllib.", "http.", "ftplib.", "smtplib.",
                 "webbrowser.", "pty.", "fcntl.", "mmap.", "sqlite3.", "os.listdir",
                 "os.scandir", "os.chdir", "glob.")
DENY_MODULES = frozenset({"socket", "_socket", "ssl", "_ssl", "subprocess", "_posixsubprocess",
                          "ctypes", "_ctypes", "multiprocessing", "urllib", "http", "ftplib",
                          "smtplib", "webbrowser", "asyncio", "pty", "winreg", "_winapi",
                          "sqlite3", "_sqlite3", "importlib", "pickle", "_pickle", "marshal",
                          "shelve", "dbm", "zipimport", "runpy", "code", "codeop"})
LIB_ROOTS = tuple({str(Path(p).resolve()) for p in (sys.prefix, sys.base_prefix, sys.exec_prefix)})
WRITE_FLAGS = 0o1 | 0o2 | 0o100 | 0o1000 | 0o2000  # O_WRONLY | O_RDWR | O_CREAT | O_TRUNC | O_APPEND
OUTPUT_CAP = 20_000


class Blocked(PermissionError):
    pass


def _readable(path: object) -> bool:
    if isinstance(path, int):
        return True  # an already-open descriptor (stdin/stdout)
    try:
        resolved = str(Path(str(path if not isinstance(path, bytes) else path.decode())).resolve())
    except (OSError, ValueError):
        return False
    return any(resolved == root or resolved.startswith(root + os.sep) for root in LIB_ROOTS)


def _hook(event: str, args: tuple) -> None:
    # No "exec" rule: pandas and numpy exec code internally. The ways user code could reach
    # exec (builtins, frames, getattr) are refused by policy.check and the module views.
    if event.startswith(DENY_PREFIXES):
        raise Blocked(f"blocked: {event}")
    if event == "import" and args and str(args[0]).split(".")[0] in DENY_MODULES:
        raise Blocked(f"blocked import: {args[0]}")
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        writes = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & WRITE_FLAGS)
        if writes or not _readable(path):
            raise Blocked("blocked: file access")


class _Module:
    """A read-only view of an allowed module: no private names, and a submodule is reachable
    only inside the same package (`pd.io.common.os` stops at `os`)."""

    __slots__ = ("_mod", "_root")

    def __init__(self, mod: ModuleType, root: str):
        object.__setattr__(self, "_mod", mod)
        object.__setattr__(self, "_root", root)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        value = getattr(self._mod, name)
        if isinstance(value, ModuleType):
            if value.__name__.split(".")[0] != self._root:
                raise AttributeError(f"module {name} is not available")
            return _Module(value, self._root)
        return value

    def __setattr__(self, name: str, value) -> None:
        raise AttributeError("read-only")

    def __dir__(self):
        return [n for n in dir(self._mod) if not n.startswith("_")]


def _view(mod: ModuleType) -> _Module:
    return _Module(mod, mod.__name__.split(".")[0])


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if level or root not in MODULES:
        raise ImportError(f"import not allowed: {name}")
    if not fromlist:
        __import__(name)
        return _view(MODULES[root])
    module = __import__(name, globals, locals, fromlist, level)
    return _view(module)


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, (pd.Timestamp, datetime.date)):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int, str)):
        return value
    raise TypeError(type(value).__name__)


def _emit(payload: dict) -> None:
    line = json.dumps(payload, allow_nan=False)
    if len(line) > OUTPUT_CAP:
        line = json.dumps({"ok": False, "error": "output too large", "stdout": ""})
    out = sys.__stdout__
    assert out is not None
    out.write(line + "\n")
    out.flush()


def main() -> None:
    request = json.loads(sys.stdin.read())
    code, bundle = request["code"], request.get("bundle") or {}
    refusal = _policy.check(code)
    if refusal:
        _emit({"ok": False, "error": refusal, "stdout": ""})
        return
    frames = {name: pd.DataFrame(rows) for name, rows in (bundle.get("frames") or {}).items()}
    printed = io.StringIO()

    def _print(*args, **kwargs):
        kwargs.pop("file", None)
        print(*args, file=printed, **kwargs)

    safe = {name: __builtins__[name] if isinstance(__builtins__, dict) else getattr(__builtins__, name)
            for name in ("abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "int",
                         "len", "list", "map", "max", "min", "range", "reversed", "round", "set",
                         "sorted", "str", "sum", "tuple", "zip", "isinstance", "Exception",
                         "ValueError", "KeyError", "TypeError", "ZeroDivisionError", "True",
                         "False", "None")
            if (name in __builtins__ if isinstance(__builtins__, dict) else hasattr(__builtins__, name))}
    safe["print"] = _print
    safe["__import__"] = _guarded_import
    scope = {"__builtins__": safe, "pd": _view(pd), "pandas": _view(pd), "np": _view(np),
             "numpy": _view(np), **frames}
    compiled = compile(code, "<agent>", "exec")
    sys.addaudithook(_hook)
    try:
        exec(compiled, scope)
    except BaseException as exc:  # report, never crash: the parent reads one JSON line
        _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500],
               "stdout": printed.getvalue()[:4000]})
        return
    try:
        result = _jsonable(scope.get("result"))
    except TypeError as exc:
        _emit({"ok": False, "error": f"result is not JSON-serialisable ({exc})",
               "stdout": printed.getvalue()[:4000]})
        return
    _emit({"ok": True, "result": result, "stdout": printed.getvalue()[:4000]})


if __name__ == "__main__":
    main()
