"""complete-match-exhaustiveness develop objective — fill the missing arm of a
dispatch over a PROVABLY-CLOSED discriminant set (an in-module ``Enum``, a
``Literal[...]`` of simple constants, or ``bool``) with a LOUD exhaustiveness sentinel
(``raise AssertionError(f"unhandled <subj>: {<subj>!r}")``), turning a silent
fall-through into a total, loud dispatch.

SOUNDNESS is STRUCTURAL: the inserted arm executes ONLY on a discriminant value the
existing code does not handle today, so it is either dead code (the value can't occur →
behaviour-preserving) or it makes a pre-existing silent fall-through loud (an
improvement). In both cases no currently-passing test can regress — the runtime-additive
posture of enforce-enum-unique's @unique. The transform REFUSES (an honest no-op) on
every uncertainty.

Covers: the core transform LANDING (a ``match`` over an in-module enum missing a member
gains a trailing ``case _:``; an ``if``/``elif`` over a ``Literal`` / ``bool`` missing a
branch gains a trailing ``else:``; enum inferred from arm values when no annotation;
``in (...)`` membership; multiple dispatches in one module; trailing-newline
preservation; never broken Python) plus EVERY refusal — a wildcard ``case _:`` already
present, a capture ``case other:``, a trailing ``else:`` already present, an open
``str``/``int`` discriminant, a non-literal ``Literal``, an enum imported/aliased from
another module, an unmodelled match subject, a guarded case, a side-effect-before
dispatch, a syntax error; plus idempotency and determinism; objective registration /
reachability (available, callable spec, reachable-from-facet, the facet-map<->registry
1:1 parity invariant, substring-safety, the north-star manifest classing it CONCRETE
with the reverse tripwire clean, the soundness strategy present with its reverse
tripwire clean, the facet ladder carrying the phrase with the originals still leading);
the plan + END-TO-END landing (``apply_rename`` verify=True appends the sentinel and the
suite — which exercises only the HANDLED members — stays green); and the never-fake-green
capstone (a module whose discriminant set is NOT provably closed — an open ``str`` — is
REFUSED before any apply, empty plan).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.match_exhaustiveness import (
    closed_dispatches,
    complete_match_exhaustiveness,
)
from app.execution.objectives.complete_match_exhaustiveness import (
    plan_complete_match_exhaustiveness,
)

# A 3-member in-module enum whose match handles only two members: gains a trailing
# ``case _:`` sentinel naming the subject ``s``.
_ENUM_MATCH = (
    "from enum import Enum\n"
    "\n"
    "\n"
    "class State(Enum):\n"
    "    START = 1\n"
    "    RUN = 2\n"
    "    STOP = 3\n"
    "\n"
    "\n"
    "def label(s: State) -> int:\n"
    "    match s:\n"
    "        case State.START:\n"
    "            return 1\n"
    "        case State.RUN:\n"
    "            return 2\n"
)

# An if/elif over a Literal handling two of three constants: gains a trailing ``else:``.
_LITERAL_IF = (
    "from typing import Literal\n"
    "\n"
    "\n"
    "def kind(s: Literal['a', 'b', 'c']) -> int:\n"
    "    if s == 'a':\n"
    "        return 1\n"
    "    elif s == 'b':\n"
    "        return 2\n"
)

_PHRASE = "a closed-set dispatch missing an exhaustiveness arm"


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


# --- the core transform: detection ------------------------------------------

def test_closed_dispatches_detects_enum_match():
    assert closed_dispatches(_ENUM_MATCH) == ["s"]


def test_closed_dispatches_detects_literal_if():
    assert closed_dispatches(_LITERAL_IF) == ["s"]


def test_closed_dispatches_empty_on_syntax_error():
    assert closed_dispatches("def (:\n") == []


# --- the core transform: rewrite (LANDS) ------------------------------------

def test_match_over_enum_gets_wildcard_sentinel():
    out = complete_match_exhaustiveness(_ENUM_MATCH)
    assert out is not None
    compile(out, "<m>", "exec")  # never broken Python
    assert "        case _:\n" in out
    assert '            raise AssertionError(f"unhandled s: {s!r}")' in out
    # the sentinel is the LAST arm, directly after the last real case body
    assert out.rstrip().endswith('raise AssertionError(f"unhandled s: {s!r}")')


def test_if_elif_over_literal_gets_else_sentinel():
    out = complete_match_exhaustiveness(_LITERAL_IF)
    assert out is not None
    compile(out, "<m>", "exec")
    assert "    else:\n" in out
    assert '        raise AssertionError(f"unhandled s: {s!r}")' in out


def test_if_over_bool_gets_else_sentinel():
    src = "def h(flag: bool) -> int:\n    if flag is True:\n        return 1\n"
    out = complete_match_exhaustiveness(src)
    assert out is not None
    compile(out, "<m>", "exec")
    assert '        raise AssertionError(f"unhandled flag: {flag!r}")' in out


def test_enum_inferred_from_arm_values_without_annotation():
    # No annotation on ``x`` — the enum is inferred because EVERY arm value is a
    # ``State.MEMBER`` of one in-module enum, so the closed set is still provable.
    src = (
        "from enum import Enum\n\n\nclass State(Enum):\n"
        "    ON = 1\n    OFF = 2\n    IDLE = 3\n\n\n"
        "def k(x):\n    match x:\n        case State.ON:\n            return 1\n"
        "        case State.OFF:\n            return 2\n"
    )
    out = complete_match_exhaustiveness(src)
    assert out is not None
    assert "        case _:\n" in out
    assert '            raise AssertionError(f"unhandled x: {x!r}")' in out


def test_in_tuple_membership_counts_each_member():
    # ``c in (State.START, State.RUN)`` handles TWO members in one branch; STOP is
    # still missing, so a trailing else lands.
    src = (
        "from enum import Enum\n\n\nclass State(Enum):\n"
        "    START = 1\n    RUN = 2\n    STOP = 3\n\n\n"
        "def f(c: State) -> int:\n    if c in (State.START, State.RUN):\n        return 1\n"
    )
    out = complete_match_exhaustiveness(src)
    assert out is not None
    assert '        raise AssertionError(f"unhandled c: {c!r}")' in out


def test_auto_valued_enum_lands_names_enumerate():
    # ``auto()`` values are fine here — we need member NAMES, not value-distinctness.
    src = (
        "from enum import Enum, auto\n\n\nclass State(Enum):\n"
        "    A = auto()\n    B = auto()\n    C = auto()\n\n\n"
        "def f(s: State) -> int:\n    match s:\n        case State.A:\n            return 1\n"
        "        case State.B:\n            return 2\n"
    )
    out = complete_match_exhaustiveness(src)
    assert out is not None
    assert "        case _:\n" in out


def test_multiple_dispatches_all_filled():
    src = (
        "from enum import Enum\n\n\nclass State(Enum):\n"
        "    A = 1\n    B = 2\n    C = 3\n\n\n"
        "def f(s: State) -> int:\n    match s:\n        case State.A:\n            return 1\n"
        "        case State.B:\n            return 2\n\n\n"
        "def g(s: State) -> int:\n    if s == State.A:\n        return 1\n"
        "    elif s == State.C:\n        return 9\n"
    )
    out = complete_match_exhaustiveness(src)
    assert out is not None
    compile(out, "<m>", "exec")
    assert out.count("raise AssertionError") == 2


def test_preserves_trailing_newline_absence():
    out = complete_match_exhaustiveness(_ENUM_MATCH.rstrip("\n"))
    assert out is not None and not out.endswith("\n")


# --- the core transform: REFUSALS (honest no-ops, the soundness surface) ----

def test_refuses_existing_wildcard():
    src = (
        "from enum import Enum\n\n\nclass S(Enum):\n    A = 1\n    B = 2\n    C = 3\n\n\n"
        "def f(x: S) -> int:\n    match x:\n        case S.A:\n            return 1\n"
        "        case _:\n            return 0\n"
    )
    assert complete_match_exhaustiveness(src) is None  # already total


def test_refuses_capture_pattern():
    src = (
        "from enum import Enum\n\n\nclass S(Enum):\n    A = 1\n    B = 2\n    C = 3\n\n\n"
        "def f(x: S) -> int:\n    match x:\n        case S.A:\n            return 1\n"
        "        case other:\n            return other\n"
    )
    assert complete_match_exhaustiveness(src) is None  # irrefutable capture = catch-all


def test_refuses_existing_trailing_else():
    src = (
        "from enum import Enum\n\n\nclass S(Enum):\n    A = 1\n    B = 2\n    C = 3\n\n\n"
        "def f(x: S) -> int:\n    if x == S.A:\n        return 1\n"
        "    elif x == S.B:\n        return 2\n    else:\n        return 0\n"
    )
    assert complete_match_exhaustiveness(src) is None  # already total


def test_refuses_open_str_discriminant():
    src = (
        "def f(s: str) -> int:\n    match s:\n        case 'a':\n            return 1\n"
        "        case 'b':\n            return 2\n"
    )
    assert complete_match_exhaustiveness(src) is None  # str is not a closed set


def test_refuses_open_int_discriminant():
    src = "def f(n: int) -> int:\n    if n == 1:\n        return 1\n    elif n == 2:\n        return 2\n"
    assert complete_match_exhaustiveness(src) is None  # int is not a closed set


def test_refuses_non_literal_literal():
    src = (
        "from typing import Literal\n\nX = 1\n\n\ndef f(s: Literal[X, 2]) -> int:\n"
        "    match s:\n        case 2:\n            return 1\n"
    )
    assert complete_match_exhaustiveness(src) is None  # a Name element — not provable


def test_refuses_enum_imported_from_another_module():
    # ``Color`` is imported, not defined in-module, so its full member set cannot be
    # proven statically — refuse (the conservative enum_unique stance).
    src = (
        "from other import Color\n\n\ndef f(c: Color) -> int:\n    match c:\n"
        "        case Color.RED:\n            return 1\n"
        "        case Color.GREEN:\n            return 2\n"
    )
    assert complete_match_exhaustiveness(src) is None


def test_refuses_unmodelled_match_subject():
    src = (
        "from enum import Enum\n\n\nclass S(Enum):\n    A = 1\n    B = 2\n    C = 3\n\n\n"
        "def f(obj) -> int:\n    match obj.state:\n        case S.A:\n            return 1\n"
        "        case S.B:\n            return 2\n"
    )
    assert complete_match_exhaustiveness(src) is None  # subject is not a bare Name


def test_refuses_guarded_case():
    src = (
        "from enum import Enum\n\n\nclass S(Enum):\n    A = 1\n    B = 2\n    C = 3\n\n\n"
        "def f(x: S) -> int:\n    match x:\n        case S.A if x.value > 0:\n            return 1\n"
        "        case S.B:\n            return 2\n"
    )
    assert complete_match_exhaustiveness(src) is None  # a guard — coverage unprovable


def test_refuses_side_effect_before_appended_arm_is_not_a_dispatch():
    # A subject whose set is not provably closed (a bare param, no enum/Literal/bool
    # annotation and arms that don't all name one in-module enum) is refused — there is
    # no closed set to complete, so nothing is appended after the side effects.
    src = (
        "def f(x):\n    print('side effect')\n    if x == 1:\n        return 1\n"
        "    elif x == 2:\n        return 2\n"
    )
    assert complete_match_exhaustiveness(src) is None


def test_refuses_already_total_match():
    src = (
        "from enum import Enum\n\n\nclass S(Enum):\n    A = 1\n    B = 2\n\n\n"
        "def f(x: S) -> int:\n    match x:\n        case S.A:\n            return 1\n"
        "        case S.B:\n            return 2\n"
    )
    assert complete_match_exhaustiveness(src) is None  # every member already handled


def test_refuses_syntax_error():
    assert complete_match_exhaustiveness("def (:\n") is None


# --- the "dispatch must be the LAST statement in its block" soundness guard ---
# When code FOLLOWS the dispatch, the "unhandled" value is NOT a silent
# fall-through — that following code (a later guard, or the function's fall-through
# return) already reaches it, so a sentinel ``else:`` / ``case _:`` would CHANGE
# behaviour. Refuse. Only a TERMINAL dispatch (nothing after it in the block) has
# the silent fall-through the sentinel is allowed to make loud. Field bug: both
# shapes below are exactly what fired on ``app/policy/mode.py``.

def test_refuses_guard_return_before_later_handlers():
    # The ``_default_safety_policy`` shape: a standalone ``if mode == E.REPORT:
    # return ...`` guard, then SUBSEQUENT statements handle SUPERVISED / default.
    # An ``else: raise`` after the guard makes those later handlers UNREACHABLE, so
    # the dispatch (not the last statement in its block) must be refused.
    src = (
        "from enum import Enum\n\n\nclass Mode(Enum):\n"
        "    REPORT = 1\n    SUPERVISED = 2\n    AUTO = 3\n\n\n"
        "def policy(mode: Mode) -> int:\n"
        "    if mode == Mode.REPORT:\n        return 0\n"
        "    if mode == Mode.SUPERVISED:\n        return 5\n"
        "    return 20\n"
    )
    assert complete_match_exhaustiveness(src) is None  # later code reaches the value


def test_refuses_if_elif_before_fallthrough_return():
    # The ``from_env`` shape: an ``if E.SUPERVISED / elif E.AUTO`` chain that does
    # NOT return, followed by a ``return ...``. ``E.REPORT`` intentionally falls
    # through the chain to that return. An ``else: raise`` would CRASH the valid
    # unhandled member — the chain is not the last statement in its block, so refuse.
    src = (
        "from enum import Enum\n\n\nclass Mode(Enum):\n"
        "    REPORT = 1\n    SUPERVISED = 2\n    AUTO = 3\n\n\n"
        "def build(mode: Mode) -> dict:\n    flags = {}\n"
        "    if mode == Mode.SUPERVISED:\n        flags['s'] = True\n"
        "    elif mode == Mode.AUTO:\n        flags['a'] = True\n"
        "    return flags\n"
    )
    assert complete_match_exhaustiveness(src) is None  # REPORT falls through to return


def test_refuses_match_before_following_code():
    # The symmetric ``match`` case: a ``match`` missing a member, but followed by
    # more statements — the unhandled value reaches that code today, so a trailing
    # ``case _: raise`` would change behaviour. Refuse.
    src = (
        "from enum import Enum\n\n\nclass S(Enum):\n"
        "    A = 1\n    B = 2\n    C = 3\n\n\n"
        "def f(s: S) -> int:\n    seen = 0\n"
        "    match s:\n        case S.A:\n            seen = 1\n"
        "        case S.B:\n            seen = 2\n"
        "    return seen\n"
    )
    assert complete_match_exhaustiveness(src) is None  # the match is not last in block


def test_still_fires_on_terminal_if_chain_missing_arm():
    # No over-refusal: a closed ``if``/``elif`` missing a member with NOTHING after
    # it in the block IS the silent fall-through — it still gains a trailing
    # ``else:`` sentinel.
    src = (
        "from enum import Enum\n\n\nclass S(Enum):\n"
        "    A = 1\n    B = 2\n    C = 3\n\n\n"
        "def f(s: S) -> int:\n"
        "    if s == S.A:\n        return 1\n"
        "    elif s == S.B:\n        return 2\n"
    )
    out = complete_match_exhaustiveness(src)
    assert out is not None
    compile(out, "<m>", "exec")
    assert out.rstrip().endswith('raise AssertionError(f"unhandled s: {s!r}")')


def test_still_fires_on_terminal_match_missing_case():
    # No over-refusal: a closed ``match`` missing a member with NOTHING after it
    # still gains a trailing ``case _:`` sentinel.
    src = (
        "from enum import Enum\n\n\nclass S(Enum):\n"
        "    A = 1\n    B = 2\n    C = 3\n\n\n"
        "def f(s: S) -> int:\n    match s:\n"
        "        case S.A:\n            return 1\n"
        "        case S.B:\n            return 2\n"
    )
    out = complete_match_exhaustiveness(src)
    assert out is not None
    compile(out, "<m>", "exec")
    assert "        case _:\n" in out
    assert out.rstrip().endswith('raise AssertionError(f"unhandled s: {s!r}")')


def test_nested_terminal_dispatch_inside_block_still_fires():
    # A dispatch that is the LAST statement of a NESTED block (an ``if`` body) is
    # still terminal in ITS suite — the unhandled value falls off that nested block
    # silently — so it still fires. Guards the helper against only checking top level.
    src = (
        "from enum import Enum\n\n\nclass S(Enum):\n"
        "    A = 1\n    B = 2\n    C = 3\n\n\n"
        "def f(s: S, go: bool) -> int:\n    if go:\n"
        "        if s == S.A:\n            return 1\n"
        "        elif s == S.B:\n            return 2\n"
        "    return 0\n"
    )
    out = complete_match_exhaustiveness(src)
    assert out is not None
    compile(out, "<m>", "exec")
    assert out.count("raise AssertionError") == 1


def test_does_not_edit_the_live_mode_policy_source():
    # SANITY-REPRO of the field bug: running the transform over the LITERAL shipped
    # ``app/policy/mode.py`` must return NO edit. Both its dispatches are followed by
    # code (a guard-return before later handlers; an if/elif before a fall-through
    # ``return cls(...)``), so a sentinel would have made valid modes crash/unreachable.
    from pathlib import Path

    src = Path("app/policy/mode.py").read_text(encoding="utf-8")
    assert complete_match_exhaustiveness(src) is None


# --- the "dispatch inside a reachable try must be refused" soundness guard ---
# The block-position guard proves nothing about EXCEPT reachability. A dispatch that
# is the LAST statement of a ``try:`` body silently falls through today (returns
# ``None``); appending a ``raise AssertionError`` there is CAUGHT by the try's
# ``except`` — the raise is swallowed / rerouted instead of falling through, a
# behaviour change. Refuse whenever the new raise could be intercepted.

def test_refuses_dispatch_last_in_try_body_with_reachable_except():
    # The dispatch is the terminal statement of a ``try:`` whose ``except`` would
    # catch the appended ``raise AssertionError`` — refuse (the raise would be
    # swallowed, not fall through as today).
    src = (
        "from enum import Enum\n\n\nclass S(Enum):\n"
        "    A = 1\n    B = 2\n    C = 3\n\n\n"
        "def f(s: S) -> int:\n    try:\n"
        "        if s == S.A:\n            return 1\n"
        "        elif s == S.B:\n            return 2\n"
        "    except AssertionError:\n        return -1\n"
        "    return 0\n"
    )
    assert complete_match_exhaustiveness(src) is None  # the except would catch the raise


def test_refuses_match_last_in_try_body_with_broad_except():
    # A ``match`` terminal in a ``try:`` body whose broad ``except Exception:`` would
    # catch the sentinel raise — refuse.
    src = (
        "from enum import Enum\n\n\nclass S(Enum):\n"
        "    A = 1\n    B = 2\n    C = 3\n\n\n"
        "def f(s: S) -> int:\n    try:\n        match s:\n"
        "            case S.A:\n                return 1\n"
        "            case S.B:\n                return 2\n"
        "    except Exception:\n        return -1\n"
    )
    assert complete_match_exhaustiveness(src) is None  # the broad except would catch it


def test_refuses_dispatch_in_try_body_with_finally():
    # A ``finally`` reroutes control out of the ``try`` regardless of the raise — a
    # dispatch terminal in the body of such a ``try`` is refused.
    src = (
        "from enum import Enum\n\n\nclass S(Enum):\n"
        "    A = 1\n    B = 2\n    C = 3\n\n\n"
        "def f(s: S) -> int:\n    try:\n"
        "        if s == S.A:\n            return 1\n"
        "        elif s == S.B:\n            return 2\n"
        "    finally:\n        cleanup()\n"
    )
    assert complete_match_exhaustiveness(src) is None  # the finally reroutes control


def test_refuses_dispatch_nested_under_if_inside_try_body():
    # The risky-try region includes descendants: a dispatch nested under an ``if``
    # inside a guarded ``try:`` body is still inside the region whose raise the
    # ``except`` catches — refuse.
    src = (
        "from enum import Enum\n\n\nclass S(Enum):\n"
        "    A = 1\n    B = 2\n    C = 3\n\n\n"
        "def f(s: S, go: bool) -> int:\n    try:\n        if go:\n"
        "            if s == S.A:\n                return 1\n"
        "            elif s == S.B:\n                return 2\n"
        "    except AssertionError:\n        return -1\n"
        "    return 0\n"
    )
    assert complete_match_exhaustiveness(src) is None  # inside the guarded region


def test_still_fires_on_terminal_dispatch_not_in_any_try():
    # No over-refusal: the SAME dispatch shape, NOT inside a ``try``, is a genuine
    # silent fall-through and still gains its sentinel.
    src = (
        "from enum import Enum\n\n\nclass S(Enum):\n"
        "    A = 1\n    B = 2\n    C = 3\n\n\n"
        "def f(s: S) -> int:\n"
        "    if s == S.A:\n        return 1\n"
        "    elif s == S.B:\n        return 2\n"
    )
    out = complete_match_exhaustiveness(src)
    assert out is not None
    compile(out, "<m>", "exec")
    assert out.rstrip().endswith('raise AssertionError(f"unhandled s: {s!r}")')


def test_still_fires_on_terminal_dispatch_in_try_orelse_no_finally():
    # A dispatch terminal in a ``try``'s ``else:`` (which runs only after the body
    # SUCCEEDS) is NOT caught by that try's ``except`` in Python, and with no
    # ``finally`` there is no reroute — the fall-through is genuine, so it still
    # fires. Guards against over-refusing every dispatch merely near a ``try``.
    src = (
        "from enum import Enum\n\n\nclass S(Enum):\n"
        "    A = 1\n    B = 2\n    C = 3\n\n\n"
        "def f(s: S) -> int:\n    try:\n        setup()\n"
        "    except AssertionError:\n        return -1\n"
        "    else:\n"
        "        if s == S.A:\n            return 1\n"
        "        elif s == S.B:\n            return 2\n"
    )
    out = complete_match_exhaustiveness(src)
    assert out is not None
    compile(out, "<m>", "exec")
    assert out.rstrip().endswith('raise AssertionError(f"unhandled s: {s!r}")')


# --- idempotency / determinism ----------------------------------------------

def test_idempotent_second_run_is_noop():
    once = complete_match_exhaustiveness(_ENUM_MATCH)
    assert once is not None
    assert complete_match_exhaustiveness(once) is None  # 2nd run sees the wildcard


def test_deterministic_across_two_runs():
    a = complete_match_exhaustiveness(_ENUM_MATCH)
    b = complete_match_exhaustiveness(_ENUM_MATCH)
    assert a is not None and a == b


# --- registration / reachability --------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "complete-match-exhaustiveness" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["complete-match-exhaustiveness"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "complete-match-exhaustiveness"


def test_facet_reachability_parity_invariant_holds():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_facet_phrase_is_substring_order_safe():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    keys = list(FACET_OBJECTIVE_MAP)
    assert _PHRASE in keys
    for other in keys:
        if other == _PHRASE:
            continue
        assert _PHRASE not in other, f"{_PHRASE!r} is a substring of {other!r}"
        assert other not in _PHRASE, f"{other!r} is a substring of {_PHRASE!r}"


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "complete-match-exhaustiveness" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []


def test_soundness_strategy_present_and_reverse_tripwire_clean():
    from app.engine.objective_compiler import available_objectives
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        strategy_completeness,
        strategy_subset_of_registry,
    )

    table = strategy_completeness(available_objectives())
    assert "complete-match-exhaustiveness" in table
    assert strategy_subset_of_registry() == []
    # the proof is intra-module/structural — NOT a scope_verify objective.
    assert "complete-match-exhaustiveness" not in SCOPE_VERIFY_ALLOWLIST


def test_objective_does_not_set_scope_verify():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["complete-match-exhaustiveness"]
    assert getattr(spec, "scope_verify", False) is False


def test_facet_phrase_lives_in_the_property_invariants_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["property invariants"]
    assert _PHRASE in ladder
    assert ladder[0] == "idempotence"  # originals still lead


# --- the plan ----------------------------------------------------------------

def test_plan_lands_sentinel(tmp_path: Path):
    _project(tmp_path, "app/dispatch.py", _ENUM_MATCH)
    plan = plan_complete_match_exhaustiveness(str(tmp_path), "app/dispatch.py")
    assert plan.ok
    new = plan.new_contents["app/dispatch.py"]
    assert "        case _:\n" in new
    assert '            raise AssertionError(f"unhandled s: {s!r}")' in new
    assert plan.originals["app/dispatch.py"] == _ENUM_MATCH  # original captured
    assert plan.edits_by_file["app/dispatch.py"] == 1


def test_plan_refuses_already_total_dispatch(tmp_path: Path):
    total = (
        "from enum import Enum\n\n\nclass S(Enum):\n    A = 1\n    B = 2\n\n\n"
        "def f(x: S) -> int:\n    match x:\n        case S.A:\n            return 1\n"
        "        case S.B:\n            return 2\n        case _:\n            return 0\n"
    )
    _project(tmp_path, "app/dispatch.py", total)
    assert not plan_complete_match_exhaustiveness(str(tmp_path), "app/dispatch.py").new_contents


def test_plan_refuses_test_file_input(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", _ENUM_MATCH)
    assert not plan_complete_match_exhaustiveness(str(tmp_path), "tests/test_x.py").new_contents


def test_plan_refuses_fixture_file_input(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", _ENUM_MATCH)
    assert not plan_complete_match_exhaustiveness(str(tmp_path), "fixtures/sample.py").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_complete_match_exhaustiveness(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- end-to-end: gated apply, real landing, suite stays green ----------------

def test_end_to_end_lands_sentinel_and_keeps_green(tmp_path: Path):
    _suite_project(tmp_path)
    (tmp_path / "app" / "dispatch.py").write_text(_ENUM_MATCH, encoding="utf-8")
    # the suite exercises ONLY the HANDLED members (START, RUN), so the new
    # ``case _:`` arm — which fires only on the unhandled STOP — never runs in it.
    (tmp_path / "tests" / "test_dispatch.py").write_text(
        "from app.dispatch import State, label\n"
        "def test_handled():\n"
        "    assert label(State.START) == 1\n"
        "    assert label(State.RUN) == 2\n",
        encoding="utf-8")

    plan = plan_complete_match_exhaustiveness(str(tmp_path), "app/dispatch.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "dispatch.py").read_text(encoding="utf-8")
    assert "        case _:\n" in landed  # the sentinel LANDED
    assert '            raise AssertionError(f"unhandled s: {s!r}")' in landed


def test_never_lands_on_an_open_set(tmp_path: Path):
    # The never-fake-green capstone: a dispatch whose discriminant set is NOT provably
    # closed (an open ``str``) is REFUSED before any apply — no plan, no write. We never
    # append a sentinel where the "missing" arm might actually be a legitimate value the
    # code routes elsewhere; only a PROVABLY closed set is filled.
    _project(
        tmp_path, "app/open.py",
        "def f(s: str) -> int:\n    match s:\n        case 'a':\n            return 1\n"
        "        case 'b':\n            return 2\n")
    plan = plan_complete_match_exhaustiveness(str(tmp_path), "app/open.py")
    assert not plan.new_contents  # the open set is refused before any apply
