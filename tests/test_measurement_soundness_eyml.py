"""MEASUREMENT-SOUNDNESS AUDIT — pin the soundness of the mutation-testing
"proof" infrastructure (``app/engine/mutation_tester.py``).

Apex's moat is "never fakes green", PROVEN by mutation testing + the green gate.
That proof is only worth anything if the *measurement* is sound. This module
audits and PINS three soundness properties, building tiny throwaway projects in
``tmp_path`` so every per-mutant pytest run stays fast and hermetic (nothing
here depends on the Apex repo's own git state or on wall-clock / iteration
order).

The three pinned areas, mirroring the audit brief:

1. The "git-show-in-sandbox" artifact. The mutant sandbox is a
   ``shutil.copytree`` that EXCLUDES ``.git`` (it is in ``SKIPPED_DIRS``). A
   covering test that reconstructs a file via ``git show HEAD:...`` therefore
   ERRORS uniformly inside the sandbox — independent of the mutant — so
   ``_verify_killed`` returns "killed" for EVERY mutant and the run reports a
   FALSE 100% score, masking real survivors. ``mutation_tester`` does NOT run a
   baseline (assert the covering suite passes on the UNMUTATED module), so this
   is a REAL, exploitable measurement-soundness hole. The reproducer below pins
   it deterministically and is contrasted with a sound weak test that honestly
   surfaces the same survivors. See the module-level audit verdict in the final
   report.

2. ``_collect_sites`` / ``_splice`` determinism + correctness: splicing a site
   and restoring the span yields the ORIGINAL source byte-for-byte; site
   enumeration is deterministic across independent walks; and an
   equivalent / no-op-shaped mutation that a passing test cannot observe is NOT
   counted as killed (survivors are reported honestly).

3. Covering-test selection blind spots: a test that reaches the module only via
   a re-export, or that ``exec``s its import as a string, is NOT detected by the
   AST-based ``covering_test_files`` (it sees only literal ``import`` /
   ``from ... import`` statements). These blind spots are pinned so they cannot
   silently worsen.
"""

from __future__ import annotations

import ast
import subprocess

from app.engine.mutation_tester import (
    _collect_sites,
    _splice,
    covering_test_files,
    mutation_score,
)
from app.engine.skip_dirs import SKIPPED_DIRS


# --- shared scaffolding ----------------------------------------------------

def _write_pkg_project(root, module_src, test_src,
                       module_rel="app/foo.py", test_name="test_foo.py"):
    """Lay down a minimal ``app/`` package + ``tests/`` project so the dotted
    import path (``app.foo``) is real and ``covering_test_files`` can match it."""
    pkg = root / "app"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (root / module_rel).write_text(module_src, encoding="utf-8")
    tests = root / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    (tests / test_name).write_text(test_src, encoding="utf-8")
    return module_rel


# A module with a clear boundary + return + numeric blind spot. A weak suite
# (one that never probes the boundary or the exact value) lets several mutants
# survive — the honest baseline this audit measures against.
_BRANCHY_MODULE = (
    "def classify(x):\n"
    "    if x > 10:\n"
    "        return \"big\"\n"
    "    return \"small\"\n"
)


# ===========================================================================
# 1. The git-show-in-sandbox artifact: a covering test that errors UNIFORMLY
#    yields a false "all killed". This is the exploitable hole.
# ===========================================================================

def test_sandbox_copytree_excludes_git_dir():
    """PIN the precondition for the artifact: ``.git`` is excluded from the
    mutant sandbox, so any covering test that shells out to git against HEAD
    cannot see repository state inside the copy."""
    assert ".git" in SKIPPED_DIRS


def test_git_dependent_covering_test_fakes_full_kill(tmp_path):
    """REPRODUCER (REAL DEFECT): a covering test that reconstructs the module
    via ``git show HEAD:...`` ERRORS uniformly inside the sandbox (no ``.git``),
    so EVERY mutant is reported "killed" and the score is a FALSE 100% — even
    though the test never discriminates one mutant from another.

    This is the "fakes green" failure the moat claims to prevent, occurring
    inside the very measurement that is supposed to prove the moat. The test
    DOES import the module, so it is selected by ``covering_test_files``; its
    git dependency — not any real assertion — is what kills every mutant.
    """
    test_src = (
        "import subprocess\n"
        "from app.foo import classify\n"
        "def test_via_git():\n"
        "    out = subprocess.run(\n"
        "        ['git', 'show', 'HEAD:app/foo.py'],\n"
        "        capture_output=True, text=True,\n"
        "    )\n"
        "    assert out.returncode == 0, 'git show failed'\n"
        "    assert classify(11) == 'big'\n"
    )
    rel = _write_pkg_project(tmp_path, _BRANCHY_MODULE, test_src)

    # The git-dependent test IS selected as covering (it imports app.foo).
    assert covering_test_files(str(tmp_path), rel) == ["tests/test_foo.py"]

    result = mutation_score(str(tmp_path), rel, max_mutants=10)

    # The artifact: a FALSE 100%. Every mutant "killed", zero survivors — not
    # because the assertions caught them, but because git errored uniformly.
    assert result.total > 0
    assert result.killed == result.total
    assert result.survived == 0
    assert result.score == 1.0
    assert result.survivors == []


def test_sound_weak_test_honestly_reports_survivors(tmp_path):
    """CONTRAST + the property that PROTECTS against the artifact: a sound
    covering test — one that actually PASSES on the unmutated module and only
    observes "not None" — honestly surfaces the survivors the git-dependent
    test falsely hid. The same module under a measurement-sound suite yields a
    score well below 1.0 with concrete blind-spot survivors.

    The protective invariant a sound mutation run requires (and which
    ``mutation_tester`` does NOT currently enforce) is BASELINE GREEN: the
    covering suite must PASS on the UNMUTATED module. Here it does, so the
    survivors are real test blind spots, not measurement artifacts.
    """
    test_src = (
        "from app.foo import classify\n"
        "def test_smoke():\n"
        "    assert classify(11) is not None\n"
    )
    rel = _write_pkg_project(tmp_path, _BRANCHY_MODULE, test_src)

    result = mutation_score(str(tmp_path), rel, max_mutants=10)

    # An honest measurement: the weak "not None" test cannot observe the
    # boundary flip, the off-by-one number bump, or the comparison negation.
    assert result.total > 0
    assert result.survived > 0
    assert result.score < 1.0
    survivor_ops = {m.operator for m in result.survivors}
    # The boundary/off-by-one blind spots the weak suite genuinely misses.
    assert "boundary:>>>=" in survivor_ops
    assert "number:10>11" in survivor_ops


def test_baseline_green_is_not_verified_by_mutation_tester(tmp_path):
    """PIN the root cause of the artifact as a characterization so it cannot
    silently change: ``mutation_tester`` never runs the covering suite against
    the UNMUTATED module to confirm it is green. A covering test that fails
    REGARDLESS of the module (here it asserts ``False`` after importing) is
    counted as killing every mutant — a baseline-red suite reported as a
    perfect score.

    If a future change ADDS a baseline-green guard (the sound fix), this
    characterization will trip and should be updated to assert the guard
    instead — that is the intended regression signal.
    """
    test_src = (
        "from app.foo import classify\n"
        "def test_always_red():\n"
        "    assert classify(11) is not None\n"
        "    assert False, 'unconditional failure independent of any mutant'\n"
    )
    rel = _write_pkg_project(tmp_path, _BRANCHY_MODULE, test_src)

    # The unconditionally-failing test is still selected (it imports the module).
    assert covering_test_files(str(tmp_path), rel) == ["tests/test_foo.py"]

    result = mutation_score(str(tmp_path), rel, max_mutants=10)

    # CHARACTERIZATION of the unsound behaviour: a baseline-RED suite is read as
    # killing every mutant -> a meaningless, FALSE 100%. No baseline check
    # exists to reject this. (Update this pin when the guard lands.)
    assert result.total > 0
    assert result.killed == result.total
    assert result.score == 1.0


# ===========================================================================
# 2. _collect_sites / _splice determinism + round-trip correctness.
# ===========================================================================

def test_splice_then_restore_round_trips_byte_for_byte():
    """Splicing a site and then restoring the original span reproduces the
    source EXACTLY — the splice is byte-for-byte reversible, so the sandbox
    target differs from the original only at the one mutated token."""
    src = (
        "def f(a, b, n):\n"
        "    return a == b and a + b > n\n"
    )
    lines = src.splitlines(keepends=True)
    sites = _collect_sites(ast.parse(src), lines)
    assert sites  # there are mutable sites to exercise

    for site in sites:
        mutated = _splice(lines, site)
        assert mutated is not None, site.operator
        # The mutated source differs from the original (a real fault was seeded).
        assert mutated != src, site.operator
        # Restore: replace the mutated token back with the original token at the
        # same span and confirm we recover the source byte-for-byte.
        mut_lines = mutated.splitlines(keepends=True)
        li = site.line - 1
        line = mut_lines[li]
        restored_line = (
            line[: site.col]
            + site.original
            + line[site.col + len(site.mutated):]
        )
        mut_lines[li] = restored_line
        assert "".join(mut_lines) == src, site.operator


def test_splice_only_changes_the_targeted_token():
    """Every byte outside the spliced span is preserved: the only difference
    between original and mutant is the single ``original -> mutated`` token."""
    src = "result = lo <= hi and count + 1 > 0\n"
    lines = src.splitlines(keepends=True)
    sites = _collect_sites(ast.parse(src), lines)
    assert sites
    for site in sites:
        mutated = _splice(lines, site)
        assert mutated is not None, site.operator
        # Prefix before the span and suffix after it are identical.
        prefix = src[: site.col]
        suffix = src[site.end_col:]
        assert mutated.startswith(prefix), site.operator
        assert mutated.endswith(suffix), site.operator
        # The middle is exactly the replacement token.
        middle = mutated[site.col: site.col + len(site.mutated)]
        assert middle == site.mutated, site.operator


def test_collect_sites_is_deterministic_across_independent_walks():
    """Two independent enumerations of the same source yield byte-identical
    site tuples — no randomness, fixed operator + document order."""
    src = (
        "def g(a, b, c, x, n):\n"
        "    total = 0\n"
        "    total += 1\n"
        "    flag = a == b and b < c or x >= n\n"
        "    return total + x\n"
    )
    lines = src.splitlines(keepends=True)

    def _tuples(ss):
        return [
            (s.line, s.col, s.end_col, s.operator, s.original, s.mutated)
            for s in ss
        ]

    a = _tuples(_collect_sites(ast.parse(src), lines))
    b = _tuples(_collect_sites(ast.parse(src), lines))
    assert a == b
    # And the document order is exactly (line, col, operator)-sorted.
    assert a == sorted(a, key=lambda t: (t[0], t[1], t[3]))


def test_equivalent_no_op_mutation_is_not_counted_as_killed(tmp_path):
    """A mutation the passing test cannot observe (here ``+`` flipped under a
    test that only checks the return type, never the value) is correctly
    reported as a SURVIVOR — a passing suite must not be credited with killing
    a mutant it cannot distinguish. This is the soundness floor: no false kills.
    """
    module_src = (
        "def total(a, b):\n"
        "    return a + b\n"
    )
    test_src = (
        "from app.foo import total\n"
        "def test_total_type():\n"
        "    assert isinstance(total(2, 2), int)\n"
    )
    rel = _write_pkg_project(tmp_path, module_src, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10)

    # The type-only assertion holds for both ``a + b`` and ``a - b`` (both ints),
    # so the arithmetic flip must survive — it is NOT a kill.
    assert result.total > 0
    survivor_ops = {m.operator for m in result.survivors}
    assert "arithmetic:+>-" in survivor_ops


# ===========================================================================
# 3. Covering-test selection blind spots: re-export and exec'd import.
# ===========================================================================

def test_covering_selection_misses_reexport_indirection(tmp_path):
    """BLIND SPOT (pinned): a test that reaches the target only through a
    re-export shim (``from app.shim import classify`` where ``app/shim.py``
    does ``from app.foo import classify``) is NOT selected — the AST scan sees
    only the test's literal imports (``app.shim``), never the transitive
    ``app.foo`` the shim pulls in. Such a test, even if strong, is excluded
    from the scope.
    """
    rel = _write_pkg_project(
        tmp_path, _BRANCHY_MODULE,
        # The test imports the SHIM, not app.foo directly.
        "from app.shim import classify\n"
        "def test_reexport():\n"
        "    assert classify(11) == 'big'\n"
        "    assert classify(5) == 'small'\n",
    )
    # The re-export shim that actually pulls in app.foo.
    (tmp_path / "app" / "shim.py").write_text(
        "from app.foo import classify\n", encoding="utf-8",
    )

    # app.foo is reached only transitively, so the test is NOT in the scope.
    assert covering_test_files(str(tmp_path), rel) == []


def test_covering_selection_misses_exec_string_import(tmp_path):
    """BLIND SPOT (pinned): a test that imports the module by ``exec``-ing an
    import statement built as a STRING is not detected — the dotted name lives
    in a string literal, never in an ``ast.Import`` / ``ast.ImportFrom`` node,
    so ``covering_test_files`` cannot see it.
    """
    rel = _write_pkg_project(
        tmp_path, _BRANCHY_MODULE,
        "def test_dynamic():\n"
        "    ns = {}\n"
        "    exec('from app.foo import classify', ns)\n"
        "    assert ns['classify'](11) == 'big'\n",
    )
    assert covering_test_files(str(tmp_path), rel) == []


def test_covering_selection_detects_literal_import(tmp_path):
    """CONTROL: the same module IS selected when a test imports it with a
    literal ``from app.foo import ...`` — proving the misses above are about the
    indirection, not the scaffolding."""
    rel = _write_pkg_project(
        tmp_path, _BRANCHY_MODULE,
        "from app.foo import classify\n"
        "def test_direct():\n"
        "    assert classify(11) == 'big'\n",
    )
    assert covering_test_files(str(tmp_path), rel) == ["tests/test_foo.py"]


def test_exec_string_import_test_is_excluded_then_falls_back(tmp_path):
    """End-to-end consequence of the exec blind spot: because the only (strong)
    test is invisible to scoping, the scope is empty and ``mutation_score``
    FALLS BACK to the full suite — so correctness is preserved here (the strong
    test runs anyway and kills the mutants) and ``scoped_tests`` records the
    fallback by staying empty. This pins that the blind spot degrades scope
    PRECISION, not measurement soundness, in the fallback case.
    """
    rel = _write_pkg_project(
        tmp_path, _BRANCHY_MODULE,
        "def test_dynamic():\n"
        "    ns = {}\n"
        "    exec('from app.foo import classify', ns)\n"
        "    assert ns['classify'](11) == 'big'\n"
        "    assert ns['classify'](10) == 'small'\n"
        "    assert ns['classify'](5) == 'small'\n",
    )
    result = mutation_score(str(tmp_path), rel, max_mutants=10)

    # Scope is empty (the exec'd import is invisible) -> full-suite fallback.
    assert result.scoped_tests == []
    # The strong test still ran via fallback and killed the boundary mutant.
    assert result.total > 0
    survivor_ops = {m.operator for m in result.survivors}
    assert "boundary:>>>=" not in survivor_ops


def test_covering_selection_determinism(tmp_path):
    """The covering scope is a sorted, de-duplicated list — identical across
    repeated calls (no set-iteration nondeterminism leaks out)."""
    rel = _write_pkg_project(
        tmp_path, _BRANCHY_MODULE,
        "from app.foo import classify\n"
        "def test_a():\n    assert classify(11) == 'big'\n",
        test_name="test_a.py",
    )
    (tmp_path / "tests" / "test_b.py").write_text(
        "import app.foo\n"
        "def test_b():\n    assert app.foo.classify(5) == 'small'\n",
        encoding="utf-8",
    )
    first = covering_test_files(str(tmp_path), rel)
    second = covering_test_files(str(tmp_path), rel)
    assert first == second == ["tests/test_a.py", "tests/test_b.py"]


def test_no_subprocess_leak_in_pure_selection(tmp_path, monkeypatch):
    """Defensive determinism pin: ``covering_test_files`` is pure AST analysis —
    it must not shell out. If it ever did, this would catch the regression."""
    def _boom(*args, **kwargs):  # pragma: no cover - only fires on regression
        raise AssertionError("covering_test_files must not run subprocesses")

    monkeypatch.setattr(subprocess, "run", _boom)
    rel = _write_pkg_project(
        tmp_path, _BRANCHY_MODULE,
        "from app.foo import classify\n"
        "def test_x():\n    assert classify(11) == 'big'\n",
    )
    assert covering_test_files(str(tmp_path), rel) == ["tests/test_foo.py"]
