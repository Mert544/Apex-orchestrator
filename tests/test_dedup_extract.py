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


def test_self_contained_tail_return_extracts(tmp_path):
    # A self-contained block (no params, no live-out) whose tail is a `return`
    # now lifts into a no-arg returning helper — each copy becomes `return _shared_1()`.
    root = tmp_path
    _write(root, "mod.py", _WITH_RETURN)
    blocks = find_duplicates(root, min_statements=5, min_occurrences=2)
    assert blocks
    plan = plan_dedup_extract(root, blocks[0])
    assert plan.ok, f"tail-return block should extract, blockers={plan.blockers}"
    new = plan.new_contents["mod.py"]
    assert "def _shared_1():" in new
    assert new.count("return _shared_1()") == 2
    ns = _exec_module(new)
    assert ns["alpha"]() == 10 and ns["beta"]() == 10


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


# ── tail-return: a block ending in `return <expr>` → returning helper ──

_TAIL_RETURN = '''\
def alpha(x):
    a = x + 1
    b = a * 2
    c = b - 3
    d = c + 4
    return d + 5


def beta(x):
    a = x + 1
    b = a * 2
    c = b - 3
    d = c + 4
    return d + 5
'''


def test_tail_return_block_extracts_returning_helper(tmp_path):
    # Previously blocked ("the range contains a return"); now lifted into a
    # helper that returns, with each copy rewritten to `return _shared_n(...)`.
    _write(tmp_path, "pkg/mod.py", _TAIL_RETURN)
    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert blocks
    plan = plan_dedup_extract(tmp_path, blocks[0])
    assert plan.ok, f"tail-return block should extract now, blockers={plan.blockers}"

    new = plan.new_contents["pkg/mod.py"]
    assert "def _shared_1(x):" in new
    assert new.count("return _shared_1(x)") == 2   # both copies call-and-return
    assert "return d + 5" in new                   # the return lives in the helper now

    ns = _exec_module(new)
    assert ns["alpha"](10) == 28 and ns["beta"](10) == 28   # behaviour preserved


# ── an EARLY (non-tail) return still blocks ──

_EARLY_RETURN = '''\
def alpha(x):
    a = x + 1
    if a > 5:
        return a
    b = a * 2
    c = b + 3
    return c


def beta(x):
    a = x + 1
    if a > 5:
        return a
    b = a * 2
    c = b + 3
    return c
'''


def test_early_return_still_blocks(tmp_path):
    _write(tmp_path, "pkg/mod.py", _EARLY_RETURN)
    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert blocks
    plan = plan_dedup_extract(tmp_path, blocks[0])
    assert not plan.ok and plan.blockers   # a non-tail return is not liftable


# ── descriptive helper naming: common tokens of enclosing function names ──

_COMMON_TOKENS = '''\
def generate_patch_requests_skill():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return e


def generate_semantic_patch_skill():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return e + 100
'''


def test_descriptive_helper_name_from_common_function_tokens(tmp_path):
    # generate_patch_requests_skill + generate_semantic_patch_skill share the
    # ORDERED tokens generate, patch, skill → the helper is `_generate_patch_skill`.
    _write(tmp_path, "pkg/mod.py", _COMMON_TOKENS)
    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert blocks
    plan = plan_dedup_extract(tmp_path, blocks[0])
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"
    assert plan.new == "_generate_patch_skill"
    new = plan.new_contents["pkg/mod.py"]
    assert "def _generate_patch_skill():" in new
    assert new.count("_generate_patch_skill()") >= 2
    # Behaviour preserved.
    before = _exec_module(_COMMON_TOKENS)
    after = _exec_module(new)
    assert before["generate_patch_requests_skill"]() == \
        after["generate_patch_requests_skill"]()


# ── fallback: no common tokens → the machine `_shared_<n>` scheme still fires ──

_NO_COMMON_TOKENS = '''\
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


def test_no_common_tokens_falls_back_to_shared(tmp_path):
    # `alpha` and `beta` share no identifier tokens → there is no descriptive
    # base, so the helper keeps the deterministic `_shared_<n>` machine name.
    _write(tmp_path, "pkg/mod.py", _NO_COMMON_TOKENS)
    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert blocks
    plan = plan_dedup_extract(tmp_path, blocks[0])
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"
    assert plan.new == "_shared_1"
    assert "def _shared_1():" in plan.new_contents["pkg/mod.py"]


def test_descriptive_name_collision_appends_suffix(tmp_path):
    # When the descriptive base is already bound at module level, the planner
    # appends `_2`, `_3`, … rather than colliding or silently falling back.
    src = (
        "_generate_patch_skill = 1\n\n\n"
        + _COMMON_TOKENS
    )
    _write(tmp_path, "pkg/mod.py", src)
    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert blocks
    plan = plan_dedup_extract(tmp_path, blocks[0])
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"
    assert plan.new == "_generate_patch_skill_2"
    assert "def _generate_patch_skill_2():" in plan.new_contents["pkg/mod.py"]
