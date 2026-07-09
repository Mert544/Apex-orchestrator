"""Red-first + regression-guard tests for W4A / Stage 1 of the develop-loop
perf remediation (``docs/rnd/apex-perf-develop-dongusu-teshisi.md``).

Stage 1 wires ALREADY-EXISTING caches (the source index, ``parse_cached``)
through the objectives that previously re-read/re-parsed a module from disk on
every single call, via optional ``source=``/``trees=`` parameters — additive,
byte-identical by construction (the same pattern already proven by
``plan_extract_constant(..., source=None)``).

Tests 1, 2, 4, 5, 6 and 10 pin a concrete "today RED" behavior (verified via
``git stash`` on the pre-change tree) that the corresponding Stage-1 item
fixes. Tests 8 and 9 are must-stay-GREEN regression guards: 8 pins that the
``inline-helpers`` scan population is byte-identical before/after the
``trees=`` wiring (the own-only vs. tests-included scope boundary — RISK #2);
9 pins that the apply-time stale-content fail-closed guard still refuses a
plan built against content that no longer matches disk (RISK #1), which the
new ``source=`` threading into a ``Move.build_plan`` closure makes newly
reachable in a way it wasn't before.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _write(root: Path, rel: str, source: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


# ── Test 1 (pins Stage-1 item 9: inline-helpers trees= wiring) ───────────────

def test_suggest_inlines_reuses_shared_trees_no_uncached_reparse(tmp_path, monkeypatch):
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use(n):\n"
           "    return fee(n)\n")

    import app.execution.inline_function as inline_mod

    calls: list[Path] = []
    orig_py_files = inline_mod._py_files

    def _counting_py_files(root):
        calls.append(root)
        return orig_py_files(root)

    monkeypatch.setattr(inline_mod, "_py_files", _counting_py_files)

    from app.engine.objective_compiler import _inline_moves, inlinable_helper_fitness

    fitness = inlinable_helper_fitness(str(tmp_path))
    moves = _inline_moves(str(tmp_path))

    assert fitness == 1.0
    assert len(moves) == 1
    # Today RED: `_inlinable_helpers` calls `suggest_inlines` with no `trees=`,
    # so `_suggest_trees` falls back to ITS OWN uncached `_py_files` walk — once
    # for the fitness scan, once again for `_inline_moves`'s own scan (2 full
    # uncached walks for one pass, zero cache credit). After Stage-1 item 9
    # (`trees=all_parsed_trees(...)` threaded in), `suggest_inlines` never calls
    # `_py_files` at all — the trees come from the shared source index instead.
    assert calls == []


# ── Test 2 (pins Stage-1 item 10: SourceIndex.build routed through parse_cached) ──

def test_source_index_and_dead_params_share_one_parse_per_file(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    m_source = "def f(a, b):\n    return a\n"
    _write(tmp_path, "app/m.py", m_source)
    _write(tmp_path, "tests/test_m.py",
           "import app.m\ndef test_import():\n    assert app.m is not None\n")
    _write(tmp_path, "pyproject.toml", "[project]\nname='m'\nversion='0'\n")

    import ast as ast_mod

    parses_of_m: list[int] = []
    orig_parse = ast_mod.parse

    def _counting_parse(source, *a, **kw):
        if source == m_source:
            parses_of_m.append(1)
        return orig_parse(source, *a, **kw)

    monkeypatch.setattr(ast_mod, "parse", _counting_parse)

    from app.engine.objective_compiler import dead_parameter_fitness
    from app.engine.source_index import indexed_project

    dead_parameter_fitness(str(tmp_path))
    n_after_dead_params = len(parses_of_m)
    assert n_after_dead_params == 1  # dead-params' own scan parsed app/m.py once

    # Isolate exactly the `SourceIndex.build()` step every `_own_modules()`
    # caller (`modernize_fitness`, `_bool_return_modules`, …) triggers, without
    # the noise of an unrelated tidy-transform's OWN internal `ast.parse` calls.
    indexed_project(str(tmp_path))
    n_after_index_build = len(parses_of_m)

    # Today RED: `SourceIndex.build()` did its own raw `ast.parse(source)`, so
    # `app/m.py` is parsed AGAIN even though `dead_parameter_fitness`'s scan
    # (routed through `parse_cached`) already parsed the identical, unchanged
    # file. After Stage-1 item 10 (SourceIndex.build routed through
    # `parse_cached` too), this call is a cache HIT — zero new parses.
    assert n_after_index_build == n_after_dead_params


# ── Test 4 (pins Stage-1 items 6-7: register_module_objective source= threading) ──

def test_register_module_objective_reads_module_once_per_pass(tmp_path, monkeypatch):
    _write(tmp_path, "m.py", "import os\nX = 1\n")

    disk_reads: list[str] = []

    class _FakePlan:
        def __init__(self, new_contents):
            self.new_contents = new_contents

    def plan_fn(project_root, module_rel, source=None):
        text = source
        if text is None:
            text = (Path(project_root) / module_rel).read_text(encoding="utf-8")
            disk_reads.append(module_rel)
        changed = text.replace("import os\n", "")
        return _FakePlan({module_rel: changed} if changed != text else {})

    import app.execution.objectives._base as base_mod

    # Bypass the soundness-manifest registration gate (irrelevant to this unit
    # test of the fitness/moves closures) — a no-op stand-in for `register`.
    monkeypatch.setattr(base_mod, "register", lambda spec: spec)

    spec = base_mod.register_module_objective(
        "test-fake-drop-import", plan_fn,
        operator="fake_drop_import", description="fake {rel}")

    fitness_value = spec.fitness(str(tmp_path))
    moves = spec.moves(str(tmp_path))

    assert fitness_value == 1.0
    assert len(moves) == 1
    # Today RED (pre Stage-1 items 6-7): `plan_fn` is invoked once by the
    # fitness scan (`_modules`) and once again, independently, by `moves` — each
    # call gets no `source`, so each falls into `plan_fn`'s own disk read: 2
    # reads for one module in one pass. After Stage-1: `register_module_objective`
    # detects `plan_fn`'s optional `source` parameter and threads the ALREADY-
    # read text from `_own_modules()` into every call, so `plan_fn`'s own
    # internal read is never taken.
    assert disk_reads == []


# ── Test 5 (pins Stage-1 item 8: _dead_param_moves reuses _own_modules source) ──

def test_dead_param_moves_reuses_own_modules_source(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    _write(tmp_path, "app/m.py", "def _helper(a, b):\n    return a\n")

    # Pre-warm the shared source index — the state a real develop pass reaches
    # (an earlier objective/scan already built it) — BEFORE counting reads.
    from app.engine.objective_compiler import _own_modules
    _own_modules(str(tmp_path))

    read_calls: list[str] = []
    orig_read_text = Path.read_text

    def _counting_read_text(self, *a, **kw):
        if self.name == "m.py":
            read_calls.append(str(self))
        return orig_read_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", _counting_read_text)

    from app.engine.objective_compiler import _dead_param_moves

    moves = _dead_param_moves(str(tmp_path))

    assert len(moves) == 1  # `b` is dead; `_helper` is non-public -> droppable
    # Today RED: `_dead_param_moves`'s own `source_cache`/`_module_source` reads
    # `app/m.py` from disk again, even though `_own_modules()` already had its
    # text cached from the pre-warm above.
    assert read_calls == []


# ── Test 6 (extends Stage-1 item 6's pattern to the modernize/_content_plan
#    single-file family, needed so this RED-FIRST pin from the plan is honored) ──

def test_modernize_content_plan_reuses_own_modules_source(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    _write(tmp_path, "app/m.py",
           "def f(x):\n"
           "    if x == None:\n"
           "        return 1\n"
           "    return 0\n")

    read_calls: list[str] = []
    orig_read_text = Path.read_text

    def _counting_read_text(self, *a, **kw):
        if self.name == "m.py":
            read_calls.append(str(self))
        return orig_read_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", _counting_read_text)

    from app.engine.objective_compiler import _modernize_moves

    moves = _modernize_moves(str(tmp_path))
    assert len(moves) >= 1
    reads_after_scan = len(read_calls)
    assert reads_after_scan >= 1  # the one legitimate _own_modules() read

    plan = moves[0].build_plan()
    assert plan.new_contents  # a real rewrite landed

    # DELIBERATELY INVERTED from the first Stage-1 version (which pinned
    # zero build_plan reads): carrying scan-time source into the APPLY-time
    # thunk broke multi-move-per-file passes — the first landed move changes
    # the file on disk, and every later same-file plan built from the stale
    # scan text is (correctly) refused by the staleness gate, halving what a
    # modernize pass lands (caught live by
    # test_modernize_applied_result_is_pinned at the full gate). Scan-side
    # detection keeps the source= reuse (that's the measured win); the
    # apply-side thunk MUST re-read fresh disk — exactly one extra read.
    assert len(read_calls) == reads_after_scan + 1


# ── Test 8 (must stay GREEN: byte-identical suggest_inlines population) ──────

def test_inline_helpers_output_unchanged_after_trees_wiring(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    _write(tmp_path, "app/m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use(n):\n"
           "    return fee(n)\n")
    # An IDENTICALLY-named helper defined in a test file too — the own-only
    # (source-index) vs. tests-included (`_py_files`) scope boundary: `fee` is
    # now defined TWICE project-wide, so it must NOT be suggested (suggest_inlines
    # only fires on a name defined exactly once). If `all_parsed_trees`
    # accidentally narrowed to the own-only set, this test file's `fee` would
    # vanish from the scan and `app/m.py`'s `fee` would wrongly look unique.
    _write(tmp_path, "tests/test_other.py",
           "def fee(x):\n"
           "    return x + 1\n"
           "\n"
           "\n"
           "def test_fee():\n"
           "    assert fee(1) == 2\n")
    # A syntactically BROKEN residual (test) file: both the old `_py_files` +
    # `ast.parse` fallback and the new `all_parsed_trees` (via `parse_cached`'s
    # None-degrade) must silently DROP it from the scanned universe — the
    # explicit unparsable-file equivalence check.
    _write(tmp_path, "tests/test_broken.py", "def oops(:\n")
    _write(tmp_path, "pyproject.toml", "[project]\nname='m'\nversion='0'\n")

    from app.engine.objective_compiler import _inlinable_helpers
    from app.engine.source_index import all_parsed_trees
    from app.execution.inline_function import suggest_inlines

    before = suggest_inlines(str(tmp_path))          # the old, un-wired fallback
    after = _inlinable_helpers(str(tmp_path))         # the new trees=-wired call site

    assert before == after
    # The scope boundary itself: `fee` is correctly excluded (defined twice
    # project-wide) — proving the tests-inclusive universe survived the
    # `trees=` wiring rather than narrowing to the own-only set.
    assert all(s["function"] != "fee" for s in after)
    # Unparsable-file equivalence, checked on the tree populations directly:
    # the broken residual file is absent from BOTH paths' universes (excluded,
    # not crashed on), while the parsable test file is present in both.
    trees = all_parsed_trees(str(tmp_path))
    assert "tests/test_broken.py" not in trees
    assert "tests/test_other.py" in trees
    assert "app/m.py" in trees


# ── Test 9 (must stay GREEN: fail-closed on a stale plan) ────────────────────

def test_stale_external_edit_between_passes_still_refused(tmp_path):
    (tmp_path / "app").mkdir()
    original = (
        "def f(x):\n"
        "    if x > 0:\n"
        "        return True\n"
        "    else:\n"
        "        return False\n"
    )
    _write(tmp_path, "app/m.py", original)

    from app.engine.objective_compiler import _bool_return_moves
    from app.execution.cross_file_rename import apply_rename

    moves = _bool_return_moves(str(tmp_path))
    assert len(moves) == 1
    plan = moves[0].build_plan()
    assert plan.new_contents  # a real rewrite was queued

    # A concurrent external edit lands on disk AFTER the plan was built (a
    # `git checkout`, another tool, a human) — BEFORE this queued move applies.
    # This is exactly the window the new `source=` threading (item 6) makes a
    # `Move.build_plan` closure carry a snapshot through, so the apply-time
    # guard is what has to catch it, not the planner.
    edited = original + "    # edited externally, after planning\n"
    _write(tmp_path, "app/m.py", edited)

    result = apply_rename(str(tmp_path), plan, verify=False)

    # Fail-closed: the stale-content guard (`_stale_plan_reason`) refuses
    # rather than overwriting the external edit or splicing against stale
    # line/column offsets. This invariant is load-bearing through every
    # caching stage — it is what lets a cache bug fail SAFE at apply time
    # instead of corrupting a file.
    assert result["applied"] is False
    assert "stale plan" in result["reason"]
    live = (tmp_path / "app" / "m.py").read_text(encoding="utf-8")
    assert "edited externally" in live       # the external edit survived untouched
    assert "return bool(" not in live        # the queued rewrite was NOT applied


# ── Adversarial finding 2a (must REFUSE, never crash: undecodable live file) ─

def test_stale_gate_refuses_undecodable_file_instead_of_crashing(tmp_path):
    (tmp_path / "app").mkdir()
    original = (
        "def f(x):\n"
        "    if x > 0:\n"
        "        return True\n"
        "    else:\n"
        "        return False\n"
    )
    _write(tmp_path, "app/m.py", original)

    from app.engine.objective_compiler import _bool_return_moves
    from app.execution.cross_file_rename import apply_rename

    moves = _bool_return_moves(str(tmp_path))
    assert len(moves) == 1
    plan = moves[0].build_plan()
    assert plan.new_contents  # a real rewrite was queued

    # An external process rewrites the file with bytes that are NOT valid
    # UTF-8 — the decode-honesty edge: the `source=` threading feeds planners
    # the index's LENIENT (errors="ignore") decode, so a plan can now exist
    # for a file whose STRICT re-read raises. The staleness gate's live-file
    # comparison is where that strict read happens; it must REFUSE with an
    # honest reason, never crash with an uncaught UnicodeDecodeError.
    invalid = b"def f(x):\n    return \xff\xfe\n"
    (tmp_path / "app" / "m.py").write_bytes(invalid)

    result = apply_rename(str(tmp_path), plan, verify=False)  # today: CRASHES

    assert result["applied"] is False
    assert "not decodable" in result["reason"]
    # The invalid bytes survive untouched — fail-closed, no partial write.
    assert (tmp_path / "app" / "m.py").read_bytes() == invalid


# ── Adversarial finding 3 (same-read invariant: .tree is the parse of .source) ─

def test_source_index_build_single_read_and_tree_from_source(tmp_path, monkeypatch):
    import ast as ast_mod

    _write(tmp_path, "m.py", "X = 1\n")

    read_calls: list[str] = []
    orig_read_text = Path.read_text

    def _counting_read_text(self, *a, **kw):
        if self.name == "m.py":
            read_calls.append(str(self))
        return orig_read_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", _counting_read_text)

    from app.engine.source_index import SourceIndex

    index = SourceIndex.build(tmp_path)

    m = index.get("m.py")
    assert m is not None and m.tree is not None
    # Today RED: routing the parse through `parse_cached(path)` made build()
    # RE-READ the file from disk inside `_parse_tree` even though `_py_files`
    # had just read it — two reads, and (worse) `.source` and `.tree` from two
    # DIFFERENT reads, so a mid-window edit could silently diverge them. After
    # `parse_cached_text(path, text)` (same cache key + store, parses the text
    # the walk already read): exactly ONE disk read per file, and `.tree` is by
    # construction the parse of `.source`.
    assert len(read_calls) == 1
    assert ast_mod.dump(m.tree) == ast_mod.dump(ast_mod.parse(m.source))


# ── Test 10 (pins Stage-1 item 10's except-clause reconciliation, RISK #3) ───

def test_source_index_except_clause_parity_after_unification(tmp_path, monkeypatch):
    _write(tmp_path, "m.py", "X = 1\n")

    import app.engine.source_index as si_mod

    def _raising_parse_cached_text(path, text):
        raise OSError("simulated read failure mid-parse")

    monkeypatch.setattr(si_mod, "parse_cached_text", _raising_parse_cached_text,
                        raising=False)

    # Today RED under a NAIVE unification (routing the per-file parse through
    # the shared `parse_cached`/`parse_cached_text` store with no reconciled
    # except-clause around the call site): `OSError` was never part of
    # `source_index`'s OWN except-clause
    # (`SyntaxError, ValueError, RecursionError, MemoryError`) — an
    # unreconciled call site would let it propagate and CRASH the whole index
    # build rather than degrading just this one module. After reconciliation
    # (the union except-clause wrapping the cached-parse call), the module is
    # still indexed with `tree=None` — the honest "didn't parse" degrade,
    # matching `python_structure._parse_tree`'s own OSError tolerance —
    # instead of the whole build blowing up.
    index = si_mod.SourceIndex.build(tmp_path)

    m = index.get("m.py")
    assert m is not None
    assert m.tree is None
    assert m.source == "X = 1\n"  # the source text is still captured correctly


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
