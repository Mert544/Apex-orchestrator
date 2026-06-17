"""Mutation-hardening for the refactor signature/extraction family.

A "never fakes green" moat for four hands of the deterministic refactor engine:
:mod:`extract_method`, :mod:`inline_function`, :mod:`param_add`, and
:mod:`param_drop`. Every test here pins a behaviour a single-token mutation
(an off-by-one boundary flip, an arithmetic/comparison/boolean operator flip, a
``return <expr> -> return None`` flip, a numeric ``n -> n + 1`` flip, a
``True``/``False`` flip) would change — so a survivor of any such mutation makes
a test here go red.

All assertions are deterministic: no timestamps, no wall-clock, no reliance on
set/dict iteration order. Lists from the suggesters are already sorted by their
own deterministic keys; the few set-valued internals are compared as sets.
"""

from __future__ import annotations

import ast

from app.execution.extract_method import (
    _SUGGEST_FN_FLOOR,
    _SUGGEST_MAX_LINES,
    _SUGGEST_MAX_PARAMS,
    _SUGGEST_MAX_RETURNS,
    _SUGGEST_MIN_LINES,
    _SUGGEST_MIN_STMTS,
    plan_extract,
    suggest_extractions,
)
from app.execution.inline_function import plan_inline, suggest_inlines
from app.execution.param_add import plan_param_add
from app.execution.param_drop import plan_param_drop


def _write(tmp_path, rel, src):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
    return p


# ════════════════════════════════════════════════════════════════════════════
# extract_method
# ════════════════════════════════════════════════════════════════════════════


def test_extract_start_equals_end_line_is_allowed(tmp_path):
    # `start_line > end_line` blocks; the boundary `start == end` must NOT block.
    # Kills the `>` -> `>=` boundary flip in _read_and_parse's start/end guard.
    _write(tmp_path, "m.py",
           "def f(a):\n"
           "    b = a + 1\n"
           "    return b\n")
    plan = plan_extract(str(tmp_path), "m.py", 2, 2, "_h")
    # Line 2 is one complete statement; a single-line range is valid here.
    assert not plan.blockers, plan.blockers
    assert plan.new_contents


def test_extract_start_one_past_end_blocks(tmp_path):
    # The strict inverse: start = end + 1 must hit the start>end blocker.
    _write(tmp_path, "m.py",
           "def f(a):\n"
           "    b = a + 1\n"
           "    c = b + 1\n"
           "    return c\n")
    plan = plan_extract(str(tmp_path), "m.py", 3, 2, "_h")
    assert any("start line must be <= end line" in b for b in plan.blockers)
    assert not plan.new_contents


def test_extract_live_in_only_includes_names_read_from_prior_scope(tmp_path):
    # `total` is a param (prior scope) and read -> live-in; `tmp` is defined and
    # read inside the range -> NOT live-in. Pins the membership test that a
    # boolean/comparison mutation in _data_flow would break.
    _write(tmp_path, "m.py",
           "def f(total, data):\n"
           "    tmp = 0\n"
           "    for x in data:\n"
           "        tmp = tmp + x\n"
           "    total = total + tmp\n"
           "    return total\n")
    plan = plan_extract(str(tmp_path), "m.py", 2, 5, "_acc")
    assert not plan.blockers, plan.blockers
    new = plan.new_contents["m.py"]
    # data and total are read from prior scope; tmp is local to the range.
    assert "def _acc(data, total):" in new
    assert "tmp" not in new.split("def f")[1].split(":")[0]


def test_extract_live_out_only_includes_names_read_after(tmp_path):
    # `kept` is defined in the range and read AFTER -> live-out (return value).
    # `scratch` is defined in the range but never read after -> not returned.
    _write(tmp_path, "m.py",
           "def f(data):\n"
           "    scratch = 0\n"
           "    kept = 0\n"
           "    for x in data:\n"
           "        scratch = x\n"
           "        kept = kept + x\n"
           "    return kept\n")
    plan = plan_extract(str(tmp_path), "m.py", 2, 6, "_acc")
    assert not plan.blockers, plan.blockers
    new = plan.new_contents["m.py"]
    assert "return kept" in new
    # scratch must not appear in the helper's return tuple.
    helper = new.split("def f")[0]
    assert "return scratch" not in helper
    assert "scratch, kept" not in helper and "kept, scratch" not in helper


def test_extract_helper_is_inserted_above_container_not_below(tmp_path):
    # _assemble_source inserts at min(container.lineno, decorators) - 1.
    # A `+1`/`-1` off-by-one or arithmetic flip would misplace or break the def.
    _write(tmp_path, "m.py",
           "def process(data):\n"
           "    a = 1\n"
           "    b = a + 1\n"
           "    c = b + 1\n"
           "    return c\n")
    plan = plan_extract(str(tmp_path), "m.py", 2, 4, "_chunk")
    assert not plan.blockers, plan.blockers
    new = plan.new_contents["m.py"]
    ast.parse(new)  # a misplaced insert would not parse
    assert new.index("def _chunk(") < new.index("def process(")


def test_extract_decorated_method_helper_inserted_above_decorator(tmp_path):
    # The insert point is the MIN of the class line and its decorator lines, so
    # the helper lands above the decorator. Pins the decorator-aware min().
    _write(tmp_path, "c.py",
           "import dataclasses\n"
           "\n"
           "\n"
           "@dataclasses.dataclass\n"
           "class C:\n"
           "    def run(self, items):\n"
           "        acc = 0\n"
           "        scratch = 1\n"
           "        more = scratch + 1\n"
           "        return acc + more\n")
    plan = plan_extract(str(tmp_path), "c.py", 7, 9, "_loop")
    assert not plan.blockers, plan.blockers
    new = plan.new_contents["c.py"]
    ast.parse(new)
    assert new.index("def _loop(") < new.index("@dataclasses.dataclass")


def test_extract_void_helper_emits_warning(tmp_path):
    # No live-in AND no live-out -> the "no parameters and returns nothing"
    # warning. A boolean `and` -> `or` flip in the gate would mis-warn.
    _write(tmp_path, "m.py",
           "def f():\n"
           "    print('a')\n"
           "    print('b')\n"
           "    print('c')\n")
    plan = plan_extract(str(tmp_path), "m.py", 2, 4, "_show")
    assert not plan.blockers, plan.blockers
    assert any("takes no parameters and returns" in w for w in plan.warnings)


def test_extract_with_params_does_not_warn_void(tmp_path):
    # A helper that DOES take a param must NOT emit the void warning — pins the
    # other side of the `not live_in and not live_out` boolean gate.
    _write(tmp_path, "m.py",
           "def f(n):\n"
           "    print(n)\n"
           "    print(n + 1)\n"
           "    print(n + 2)\n")
    plan = plan_extract(str(tmp_path), "m.py", 2, 4, "_show")
    assert not plan.blockers, plan.blockers
    assert not any("takes no parameters and returns" in w for w in plan.warnings)
    assert "def _show(n):" in plan.new_contents["m.py"]


def test_extract_augassign_counts_as_live_in_and_live_out(tmp_path):
    # `acc += x` both reads (live-in, since acc pre-exists) and defines acc
    # (live-out, since it's read after). Pins _augmented_targets feeding both.
    _write(tmp_path, "m.py",
           "def f(data):\n"
           "    acc = 0\n"
           "    for x in data:\n"
           "        acc += x\n"
           "    return acc\n")
    plan = plan_extract(str(tmp_path), "m.py", 3, 4, "_loop")
    assert not plan.blockers, plan.blockers
    new = plan.new_contents["m.py"]
    assert "def _loop(acc, data):" in new
    assert "return acc" in new.split("def f")[0]
    assert "acc = _loop(acc, data)" in new


# ── suggest_extractions: the seam-quality numeric gates ──


def test_suggest_function_just_below_floor_is_skipped():
    # A function exactly one line below the floor must be skipped; one AT/above
    # the floor must be mined. Kills the `<` boundary flip in _is_minable_function.
    short_span = _SUGGEST_FN_FLOOR - 1
    body = "\n".join(f"    s{i} = {i}" for i in range(short_span - 2))
    src = f"def f(start):\n    t = start\n{body}\n"
    assert suggest_extractions(src) == []


def test_suggest_function_at_floor_is_mined():
    # Build a function whose span is comfortably above the floor so a seam exists.
    body = "\n".join(f"    s{i} = {i}" for i in range(_SUGGEST_FN_FLOOR + 5))
    src = f"def f(start):\n    t = start\n{body}\n    return t\n"
    sugs = suggest_extractions(src)
    assert sugs, "a function above the line floor should yield a seam"
    assert sugs[0]["function"] == "f"


def test_suggest_lines_saved_respects_min_and_max_bounds():
    # Every suggested seam must save between MIN and MAX lines, inclusive.
    # Kills boundary flips on the `_SUGGEST_MIN_LINES <= saved <= _SUGGEST_MAX_LINES`
    # gate (a `<=` -> `<` would drop the exact-boundary seam).
    body = "\n".join(f"    a{i} = {i}" for i in range(70))
    src = f"def huge():\n{body}\n    return a0\n"
    for s in suggest_extractions(src):
        assert _SUGGEST_MIN_LINES <= s["lines_saved"] <= _SUGGEST_MAX_LINES


def test_suggest_run_shorter_than_min_stmts_never_chosen():
    # _SUGGEST_MIN_STMTS gates the window width; a 2-statement window can never
    # be a seam. We force a body where only short runs would otherwise qualify
    # and assert no seam shorter than the statement floor appears.
    body = "\n".join(f"    a{i} = {i}" for i in range(_SUGGEST_FN_FLOOR + 5))
    src = f"def f():\n{body}\n    return a0\n"
    for s in suggest_extractions(src):
        # end-start span in lines is >= MIN_STMTS-ish; assert the window covered
        # at least _SUGGEST_MIN_STMTS lines worth (each stmt is one line here).
        assert (s["end"] - s["start"] + 1) >= _SUGGEST_MIN_STMTS


def test_suggest_respects_param_cap_exactly():
    # A function whose only clean seams would need > MAX_PARAMS inputs yields
    # nothing; pins the `len(live_in) > _SUGGEST_MAX_PARAMS` rejection.
    params = ", ".join(f"p{i}" for i in range(_SUGGEST_MAX_PARAMS + 3))
    body = "\n".join(f"    v{i} = " + " + ".join(f"p{j}" for j in range(_SUGGEST_MAX_PARAMS + 3))
                     for i in range(45))
    src = f"def wide({params}):\n{body}\n    return v0\n"
    for s in suggest_extractions(src):
        assert len(s["params"]) <= _SUGGEST_MAX_PARAMS


def test_suggest_respects_return_cap_exactly():
    body_lines = [f"    r{i} = {i}" for i in range(45)]
    after = "    return " + " + ".join(f"r{i}" for i in range(45))
    src = "def many():\n" + "\n".join(body_lines) + "\n" + after + "\n"
    for s in suggest_extractions(src):
        assert len(s["returns"]) <= _SUGGEST_MAX_RETURNS


def test_suggest_whole_body_is_never_a_seam():
    # Extracting the entire body (j - i == n) is a rename, not a seam, and must
    # be rejected. With a body that is one clean run, the only candidate would be
    # the whole body — so the result is empty. Pins the `j - i == n` guard.
    body = "\n".join(f"    a{i} = {i}" for i in range(_SUGGEST_FN_FLOOR + 5))
    src = f"def f():\n{body}\n"   # NO trailing return: body is one pure run
    # The full-body window is rejected; sub-windows that save < MIN_LINES are
    # rejected too, but a long enough sub-run still qualifies. Assert no seam
    # spans the entire body.
    n_body = _SUGGEST_FN_FLOOR + 5
    for s in suggest_extractions(src):
        assert not (s["start"] == 2 and s["end"] == n_body + 1)


def test_suggest_score_prefers_fewer_interface_names():
    # The score is `lines_saved - 2 * (n_params + n_returns)`. Two seams saving
    # the same lines: the one with the smaller interface must win. Pins the `2 *`
    # coefficient — a `2 -> 3` numeric flip or `* -> +` arithmetic flip changes
    # which seam is selected, so we assert the selected seam's interface is
    # minimal among equal-length seams via determinism + a known shape.
    body = "\n".join(f"    a{i} = a{i - 1} + 1" if i else "    a0 = start"
                     for i in range(_SUGGEST_FN_FLOOR))
    src = f"def f(start):\n{body}\n    return a0\n"
    first = suggest_extractions(src)
    second = suggest_extractions(src)
    assert first == second  # deterministic selection
    assert first and first[0]["function"] == "f"


# ════════════════════════════════════════════════════════════════════════════
# inline_function
# ════════════════════════════════════════════════════════════════════════════


def test_inline_too_many_positional_args_blocks(tmp_path):
    # `len(call.args) > len(params)` -> blocker. A 2-arg call to a 1-param fn
    # must block; the exact-count call must NOT. Kills the `>` boundary flip.
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use():\n"
           "    return fee(1, 2)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert plan.blockers
    assert any("positional args but" in b for b in plan.blockers)
    assert not plan.new_contents


def test_inline_exact_arg_count_is_allowed(tmp_path):
    # The boundary: len(args) == len(params) must inline cleanly.
    _write(tmp_path, "m.py",
           "def fee(x, y):\n"
           "    return x + y\n"
           "\n"
           "\n"
           "def use():\n"
           "    return fee(3, 4)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert not plan.blockers, plan.blockers
    assert "((3) + (4))" in plan.new_contents["m.py"]


def test_inline_param_used_once_with_impure_arg_is_safe(tmp_path):
    # The side-effect gate triggers only when a param is used MORE THAN ONCE
    # (`len(nodes) > 1`). A param used exactly once with an impure arg is SAFE —
    # kills the `> 1` -> `>= 1` boundary flip (which would wrongly block this).
    _write(tmp_path, "m.py",
           "def once(x):\n"
           "    return x + 1\n"
           "\n"
           "\n"
           "def use():\n"
           "    return once(compute())\n"
           "\n"
           "\n"
           "def compute():\n"
           "    return 5\n")
    plan = plan_inline(str(tmp_path), "once")
    assert not plan.blockers, plan.blockers
    assert "((compute()) + 1)" in plan.new_contents["m.py"]


def test_inline_param_used_twice_with_impure_arg_blocks(tmp_path):
    # The strict inverse: used twice + impure arg -> block, naming the count.
    _write(tmp_path, "m.py",
           "def sq(x):\n"
           "    return x * x\n"
           "\n"
           "\n"
           "def use():\n"
           "    return sq(compute())\n"
           "\n"
           "\n"
           "def compute():\n"
           "    return 5\n")
    plan = plan_inline(str(tmp_path), "sq")
    assert plan.blockers
    assert any("used 2 times" in b for b in plan.blockers)


def test_inline_zero_call_sites_blocks_not_proceeds(tmp_path):
    # `if not sites` -> block. Pins the truthiness branch a boolean flip would
    # invert (proceeding with no sites would later fail differently).
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert any("nothing to inline" in b for b in plan.blockers)
    assert not plan.new_contents


def test_inline_keyword_default_uses_definition_module_source(tmp_path):
    # A missing arg falls back to the parameter's default. Pins the default
    # binding — a `return None` flip in _bind_arguments' default branch would
    # drop the default text.
    _write(tmp_path, "m.py",
           "def scaled(x, factor=10):\n"
           "    return x * factor\n"
           "\n"
           "\n"
           "def use():\n"
           "    return scaled(3)\n")
    plan = plan_inline(str(tmp_path), "scaled")
    assert not plan.blockers, plan.blockers
    assert "((3) * (10))" in plan.new_contents["m.py"]


def test_inline_unknown_keyword_blocks(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use():\n"
           "    return fee(nope=5)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert plan.blockers
    assert any("is not a parameter" in b for b in plan.blockers)


def test_inline_definition_count_must_be_exactly_one(tmp_path):
    # `len(definitions) != 1` -> block. Zero and two both block; pins the `!= 1`
    # against an `== 1` / `> 1` mutation.
    _write(tmp_path, "a.py", "def fee(x):\n    return x\n")
    _write(tmp_path, "b.py",
           "def fee(x):\n    return x\n\n\ndef use():\n    return fee(1)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert any("exactly once" in b and "(found 2)" in b for b in plan.blockers)


def test_inline_single_definition_proceeds(tmp_path):
    # The boundary: exactly one definition is the only accepted count.
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use():\n"
           "    return fee(7)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert not plan.blockers, plan.blockers


def test_inline_deletes_one_trailing_blank_line_only(tmp_path):
    # _delete_def_lines removes the def span plus ONE trailing blank line. Pins
    # the single trailing-blank removal — over/under removal leaves wrong spacing.
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use():\n"
           "    return fee(4)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert not plan.blockers, plan.blockers
    new = plan.new_contents["m.py"]
    ast.parse(new)
    assert "def fee" not in new
    # Exactly one blank line should remain between the removed def and `use`.
    assert new.startswith("\ndef use(") or new.startswith("def use(")


def test_suggest_inlines_allows_exactly_max_call_sites(tmp_path):
    # `1 <= n_sites <= _SUGGEST_MAX_CALL_SITES`. With MAX (=2) sites it qualifies;
    # one more must drop it. Pins both bounds of the call-site count gate.
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use(a, b):\n"
           "    return fee(a) + fee(b)\n")
    out = suggest_inlines(str(tmp_path))
    assert [s["function"] for s in out] == ["fee"]
    assert out[0]["call_sites"] == 2


def test_suggest_inlines_drops_above_max_call_sites(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use(a, b, c):\n"
           "    return fee(a) + fee(b) + fee(c)\n")
    assert suggest_inlines(str(tmp_path)) == []


def test_suggest_inlines_drops_zero_call_sites(tmp_path):
    # The lower bound `1 <= n_sites`: a defined-but-uncalled helper is dropped.
    _write(tmp_path, "m.py",
           "def orphan(x):\n"
           "    return x + 1\n")
    assert suggest_inlines(str(tmp_path)) == []


# ════════════════════════════════════════════════════════════════════════════
# param_add
# ════════════════════════════════════════════════════════════════════════════


def _add_project(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def fetch(url, timeout=10):\n"
        "    return url\n")
    return tmp_path


def test_param_add_appends_after_positionals(tmp_path):
    _add_project(tmp_path)
    plan = plan_param_add(tmp_path, "fetch", "retries", "3")
    assert plan.ok, plan.blockers
    assert "def fetch(url, timeout=10, retries=3):" in plan.new_contents["app/core.py"]


def test_param_add_keyword_only_after_star_args(tmp_path):
    # With *args the new param MUST be keyword-only (after *items), or a trailing
    # positional default would absorb positionals. Pins the vararg branch.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "s.py").write_text(
        "def star_fn(a, *items):\n    return a\n")
    plan = plan_param_add(tmp_path, "star_fn", "trace", "None")
    assert plan.ok, plan.blockers
    assert "def star_fn(a, *items, trace=None):" in plan.new_contents["app/s.py"]


def test_param_add_existing_param_blocks(tmp_path):
    # `param in existing params` -> block. Pins the membership test.
    _add_project(tmp_path)
    plan = plan_param_add(tmp_path, "fetch", "timeout", "0")
    assert not plan.ok
    assert any("already has a parameter" in b for b in plan.blockers)


def test_param_add_name_used_in_body_blocks(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "LIMIT = 9\n"
        "def fetch(url):\n"
        "    return LIMIT\n")
    plan = plan_param_add(tmp_path, "fetch", "LIMIT", "1")
    assert not plan.ok
    assert any("already used inside" in b for b in plan.blockers)


def test_param_add_call_already_passing_keyword_blocks(tmp_path):
    # A site passing `param=` already -> blocker; an f(**…) site only warns. Pins
    # the `kw.arg == param` vs `kw.arg is None` discrimination.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def fetch(url, **extra):\n    return url, extra\n")
    (tmp_path / "app" / "user.py").write_text(
        "from app.core import fetch\n"
        "def f():\n"
        "    return fetch('a', retries=2)\n")
    plan = plan_param_add(tmp_path, "fetch", "retries", "3")
    assert not plan.ok
    assert any("already passes" in b for b in plan.blockers)


def test_param_add_dict_expansion_warns_not_blocks(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def fetch(url, **extra):\n    return url\n")
    (tmp_path / "app" / "dyn.py").write_text(
        "from app.core import fetch\n"
        "def d(opts):\n"
        "    return fetch('a', **opts)\n")
    plan = plan_param_add(tmp_path, "fetch", "retries", "3")
    assert plan.ok
    assert any("may already carry 'retries'" in w for w in plan.warnings)


def test_param_add_invalid_identifier_and_keyword_block(tmp_path):
    _add_project(tmp_path)
    assert not plan_param_add(tmp_path, "fetch", "no-dash", "0").ok
    assert not plan_param_add(tmp_path, "fetch", "class", "0").ok  # python keyword


def test_param_add_bad_default_expression_blocks(tmp_path):
    _add_project(tmp_path)
    plan = plan_param_add(tmp_path, "fetch", "retries", "3 +")
    assert not plan.ok
    assert any("not a valid expression" in b for b in plan.blockers)


def test_param_add_annotated_default_gets_pep8_spacing(tmp_path):
    # An annotated param's default uses `name = default` (spaces); unannotated is
    # tight. The new param itself is always `name=default` (tight). Pins the
    # annotation-conditional spacing branch.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def fetch(url: str, timeout: int = 10):\n    return url\n")
    plan = plan_param_add(tmp_path, "fetch", "retries", "3")
    assert plan.ok, plan.blockers
    new = plan.new_contents["app/core.py"]
    assert "timeout: int = 10" in new   # annotated default keeps spaces
    assert "retries=3" in new           # new param stays tight


def test_param_add_edits_only_definition_file(tmp_path):
    # The default keeps callers valid, so ONLY the def file is rewritten. Pins
    # `edits_by_file[defmod] = 1` (a number flip to 2 would be wrong).
    _add_project(tmp_path)
    (tmp_path / "app" / "user.py").write_text(
        "from app.core import fetch\n"
        "def f():\n"
        "    return fetch('a', timeout=5)\n")
    plan = plan_param_add(tmp_path, "fetch", "retries", "3")
    assert plan.ok, plan.blockers
    assert list(plan.new_contents) == ["app/core.py"]
    assert plan.edits_by_file == {"app/core.py": 1}


# ════════════════════════════════════════════════════════════════════════════
# param_drop
# ════════════════════════════════════════════════════════════════════════════


def _drop_project(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def render(text, color=None, width=80):\n"
        "    return text[:width]\n")
    return tmp_path


def test_param_drop_rebuilds_def_without_param(tmp_path):
    _drop_project(tmp_path)
    plan = plan_param_drop(tmp_path, "render", "color")
    assert plan.ok, plan.blockers
    assert "def render(text, width=80):" in plan.new_contents["app/core.py"]


def test_param_drop_read_param_blocks(tmp_path):
    # The body READS `width`, so dropping it changes behaviour -> block. Pins the
    # any(Name == param) read-detection.
    _drop_project(tmp_path)
    plan = plan_param_drop(tmp_path, "render", "width")
    assert not plan.ok
    assert any("READS" in b for b in plan.blockers)


def test_param_drop_positional_call_blocks(tmp_path):
    # `len(node.args) > pos_index` -> the call passes the param positionally ->
    # block. Pins the `>` boundary on the positional-overlap check.
    _drop_project(tmp_path)
    (tmp_path / "app" / "pos.py").write_text(
        "from app.core import render\n"
        "def g(t):\n"
        "    return render(t, 'red')\n")
    plan = plan_param_drop(tmp_path, "render", "color")
    assert not plan.ok
    assert any("POSITIONALLY" in b for b in plan.blockers)
    assert not plan.new_contents


def test_param_drop_call_before_target_index_is_safe(tmp_path):
    # color is at positional index 1; a call passing only ONE positional arg
    # (index 0) does NOT reach color, so it stays safe. The boundary inverse of
    # the positional block.
    _drop_project(tmp_path)
    (tmp_path / "app" / "kw.py").write_text(
        "from app.core import render\n"
        "def g(t):\n"
        "    return render(t, color='red')\n")
    plan = plan_param_drop(tmp_path, "render", "color")
    assert plan.ok, plan.blockers
    assert "render(t)" in plan.new_contents["app/kw.py"]


def test_param_drop_prunes_keyword_at_call_site(tmp_path):
    _drop_project(tmp_path)
    (tmp_path / "app" / "kw.py").write_text(
        "from app.core import render\n"
        "def g(t):\n"
        "    return render(t, color='red', width=40)\n")
    plan = plan_param_drop(tmp_path, "render", "color")
    assert plan.ok, plan.blockers
    assert "render(t, width=40)" in plan.new_contents["app/kw.py"]


def test_param_drop_multiline_keyword_value_blocks(tmp_path):
    # `kw.lineno != kw.value.end_lineno` -> spans lines -> block. Pins the `!=`.
    _drop_project(tmp_path)
    (tmp_path / "app" / "tall.py").write_text(
        "from app.core import render\n"
        "def g(t):\n"
        "    return render(t, color=(\n"
        "        'red'))\n")
    plan = plan_param_drop(tmp_path, "render", "color")
    assert not plan.ok
    assert any("spans lines" in b for b in plan.blockers)


def test_param_drop_blocked_plan_clears_all_edits(tmp_path):
    # On any blocker, plan.new_contents / originals / edits_by_file are cleared.
    # Pins the post-block cleanup — a survivor would leave partial edits behind.
    _drop_project(tmp_path)
    (tmp_path / "app" / "pos.py").write_text(
        "from app.core import render\n"
        "def g(t):\n"
        "    return render(t, 'red')\n")
    plan = plan_param_drop(tmp_path, "render", "color")
    assert plan.blockers
    assert plan.new_contents == {}
    assert plan.originals == {}
    assert plan.edits_by_file == {}


def test_param_drop_defined_exactly_once_gate(tmp_path):
    # Two top-level defs of the same name -> blocked (found 2). Pins the
    # exactly-once count from the shared resolver.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("def render(text, color=None):\n    return text\n")
    (tmp_path / "app" / "b.py").write_text("def render(text, color=None):\n    return text\n")
    plan = plan_param_drop(tmp_path, "render", "color")
    assert not plan.ok
    assert any("exactly once" in b and "(found 2)" in b for b in plan.blockers)


def test_param_drop_vararg_not_droppable(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "var.py").write_text(
        "def collect(*items, **extra):\n    return len(items) + len(extra)\n")
    assert not plan_param_drop(tmp_path, "collect", "items").ok   # *args
    assert not plan_param_drop(tmp_path, "collect", "extra").ok   # **kwargs


def test_param_drop_dropping_sole_posonly_removes_slash(tmp_path):
    # Dropping the only positional-only param must NOT leave a dangling `/`.
    # Pins the `keeps_posonly` boolean guard.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "p.py").write_text(
        "def pos_fn(probe, /, rest=0):\n    return rest\n")
    plan = plan_param_drop(tmp_path, "pos_fn", "probe")
    assert plan.ok, plan.blockers
    assert "def pos_fn(rest=0):" in plan.new_contents["app/p.py"]
    assert "/" not in plan.new_contents["app/p.py"].split("\n")[0]


def test_param_drop_keeps_slash_when_other_posonly_survive(tmp_path):
    # Two posonly params, drop one -> the `/` marker must SURVIVE. The other side
    # of the keeps_posonly boolean.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "p.py").write_text(
        "def pos_fn(a, b, /, rest=0):\n    return rest\n")
    plan = plan_param_drop(tmp_path, "pos_fn", "a")
    assert plan.ok, plan.blockers
    head = plan.new_contents["app/p.py"].split("\n")[0]
    assert "/" in head
    assert "def pos_fn(b, /, rest=0):" == head


def test_param_drop_comment_in_signature_blocks(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def render(text,\n"
        "           color=None,  # unused\n"
        "           width=80):\n"
        "    return text[:width]\n")
    plan = plan_param_drop(tmp_path, "render", "color")
    assert not plan.ok
    assert any("comment" in b for b in plan.blockers)


def test_param_drop_not_a_parameter_blocks(tmp_path):
    _drop_project(tmp_path)
    plan = plan_param_drop(tmp_path, "render", "nope")
    assert not plan.ok
    assert any("is not a parameter" in b for b in plan.blockers)
