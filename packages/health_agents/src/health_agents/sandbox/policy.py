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

REFUSED_ATTRS = frozenset({"format", "format_map", "query", "eval"})


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
        elif isinstance(node, ast.Name):
            if node.id.startswith("_") or node.id in REFUSED_NAMES:
                return f"name not allowed: {node.id}"
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr in REFUSED_ATTRS:
                return f"attribute not allowed: {node.attr}"
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            return "global/nonlocal not allowed"
    return None
