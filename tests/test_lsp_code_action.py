"""Tests for the LSP ``textDocument/codeAction`` quick-fix surface.

The moat is I2: an LSP quick-fix applies a WorkspaceEdit WITHOUT Apex's suite-gate,
so ONLY behaviour-preserving-by-construction transforms (TIDY ∩ Tier-0 ∩
in-memory-capable ∩ sibling-insensitive) may EVER be offered. The drift/proof
tests below re-derive that safe set from FIRST PRINCIPLES and prove each
membership/exclusion, so a future objective can't silently appear or vanish as a
quick-fix, and no behaviour-introducing transform can ever leak in.
"""

from __future__ import annotations

import inspect

from app.engine.move_value import OBJECTIVE_OPERATOR
from app.engine.north_star_audit import OBJECTIVE_MANIFEST, classify_objectives
from app.engine.objective_compiler import available_objectives
from app.execution._plan_transforms import plan_from_source
from app.execution._transform_base import IN_MEMORY_ROOT, source_override
from app.execution.risk_tiers import (
    BEHAVIOUR_CHANGING_OPERATORS,
    tier_for_operator,
)
from app.lsp.quick_fixes import LSP_QUICKFIX_PLANS
from app.lsp.server import LSPServer


# --- Per-operator triggering fixtures (each FIRES at this base) --------------
#
# A buffer the operator's transform rewrites (plan.ok True). The drift test
# proves this dict's keys EQUAL the registry's, so a new quick-fix forces a new
# fixture — the include set is never asserted without a firing witness.
TRIGGER = {
    "simplify_bool_comparison": "def f(a, b):\n    return (a < b) == True\n",
    "simplify_len_comparison": "def f(x):\n    if len(x) > 0:\n        return 1\n    return 0\n",
    "simplify_negated_comparison": "def f(a, b):\n    return not (a < b)\n",
    "simplify_ternary_bool": "def f(x):\n    return True if x else False\n",
    "simplify_bool_return": "def f(x):\n    if x:\n        return True\n    else:\n        return False\n",
    "simplify_comprehension": "def f(items):\n    out = []\n    for i in items:\n        out.append(i)\n    return out\n",
    "dict_comprehension": "def f(items):\n    d = {}\n    for k in items:\n        d[k] = k\n    return d\n",
    "simplify_dict_get": "def f(d, k):\n    return d[k] if k in d else 0\n",
    "extract_guard_clause": "def f(x):\n    if x:\n        a = 1\n        b = 2\n        c = 3\n        return a + b + c\n",
    "guard_clause": "def f(x):\n    y = compute(x)\n    if y:\n        do(y)\n        more(y)\n        again(y)\n",
    "chain_comparison": "def f(a, b, c):\n    return a < b and b < c\n",
    "collapse_startswith": "def f(s):\n    return s.startswith('a') or s.startswith('b')\n",
    "combine_augmented_assign": "def f(x):\n    x = x + 1\n    return x\n",
    "combine_nested_with": "def f():\n    with a() as x:\n        with b() as y:\n            return x, y\n",
    "merge_isinstance": "def f(x):\n    return isinstance(x, int) or isinstance(x, str)\n",
    "merge_nested_if": "def f(a, b):\n    if a:\n        if b:\n            return 1\n",
    "fix_assert_tuple": "def f(x):\n    assert (x, 'msg')\n",
    "fix_not_in_is": "def f(a, b):\n    return not a in b\n",
    "fold_literal_string_concat": "x = 'aaa' + 'bbb'\n",
    "format_to_fstring": "def f(name):\n    return 'hello {}'.format(name)\n",
    "remove_double_negation": "def f(x):\n    return not not x\n",
    "remove_pointless_pass": "def f(x):\n    x += 1\n    pass\n    return x\n",
    "remove_redundant_else": "def f(x):\n    if x:\n        return 1\n    else:\n        return 2\n",
    "remove_redundant_fstring": "x = f'no placeholders here'\n",
    "remove_unreachable_after_terminator": "def f(x):\n    return x\n    y = 1\n    return y\n",
    "remove_unused_imports": "import os\nimport sys\n\nprint(sys.argv)\n",
    "set_literal": "x = set([1, 2, 3])\n",
    "use_enumerate": "def f(seq):\n    for i in range(len(seq)):\n        print(seq[i])\n",
}


# --- Derivation helpers (shared by the drift/proof tests) --------------------

def _operator_of(objective_name: str) -> str:
    """Objective NAME → Move.operator via the AUTHORITATIVE map (never a blind
    string-munge): the same bridge ``move_value.objective_value`` uses, with the
    drift-tested dash→underscore fallback for self-registered specs."""
    return OBJECTIVE_OPERATOR.get(objective_name, objective_name.replace("-", "_"))


def _tidy_tier0_objectives() -> set[str]:
    """Every TIDY objective whose operator is Tier-0 (behaviour-preserving)."""
    tidy = classify_objectives(available_objectives())["TIDY"]
    return {n for n in tidy if tier_for_operator(_operator_of(n)) == 0}


# The candidate plan-fn for each TIDY objective (NAME → module, fn). Used by the
# derivation to probe in-memory capability + sibling-sensitivity. A TIDY objective
# with NO single-module ``plan_<x>(root, rel)`` entry here (dedup/dead-params/
# inline-helpers/shrink-functions/modernize) is excluded by construction: its
# work TARGET must be precomputed by a project-wide scan, so it cannot run on a
# lone buffer at all.
_PLAN_FN = {
    "chain-comparison": ("app.execution.chain_comparison", "plan_chain_comparison"),
    "collapse-startswith": ("app.execution.startswith_tuple", "plan_collapse_startswith"),
    "combine-augmented-assign": ("app.execution.combine_augmented_assign", "plan_combine_augmented_assign"),
    "combine-nested-with": ("app.execution.nested_with", "plan_combine_nested_with"),
    "dict-comprehension": ("app.execution.dict_comprehension", "plan_dict_comprehension"),
    "extract-guard-clause": ("app.execution.extract_guard_clause", "plan_extract_guard_clause"),
    "fix-assert-tuple": ("app.execution.fix_assert_tuple", "plan_fix_assert_tuple"),
    "fix-not-in-is": ("app.execution.fix_not_in_is", "plan_fix_not_in_is"),
    "fold-literal-string-concat": ("app.execution.fold_literal_string_concat", "plan_fold_literal_string_concat"),
    "format-to-fstring": ("app.execution.format_to_fstring", "plan_format_to_fstring"),
    "fstring-convert": ("app.execution.fstring_convert", "plan_fstring_convert"),
    "guard-clause": ("app.execution.guard_clause", "plan_guard_clause"),
    "merge-duplicate-imports": ("app.execution.objectives.merge_duplicate_imports", "plan_merge_duplicate_imports"),
    "merge-isinstance": ("app.execution.merge_isinstance", "plan_merge_isinstance"),
    "merge-nested-if": ("app.execution.merge_nested_if", "plan_merge_nested_if"),
    "modernize-typing": ("app.execution.objectives.modernize_typing", "plan_modernize_typing"),
    "percent-to-fstring": ("app.execution.percent_to_fstring", "plan_percent_to_fstring"),
    "promote-staticmethod": ("app.execution.promote_staticmethods", "plan_promote_staticmethods"),
    "remove-dead-code": ("app.execution.dead_code", "plan_remove_dead_code"),
    "remove-double-negation": ("app.execution.remove_double_negation", "plan_remove_double_negation"),
    "remove-pointless-pass": ("app.execution.remove_pointless_pass", "plan_remove_pointless_pass"),
    "remove-redundant-else": ("app.execution.redundant_else", "plan_remove_redundant_else"),
    "remove-redundant-fstring": ("app.execution.remove_redundant_fstring", "plan_remove_redundant_fstring"),
    "remove-unreachable-after-terminator": ("app.execution.remove_unreachable_after_terminator", "plan_remove_unreachable_after_terminator"),
    "remove-unused-imports": ("app.execution.unused_imports", "plan_remove_unused_imports"),
    "set-literal": ("app.execution.set_literal", "plan_set_literal"),
    "simplify-bool-comparison": ("app.execution.simplify_bool_comparison", "plan_simplify_bool_comparison"),
    "simplify-bool-return": ("app.execution.bool_return", "plan_simplify_bool_return"),
    "simplify-comprehension": ("app.execution.comprehension", "plan_simplify_comprehension"),
    "simplify-dict-get": ("app.execution.dict_get", "plan_simplify_dict_get"),
    "simplify-len-comparison": ("app.execution.simplify_len_comparison", "plan_simplify_len_comparison"),
    "simplify-negated-comparison": ("app.execution.simplify_negated_comparison", "plan_simplify_negated_comparison"),
    "simplify-ternary-bool": ("app.execution.simplify_ternary_bool", "plan_simplify_ternary_bool"),
    "sort-dunder-all": ("app.execution.objectives.sort_dunder_all", "plan_sort_dunder_all"),
    "sort-imports": ("app.execution.import_sort", "plan_sort_imports"),
    "use-enumerate": ("app.execution.use_enumerate", "plan_use_enumerate"),
    "dedup-dunder-all": ("app.execution.objectives.dedup_dunder_all", "plan_dedup_dunder_all"),
    "extract-constant": ("app.execution.extract_constant", "plan_extract_constant"),
}


def _load_plan_fn(objective_name: str):
    import importlib

    mod, fn = _PLAN_FN[objective_name]
    return getattr(importlib.import_module(mod), fn)


def _is_two_arg_callable(fn) -> bool:
    """Is ``fn`` callable as ``fn(project_root, module_rel)`` — i.e. exactly two
    REQUIRED positional params? A scan-based transform takes a precomputed target
    (block / func_name / span) as its second arg, so it fails this and is excluded
    (it cannot run on a lone buffer)."""
    params = inspect.signature(fn).parameters.values()
    required = [p for p in params
                if p.default is inspect.Parameter.empty
                and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    return len(required) == 2


def _honors_source_override(fn) -> bool:
    """Does ``fn`` read its subject through ``read_module_source`` (so
    ``plan_from_source`` feeds it the buffer)? Probe with a BROKEN buffer: a
    buffer-reading transform reports a PARSE error (it saw the buffer); a
    disk-reading transform reports 'cannot read'/'not found' or a silent no-op
    (it never saw the buffer)."""
    plan = plan_from_source(fn, "m.py", "def broken(:\n    pass\n")
    return any("parse" in b or "syntax" in b.lower() for b in plan.blockers)


def _sibling_insensitive(objective_name: str, fn) -> bool:
    """Is ``fn``'s plan a pure function of ``module_rel`` alone? Run it on the lone
    triggering buffer, then again with a sibling module in the override map, and
    require an IDENTICAL plan. (Disk-walking eligibility — ``_build_index`` —
    can't even SEE the override sibling, so we ALSO source-inspect for that index
    below; here the behavioural probe catches read-via-override sibling use.)"""
    operator = _operator_of(objective_name)
    src = TRIGGER.get(operator)
    if src is None:
        return False  # no firing witness => cannot vouch; treat as excluded
    lone = plan_from_source(fn, "m.py", src)
    if not lone.ok:
        return False
    sibling = ("from m import f\ndef other():\n    return f(1)\n"
               "z = 'aaa' + 'bbb'\n")
    with source_override({"m.py": src, "sib.py": sibling}):
        withsib = fn(IN_MEMORY_ROOT, "m.py")
    return withsib.new_contents.get("m.py") == lone.new_contents.get("m.py")


def _derive_safe_operators() -> set[str]:
    """Re-derive the safe operator set from first principles: TIDY ∩ Tier-0 ∩
    {2-arg-callable plan_<x>} ∩ {honors source_override} ∩ {sibling-insensitive}.
    NON-tautological — computed without reference to ``LSP_QUICKFIX_PLANS``."""
    safe: set[str] = set()
    for name in _tidy_tier0_objectives():
        if name not in _PLAN_FN:
            continue  # no single-module plan fn (scan-based / meta) — excluded
        fn = _load_plan_fn(name)
        if not _is_two_arg_callable(fn):
            continue
        if not _honors_source_override(fn):
            continue
        if not _sibling_insensitive(name, fn):
            continue
        safe.add(_operator_of(name))
    return safe


def _concrete_operators() -> set[str]:
    """Every CONCRETE objective's operator (via the authoritative bridge)."""
    return {_operator_of(n) for n in OBJECTIVE_MANIFEST["CONCRETE"]}


# --- Small handler driver ----------------------------------------------------

def _code_actions(uri: str, text: str | None) -> list[dict]:
    """Drive ``_handle_textDocument_codeAction`` directly, capturing the result."""
    server = LSPServer()
    out: dict = {}
    server._send_response = lambda i, result=None, error=None: out.update(result=result)
    if text is not None:
        server._documents[uri] = text
    server._handle_textDocument_codeAction(1, {"textDocument": {"uri": uri}, "range": {}})
    return out["result"]


# --- T1: a TIDY transform is offered, with the exact rewritten text ----------

def test_t1_tidy_transform_offered_with_exact_edit():
    uri = "file:///t.py"
    text = "def f(a, b):\n    return (a < b) == True\n"
    actions = _code_actions(uri, text)
    assert len(actions) == 1
    action = actions[0]
    assert action["kind"] == "quickfix"
    assert "== True" in action["title"] or "boolean comparison" in action["title"]
    # The edit's newText is byte-identical to the transform's own new_contents.
    from app.execution.simplify_bool_comparison import plan_simplify_bool_comparison
    plan = plan_from_source(plan_simplify_bool_comparison, "t.py", text)
    edit = action["edit"]["changes"][uri][0]
    assert edit["newText"] == plan.new_contents["t.py"]
    assert edit["newText"] == "def f(a, b):\n    return (a < b)\n"


def test_t1_extract_guard_clause_offered():
    uri = "file:///g.py"
    text = TRIGGER["extract_guard_clause"]
    actions = _code_actions(uri, text)
    titles = [a["title"] for a in actions]
    assert any("guard clause" in t for t in titles)
    from app.execution.extract_guard_clause import plan_extract_guard_clause
    plan = plan_from_source(plan_extract_guard_clause, "g.py", text)
    guard = next(a for a in actions if "guard clause" in a["title"]
                 and a["edit"]["changes"][uri][0]["newText"] == plan.new_contents["g.py"])
    assert guard["edit"]["changes"][uri][0]["range"] == {
        "start": {"line": 0, "character": 0},
        "end": {"line": text.count("\n"), "character": 0},
    }


# --- T2 (I2 moat): no behaviour-introducing transform EVER offered -----------

def test_t2_no_behaviour_changing_operator_in_registry():
    leaked = BEHAVIOUR_CHANGING_OPERATORS & set(LSP_QUICKFIX_PLANS)
    assert not leaked, f"behaviour-changing operator(s) offered as quick-fix: {leaked}"


def test_t2_no_concrete_objective_in_registry():
    leaked = _concrete_operators() & set(LSP_QUICKFIX_PLANS)
    assert not leaked, f"CONCRETE objective operator(s) offered as quick-fix: {leaked}"


def test_t2_union_of_unsafe_operators_all_absent():
    unsafe = BEHAVIOUR_CHANGING_OPERATORS | _concrete_operators()
    for op in sorted(unsafe):
        assert op not in LSP_QUICKFIX_PLANS, f"{op} must never be a quick-fix"


def test_t2_live_eval_os_system_yields_no_harden():
    text = "import os\ndef f(x):\n    eval(x)\n    os.system('ls')\n"
    actions = _code_actions("file:///s.py", text)
    assert all("harden" not in a["title"].lower() for a in actions)
    assert all("security" not in a["title"].lower() for a in actions)


def test_t2_live_dead_param_yields_no_dead_params_fix():
    # A never-read param + an external caller: dead-params would rewrite the
    # signature AND the caller across the project — unsafe from a lone buffer, so
    # it is excluded and nothing is offered.
    text = ("def helper(used, never_read):\n    return used + 1\n\n"
            "def caller():\n    return helper(1, 2)\n")
    actions = _code_actions("file:///d.py", text)
    assert all("param" not in a["title"].lower() for a in actions)


def test_t2_live_promotable_method_yields_no_promote_staticmethod():
    # A self-free-looking method: promote-staticmethod's safety check walks the
    # WHOLE project (subclass-override / external-usage), blind on a lone buffer,
    # so it is excluded and never offered.
    text = ("class C:\n    def helper(self, x):\n        return x + 1\n"
            "    def use(self):\n        return self.helper(2)\n")
    actions = _code_actions("file:///p.py", text)
    assert all("static" not in a["title"].lower() for a in actions)


# --- T3: a clean file offers nothing -----------------------------------------

def test_t3_clean_file_offers_nothing():
    assert _code_actions("file:///c.py", "def f(x):\n    return x + 1\n") == []


# --- T4: determinism ----------------------------------------------------------

def test_t4_determinism_same_buffer_same_actions():
    uri, text = "file:///t.py", TRIGGER["simplify_bool_comparison"]
    first = _code_actions(uri, text)
    second = _code_actions(uri, text)
    assert first == second
    assert len(first) == 1


# --- T5: an unparseable buffer never crashes ----------------------------------

def test_t5_unparseable_buffer_returns_empty():
    assert _code_actions("file:///b.py", "def broken(:\n    pass\n") == []


def test_t5_empty_and_unknown_documents_return_empty():
    assert _code_actions("file:///e.py", "") == []
    assert _code_actions("file:///missing.py", None) == []  # never didOpen'd


# --- T6: initialize advertises codeActionProvider ----------------------------

def test_t6_initialize_advertises_code_action_provider():
    server = LSPServer()
    out: dict = {}
    server._send_response = lambda i, result=None, error=None: out.update(result=result)
    server._handle_initialize(1, {})
    caps = out["result"]["capabilities"]
    assert caps["codeActionProvider"] == {"codeActionKinds": ["quickfix"]}


# --- T7: end-to-end stdio run() loop -----------------------------------------

import io
import json


class _FakeStdout:
    def __init__(self):
        self.buffer = io.BytesIO()


def _frame(msg: dict) -> str:
    body = json.dumps(msg)
    return f"Content-Length: {len(body.encode())}\r\n\r\n{body}"


def _parse_frames(raw: bytes) -> list[dict]:
    out = []
    text = raw.decode("utf-8")
    while "Content-Length:" in text:
        header, _, rest = text.partition("\r\n\r\n")
        length = int(header.split("Content-Length:")[1].strip().splitlines()[0])
        out.append(json.loads(rest[:length]))
        text = rest[length:]
    return out


def _drive(monkeypatch, messages: list[dict]) -> list[dict]:
    stream = "".join(_frame(m) for m in messages)
    fake_out = _FakeStdout()
    monkeypatch.setattr("sys.stdin", io.StringIO(stream))
    monkeypatch.setattr("sys.stdout", fake_out)
    LSPServer().run()
    return _parse_frames(fake_out.buffer.getvalue())


def test_t7_end_to_end_code_action_over_stdio(monkeypatch):
    uri = "file:///e2e.py"
    text = "def f(a, b):\n    return (a < b) == True\n"
    replies = _drive(monkeypatch, [
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": uri, "text": text}}},
        {"jsonrpc": "2.0", "id": 42, "method": "textDocument/codeAction", "params": {
            "textDocument": {"uri": uri},
            "range": {"start": {"line": 1, "character": 0},
                      "end": {"line": 1, "character": 0}}}},
        {"jsonrpc": "2.0", "method": "exit"},
    ])
    reply = next(r for r in replies if r.get("id") == 42)
    actions = reply["result"]
    assert len(actions) == 1
    assert actions[0]["kind"] == "quickfix"
    assert actions[0]["edit"]["changes"][uri][0]["newText"] == "def f(a, b):\n    return (a < b)\n"


def test_t7_end_to_end_clean_buffer_returns_empty(monkeypatch):
    uri = "file:///clean.py"
    replies = _drive(monkeypatch, [
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": uri, "text": "x = 1\n"}}},
        {"jsonrpc": "2.0", "id": 7, "method": "textDocument/codeAction", "params": {
            "textDocument": {"uri": uri}, "range": {}}},
        {"jsonrpc": "2.0", "method": "exit"},
    ])
    reply = next(r for r in replies if r.get("id") == 7)
    assert not reply["result"]  # [] normalizes to falsy


# --- T8 (I1/I5 drift + proof): the registry IS the derived safe set ----------

def test_t8_registry_keys_equal_derived_safe_set():
    derived = _derive_safe_operators()
    assert set(LSP_QUICKFIX_PLANS) == derived, (
        "LSP_QUICKFIX_PLANS drifted from TIDY ∩ Tier-0 ∩ in-memory-capable ∩ "
        "sibling-insensitive: "
        f"registry-only={set(LSP_QUICKFIX_PLANS) - derived}, "
        f"derived-only={derived - set(LSP_QUICKFIX_PLANS)}"
    )


def test_t8_every_registered_operator_is_tier0():
    for operator in LSP_QUICKFIX_PLANS:
        assert tier_for_operator(operator) == 0, f"{operator} is not Tier-0"


def test_t8_every_registered_plan_fn_fires_on_its_fixture():
    # I4 floor: each offered transform actually produces a valid, re-parseable
    # plan from a representative buffer via plan_from_source (no dead entry).
    import ast

    for operator, (title, plan_fn) in LSP_QUICKFIX_PLANS.items():
        assert title and title.startswith("Apex:")
        assert operator in TRIGGER, f"no firing fixture for {operator}"
        plan = plan_from_source(plan_fn, "m.py", TRIGGER[operator])
        assert plan.ok, f"{operator} did not fire on its fixture"
        new = plan.new_contents["m.py"]
        ast.parse(new)  # the rewritten module must re-parse


def test_t8_every_registered_plan_fn_is_sibling_insensitive():
    # The moat-critical filter, proven per-member: adding a sibling module never
    # changes the plan (so a lone buffer is a sound basis for the edit).
    for name in _tidy_tier0_objectives():
        operator = _operator_of(name)
        if operator not in LSP_QUICKFIX_PLANS:
            continue
        assert _sibling_insensitive(name, _load_plan_fn(name)), (
            f"{operator} consults sibling modules — unsafe as a lone-buffer quick-fix"
        )


# --- Exclusion proofs: each excluded TIDY op genuinely fails a safe property --

def test_excluded_cross_module_ops_are_not_offered():
    # Proven cross-module (work-discovery / eligibility / call-site rewrite).
    for op in ["dedup_extract", "dedup_parameterized", "dedup_total_return",
               "drop_param", "inline", "extract", "promote_staticmethod"]:
        assert op not in LSP_QUICKFIX_PLANS


def test_excluded_scan_based_ops_are_not_two_arg_callable():
    # dedup / dead-params / inline-helpers / shrink-functions need a precomputed
    # target (block / func_name / span) — NOT callable as plan_fn(root, rel).
    for name in ["dedup", "dead-params", "inline-helpers", "shrink-functions"]:
        if name in _PLAN_FN:
            assert not _is_two_arg_callable(_load_plan_fn(name)), name
        assert _operator_of(name) not in LSP_QUICKFIX_PLANS


def test_excluded_promote_staticmethod_consults_whole_project():
    # Its plan module walks every module (_build_index / _py_files) to decide a
    # method is safe to promote — blind on a lone buffer.
    import app.execution.promote_staticmethods as mod

    src = inspect.getsource(mod)
    assert "_build_index" in src or "_py_files" in src
    assert "promote_staticmethod" not in LSP_QUICKFIX_PLANS


def test_excluded_disk_read_ops_do_not_honor_source_override():
    # Behaviour-preserving + sibling-insensitive, but they read the file straight
    # off disk (bypass source_override) so plan_from_source can't drive them — a
    # lone buffer would silently no-op (or read a stale file). Excluded for
    # honesty (I4), proven by the broken-buffer probe seeing no parse error.
    for name in ["extract-constant", "fstring-convert", "percent-to-fstring",
                 "remove-dead-code", "sort-imports", "dedup-dunder-all",
                 "merge-duplicate-imports", "modernize-typing", "sort-dunder-all"]:
        fn = _load_plan_fn(name)
        assert not _honors_source_override(fn), f"{name} unexpectedly buffer-readable"
        assert _operator_of(name) not in LSP_QUICKFIX_PLANS


def test_modernize_has_no_single_module_plan_and_is_excluded():
    # `modernize` is a fan-out meta-objective (no single plan_modernize(root, rel)),
    # so it cannot be a single quick-fix; its constituent idioms ARE separate
    # registry entries.
    assert "modernize" not in _PLAN_FN
    assert _operator_of("modernize") not in LSP_QUICKFIX_PLANS


def test_partition_is_exhaustive():
    # Every TIDY+Tier-0 objective is either offered or provably excluded — no
    # silent gaps. (Safe ∪ not-2-arg ∪ not-honoring ∪ not-sibling-insensitive.)
    for name in _tidy_tier0_objectives():
        operator = _operator_of(name)
        if operator in LSP_QUICKFIX_PLANS:
            continue
        no_plan = name not in _PLAN_FN
        excluded = no_plan or (
            not _is_two_arg_callable(_load_plan_fn(name))
            or not _honors_source_override(_load_plan_fn(name))
            or not _sibling_insensitive(name, _load_plan_fn(name))
        )
        assert excluded, f"{name} is neither offered nor provably excluded"
