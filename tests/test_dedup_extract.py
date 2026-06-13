"""Tests for the dedup-extract transform (duplication detector → action)."""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.dedup import DuplicateBlock, find_duplicates
from app.execution.dedup_extract import plan_dedup_extract


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _exec_module(source: str) -> dict:
    """Compile + run a module's source, returning its namespace."""
    ns: dict = {}
    exec(compile(source, "<mod>", "exec"), ns)  # noqa: S102 - controlled test src
    return ns


# ── 1. same-module, identical 5+-statement block, no live-out → extracted ──

_SAME_MODULE = '''\
def alpha():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return e


def beta():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return e + 100
'''


def test_same_module_no_live_out_extracts_shared_helper(tmp_path):
    root = tmp_path
    _write(root, "pkg/mod.py", _SAME_MODULE)
    blocks = find_duplicates(root, min_statements=5, min_occurrences=2)
    assert blocks, "the detector should find the shared block"
    block = blocks[0]

    plan = plan_dedup_extract(root, block)
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"
    assert "pkg/mod.py" in plan.new_contents
    new_src = plan.new_contents["pkg/mod.py"]

    # Re-parses, defines exactly one shared helper, and both copies are gone:
    tree = ast.parse(new_src)
    helper_name = plan.new
    defs = [n.name for n in tree.body
            if isinstance(n, ast.FunctionDef)]
    assert helper_name in defs
    assert new_src.count(f"{helper_name}(") >= 2  # one def + >=2 call sites
    # The duplicated body should no longer be literally repeated.
    assert new_src.count("d = c * 3") == 1

    # Functional equivalence: alpha()/beta() behave identically before and after.
    before = _exec_module(_SAME_MODULE)
    after = _exec_module(new_src)
    assert before["alpha"]() == after["alpha"]() == 8
    assert before["beta"]() == after["beta"]() == 108


# ── 2. differing live-in / live-out across occurrences → blocked ──

# Identical 5-statement block in both functions, but ``e`` is read AFTER the
# block in ``beta`` (live_out there) and not in ``alpha`` — so the helper's
# return signature would differ between copies → the plan must block.
_DIVERGENT = '''\
def alpha():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return d


def beta():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return e
'''


def test_divergent_signature_blocks(tmp_path):
    root = tmp_path
    _write(root, "mod.py", _DIVERGENT)
    blocks = find_duplicates(root, min_statements=5, min_occurrences=2)
    assert blocks, "the detector should still see the identical block"
    plan = plan_dedup_extract(root, blocks[0])
    assert not plan.ok, "divergent live-out should block"
    assert any("signature" in b or "data-flow" in b for b in plan.blockers)
    assert not plan.new_contents


# ── 3. block containing a `return` → blocked ──

_WITH_RETURN = '''\
def alpha():
    a = 1
    b = 2
    c = 3
    d = 4
    return a + b + c + d


def beta():
    a = 1
    b = 2
    c = 3
    d = 4
    return a + b + c + d
'''


def test_block_with_return_blocks(tmp_path):
    root = tmp_path
    _write(root, "mod.py", _WITH_RETURN)
    blocks = find_duplicates(root, min_statements=5, min_occurrences=2)
    assert blocks
    plan = plan_dedup_extract(root, blocks[0])
    assert not plan.ok
    assert any("return" in b for b in plan.blockers)
    assert not plan.new_contents


# ── 4. cross-file: two modules sharing a block → helper here, import there ──

_CROSS_A = '''\
def alpha():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return e
'''

_CROSS_B = '''\
def beta():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return e + 7
'''


def test_cross_file_helper_and_import(tmp_path):
    root = tmp_path
    _write(root, "pkg/a.py", _CROSS_A)
    _write(root, "pkg/b.py", _CROSS_B)
    _write(root, "pkg/__init__.py", "")
    blocks = find_duplicates(root, min_statements=5, min_occurrences=2)
    assert blocks
    plan = plan_dedup_extract(root, blocks[0])
    assert plan.ok, f"cross-file plan should succeed, blockers={plan.blockers}"

    # The first occurrence's module gets the helper def...
    first = plan.defined_in
    helper = plan.new
    assert first in plan.new_contents
    assert f"def {helper}(" in plan.new_contents[first]

    # ...the OTHER module gets an import of it, and no def.
    other = next(r for r in plan.new_contents if r != first)
    assert f"import {helper}" in plan.new_contents[other]
    assert f"def {helper}(" not in plan.new_contents[other]

    # Both re-parse, and the other module imports from the first's dotted path.
    for rel, src in plan.new_contents.items():
        ast.parse(src)
    first_dotted = first[:-3].replace("/", ".")
    assert f"from {first_dotted} import {helper}" in plan.new_contents[other]


# ── 5. no duplication → empty plan (blocked, nothing to do) ──

def test_no_duplication_empty_plan(tmp_path):
    root = tmp_path
    _write(root, "mod.py", "def alpha():\n    return 1\n")
    blocks = find_duplicates(root, min_statements=5, min_occurrences=2)
    assert blocks == []

    empty_block = DuplicateBlock(fingerprint="x", lines=5, occurrences=[])
    plan = plan_dedup_extract(root, empty_block)
    assert not plan.ok
    assert not plan.new_contents


# ── 6. single occurrence → blocked (a shared helper needs two) ──

def test_single_occurrence_blocks(tmp_path):
    root = tmp_path
    _write(root, "mod.py", _SAME_MODULE)
    block = DuplicateBlock(fingerprint="x", lines=5, occurrences=["mod.py:2"])
    plan = plan_dedup_extract(root, block)
    assert not plan.ok
    assert any("two occurrences" in b for b in plan.blockers)


# ── 7. malformed occurrence location → blocked, no crash ──

def test_malformed_occurrence_blocks(tmp_path):
    root = tmp_path
    block = DuplicateBlock(fingerprint="x", lines=5,
                           occurrences=["no-colon-here", "also/bad"])
    plan = plan_dedup_extract(root, block)
    assert not plan.ok
    assert not plan.new_contents
