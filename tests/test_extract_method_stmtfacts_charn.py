"""Characterization: the refactored ``_StmtFacts.__init__`` produces byte-identical
object state to the original (the base-commit version of
``app/execution/extract_method.py``).

The refactor decomposed ``_StmtFacts.__init__`` into pure module-level helpers
(``_names_with_ctx`` / ``_augassign_targets`` / ``_comprehension_targets`` /
``_statement_blocks``), keeping the single ``ast.walk`` of the statement. This
harness loads the original module straight from the base commit's blob, builds a
``_StmtFacts`` for every statement of a battery of source inputs with BOTH the
original and the refactored class, and asserts the full ``__slots__`` state
(loads / aug / raw_stores / comp / blocks) is identical. Zero mismatches is the
proof. Deterministic, stdlib-only, offline.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess

from app.execution.extract_method import _StmtFacts as refactored


# The commit this refactor is based on; pinned so the proof stays honest even
# after the refactor itself lands on HEAD.
_BASE_SHA = "6de15a129c4b2375f60bcc1c66db781dc3618cf7"


def _load_original_stmtfacts():
    """``_StmtFacts`` as it stood at the base commit (pre-refactor)."""
    repo = pathlib.Path(__file__).resolve().parents[1]
    blob = subprocess.check_output(
        ["git", "-C", str(repo), "show",
         f"{_BASE_SHA}:app/execution/extract_method.py"],
        text=True,
    )
    ns: dict = {}
    exec(compile(blob, f"<{_BASE_SHA}:extract_method.py>", "exec"), ns)
    return ns["_StmtFacts"]


original = _load_original_stmtfacts()


# A spread of statements exercising every classification branch: loads/stores,
# aug-assign, comprehensions of every kind (with tuple/nested targets), nested
# def/lambda/async-def (block), control nodes (return/yield/await/global/
# nonlocal), break/continue both inside and outside a selected loop, walrus,
# decorators, with/try/match, and plain expressions.
_SNIPPETS = [
    "x = a + b",
    "y = x * 2 + foo(bar)",
    "x += 1",
    "total += i + j",
    "d[k] = v",
    "obj.attr = a.b.c",
    "a, b = b, a",
    "(p, (q, r)) = thing",
    "res = [n for n in items if n > t]",
    "res = {k: v for k, v in pairs}",
    "res = {n for n in items}",
    "res = (n for n in gen)",
    "res = [(i, j) for i in xs for j in ys]",
    "res = [n for sub in nested for n in sub]",
    "def inner():\n    return x",
    "async def inner():\n    await thing()",
    "f = lambda t: t + a",
    "return value",
    "yield item",
    "yield from gen",
    "global g",
    "nonlocal nl",
    "for i in range(n):\n    break",
    "for i in range(n):\n    continue",
    "break",
    "continue",
    "while cond:\n    if x:\n        break\n    else:\n        continue",
    "if (m := compute()) > 0:\n    use(m)",
    "with open(p) as fh:\n    data = fh.read()",
    "try:\n    risky()\nexcept Exception as e:\n    handle(e)",
    "for i in range(n):\n    for j in range(m):\n        if i == j:\n            break",
    "x = a\nfor i in range(n):\n    total += i",
    "result = await coro()",
    "del obj",
    "assert a == b, msg",
    "raise ValueError(x)",
    "x: int = 5",
    "@deco\ndef wrapped():\n    pass",
    "class C:\n    y = 1",
    "x = [i async for i in aiter]",
    "print(f'{a}{b!r}')",
    "x = nested[i][j] + d.get(k, default)",
    "for (a, b) in pairs:\n    s = a + b",
    "lst.append(comp := [n for n in xs])",
]


def _statements():
    """Every top-level statement parsed from every snippet."""
    out = []
    for snippet in _SNIPPETS:
        for stmt in ast.parse(snippet).body:
            out.append((snippet, stmt))
    return out


def _state(facts) -> dict:
    """The full observable ``__slots__`` state of a ``_StmtFacts``."""
    return {
        "loads": set(facts.loads),
        "aug": set(facts.aug),
        "raw_stores": set(facts.raw_stores),
        "comp": set(facts.comp),
        "blocks": facts.blocks,
    }


def test_stmtfacts_byte_identical_state():
    """Original vs refactored ``_StmtFacts`` agree on every slot, every input."""
    mismatches = []
    for snippet, stmt in _statements():
        orig_state = _state(original(stmt))
        new_state = _state(refactored(stmt))
        if orig_state != new_state:
            mismatches.append((snippet, orig_state, new_state))
    assert not mismatches, f"{len(mismatches)} mismatch(es): {mismatches[:3]}"


def test_slots_unchanged():
    """The refactor keeps the same ``__slots__`` layout."""
    assert refactored.__slots__ == original.__slots__


def test_harness_covers_every_branch():
    """At least one input lands in each slot (otherwise the proof is hollow)."""
    seen_blocks = seen_loads = seen_stores = seen_aug = seen_comp = False
    for _snippet, stmt in _statements():
        f = refactored(stmt)
        seen_blocks |= f.blocks
        seen_loads |= bool(f.loads)
        seen_stores |= bool(f.raw_stores)
        seen_aug |= bool(f.aug)
        seen_comp |= bool(f.comp)
    assert seen_blocks and seen_loads and seen_stores and seen_aug and seen_comp
