"""Autonomous-39 W2: the ``deep-nesting`` seeder fact is now an EXECUTABLE
guard-clause flatten, not a human ``design_task``.

A deeply-nested function used to be devolved to a person ("you design the
flattening"). The COMMON staircase is a LEADING GUARD — a function whose whole
body is a single else-less ``if`` — and inverting that into an early-return is
deterministic: ``plan_extract_guard_clause`` rewrites only that exact shape and
BLOCKS with an empty plan on anything ambiguous. So the fact is flipped to the
delegated ``extract_guard_clause`` action: the bridge strips the ``::function``
suffix to the own-module rel and lands the flatten through
``apply_rename(impact_scope=True)`` with auto-rollback.

HONESTY: extract-guard-clause flattens only the guard-invertible part. A
deeply-nested function whose nesting is NOT a leading guard (genuinely nested
loops/conditionals needing inner-block extraction) matches nothing and yields an
empty plan ⇒ an HONEST no-op (never a fake-green). So deep-nesting becomes
autonomous for the common guard case and stays honest for the rest.

These tests lock:
  * the flip (action_type ``extract_guard_clause``, executable True, target is the
    module rel — the ``::function`` suffix stripped);
  * a real guard-invertible deeply-nested function LANDS the flatten, suite GREEN,
    with its control-flow nesting REDUCED and behaviour preserved;
  * a NON-guard nested function is an HONEST no-op (writes nothing, never
    fake-green) carrying the disclosed reason;
  * the SCOPE note: the lander runs over the MODULE, so it may flatten guard shapes
    in OTHER functions too — broader but suite-gated + auto-rolled-back;
  * an unreadable / non-``.py`` target is an empty no-op plan;
  * the existing idea-types stay byte-identical (only deep-nesting flipped).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge, _FACT_ACTIONS
from app.models.idea import IdeaNode

# A guard-invertible deeply-nested function: the WHOLE body is one else-less
# ``if`` wrapping a further nested ``if`` — inverting the outer guard into an
# early return drops the inner ``if`` one level. Behaviour: handle(2)==20,
# handle(1)==1, handle(0) falls off the end → None.
_GUARD_SRC = (
    "def handle(x):\n"
    "    if x > 0:\n"
    "        if x > 1:\n"
    "            return x * 10\n"
    "        return x\n"
)

# A genuinely-nested (NON-guard) function: setup before the loops, then nested
# for-loops — there is no sole-``if`` body to invert, so the transform refuses.
_NONGUARD_SRC = (
    "def scan(rows):\n"
    "    total = 0\n"
    "    for r in rows:\n"
    "        for c in r:\n"
    "            if c > 0:\n"
    "                total += c\n"
    "    return total\n"
)


def _max_nesting(source: str, func: str) -> int:
    """The maximum control-flow nesting depth of ``func`` in ``source``.

    Mirrors the profiler's notion: every nested compound statement
    (If/For/While/With/Try + async variants) deepens the staircase by one; a
    nested def/class starts its own count. A local, self-contained measure so the
    "nesting reduced" assertion does not couple to a private profiler helper."""
    nesters = (ast.If, ast.For, ast.While, ast.With, ast.Try,
               ast.AsyncFor, ast.AsyncWith)

    def _depth(node: ast.AST, depth: int) -> int:
        best = depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                continue
            step = 1 if isinstance(child, nesters) else 0
            best = max(best, _depth(child, depth + step))
        return best

    tree = ast.parse(source)
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == func:
            return _depth(fn, 0)
    raise AssertionError(f"function {func} not found")


def _nest_idea(subject: str) -> IdeaNode:
    """A ``deep-nesting`` root, exactly as the seeder emits it: a
    ``"<module_rel>::<function>"`` subject and the fact label on
    ``source_facts[0]`` (``_root_action`` reads ``fact.split(":")[0]``)."""
    return IdeaNode(
        id="n", title=f"Flatten the deeply-nested function `{subject}`",
        subject=subject, operator="root",
        source_facts=[f"deep-nesting: {subject} nests control flow several "
                      f"levels — a guard-clause candidate"],
    )


def _project(root: Path, module_rel: str, source: str,
             test_body: str | None = None) -> None:
    """A minimal importable project carrying ``source`` at ``module_rel``."""
    (root / "app").mkdir(exist_ok=True)
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / module_rel).write_text(source, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    if test_body is not None:
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / "test_m.py").write_text(test_body, encoding="utf-8")


# ── 1. the flip itself: the fact row is now executable ────────────────────────

def test_fact_action_is_executable_extract_guard_clause():
    action_type, _desc, executable = _FACT_ACTIONS["deep-nesting"]
    assert action_type == "extract_guard_clause"
    assert executable is True


def test_plan_idea_surfaces_executable_flatten():
    step = IdeaActionBridge().plan_idea(_nest_idea("app/m.py::handle"))
    assert step.action_type == "extract_guard_clause"
    assert step.executable is True
    # The subject is "module::function"; the surfaced target is the own-module rel
    # (the lander strips the suffix), NOT silently dropped to "".
    assert step.target == "app/m.py"
    assert "app/m.py::handle" in step.description


# ── 2. it LANDS the flatten on a real guard-invertible function, suite GREEN ──

def test_applies_and_lands_flatten_suite_green(tmp_path: Path):
    _project(
        tmp_path, "app/m.py", _GUARD_SRC,
        test_body=("from app.m import handle\n\n"
                   "def test_handle():\n"
                   "    assert handle(2) == 20\n"
                   "    assert handle(1) == 1\n"
                   "    assert handle(0) is None\n"))
    before_depth = _max_nesting(_GUARD_SRC, "handle")

    step = IdeaActionBridge().plan_idea(_nest_idea("app/m.py::handle"))
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised",
                                        verify=True)
    assert res["applied"] is True, res
    assert res["transform_type"] == "extract_guard_clause"
    assert res.get("suite_green") is True
    assert res["changed_files"] == ["app/m.py"]

    after = (tmp_path / "app" / "m.py").read_text()
    # The leading guard is inverted into an early return.
    assert "if not (x > 0):" in after
    assert "return" in after
    # The control-flow nesting is genuinely REDUCED (the inner ``if`` rose a level).
    assert _max_nesting(after, "handle") < before_depth


# ── 3. a NON-guard nested function is an HONEST no-op (writes nothing) ────────

def test_non_guard_nesting_is_honest_noop_writes_nothing(tmp_path: Path):
    _project(tmp_path, "app/m.py", _NONGUARD_SRC)
    step = IdeaActionBridge().plan_idea(_nest_idea("app/m.py::scan"))
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised",
                                        verify=True)
    assert res["applied"] is False
    assert res["transform_type"] == "extract_guard_clause"
    # A disclosed reason is carried (no silent success).
    assert res.get("reason")
    assert "no flatten" in res["reason"]
    # NOTHING was written — the module is byte-identical to before.
    assert (tmp_path / "app" / "m.py").read_text() == _NONGUARD_SRC


def test_lander_noop_plan_on_non_guard(tmp_path: Path):
    # The lander itself returns an empty no-op RenamePlan for a non-guard module
    # (the honest no-op fed to apply_rename), not a fabricated rewrite.
    _project(tmp_path, "app/m.py", _NONGUARD_SRC)
    plan = IdeaActionBridge._plan_extract_guard_clause_lander()(
        str(tmp_path), "app/m.py::scan")
    assert not plan.new_contents


# ── 4. the SCOPE note: the lander runs over the MODULE (broader but safe) ─────

def test_lander_flattens_module_scope_other_functions(tmp_path: Path):
    # The subject names ONE function but the lander runs over the whole module, so
    # a SECOND guard-invertible function in the same module is flattened too —
    # broader than the named function (suite-gated + auto-rolled-back upstream).
    two = (
        "def handle(x):\n"
        "    if x > 0:\n"
        "        return x * 2\n"
        "\n"
        "def other(y):\n"
        "    if y > 0:\n"
        "        return y + 1\n"
    )
    _project(tmp_path, "app/m.py", two)
    plan = IdeaActionBridge._plan_extract_guard_clause_lander()(
        str(tmp_path), "app/m.py::handle")
    assert plan.new_contents
    after = plan.new_contents["app/m.py"]
    # BOTH functions' leading guards were inverted, not just the named one.
    assert "if not (x > 0):" in after
    assert "if not (y > 0):" in after


# ── 5. an unreadable / non-.py target is an empty no-op plan ──────────────────

def test_lander_missing_target_is_empty_noop_plan(tmp_path: Path):
    _project(tmp_path, "app/m.py", _GUARD_SRC)
    # A module rel that does not exist → the real lander appends a "cannot read"
    # blocker and returns an empty plan (an honest no-op, never a raise).
    plan = IdeaActionBridge._plan_extract_guard_clause_lander()(
        str(tmp_path), "app/absent.py::nope")
    assert not plan.new_contents
    assert plan.blockers


def test_strips_function_suffix_to_module_rel(tmp_path: Path):
    # The lander resolves "module::function" → the module rel (the suffix is
    # dropped), and a plain module target (no "::") is unchanged — both flatten.
    _project(tmp_path, "app/m.py", _GUARD_SRC)
    lander = IdeaActionBridge._plan_extract_guard_clause_lander()
    via_subject = lander(str(tmp_path), "app/m.py::handle")
    via_module = lander(str(tmp_path), "app/m.py")
    assert via_subject.new_contents == via_module.new_contents
    assert via_module.new_contents  # the guard-invertible module flattens


# ── 6. the existing idea-types stay byte-identical (only deep-nesting flipped) ─

def test_other_fact_actions_unchanged():
    # Only the deep-nesting row's (action_type, executable) flipped; a sample of
    # the neighbouring fact rows must be byte-identical to their pre-flip shape.
    assert _FACT_ACTIONS["coordinator"] == (
        "design_task",
        "Decouple the coordinator module {s} — it imports many "
        "internal modules; split its responsibilities (Apex names "
        "the god-module, you design the seams)", False)
    assert _FACT_ACTIONS["god-class"][0] == "design_task"
    assert _FACT_ACTIONS["god-class"][2] is False
    # The W1 sibling stays as W1 left it (this wave touches only deep-nesting).
    assert _FACT_ACTIONS["generalizable-duplication"][0] == "dedup_parameterized"
    # incomplete-protocol was design_task at W2 time; Autonomous-39 W5 later flipped
    # it to the executable seal_hashable_eq lander — assert that current reality.
    assert _FACT_ACTIONS["incomplete-protocol"][0] == "seal_hashable_eq"
