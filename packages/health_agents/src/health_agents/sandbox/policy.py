"""Static check of model-written code before it runs: the first of the sandbox's layers.

Refuses imports outside a small allowlist, any name or attribute beginning with `_` (the
door to `__class__.__subclasses__()` and friends), names that reach the interpreter
(`exec`, `open`, `getattr`, ...), and the few pandas/str methods that evaluate strings
(`format`, `query`, `eval`). It is one layer: the runner's audit hook and resource limits
still apply to whatever passes.
"""
from __future__ import annotations

import ast

ALLOWED_IMPORTS = frozenset({"pandas", "numpy", "math", "statistics", "datetime", "json"})

REFUSED_NAMES = frozenset({
    "exec", "eval", "compile", "open", "__import__", "getattr", "setattr", "delattr",
    "globals", "locals", "vars", "input", "breakpoint", "help", "memoryview", "type",
    "object", "super", "classmethod", "staticmethod", "property",
})

REFUSED_ATTRS = REFUSED_NAMES | frozenset({
    "format", "format_map", "query", "eval",
    # modules and interpreter internals reachable through attributes
    "sys", "os", "io", "common", "modules", "builtins", "import_module", "subprocess", "ctypes",
    "ctypeslib", "socket", "importlib", "pickle", "marshal", "compat",
    # frames, code and tracebacks (reflective access to globals and builtins)
    "gi_frame", "gi_code", "cr_frame", "cr_code", "ag_frame", "ag_code", "f_globals",
    "f_builtins", "f_locals", "f_back", "f_code", "tb_frame", "tb_next", "func_globals",
    # file IO that bypasses Python's open (C-level readers and writers)
    "load", "loads", "tofile", "fromfile", "save", "savez", "savez_compressed", "savetxt",
    "loadtxt", "genfromtxt", "memmap", "fromregex",
})
# pandas readers and writers do file or database IO; these conversions do not.
_IO_PREFIX = ("read_", "to_")
ALLOWED_TO = frozenset({"to_dict", "to_list", "to_numpy", "to_frame", "to_string", "to_datetime",
                        "to_timedelta", "to_numeric", "to_period", "to_timestamp",
                        "to_pydatetime", "to_records", "to_flat_index", "to_series"})


def _attr_refusal(name: str) -> str | None:
    if name.startswith("_") or name in REFUSED_ATTRS:
        return f"attribute not allowed: {name}"
    if name.startswith(_IO_PREFIX) and name not in ALLOWED_TO:
        return f"file or database IO not allowed: {name}"
    return None


def check(code: str) -> str | None:
    """A refusal reason, or None when the code may run."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        return f"syntax error: {exc.msg} (line {exc.lineno})"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    return f"import not allowed: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                return f"import not allowed: {node.module}"
            for alias in node.names:
                if alias.name == "*" or _attr_refusal(alias.name):
                    return f"import not allowed: {alias.name}"
        elif isinstance(node, ast.Name):
            if node.id.startswith("_") or node.id in REFUSED_NAMES:
                return f"name not allowed: {node.id}"
        elif isinstance(node, ast.Attribute):
            refusal = _attr_refusal(node.attr)
            if refusal:
                return refusal
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            return "global/nonlocal not allowed"
    return None
