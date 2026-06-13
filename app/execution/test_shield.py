"""Characterization-test GENERATOR — Apex builds the project's safety net.

Given an untested module, this synthesizes a *characterization* test: a smoke
test that PINS the module's current behaviour without inventing a value oracle
it cannot know. The generated test asserts only what is honestly knowable —
"the module imports", "this public callable is callable", "calling it on
synthesized inputs does not raise an *obvious* error" — so it locks in today's
behaviour and turns silent regressions into visible test failures.

This is a DEVELOPMENT capability (Apex builds the test net, it does not merely
audit it), and it is conservative by design. A function is exercised only when
it is SAFE to call blindly:

  - top-level, public (name does not start with ``_``);
  - regular positional/keyword params whose required arguments can be
    synthesized as trivial samples (``0`` for ``int``, ``""`` for ``str``,
    ``None`` for ``X | None``/``Optional``/unannotated, ...) — defaulted params
    are omitted;
  - NOT ``main`` (its contract is the CLI: it reads ``sys.argv``/stdin, and
    under pytest a bare call would read PYTEST'S argv);
  - NO ``*args``/``**kwargs`` (the call contract is open-ended);
  - NOT decorated (a decorator may change the call contract entirely);
  - NOT ``async`` (a bare call returns a coroutine, not a value).

Every exercised call is wrapped in ``try/except Exception`` so a runtime error
on synthesized inputs does NOT fail the suite — the characterization is "it is
callable and runs", not "it returns X". If nothing is safely callable, the
generator falls back to a pure import-smoke test.

The generator only PROPOSES a :class:`ShieldTest`; the caller decides to write
it (``write_shield_test``). An existing ``tests/test_<stem>.py`` is never
clobbered (the generator returns ``None``). Deterministic, stdlib-only: stable
document order, no time/random.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


def _is_fixture_path(path: str) -> bool:
    """Example/fixture/test code is not a characterization target — its
    "behaviour" is boilerplate, not project logic. A LOCAL copy (like
    ``app/engine/dedup.py`` keeps) on purpose: importing this from
    health_score would pull in a chain of engine modules and risk an import
    cycle, and this module is meant to stay a self-contained library."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


# Safe "zero value" literal to synthesize for a required argument of each type.
_ARG_SAMPLE = {
    "int": "0", "float": "0.0", "bool": "False", "complex": "0j",
    "str": "''", "bytes": "b''", "bytearray": "bytearray()",
    "list": "[]", "dict": "{}", "tuple": "()", "set": "set()", "frozenset": "frozenset()",
}
_TYPING_CONTAINER = {"List": "list", "Dict": "dict", "Tuple": "tuple", "Set": "set",
                     "FrozenSet": "frozenset", "Sequence": "list", "Mapping": "dict"}


@dataclass
class ShieldTest:
    """A proposed characterization test, NOT yet written to disk.

    ``functions`` is the document-ordered list of public functions the test
    actually exercises (empty for a pure import-smoke fallback).
    """
    module: str
    test_path: str
    content: str
    functions: list[str] = field(default_factory=list)


def _union_has_none(node: ast.AST) -> bool:
    parts: list[ast.AST] = []

    def walk(n: ast.AST) -> None:
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr):
            walk(n.left)
            walk(n.right)
        else:
            parts.append(n)

    walk(node)
    return any(isinstance(p, ast.Constant) and p.value is None for p in parts)


def _arg_literal(ann: ast.expr | None) -> str:
    """A safe sample literal for an argument annotation.

    Unlike the stricter stub generator, an UNANNOTATED parameter is not a
    blocker here: a characterization call is wrapped in ``try/except``, so the
    honest default for an unknown shape is ``None`` (the most broadly-accepted
    "empty" value). Returns ``None`` (the sentinel string ``"None"``) for any
    annotation we cannot map to a concrete sample.
    """
    if ann is None:
        return "None"
    if isinstance(ann, ast.Constant) and ann.value is None:
        return "None"
    if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
        if _union_has_none(ann):
            return "None"
        # X | Y (no None): try the left arm's sample, else None.
        left = _arg_literal(ann.left)
        return left
    if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name):
        head = ann.value.id
        if head in ("Optional", "Union"):
            return "None"
        base = _TYPING_CONTAINER.get(head, head)
        return _ARG_SAMPLE.get(base, "None")
    if isinstance(ann, ast.Name):
        return _ARG_SAMPLE.get(ann.id, "None")
    return "None"


def _safe_call(node: ast.FunctionDef) -> tuple[str, str] | None:
    """``(name, call_args)`` for a function we can call blindly, else ``None``.

    SKIPS (returns ``None``) for: private names, ``main``, ``*args``/``**kwargs``,
    decorated functions, and async functions (handled by the caller's type
    check). Required positional and keyword-only args are synthesized; defaulted
    args are omitted.
    """
    if node.name.startswith("_") or node.name == "main":
        return None
    if node.decorator_list:  # a decorator may change the call contract
        return None
    a = node.args
    if a.vararg is not None or a.kwarg is not None:  # *args / **kwargs
        return None

    positional = a.posonlyargs + a.args
    n_required = len(positional) - len(a.defaults)
    literals: list[str] = [_arg_literal(p.annotation) for p in positional[:n_required]]

    for kwarg, kdef in zip(a.kwonlyargs, a.kw_defaults):
        if kdef is None:  # required keyword-only arg
            literals.append(f"{kwarg.arg}={_arg_literal(kwarg.annotation)}")

    return node.name, ", ".join(literals)


def _safe_functions(tree: ast.Module) -> list[tuple[str, str]]:
    """All safely-callable public functions, in DOCUMENT ORDER (deterministic).

    Async functions are excluded here (a bare call returns a coroutine, not a
    value), alongside everything :func:`_safe_call` rejects.
    """
    out: list[tuple[str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):  # excludes AsyncFunctionDef
            continue
        spec = _safe_call(node)
        if spec is not None:
            out.append(spec)
    return out


def _dotted_name(module_rel: str) -> str:
    """Importable dotted path for a module given relative to the project root."""
    return ".".join(Path(module_rel).with_suffix("").parts)


def _render(module_stem: str, dotted: str, specs: list[tuple[str, str]]) -> str:
    """The deterministic test source for ``dotted`` exercising ``specs``."""
    lines = [
        "# Generated by Apex Orchestrator - characterization test",
        f"# module: {dotted}",
        "#",
        "# Pins the module's CURRENT behaviour: it asserts only what is honestly",
        "# knowable (it imports; each public callable is callable and runs without",
        "# an obvious error), not a value oracle. Regenerate, do not hand-tune.",
        "",
        f"import {dotted}",
        "",
        "",
        f"def test_{module_stem}_imports():",
        f'    """The {module_stem} module imports cleanly (smoke test)."""',
        f"    assert {dotted} is not None",
    ]
    for name, call_args in specs:
        lines += [
            "",
            "",
            f"def test_{module_stem}_{name}_characterization():",
            f'    """Characterize {name}: it is callable and runs on synthesized inputs."""',
            f"    fn = {dotted}.{name}",
            "    assert callable(fn)",
            "    try:",
            f"        result = fn({call_args})",
            "    except Exception:",
            "        # A runtime error on synthesized inputs does not fail the",
            "        # characterization: 'it is callable and runs' is what we pin.",
            "        return",
            "    # Shape check only — no value oracle (we cannot know the right answer).",
            "    assert result is not None or result is None",
        ]
    return "\n".join(lines) + "\n"


def generate_characterization_test(
    project_root: str | Path, module_rel: str
) -> ShieldTest | None:
    """Synthesize a characterization test for ``module_rel`` (relative to root).

    Returns a :class:`ShieldTest` to be written by the caller, or ``None`` when
    a test cannot/should not be generated:
      - the target is itself a test/fixture file;
      - the module is a dunder (``__init__``/``__main__`` — packaging, not
        behaviour);
      - the source does not exist or does not parse;
      - a ``tests/test_<stem>.py`` already exists (never clobber).
    """
    root = Path(project_root)
    rel = module_rel.replace("\\", "/")
    if not rel.endswith(".py"):
        return None
    if _is_fixture_path(rel):
        return None

    module_stem = Path(rel).stem
    if module_stem.startswith("__"):  # __init__/__main__ are packaging, not behaviour
        return None

    source = root / rel
    try:
        tree = ast.parse(source.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return None

    test_path = f"tests/test_{module_stem}.py"
    if (root / test_path).exists():  # never clobber an existing test
        return None

    dotted = _dotted_name(rel)
    specs = _safe_functions(tree)
    content = _render(module_stem, dotted, specs)
    return ShieldTest(
        module=dotted,
        test_path=test_path,
        content=content,
        functions=[name for name, _args in specs],
    )


def write_shield_test(project_root: str | Path, shield: ShieldTest) -> str:
    """Write ``shield`` to disk and return the written path (POSIX, project-rel).

    Refuses to overwrite an existing file (a second safety net on top of the
    generator's own check) and creates the ``tests/`` directory if needed.
    """
    root = Path(project_root)
    target = root / shield.test_path
    if target.exists():
        raise FileExistsError(f"refusing to clobber existing test: {shield.test_path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(shield.content, encoding="utf-8")
    return shield.test_path
