"""Mutation-hardening tests for app/engine/detectors.py and
app/engine/health_score.py.

Each test pins an exact behavior so a single-token mutation (a flipped
comparison/boundary/boolean, a swapped constant, or a ``return <expr>`` turned
into ``return None``) in the source breaks at least one assertion here. Pure,
deterministic, stdlib-only inputs — no timestamps, wall-clock, or set ordering
is asserted on.
"""

from __future__ import annotations

from pathlib import Path

from app.engine import detectors as D
from app.engine.detectors import (
    Issue,
    detect,
    has_base_exception,
    has_collection_literal,
    has_fixable_raise_without_from,
    has_fstring_no_placeholder,
    has_identity_literal,
    has_mutable_default,
    has_negated_comparison,
    has_network_call_without_timeout,
    has_none_comparison,
    has_open_without_encoding,
    has_silent_broad_except,
    has_unreachable_code,
    security_label,
    security_labels,
)
from app.engine.health_score import (
    HealthScore,
    _letter,
    grade,
    load_grade_snapshot,
    render_grade_diff_markdown,
    render_grade_markdown,
    save_grade_snapshot,
)

# Imported module-qualified (not by name) so pytest does not collect the
# detector helper ``test_has_substantive_assertions`` as a test itself.
substantive_assertions = D.test_has_substantive_assertions


# --------------------------------------------------------------------------
# detectors.py — _suppressed (nosec / noqa directive semantics + returns)
# --------------------------------------------------------------------------

def test_suppress_nosec_silences_security_not_other_categories():
    # nosec on an eval() line removes the security finding entirely.
    assert security_label("x = eval(data)  # nosec") is None
    # but nosec must NOT silence a non-security (style) finding on the line.
    assert has_none_comparison("if a == None:  # nosec\n    pass\n") is True


def test_suppress_bare_noqa_silences_everything_on_the_line():
    # A bare noqa with no codes disables ALL findings on that line.
    assert has_none_comparison("if a == None:  # noqa\n    pass\n") is False


def test_suppress_noqa_without_match_keeps_finding():
    # noqa naming an unrelated code leaves a style finding in place.
    assert has_none_comparison("if a == None:  # noqa: E501\n    pass\n") is True


def test_suppress_security_needs_nosec_not_noqa_s_code():
    # FIELD-FIX P1c (footgun closed): a coded `noqa: S###` is the dev's ruff/Bandit
    # lint code, NOT an Apex security opt-out — it no longer zeroes a security
    # finding (silently telling a student their live eval() is secure).
    assert security_label("eval(x)  # noqa: S307") == "eval"
    assert security_label("eval(x)  # noqa: S5") == "eval"
    # ...the EXPLICIT Apex/security opt-out (# nosec) DOES suppress (the chosen
    # convention — pins the `directive == 'nosec'` branch).
    assert security_label("eval(x)  # nosec") is None
    # A non-S, non-nosec code on a security finding never suppressed it.
    assert security_label("eval(x)  # noqa: E501") == "eval"
    # A bare 'S' with no digit was never an S-code either (still surfaced).
    assert security_label("eval(x)  # noqa: S") == "eval"


def test_suppress_fixkind_noqa_code_maps_bare_except():
    src = "try:\n    pass\nexcept:  # noqa: E722\n    pass\n"
    # E722 maps to the bare-except fix_kind, so that security finding is gone.
    labels = {i.fix_kind for i in detect(src) if i.category == "security"}
    assert "bare except" not in labels


def test_suppress_identity_literal_via_f632_and_message():
    # F632 only suppresses when the message is the identity-literal one.
    assert has_identity_literal("if x is 5:  # noqa: F632\n    pass\n") is False
    # F632 on an unrelated finding leaves it alone.
    assert has_none_comparison("if a == None:  # noqa: F632\n    pass\n") is True


def test_suppress_no_comment_returns_false_finding_kept():
    # No suppression comment at all: the finding survives (kills `return False`
    # at the top of _suppressed flipping to True).
    assert has_none_comparison("if a == None:\n    pass\n") is True


def test_suppress_applies_on_first_line():
    # A finding on line 1 must still be suppression-checked: kills the lower-bound
    # `1 <= i.line` constant flip (1 -> 2) that would skip line-1 suppression.
    assert has_none_comparison("if a == None:  # noqa\n    pass\n") is False
    # And the finding on line 1 with no suppression is kept.
    assert has_none_comparison("if a == None:\n    pass\n") is True


# --------------------------------------------------------------------------
# detectors.py — _has_usedforsecurity_false
# --------------------------------------------------------------------------

def test_weak_hash_flagged_without_usedforsecurity_false():
    assert security_label("import hashlib\nhashlib.md5(b'x')") == "weak-hash"


def test_weak_hash_suppressed_with_usedforsecurity_false():
    assert security_label(
        "import hashlib\nhashlib.md5(b'x', usedforsecurity=False)") is None


def test_weak_hash_usedforsecurity_true_still_flagged():
    # usedforsecurity=True is NOT False, so the finding stays.
    assert security_label(
        "import hashlib\nhashlib.md5(b'x', usedforsecurity=True)") == "weak-hash"


# --------------------------------------------------------------------------
# detectors.py — Issue.auto_fixable
# --------------------------------------------------------------------------

def test_issue_auto_fixable_true_only_with_fix_kind():
    assert Issue(1, "security", "high", "m", "eval").auto_fixable is True
    assert Issue(1, "bug", "high", "m", "").auto_fixable is False


def test_issue_is_frozen_dataclass():
    # The Issue dataclass is declared frozen=True; mutating a field must raise.
    import dataclasses
    iss = Issue(1, "security", "high", "m", "eval")
    try:
        iss.line = 2  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:  # pragma: no cover - only reached if frozen=True is mutated away
        raise AssertionError("Issue must be frozen")


# --------------------------------------------------------------------------
# detectors.py — detect() syntax error path (exc.lineno or 1)
# --------------------------------------------------------------------------

def test_detect_syntax_error_reports_lineno_from_exception():
    # Error is on line 3; the finding must carry that line (kills `or 1` if the
    # real lineno were dropped, and pins the high-severity bug shape).
    out = detect("a = 1\nb = 2\ndef (:\n")
    assert len(out) == 1
    assert out[0].line == 3
    assert out[0].category == "bug" and out[0].severity == "high"
    assert out[0].fix_kind == ""


# --------------------------------------------------------------------------
# detectors.py — _detect_call_name (eval/exec/open/collection literal)
# --------------------------------------------------------------------------

def test_eval_and_exec_distinct_findings():
    assert security_label("eval(x)") == "eval"
    # exec is a security finding but with no fix_kind, so security_labels (which
    # filters on fix_kind) excludes it while security_label still reports nothing
    # better — exec maps to "" so no label.
    labels = {(i.category, i.message) for i in detect("exec(x)")}
    assert ("security", "exec() — code injection risk") in labels


def test_open_without_encoding_flagged_text_mode():
    assert has_open_without_encoding("open('f.txt')") is True
    assert has_open_without_encoding("open('f.txt', encoding='utf-8')") is False


def test_collection_literal_only_for_empty_constructor():
    assert has_collection_literal("d = dict()") is True
    assert has_collection_literal("d = dict(a=1)") is False
    assert has_collection_literal("d = list()") is True


# --------------------------------------------------------------------------
# detectors.py — _CALL_ATTR_RULES (first-match ordering, each rule)
# --------------------------------------------------------------------------

def test_call_attr_rules_each_label():
    assert security_label("import os\nos.system('x')") == "os.system"
    assert security_label("import pickle\npickle.loads(b)") == "pickle"
    assert security_label("import yaml\nyaml.load(s)") == "yaml"
    assert security_label("import tempfile\ntempfile.mktemp()") == "tempfile"


def test_call_attr_rules_require_both_owner_and_attr():
    # Each rule is owner==X AND attr==Y. The same owner with a different attr,
    # or the same attr on a different owner, must NOT match (kills the
    # per-rule `and` -> `or` flips).
    assert security_label("import os\nos.path('x')") is None        # os, wrong attr
    assert security_label("import socket\nsocket.system('x')") is None  # wrong owner
    assert security_label("import pickle\npickle.dumps(b)") is None  # pickle, wrong attr
    assert security_label("import other\nother.loads(b)") is None    # wrong owner
    assert security_label("import yaml\nyaml.safe_load(s)") is None  # yaml, safe attr
    assert security_label("import tempfile\ntempfile.mkstemp()") is None  # safe attr


def test_sql_fstring_flagged_only_with_joinedstr():
    assert security_label("cur.execute(f'select {x}')") == "sql"
    # A plain string (no f) is not flagged.
    assert security_label("cur.execute('select 1')") is None


def test_shell_true_flagged_only_when_true():
    msg = {i.message for i in detect("subprocess.run(c, shell=True)")}
    assert "subprocess with shell=True — command injection risk" in msg
    assert "subprocess with shell=True — command injection risk" not in {
        i.message for i in detect("subprocess.run(c, shell=False)")}


# --------------------------------------------------------------------------
# detectors.py — except handlers (bare / BaseException / silent / raise-from)
# --------------------------------------------------------------------------

def test_bare_except_finding():
    src = "try:\n    pass\nexcept:\n    x = 1\n"
    assert any(i.fix_kind == "bare except" for i in detect(src))


def test_base_exception_flagged_unless_reraised():
    swallow = "try:\n    pass\nexcept BaseException:\n    x = 1\n"
    assert has_base_exception(swallow) is True
    reraise = "try:\n    pass\nexcept BaseException:\n    raise\n"
    assert has_base_exception(reraise) is False


def test_silent_swallow_pass_only_body():
    src = "try:\n    pass\nexcept ValueError:\n    pass\n"
    assert any("silently swallowed" in i.message for i in detect(src))


def test_silent_broad_except_covers_ellipsis_body():
    src = "try:\n    pass\nexcept Exception:\n    ...\n"
    assert has_silent_broad_except(src) is True
    # A narrow type silent body is intentionally NOT a broad-silent finding.
    assert has_silent_broad_except("try:\n    pass\nexcept KeyError:\n    ...\n") is False


def test_raise_without_from_autofixable_only_when_bound():
    bound = "try:\n    pass\nexcept ValueError as err:\n    raise KeyError()\n"
    assert has_fixable_raise_without_from(bound) is True
    unbound = "try:\n    pass\nexcept ValueError:\n    raise KeyError()\n"
    # Still a finding, but not auto-fixable (fix_kind == "").
    assert has_fixable_raise_without_from(unbound) is False
    assert any("without `from`" in i.message for i in detect(unbound))


# --------------------------------------------------------------------------
# detectors.py — try (escapes finally / unreachable handlers)
# --------------------------------------------------------------------------

def test_return_in_finally_flagged():
    src = "try:\n    pass\nfinally:\n    return 1\n"
    assert any("finally" in i.message for i in detect(src))


def test_bare_break_in_finally_flagged_but_break_in_loop_is_not():
    # A bare break directly in finally escapes the loop's control flow.
    bare = "while x:\n    try:\n        pass\n    finally:\n        break\n"
    assert any("finally" in i.message for i in detect(bare))
    # A break inside a loop nested *within* the finally is fine (loop_depth>0):
    # kills the `loop_depth + 1` arithmetic/number flips and the `== 0` check.
    nested = ("try:\n    pass\nfinally:\n    for i in range(3):\n"
              "        break\n")
    assert not any("finally" in i.message for i in detect(nested))


def test_unreachable_handler_after_broad():
    src = "try:\n    pass\nexcept Exception:\n    a = 1\nexcept ValueError:\n    b = 2\n"
    assert any("unreachable except" in i.message for i in detect(src))


def test_base_tier_handler_after_exception_is_reachable():
    # KeyboardInterrupt is in the base tier, so it is NOT shadowed by Exception.
    src = ("try:\n    pass\nexcept Exception:\n    a = 1\n"
           "except KeyboardInterrupt:\n    b = 2\n")
    assert not any("unreachable except" in i.message for i in detect(src))


def test_exc_names_empty_list_keeps_handler_scan_working():
    # A bare except among multiple handlers exercises _exc_names(None) -> [].
    # A bare except does not establish a broad shadow above the typed handler,
    # so the ValueError handler below it is NOT flagged unreachable.
    src = ("try:\n    pass\nexcept:\n    a = 1\nexcept ValueError:\n    b = 2\n")
    out = detect(src)
    assert not any("unreachable except" in i.message for i in out)
    # the bare except is still its own security finding.
    assert any(i.fix_kind == "bare except" for i in out)


def test_unreachable_handler_with_bare_except_below_broad():
    # except Exception then a bare except: _exc_names(None) -> [] path again, and
    # the bare except below a broad handler IS reachable (catches base-tier too).
    src = ("try:\n    pass\nexcept Exception:\n    a = 1\nexcept:\n    b = 2\n")
    out = detect(src)
    # bare except after Exception is NOT reported unreachable (names empty).
    assert not any("unreachable except" in i.message for i in out)


# --------------------------------------------------------------------------
# detectors.py — assert on tuple
# --------------------------------------------------------------------------

def test_assert_on_nonempty_tuple_flagged_empty_tuple_not():
    assert any("assert on a tuple" in i.message for i in detect("assert (a, b)\n"))
    # An empty tuple has no elts, so it must NOT fire.
    assert not any("assert on a tuple" in i.message for i in detect("assert ()\n"))


# --------------------------------------------------------------------------
# detectors.py — negated comparison
# --------------------------------------------------------------------------

def test_negated_in_and_is_flagged():
    assert has_negated_comparison("if not x in y:\n    pass\n") is True
    assert has_negated_comparison("if not x is y:\n    pass\n") is True
    # `not (x < y)` is a different operator, untouched.
    assert has_negated_comparison("if not x < y:\n    pass\n") is False


def test_negated_comparison_messages_distinguish_in_vs_is():
    in_msg = {i.message for i in detect("z = not x in y\n")}
    assert any("not in" in m for m in in_msg)
    is_msg = {i.message for i in detect("z = not x is y\n")}
    assert any("is not" in m for m in is_msg)


# --------------------------------------------------------------------------
# detectors.py — compare helpers (none/bool/type/identity/self)
# --------------------------------------------------------------------------

def test_none_comparison_only_with_eq_ops():
    assert has_none_comparison("if a == None:\n    pass\n") is True
    # `is None` is the correct form; not flagged as a none-comparison.
    assert has_none_comparison("if a is None:\n    pass\n") is False


def test_bool_literal_comparison_flagged():
    assert any("True/False" in i.message for i in detect("if a == True:\n    pass\n"))


def test_type_call_comparison_flagged():
    assert any("isinstance" in i.message
               for i in detect("if type(a) == type(b):\n    pass\n"))


def test_identity_literal_flagged_for_int_not_for_none_or_bool():
    assert has_identity_literal("if x is 5:\n    pass\n") is True
    assert has_identity_literal("if x is None:\n    pass\n") is False
    assert has_identity_literal("if x is True:\n    pass\n") is False


def test_self_comparison_flagged_for_non_eq_ops_only():
    assert any("comparison with itself" in i.message
               for i in detect("if a.b < a.b:\n    pass\n"))
    # x == x / x != x are idiomatic NaN checks — never flagged as self-compare.
    assert not any("comparison with itself" in i.message
                   for i in detect("if a.b == a.b:\n    pass\n"))


def test_self_comparison_not_flagged_for_call_operands():
    # _same_ref restricts to Name/Attribute; a call on both sides may differ, so
    # f() < f() is NOT a self-comparison (kills the two-sided isinstance `and`).
    assert not any("comparison with itself" in i.message
                   for i in detect("if f() < f():\n    pass\n"))


def test_self_comparison_distinct_names_not_flagged():
    # a < b are different references — not a self-comparison.
    assert not any("comparison with itself" in i.message
                   for i in detect("if a < b:\n    pass\n"))


def test_self_comparison_uses_adjacent_operand_in_chain():
    # In a chained compare the self-test compares operand i with operand i+1.
    # `x < x < y`: the FIRST pair (x, x) is identical -> flagged. If the index
    # were i-1 instead of i+1, the first op would compare x with the LAST
    # operand y (different) and miss it. Kills the `i + 1` arithmetic flip.
    assert any("comparison with itself" in i.message
               for i in detect("if x < x < y:\n    pass\n"))
    # `y < x < x`: the SECOND pair (x, x) is identical -> flagged.
    assert any("comparison with itself" in i.message
               for i in detect("if y < x < x:\n    pass\n"))


# --------------------------------------------------------------------------
# detectors.py — frozen dataclass mutation + mutable class attribute
# --------------------------------------------------------------------------

def test_frozen_dataclass_self_assignment_flagged():
    src = (
        "from dataclasses import dataclass\n"
        "@dataclass(frozen=True)\n"
        "class C:\n"
        "    x: int\n"
        "    def f(self):\n"
        "        self.x = 1\n"
    )
    assert any("frozen dataclass" in i.message for i in detect(src))


def test_non_frozen_dataclass_self_assignment_not_flagged():
    src = (
        "from dataclasses import dataclass\n"
        "@dataclass(frozen=False)\n"
        "class C:\n"
        "    x: int\n"
        "    def f(self):\n"
        "        self.x = 1\n"
    )
    assert not any("frozen dataclass" in i.message for i in detect(src))


def test_non_dataclass_decorator_with_frozen_kwarg_not_flagged():
    # A non-dataclass decorator that happens to take frozen=True must NOT be
    # treated as a frozen dataclass (kills the `name == "dataclass" and ...`
    # boolean flip to `or`).
    src = (
        "@register(frozen=True)\n"
        "class C:\n"
        "    x: int\n"
        "    def f(self):\n"
        "        self.x = 1\n"
    )
    assert not any("frozen dataclass" in i.message for i in detect(src))


def test_dataclass_without_frozen_kwarg_not_flagged():
    # @dataclass() with no frozen= kwarg is mutable; self-assignment is fine.
    src = (
        "from dataclasses import dataclass\n"
        "@dataclass()\n"
        "class C:\n"
        "    x: int\n"
        "    def f(self):\n"
        "        self.x = 1\n"
    )
    assert not any("frozen dataclass" in i.message for i in detect(src))


def test_mutable_class_attribute_shared_state_flagged():
    src = (
        "class C:\n"
        "    items = []\n"
        "    def add(self, v):\n"
        "        self.items.append(v)\n"
    )
    assert any("mutable class attribute" in i.message for i in detect(src))


def test_annotated_mutable_class_attribute_flagged():
    # An annotated class attribute (items: list = []) that is mutated in place is
    # the same shared-state bug — exercises the AnnAssign branch.
    src = (
        "class C:\n"
        "    items: list = []\n"
        "    def add(self, v):\n"
        "        self.items.append(v)\n"
    )
    assert any("mutable class attribute" in i.message for i in detect(src))


def test_annotated_non_mutable_value_not_flagged():
    # items: list = compute() — annotated but the value is NOT a mutable literal,
    # so it must not be treated as a class-level mutable (kills the AnnAssign
    # `isinstance(target, Name) and _is_mutable_constructor(value)` -> `or`).
    src = (
        "class C:\n"
        "    items: list = compute()\n"
        "    def add(self, v):\n"
        "        self.items.append(v)\n"
    )
    assert not any("mutable class attribute" in i.message for i in detect(src))


def test_mutable_class_attribute_only_read_not_flagged():
    # A class-level mutable that is only READ (non-mutating method) is not a
    # shared-state bug — kills the `attr in _MUTATING_METHODS` guard going away.
    src = (
        "class C:\n"
        "    items = []\n"
        "    def count(self):\n"
        "        return self.items.index(1)\n"
    )
    assert not any("mutable class attribute" in i.message for i in detect(src))


def test_mutable_class_attribute_reassigned_in_init_not_flagged():
    src = (
        "class C:\n"
        "    items = []\n"
        "    def __init__(self):\n"
        "        self.items = []\n"
        "    def add(self, v):\n"
        "        self.items.append(v)\n"
    )
    assert not any("mutable class attribute" in i.message for i in detect(src))


# --------------------------------------------------------------------------
# detectors.py — f-string without placeholder
# --------------------------------------------------------------------------

def test_fstring_without_placeholder_flagged_with_placeholder_not():
    assert has_fstring_no_placeholder("x = f'plain'\n") is True
    assert has_fstring_no_placeholder("x = f'{val}'\n") is False


# --------------------------------------------------------------------------
# detectors.py — function (mutable default + missing docstring)
# --------------------------------------------------------------------------

def test_mutable_default_flagged_for_list_and_call_form():
    assert has_mutable_default("def f(a=[]):\n    return a\n") is True
    assert has_mutable_default("def f(a=list()):\n    return a\n") is True
    assert has_mutable_default("def f(a=()):\n    return a\n") is False


def test_public_function_missing_docstring_flagged_private_not():
    pub = {i.fix_kind for i in detect("def f():\n    return 1\n")}
    assert "docstring" in pub
    priv = {i.fix_kind for i in detect("def _f():\n    return 1\n")}
    assert "docstring" not in priv


def test_documented_public_function_not_flagged():
    docd = {i.fix_kind for i in detect('def f():\n    """Doc."""\n    return 1\n')}
    assert "docstring" not in docd


# --------------------------------------------------------------------------
# detectors.py — hardcoded secret (length boundary 6, placeholders)
# --------------------------------------------------------------------------

def test_hardcoded_secret_flagged_for_long_value():
    assert any("hardcoded secret" in i.message
               for i in detect("password = 'abcdef'\n"))


def test_hardcoded_secret_length_boundary_five_chars_not_flagged():
    # len 5 < 6 is below the threshold; len 6 is at/above it. Kills both the
    # boundary flip (< 6 -> <= 6) and the constant flip (6 -> 7).
    assert not any("hardcoded secret" in i.message
                   for i in detect("password = 'abcde'\n"))
    assert any("hardcoded secret" in i.message
               for i in detect("password = 'abcdef'\n"))


def test_hardcoded_secret_placeholder_not_flagged():
    assert not any("hardcoded secret" in i.message
                   for i in detect("password = 'changeme'\n"))


def test_non_secret_name_long_string_not_flagged():
    assert not any("hardcoded secret" in i.message
                   for i in detect("greeting = 'hello world'\n"))


# --------------------------------------------------------------------------
# detectors.py — network call without timeout
# --------------------------------------------------------------------------

def test_network_call_without_timeout_flagged():
    assert has_network_call_without_timeout("import requests\nrequests.get(u)\n") is True
    assert has_network_call_without_timeout(
        "import requests\nrequests.get(u, timeout=5)\n") is False


def test_urlopen_bare_and_dotted_flagged():
    assert has_network_call_without_timeout("urlopen(u)\n") is True
    assert has_network_call_without_timeout(
        "import urllib\nurllib.request.urlopen(u)\n") is True


def test_network_call_with_kwargs_not_flagged():
    # **kwargs could carry timeout, so it is conservatively not flagged.
    assert has_network_call_without_timeout(
        "import requests\nrequests.get(u, **opts)\n") is False


def test_non_requests_owner_not_flagged():
    # session.get(...) is ambiguous (owner not requests/httpx) — not flagged.
    assert has_network_call_without_timeout("session.get(u)\n") is False


# --------------------------------------------------------------------------
# detectors.py — unreachable code
# --------------------------------------------------------------------------

def test_unreachable_code_after_return_flagged():
    src = "def f():\n    return 1\n    x = 2\n"
    assert has_unreachable_code(src) is True


def test_no_unreachable_when_terminal_is_last():
    src = "def f():\n    x = 1\n    return x\n"
    assert has_unreachable_code(src) is False


# --------------------------------------------------------------------------
# detectors.py — security_label ordering + syntax fallback
# --------------------------------------------------------------------------

def test_security_label_orders_eval_above_bare_except():
    src = "eval(x)\ntry:\n    pass\nexcept:\n    a = 1\n"
    assert security_label(src) == "eval"


def test_security_labels_returns_all_in_severity_order():
    src = (
        "import os, pickle\n"
        "eval(x)\n"
        "os.system(x)\n"
        "pickle.loads(b)\n"
    )
    labels = security_labels(src)
    # eval before os.system before pickle (descending severity order).
    assert labels.index("eval") < labels.index("os.system") < labels.index("pickle")


def test_security_label_syntax_fallback_substring():
    # Unparseable source falls back to substring scan.
    assert security_label("def (:\n eval(") == "eval"
    assert security_labels("def (:\n eval(") == ["eval"]


def test_security_label_syntax_fallback_none_when_no_needle():
    assert security_label("def (:\n  pass") is None
    assert security_labels("def (:\n  pass") == []


# --------------------------------------------------------------------------
# detectors.py — test_has_substantive_assertions
# --------------------------------------------------------------------------

def test_substantive_assertions_value_compare_is_substantive():
    assert substantive_assertions("def test_x():\n    assert f() == 3\n") is True


def test_substantive_assertions_bare_name_is_shallow():
    assert substantive_assertions("def test_x():\n    assert mod\n") is False


def test_substantive_assertions_isinstance_is_shallow():
    assert substantive_assertions(
        "def test_x():\n    assert isinstance(a, int)\n") is False


def test_substantive_assertions_is_none_is_shallow():
    assert substantive_assertions(
        "def test_x():\n    assert a is None\n") is False


def test_substantive_assertions_syntax_error_returns_false():
    assert substantive_assertions("def (:\n") is False


def test_substantive_assertions_negated_isinstance_is_shallow():
    # not isinstance(...) recurses into the operand, still shallow.
    assert substantive_assertions(
        "def test_x():\n    assert not isinstance(a, int)\n") is False


def test_substantive_assertions_plain_call_is_substantive():
    assert substantive_assertions(
        "def test_x():\n    assert validate(a)\n") is True


# --------------------------------------------------------------------------
# health_score.py — _letter cutoffs (every boundary)
# --------------------------------------------------------------------------

def test_letter_exact_cutoffs():
    assert _letter(97) == "A+"
    assert _letter(96) == "A"
    assert _letter(93) == "A"
    assert _letter(92) == "A-"
    assert _letter(90) == "A-"
    assert _letter(89) == "B+"
    assert _letter(87) == "B+"
    assert _letter(83) == "B"
    assert _letter(80) == "B-"
    assert _letter(77) == "C+"
    assert _letter(73) == "C"
    assert _letter(70) == "C-"
    assert _letter(67) == "D+"
    assert _letter(63) == "D"
    assert _letter(60) == "D-"
    assert _letter(59) == "F"
    assert _letter(0) == "F"


# --------------------------------------------------------------------------
# health_score.py — _is_fixture_path
# --------------------------------------------------------------------------

def test_is_fixture_path_detects_test_and_fixture_dirs():
    assert D and True  # keep import of D referenced
    from app.engine.health_score import _is_fixture_path
    assert _is_fixture_path("tests/test_x.py") is True
    assert _is_fixture_path("app/tests/test_x.py") is True
    assert _is_fixture_path("fixtures/data.py") is True
    assert _is_fixture_path("examples/demo.py") is True
    assert _is_fixture_path("app/engine/foo.py") is False
    # filename starting with test_ counts even outside a tests dir.
    assert _is_fixture_path("app/test_helper.py") is True


# --------------------------------------------------------------------------
# health_score.py — Component / HealthScore to_dict
# --------------------------------------------------------------------------

def test_component_and_healthscore_to_dict_shapes():
    from app.engine.health_score import Component
    c = Component("Security", 5, "1 finding", ["a.py"])
    d = c.to_dict()
    assert d == {"name": "Security", "points_lost": 5, "detail": "1 finding",
                 "top_files": ["a.py"]}
    h = HealthScore(score=88, letter="B+", components=[c], fixes=["fix it"])
    hd = h.to_dict()
    assert hd["score"] == 88 and hd["letter"] == "B+"
    assert hd["fixes"] == ["fix it"]
    assert hd["components"] == [d]


# --------------------------------------------------------------------------
# health_score.py — grade(): security penalty (weight + cap)
# --------------------------------------------------------------------------

def _write_project(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp_path


def test_security_finding_costs_points(tmp_path: Path):
    _write_project(tmp_path, {
        "app/bad.py": "import os\ndef run(c):\n    os.system(c)\n",
        "tests/test_bad.py": "from app.bad import run\ndef test_run():\n    assert run is not None\n",
    })
    h = grade(str(tmp_path))
    lost = {c.name: c.points_lost for c in h.components}
    assert lost["Security"] > 0


def test_security_penalty_capped_at_30(tmp_path: Path):
    body = "import os\n" + "\n".join(
        f"def f{i}(c):\n    os.system(c)\n    eval(c)\n" for i in range(40))
    _write_project(tmp_path, {
        "app/bad.py": body,
        "tests/test_bad.py": "import app.bad\ndef test_x():\n    assert 1 == 1\n",
    })
    h = grade(str(tmp_path))
    sec = next(c for c in h.components if c.name == "Security")
    assert sec.points_lost == 30


# --------------------------------------------------------------------------
# health_score.py — correctness bucket (5 pts/bug, cap 20)
# --------------------------------------------------------------------------

def test_correctness_bug_costs_five_points(tmp_path: Path):
    # one return-in-finally is a high-severity, no-fix bug.
    _write_project(tmp_path, {
        "app/bug.py": "def f():\n    try:\n        pass\n    finally:\n        return 1\n",
        "tests/test_bug.py": "import app.bug\ndef test_x():\n    assert 1 == 1\n",
    })
    h = grade(str(tmp_path))
    corr = next(c for c in h.components if c.name == "Correctness")
    assert corr.points_lost == 5


# --------------------------------------------------------------------------
# health_score.py — testing bucket (untested vs shallow half-credit)
# --------------------------------------------------------------------------

def test_untested_module_costs_testing_points(tmp_path: Path):
    _write_project(tmp_path, {
        "app/lonely.py": 'def f():\n    """D."""\n    return 1\n',
    })
    h = grade(str(tmp_path))
    testing = next(c for c in h.components if c.name == "Testing")
    assert testing.points_lost > 0


# --------------------------------------------------------------------------
# health_score.py — clean project loses nothing
# --------------------------------------------------------------------------

def test_clean_project_no_penalty(tmp_path: Path):
    _write_project(tmp_path, {
        "app/calc.py": 'def add(a, b):\n    """Add."""\n    return a + b\n',
        "tests/test_calc.py": "from app.calc import add\ndef test_add():\n    assert add(1, 2) == 3\n",
    })
    h = grade(str(tmp_path))
    assert h.score >= 90
    assert all(c.points_lost == 0 for c in h.components)


# --------------------------------------------------------------------------
# health_score.py — snapshot save/load round trip
# --------------------------------------------------------------------------

def test_save_and_load_snapshot_round_trip(tmp_path: Path):
    from app.engine.health_score import Component
    h = HealthScore(score=75, letter="C", components=[Component("Security", 3, "d")])
    save_grade_snapshot(str(tmp_path), h)
    loaded = load_grade_snapshot(str(tmp_path))
    assert loaded is not None
    assert loaded["score"] == 75
    assert loaded["letter"] == "C"


def test_load_snapshot_none_when_missing(tmp_path: Path):
    assert load_grade_snapshot(str(tmp_path)) is None


def test_load_snapshot_none_when_no_score_key(tmp_path: Path):
    import json
    p = tmp_path / ".apex"
    p.mkdir()
    (p / "grade-snapshot.json").write_text(json.dumps({"letter": "B"}), encoding="utf-8")
    assert load_grade_snapshot(str(tmp_path)) is None


# --------------------------------------------------------------------------
# health_score.py — render_grade_markdown
# --------------------------------------------------------------------------

def test_render_markdown_clean_bill_when_no_fixes():
    h = HealthScore(score=100, letter="A+", components=[], fixes=[])
    md = render_grade_markdown(h)
    assert "Clean bill of health" in md
    assert "100/100" in md


def test_render_markdown_lists_fixes_and_offenders():
    from app.engine.health_score import Component
    h = HealthScore(
        score=70, letter="C",
        components=[Component("Security", 10, "2 findings", ["app/a.py"])],
        fixes=["run apex maintain"],
    )
    md = render_grade_markdown(h)
    assert "Cheapest ways to climb" in md
    assert "run apex maintain" in md
    assert "Top offenders" in md
    assert "app/a.py" in md


def test_render_markdown_scope_line_present_only_when_set():
    h = HealthScore(score=90, letter="A-", components=[], fixes=[], scope_line="X")
    assert "_X_" in render_grade_markdown(h)
    h2 = HealthScore(score=90, letter="A-", components=[], fixes=[], scope_line="")
    assert "__" not in render_grade_markdown(h2)


# --------------------------------------------------------------------------
# health_score.py — render_grade_diff_markdown (delta sign / arrow / icons)
# --------------------------------------------------------------------------

def _diff(old_score, new_score, comps_old=None, comps_new=None):
    old = {"date": "2020-01-01", "score": old_score, "letter": "C",
           "components": comps_old or []}
    new = HealthScore(score=new_score, letter="B", components=comps_new or [])
    return render_grade_diff_markdown(old, new)


def test_diff_improvement_uses_plus_sign_and_up_arrow():
    md = _diff(70, 80)
    assert "+10" in md and "↑" in md


def test_diff_regression_uses_down_arrow_no_plus():
    md = _diff(80, 70)
    assert "-10" in md and "↓" in md
    assert "+-10" not in md


def test_diff_no_change_uses_neutral_arrow():
    md = _diff(75, 75)
    assert "→" in md
    assert "↑" not in md and "↓" not in md


def test_diff_component_improvement_shows_check_icon():
    from app.engine.health_score import Component
    md = render_grade_diff_markdown(
        {"date": "d", "score": 70, "letter": "C",
         "components": [{"name": "Security", "points_lost": 10}]},
        HealthScore(score=80, letter="B",
                    components=[Component("Security", 4, "d")]),
    )
    # prev 10 - now 4 = +6 improvement -> check icon
    assert "✅" in md


def test_diff_component_regression_shows_warning_icon():
    from app.engine.health_score import Component
    md = render_grade_diff_markdown(
        {"date": "d", "score": 80, "letter": "B",
         "components": [{"name": "Security", "points_lost": 2}]},
        HealthScore(score=70, letter="C",
                    components=[Component("Security", 8, "d")]),
    )
    # prev 2 - now 8 = -6 regression -> warning icon
    assert "⚠️" in md
