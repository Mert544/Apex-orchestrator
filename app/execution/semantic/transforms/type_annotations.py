"""Type-annotation transform — add PROVABLE type hints to unannotated functions.

Two surfaces live here:

  - :func:`apply` — the original, naive single-function ``-> None`` rewrite the
    semantic-patch generator drives (``add_type_annotations`` title). Its
    contract is unchanged: annotate the FIRST unannotated function's return as
    ``-> None``. Kept byte-for-byte so existing callers/tests are unaffected.

  - :func:`plan_type_annotations` — the develop-objective surface: a
    ``RenamePlan`` that annotates EVERY function in a module whose types are
    *provable from the AST*, never a guess. This is what the suite-gated
    ``apex develop --objective infer-type-hints`` campaign composes.

What counts as PROVABLE (the only things ever annotated):

  - **Return type** from the function's ``return`` statements when every return
    yields a value of the SAME statically-certain concrete type:
    ``int``/``str``/``bool``/``float``/``list``/``dict``/``tuple``/``set``/
    ``bytes`` constants and displays — a fully-LITERAL display is PARAMETRIZED
    (``[1, 2]`` ⇒ ``list[int]``, ``{1: 'a'}`` ⇒ ``dict[int, str]``, ``(1, 'a')``
    ⇒ the fixed-length ``tuple[int, str]``) when every element/key/value proves
    to a consistent type, else the BARE container (empty/mixed/non-literal —
    ``[]`` ⇒ ``list``, ``[1, 'a']`` ⇒ ``list``) — an f-string (``JoinedStr`` ⇒
    ``str``), a
    list/dict/set comprehension (⇒ ``list``/``dict``/``set``), a certainly-
    boolean expression (a comparison or ``not x`` ⇒ ``bool``), a SAME-TYPE-
    LITERAL binary op over a TYPE-CLOSED operator (``1 + 2`` ⇒ ``int``,
    ``'a' + 'b'`` ⇒ ``str`` — see :func:`_binop_same_type_literal`), and a
    FIXED-RESULT ``<builtin>(...)`` call whose builtin's result type does not
    depend on its args and is NOT shadowed in the function's scope (``len(x)`` ⇒
    ``int``, ``sorted(x)`` ⇒ ``list`` — see :func:`_builtin_call_returns_type`),
    and a FIXED-RESULT bytes/str method call ``<str-lit>.encode(...)`` ⇒
    ``bytes`` / ``<bytes-lit>.decode(...)`` ⇒ ``str`` / a
    ``<bytes-lit>.<bytes-method>(...)`` over a LITERAL receiver ⇒ ``bytes``
    (``b'a'.upper()`` — see :func:`_bytes_method_call_returns_type`, the bytes
    analog of the str-method rule),
    and a SAME-TYPE conditional expression ``X if C else Y`` whose BOTH branches
    independently prove to the SAME type (``'a' if c else 'b'`` ⇒ ``str`` — see
    :func:`_ifexp_same_type`; the condition does not affect the result type and a
    mismatched-branch ternary refuses).
    Or ``-> None`` when the function has no value-returning ``return`` and no
    ``yield`` (a pure procedure). REFUSED (left alone): mixed return types (e.g.
    ``int``+``float``), a generator expression (yields a generator, not a
    container) or ``and``/``or`` (returns an operand, not a bool), a ``/`` or
    ``**`` binary op or one with a non-literal/mixed-type operand (``x + 1`` ⇒
    ``x`` is a value, not a type bound), any other non-certain return
    (name/call/attribute/subscript), a ``yield`` generator, or an existing
    ``-> T``.

  - **Self / cls return type** — the one return shape the literal oracle above
    deliberately refuses (a bare ``Name``/``Call`` is "not statically certain"),
    yet which IS provable from the LANGUAGE CONTRACT: a method whose EVERY
    value-return is ``self`` returns an instance of its OWN class (subclass
    is-a holds), and a ``@classmethod`` whose every value-return is ``cls(...)``
    constructs an instance of the class/subclass — both a SOUND upper bound. So
    such a method earns ``-> "<EnclosingClass>"``, a forward-ref STRING literal
    (NOT ``typing.Self``): a string annotation is never evaluated at runtime,
    needs NO import and NO version gate, and changes no runtime value — the same
    behaviour-identical landing this module promises. See
    :func:`_infer_self_return_type` for the full refusal set (mixed returns,
    ``cls(...)`` outside ``@classmethod``, a reassigned ``self``/``cls``, a
    ``staticmethod``/``property``, no single enclosing class, …).

A parameter type from an UNCONDITIONAL runtime ``isinstance`` guard at entry:
when ``assert isinstance(x, str)`` or ``if not isinstance(x, int): raise``
opens a function body, every path that continues past it has PROVEN ``x`` is an
instance of that class, so ``x: str`` / ``x: int`` RECORDS a runtime-ENFORCED
fact (see :func:`_annotatable_params`). Strictly SINGLE bare-builtin class only
(a tuple ``(int, float)`` would need a ``Union`` ⇒ refuse); the guard must be
unconditional (not nested) and the parameter unused/unreassigned before it.
A SINGLE CONJOINED guard binds EACH conjoined parameter: ``assert isinstance(x,
A) and isinstance(y, B)`` ⇒ ``x: A, y: B`` and ``if not (isinstance(x, A) and
isinstance(y, B)): raise`` ⇒ ``x: A, y: B`` (see :func:`_guard_test_bindings`).
``and`` is SOUND because the guard raises unless EVERY conjunct holds, so past
it each conjoined parameter has its proven type — identical runtime enforcement
to the single-guard rule. ``or`` is REFUSED (an ``or`` guard proves NEITHER
operand's type), and a conjunction with ANY non-single-class operand (a
tuple-of-classes isinstance, a non-isinstance term) yields NO binding from the
whole conjunction.

Why NOT a parameter type from its default value: a default does NOT constrain
the type a parameter accepts. ``def f(x=0)`` is routinely called ``f("s")`` or
``f([1])`` — the ``0`` is only the value used when the argument is omitted, not
a type bound. Inferring ``x: int`` from ``x=0`` is therefore UNSOUND: it can
contradict the project's own passing tests (``add("ab")`` on ``def add(x=0)``)
while still being stamped ``verified`` (an annotation changes no runtime value,
so no test can ever catch the lie). That wrong-but-verified landing is exactly
what Apex must never do, so the default-value → parameter-type path stays
REMOVED. A guard is sound where a default is not BECAUSE the guard enforces the
type at run time — a value the guard rejects already raises today, so recording
the bound cannot contradict any passing test.

Never guesses: when a type is not provable from the AST the function is left
exactly as it was — an honest under-claim. Annotations are behaviour-preserving:
they add ``-> T`` text only, never change runtime values. Deterministic:
AST-only, no clock/random, a stable left-to-right walk. Test/fixture files are
refused by the plan layer.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite

from ..result import SemanticPatchResult

__all__ = [
    "apply",
    "plan_type_annotations",
    "plan_annotate_self_returns",
    "infer_annotations",
]


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return None

    lines = source.splitlines(keepends=True)
    modified = False

    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))) and (node.returns is None):
            lineno = node.lineno - 1
            line = lines[lineno]
            stripped = line.rstrip()
            if (stripped.endswith(":")) and ("->" not in stripped):
                new_line = stripped[:-1] + " -> None:\n"
                lines[lineno] = new_line
                modified = True
                break

    if not modified:
        return None

    new_content = "".join(lines)
    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_content,
            "expected_old_content": source,
        }],
        transform_type="add_type_annotations",
        rationale=[f"Added missing return type annotation in {rel_path}."],
    )


# --- Provable inference (develop objective) ----------------------------------

# Concrete literal node -> the type name to annotate with. Only these
# unambiguous literal shapes are ever inferred.
def _constant_type(value: object) -> str | None:
    """The provable type NAME for an ``ast.Constant`` value, or ``None``.

    ``bool`` is checked before ``int`` because ``True``/``False`` are
    ``ast.Constant`` with a ``bool`` value (and ``bool`` is a subclass of
    ``int`` — we want the precise ``bool``). A ``complex`` literal (``3j``) has
    a non-overridable type, so it classifies as ``complex``."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, complex):
        return "complex"
    if isinstance(value, str):
        return "str"
    if isinstance(value, bytes):
        return "bytes"
    return None


# Concrete display/comprehension node -> the type it always evaluates to. A
# ``GeneratorExp`` is deliberately ABSENT: it yields a ``generator`` object, not
# a ``list``/``set``, so its concrete type is not one we name — it must refuse.
_DISPLAY_TYPES: dict[type[ast.expr], str] = {
    ast.List: "list",
    ast.Dict: "dict",
    ast.Set: "set",
    ast.Tuple: "tuple",
    ast.ListComp: "list",
    ast.DictComp: "dict",
    ast.SetComp: "set",
}


# Single-element LITERAL display nodes whose container type takes ONE uniform
# element parameter when every element proves to the SAME type: ``ast.List`` ⇒
# ``list``, ``ast.Set`` ⇒ ``set``. (``ast.Dict`` and ``ast.Tuple`` are
# parametrized by their own shapes — see :func:`_parametrized_display_type`.)
_UNIFORM_PARAM_DISPLAYS: dict[type[ast.expr], str] = {
    ast.List: "list",
    ast.Set: "set",
}


def _element_provable_type(node: ast.expr) -> str | None:
    """The provable type NAME for ONE element/key/value inside a literal display,
    or ``None`` when not provable.

    Tries the PARAMETRIZED display type FIRST (so a nested provable display lifts
    — ``[[1]]`` ⇒ ``list[list[int]]``, ``{'a': [1]}`` ⇒ ``dict[str, list[int]]``),
    then falls back to the pure context-free :func:`_literal_type` oracle for a
    scalar/non-display element. Soundness is unchanged: every leaf still bottoms
    out in :func:`_literal_type`, and a ``Name`` / non-literal element yields
    ``None`` here and refuses its enclosing container."""
    parametrized = _parametrized_display_type(node)
    return parametrized if parametrized is not None else _literal_type(node)


def _uniform_element_type(elts: list[ast.expr]) -> str | None:
    """The single shared :func:`_element_provable_type` of EVERY element in
    ``elts``, or ``None`` when ``elts`` is empty, any element is not provable, or
    the elements disagree.

    Recurses through :func:`_element_provable_type`, so a nested provable display
    lifts too (``[[1], [2]]`` ⇒ ``list[list[int]]``); a ``Name`` or any
    unprovable element yields ``None`` there and refuses the whole container."""
    if not elts:
        return None  # an empty display under-claims the bare container
    first = _element_provable_type(elts[0])
    if first is None:
        return None
    for elt in elts[1:]:
        if _element_provable_type(elt) != first:
            return None  # disagreeing element types -> bare container
    return first


def _parametrized_dict_type(node: ast.Dict) -> str | None:
    """``dict[K, V]`` when EVERY key proves to ONE type ``K`` and EVERY value to
    ONE type ``V`` (both via :func:`_uniform_element_type`), else ``None``.

    A ``**spread`` entry has a ``None`` key (``node.keys`` carries ``None``
    there); the uniform-key oracle cannot prove a ``None`` AST slot, so a spread
    correctly forces the bare ``dict`` fallback."""
    keys = [k for k in node.keys if k is not None]
    if len(keys) != len(node.keys):
        return None  # a ``**spread`` entry -> not a fixed key/value shape
    key_type = _uniform_element_type(keys)
    if key_type is None:
        return None
    value_type = _uniform_element_type(node.values)
    return f"dict[{key_type}, {value_type}]" if value_type is not None else None


def _parametrized_tuple_type(node: ast.Tuple) -> str | None:
    """``tuple[T1, T2, ...]`` (a FIXED-length HETEROGENEOUS tuple — one slot per
    element) when EVERY element independently proves via
    :func:`_element_provable_type`, else ``None`` (empty tuple or any unprovable
    element -> bare ``tuple``).

    A ``*spread`` element is an ``ast.Starred`` that :func:`_literal_type`
    refuses, so a variadic tuple correctly falls back to the bare container."""
    if not node.elts:
        return None  # empty tuple under-claims the bare container
    parts: list[str] = []
    for elt in node.elts:
        elt_type = _element_provable_type(elt)
        if elt_type is None:
            return None
        parts.append(elt_type)
    return f"tuple[{', '.join(parts)}]"


def _parametrized_display_type(node: ast.expr) -> str | None:
    """A PARAMETRIZED PEP 585 builtin-generic type for a fully-LITERAL display,
    or ``None`` when the display cannot be parametrized (and so should fall back
    to its BARE container via :data:`_DISPLAY_TYPES`).

    Parametrized ONLY when every part proves to a consistent type via the
    recursive :func:`_element_provable_type` oracle (which bottoms out in
    :func:`_literal_type`) — so this adds NO soundness surface:
      - ``ast.List``/``ast.Set`` ⇒ ``list[T]``/``set[T]`` when all elements share
        ONE type ``T`` (:func:`_uniform_element_type`);
      - ``ast.Dict`` ⇒ ``dict[K, V]`` when all keys share ``K`` and all values
        ``V`` (:func:`_parametrized_dict_type`);
      - ``ast.Tuple`` ⇒ ``tuple[T1, ...]`` (fixed-length, heterogeneous — one
        slot per element, :func:`_parametrized_tuple_type`).

    UNDER-claims the bare container (never wrong) for an EMPTY display, a
    MIXED-element display (``[1, 'a']`` ⇒ bare ``list``), or any non-literal
    element. A COMPREHENSION is NOT a display node here (``ast.ListComp`` etc.
    are absent), so it stays bare/unchanged — its element type is not statically
    certain. PEP 585 builtin generics need NO import on the project's Python."""
    if isinstance(node, (ast.List, ast.Set)):
        uniform = _UNIFORM_PARAM_DISPLAYS[type(node)]
        element = _uniform_element_type(node.elts)
        return f"{uniform}[{element}]" if element is not None else None
    if isinstance(node, ast.Dict):
        return _parametrized_dict_type(node)
    if isinstance(node, ast.Tuple):
        return _parametrized_tuple_type(node)
    return None


def _literal_type(node: ast.expr) -> str | None:
    """The provable type NAME for a return expression, or ``None`` if the
    expression's type is not statically certain from the AST alone.

    Statically certain shapes (and ONLY these — never a guess):
      - constants: ``None``/``bool``/``int``/``float``/``complex``/``str``/``bytes``;
      - an f-string (``JoinedStr``) ⇒ always ``str``;
      - a display/comprehension literal ⇒ its (BARE) container type
        (``list``/``dict``/``set``/``tuple``, ``ListComp``/``DictComp``/
        ``SetComp``); a ``GeneratorExp`` yields a generator, NOT a concrete
        container, so it is refused. (A fully-LITERAL display is PARAMETRIZED to
        ``list[int]``/``dict[int, str]``/``tuple[int, str]`` only at the
        return-value surface — :func:`_parametrized_display_type` via
        :func:`_return_value_type` — so THIS context-free oracle, reused
        recursively by the binop/sequence-mult/str-method rules, keeps returning
        the bare container kind those rules compare on);
      - a CERTAINLY-boolean expression ⇒ ``bool``: an IDENTITY/MEMBERSHIP
        comparison (``x is None``, ``y in z`` — the ``is``/``is not``/``in``/
        ``not in`` operators always yield a ``bool``) or ``not x``. A rich
        comparison (``==``/``!=``/``<``/``<=``/``>``/``>=``) is NOT certain —
        it dispatches to an overridable dunder (``__eq__``/``__lt__``/...) that
        may return any type — so it is refused. ``and``/``or`` are NOT certain
        (``a and b`` returns an operand, not a bool), so they are refused.
      - a PROVABLY-str method call ⇒ ``str``: ``<receiver>.<method>(...)`` where
        ``<receiver>`` is itself provably ``str`` (recursively — a str constant,
        an f-string, or a provably-str method call, so ``','.join(x).upper()``
        chains) and ``<method>`` is in :data:`_STR_RETURNING_METHODS` (str
        methods that ALWAYS return ``str``). See
        :func:`_str_method_call_returns_str` for the soundness rules.
      - a FIXED-result bytes/str method call ⇒ ``bytes``/``str``/``list``/
        ``tuple``: ``<str-literal>.encode(...)`` ⇒ ``bytes``,
        ``<bytes-literal>.decode(...)`` ⇒ ``str``, a ``<bytes-literal>.<method>(...)``
        whose ``<method>`` is in :data:`_BYTES_RETURNING_METHODS` ⇒ ``bytes``,
        and a ``<str-or-bytes>.<method>(...)`` whose ``<method>`` is in
        :data:`_SEQUENCE_RETURNING_METHODS` ⇒ ``list``/``tuple`` (``split`` ⇒
        list, ``partition`` ⇒ tuple) — the receiver proved RECURSIVELY so chains
        like ``b'a'.upper().strip()`` and ``'a,b'.strip().split(',')`` compose.
        See :func:`_bytes_method_call_returns_type` for the soundness rules (a
        bare ``Name`` receiver and an args-dependent method refuse).
      - a SAME-TYPE-LITERAL binary op ⇒ that type: ``<lit> <op> <lit>`` where
        BOTH operands are provably the SAME concrete type and ``<op>`` is in the
        type-closed safe set — ``1 + 2`` ⇒ ``int``, ``'a' + 'b'`` ⇒ ``str``,
        ``[1] + [2]`` ⇒ ``list``, ``(1,) + (2,)`` ⇒ ``tuple``. See
        :func:`_binop_same_type_literal` for the soundness rules (why
        ``/``/``**`` and ``bool`` and any non-literal operand are refused).
      - a UNARY op on a NUMERIC literal ⇒ that numeric type: ``-1``/``+1`` ⇒
        ``int``, ``-1.5``/``+1.5`` ⇒ ``float``, and ``~5`` ⇒ ``int`` (``~`` is
        defined on ``int`` only — ``~1.5`` is a ``TypeError`` — so ``Invert``
        accepts an ``int`` operand only). See :func:`_unaryop_numeric_literal`.
      - a SEQUENCE/str ``*`` int literal ⇒ the sequence's type: ``'a' * 3`` ⇒
        ``str``, ``b'x' * 3`` ⇒ ``bytes``, ``[0] * 3`` ⇒ ``list``, ``(0,) * 2``
        ⇒ ``tuple`` (either operand order). This is a MIXED-type product (a
        sequence times an ``int``), so the same-type rule correctly does not
        cover it. See :func:`_mixed_sequence_int_mult`.
      - a printf-style ``<str|bytes> % x`` (``ast.Mod`` BinOp) ⇒ the LHS's type:
        ``'%s' % x`` ⇒ ``str``, ``b'%s' % x`` ⇒ ``bytes``, ``'%d' % 5`` ⇒
        ``str`` — when the LEFT operand is PROVABLY ``str``/``bytes`` (the RIGHT
        is not inspected: ``str``/``bytes`` ``__mod__`` is a non-overridable
        C-slot that always yields the LHS type). See :func:`_percent_format_type`
        (a bare-``Name`` LHS like ``n % 2`` is not provably str/bytes ⇒ refuse).

    Everything else (a name, call, attribute, subscript, etc.) is not
    statically certain ⇒ ``None`` (refuse)."""
    if isinstance(node, ast.Constant):
        return _constant_type(node.value)
    if isinstance(node, ast.JoinedStr):
        return "str"  # an f-string always evaluates to a str
    display = _DISPLAY_TYPES.get(type(node))
    if display is not None:
        return display
    if _is_certain_bool(node):
        return "bool"
    if _str_method_call_returns_str(node):
        return "str"
    method = _bytes_method_call_returns_type(node)
    if method is not None:
        return method
    unary = _unaryop_numeric_literal(node)
    if unary is not None:
        return unary
    mixed = _mixed_sequence_int_mult(node)
    if mixed is not None:
        return mixed
    percent = _percent_format_type(node)
    if percent is not None:
        return percent
    return _binop_same_type_literal(node)


# str methods that ALWAYS return a ``str`` when they return at all. Excluded by
# design: ``split``/``rsplit``/``splitlines``/``partition``/``rpartition``
# (list/tuple), ``encode`` (bytes), ``find``/``rfind``/``index``/``count`` (int),
# and every predicate (``startswith``/``isdigit``/... ⇒ bool). When unsure
# whether a method is always-str, it is EXCLUDED (conservative).
_STR_RETURNING_METHODS: frozenset[str] = frozenset({
    "join", "format", "format_map", "upper", "lower", "strip", "lstrip",
    "rstrip", "replace", "title", "capitalize", "casefold", "swapcase",
    "center", "ljust", "rjust", "zfill", "expandtabs", "translate",
    "removeprefix", "removesuffix",
})


def _str_method_call_returns_str(node: ast.expr) -> bool:
    """True only when ``node`` is a ``<receiver>.<method>(...)`` call that
    PROVABLY evaluates to a ``str``.

    Both must hold:
      1. ``<receiver>`` is PROVABLY ``str`` — defined RECURSIVELY via
         :func:`_literal_type` (``_literal_type(receiver) == "str"``): a ``str``
         constant, an f-string, or itself a provably-str method call (so
         ``','.join(x).upper()`` and ``f"a{n}".strip()`` chain soundly). A bare
         ``ast.Name`` receiver (``name.strip()`` where ``name`` is a parameter
         of unknown type) is NOT provably str ⇒ refuse — never assume a
         parameter is a ``str``.
      2. ``<method>`` is in :data:`_STR_RETURNING_METHODS` — a str method that
         ALWAYS returns ``str``. Methods returning non-str (``split`` ⇒ list,
         ``encode`` ⇒ bytes, ``find`` ⇒ int, ``startswith`` ⇒ bool) are
         excluded and so refuse.

    Call ARGUMENTS are not inspected: ``join``/``format`` return a ``str``
    regardless of args (they raise on bad args, but if they RETURN it is a str).
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in _STR_RETURNING_METHODS:
        return False
    return _literal_type(func.value) == "str"


# bytes methods that ALWAYS return ``bytes`` when they return at all — the
# analog of :data:`_STR_RETURNING_METHODS`, verified to return ``bytes`` for
# EVERY argument they accept (they may raise on bad args, but if they RETURN it
# is ``bytes``). Excluded by design: ``decode`` (str — handled separately as the
# str-producing rule), ``hex`` (str), ``split``/``rsplit``/``splitlines``/
# ``partition``/``rpartition`` (list/tuple), ``find``/``rfind``/``index``/
# ``count`` (int), and every predicate (``startswith``/``isdigit``/... ⇒ bool).
# ``bytes`` has NO ``encode``/``casefold``/``format`` — those are str-only.
_BYTES_RETURNING_METHODS: frozenset[str] = frozenset({
    "upper", "lower", "strip", "lstrip", "rstrip", "replace", "title",
    "capitalize", "swapcase", "center", "ljust", "rjust", "zfill",
    "expandtabs", "translate", "removeprefix", "removesuffix", "join",
})


# str/bytes methods whose result is ALWAYS a fixed BARE CONTAINER, identical for
# a ``str`` and a ``bytes`` receiver (both types expose every name below with the
# same result kind): ``split``/``rsplit``/``splitlines`` ⇒ ``list`` and
# ``partition``/``rpartition`` ⇒ ``tuple``, for EVERY accepted argument (they may
# raise on bad args, but a ``-> T`` only constrains a value that IS returned).
# The element type is NOT proved — ``'a,b'.split(',')`` is a ``list[str]`` but
# ``'a'.split` on a bytes receiver is ``list[bytes]``, and a non-literal receiver
# leaves elements unknowable — so the BARE container is emitted, matching how
# every other rule here (displays, sequence-mult, binops) emits a bare kind to
# the recursive oracle. Excluded — args-dependent or wrong kind: every method in
# :data:`_STR_RETURNING_METHODS`/:data:`_BYTES_RETURNING_METHODS` (⇒ str/bytes),
# ``find``/``count`` (int), predicates (bool).
_SEQUENCE_RETURNING_METHODS: dict[str, str] = {
    "split": "list", "rsplit": "list", "splitlines": "list",
    "partition": "tuple", "rpartition": "tuple",
}


def _bytes_method_call_returns_type(node: ast.expr) -> str | None:
    """The provable type NAME for a ``<receiver>.<method>(...)`` call whose
    result type is FIXED by the bytes/str method involved, or ``None``.

    Three sound shapes, each requiring a PROVABLE LITERAL receiver (resolved
    RECURSIVELY via :func:`_literal_type`, so chains compose — e.g.
    ``b'a'.upper().strip()`` proves because each step's receiver proves
    ``bytes``):

      1. ``<str>.encode(...)`` ⇒ ``bytes`` — ``str.encode`` ALWAYS returns
         ``bytes`` regardless of its codec/errors args. The receiver must prove
         ``str`` (``_literal_type(receiver) == "str"``: a str constant, an
         f-string, or a provably-str method call). The mirror of the existing
         ``str.<method>`` ⇒ ``str`` rule, on the bytes side.
      2. ``<bytes>.decode(...)`` ⇒ ``str`` — ``bytes.decode`` ALWAYS returns
         ``str`` regardless of args. The receiver must prove ``bytes``.
      3. ``<bytes>.<method>(...)`` ⇒ ``bytes`` where ``<method>`` is in
         :data:`_BYTES_RETURNING_METHODS` (a bytes method that ALWAYS returns
         ``bytes``). The receiver must prove ``bytes``.
      4. ``<str-or-bytes>.<method>(...)`` ⇒ ``list``/``tuple`` where ``<method>``
         is in :data:`_SEQUENCE_RETURNING_METHODS` — ``split``/``rsplit``/
         ``splitlines`` ⇒ ``list`` and ``partition``/``rpartition`` ⇒ ``tuple``,
         on a receiver that proves EITHER ``str`` OR ``bytes`` (both types share
         these methods with the same result kind). The BARE container is emitted
         (element type is not proved — see the set's docstring), composing with
         the recursion so ``'a,b'.strip().split(',')`` ⇒ ``list``.

    REFUSED (the LOCKED soundness rules, preserved): a bare ``ast.Name``
    receiver (``x.encode()`` / ``x.split()`` where ``x`` is a parameter of
    UNKNOWN type — never assume a receiver's type), a ``.decode()``/``.split()``
    on a non-str/bytes/unprovable receiver, and any method whose result type is
    not invariant of args for that receiver type (``hex`` ⇒ str, ``count`` ⇒
    int, predicates ⇒ bool — none are in the handled sets). Call ARGUMENTS are
    not inspected: the listed methods' result type is fixed by the method, not
    the args (they raise on bad args, but a ``-> T`` only constrains a value
    that IS returned)."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    receiver = _literal_type(func.value)
    if func.attr == "encode":
        return "bytes" if receiver == "str" else None
    if receiver in ("str", "bytes") and func.attr in _SEQUENCE_RETURNING_METHODS:
        return _SEQUENCE_RETURNING_METHODS[func.attr]
    if receiver != "bytes":
        return None
    if func.attr == "decode":
        return "str"
    return "bytes" if func.attr in _BYTES_RETURNING_METHODS else None


# Binary operators that are TYPE-CLOSED over same-type literal operands — the
# result is provably the SAME concrete type as the operands (or the op raises,
# in which case the function never returns and a ``-> T`` stays sound since it
# only constrains a value that IS returned). Verified exhaustively for
# ``int``/``float`` and for ``str``/``bytes``/``list``/``tuple``.
#
# Deliberately EXCLUDED — not type-closed, so unsound to treat as same-type:
#   - ``/`` (``Div``): ``int / int`` is always a ``float`` (``4 / 2 == 2.0``),
#     so the result type differs from the operands — left out entirely.
#   - ``**`` (``Pow``): ``2 ** -1 == 0.5`` (a ``float`` from two ``int``s) and
#     ``(-2.0) ** 0.5`` is a ``complex`` — the result escapes the operand type,
#     so ``Pow`` is unsound and left out.
#   - bitwise/shift (``|``/``&``/``^``/``<<``/``>>``/``@``): not part of the
#     provable set — left out (conservative).
_SAME_TYPE_BINOPS: tuple[type[ast.operator], ...] = (
    ast.Add, ast.Sub, ast.Mult, ast.Mod, ast.FloorDiv,
)


def _binop_same_type_literal(node: ast.expr) -> str | None:
    """The provable type NAME for ``<lit> <op> <lit>`` (``ast.BinOp``), or
    ``None`` when not provable.

    Returns a type name ONLY when ALL hold:
      1. ``<op>`` is in :data:`_SAME_TYPE_BINOPS` — a TYPE-CLOSED op (``+`` ``-``
         ``*`` ``%`` ``//``). ``/`` and ``**`` are excluded as unsound (see the
         set's docstring), so ``1 / 2`` and ``2 ** n`` refuse.
      2. BOTH operands are PROVABLY the SAME concrete type, via
         :func:`_literal_type` recursively (so a NON-literal operand — a name,
         call, or attribute like ``x`` in ``x + 1`` — yields ``None`` there and
         refuses: a value/parameter is NOT a type bound). MIXED types
         (``1 + 'a'`` ⇒ ``int`` vs ``str``) refuse.
      3. That shared type is NOT ``bool``. In Python ``bool`` is a subtype of
         ``int`` and ``True + True == 2`` is an ``int``, so a bool operand must
         NOT be reported as ``bool`` for ``+`` — refuse it rather than risk the
         bool-arithmetic-returns-int subtlety.

    Sound because ``ast.Constant``/display operands are built-ins whose dunder
    ops are not instance-overridable: ``1 + 2`` ⇒ ``int``, ``'a' + 'b'`` ⇒
    ``str``, ``[1] + [2]`` ⇒ ``list``, ``(1,) + (2,)`` ⇒ ``tuple`` are PROVABLE.
    """
    if not isinstance(node, ast.BinOp):
        return None
    if not isinstance(node.op, _SAME_TYPE_BINOPS):
        return None
    left = _literal_type(node.left)
    if left is None or left == "bool":
        return None
    return left if _literal_type(node.right) == left else None


def _percent_format_type(node: ast.expr) -> str | None:
    """The provable type NAME for printf-style ``<str|bytes> % x`` (an
    ``ast.Mod`` ``ast.BinOp``), or ``None`` when not provable.

    Returns a type ONLY when the LEFT operand PROVABLY evaluates to ``str`` or
    ``bytes`` via :func:`_literal_type` (a ``str``/``bytes`` constant, an
    f-string, or a provably-``str``/``bytes`` sub-expression that recurses). The
    RIGHT operand is DELIBERATELY NOT inspected — ``str.__mod__`` /
    ``bytes.__mod__`` are non-overridable C-slot operations that ALWAYS return
    the LHS's own type (``str``/``bytes``) when they return at all (a malformed
    format string raises, a never-returns path that keeps a ``-> str``/``->
    bytes`` sound). So ``'%s' % x`` ⇒ ``str``, ``b'%s' % x`` ⇒ ``bytes`` and
    ``'%d' % 5`` ⇒ ``str`` regardless of the right-hand value.

    This is DISJOINT from the same-type rule (:func:`_binop_same_type_literal`):
    that rule needs BOTH operands provably the same type, so for an ``ast.Mod``
    it only fires on ``int % int`` ⇒ ``int`` / ``str % str`` ⇒ ``str`` etc.,
    whereas this handles the common ``str`` (or ``bytes``) ``%`` non-string
    case. A bare-``ast.Name`` LHS (``n % 2``) is NOT provably ``str``/``bytes``
    ⇒ ``None`` (refuse), and a non-``Mod`` BinOp is not this rule ⇒ ``None``."""
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Mod):
        return None
    left = _literal_type(node.left)
    return left if left in ("str", "bytes") else None


# Unary operators whose result over a NUMERIC literal stays that numeric type.
# ``-``/``+`` (USub/UAdd) preserve ``int``/``float``; ``~`` (Invert) is handled
# separately because it is defined on ``int`` ONLY (``~1.5`` is a TypeError).
_NUMERIC_SIGN_OPS: tuple[type[ast.unaryop], ...] = (ast.USub, ast.UAdd)


def _unaryop_numeric_literal(node: ast.expr) -> str | None:
    """The provable type NAME for ``<op> <numeric literal>`` (``ast.UnaryOp``),
    or ``None`` when not provable.

    Returns a type name ONLY for these shapes (operand must be a numeric
    ``ast.Constant`` — never a name/call/attr, which are values, not type
    bounds, the LOCKED refusal):
      - ``USub``/``UAdd`` (``-x``/``+x``) on an ``int`` ⇒ ``int``, on a ``float``
        ⇒ ``float`` (sign preserves the numeric type).
      - ``Invert`` (``~x``) on an ``int`` ⇒ ``int`` ONLY. ``~`` is defined on
        ``int`` and not on ``float`` (``~1.5`` raises ``TypeError``), so a
        ``float`` operand under ``Invert`` is REFUSED.

    Sound because an ``ast.Constant`` operand is a built-in ``int``/``float``
    whose unary dunders (``__neg__``/``__pos__``/``__invert__``) are not
    instance-overridable, so ``-1`` ⇒ ``int``, ``-1.5`` ⇒ ``float``, ``~5`` ⇒
    ``int`` are PROVABLE. ``bool`` is excluded along with every non-``int``/
    ``float`` constant (``_constant_type`` returns ``bool``/``str``/... there,
    which is not in the numeric set)."""
    if not isinstance(node, ast.UnaryOp):
        return None
    if not isinstance(node.operand, ast.Constant):
        return None
    operand_type = _constant_type(node.operand.value)
    if isinstance(node.op, _NUMERIC_SIGN_OPS):
        return operand_type if operand_type in ("int", "float") else None
    if isinstance(node.op, ast.Invert):
        return "int" if operand_type == "int" else None
    return None


# Literal node types that are SEQUENCES ``*``-repeatable by an ``int`` — the
# product stays the sequence's own type. ``str``/``bytes`` are ``ast.Constant``
# (resolved via ``_constant_type``); ``list``/``tuple`` are displays.
_SEQUENCE_MULT_TYPES: frozenset[str] = frozenset({"str", "bytes", "list", "tuple"})


def _mixed_sequence_int_mult(node: ast.expr) -> str | None:
    """The provable type NAME for a SEQUENCE ``*`` int literal product
    (``ast.BinOp`` with ``Mult``), or ``None`` when not provable.

    Returns the sequence operand's type when ONE operand is a literal ``str``/
    ``bytes``/``list``/``tuple`` and the OTHER is an ``int`` ``ast.Constant``
    (EITHER order — ``'a' * 3`` and ``3 * 'a'`` both ⇒ ``str``). This is a
    MIXED-type product (sequence × int), so the same-type rule in
    :func:`_binop_same_type_literal` correctly does NOT cover it.

    Sound because the sequence literal and the ``int`` constant are built-ins
    whose ``__mul__``/``__rmul__`` are not instance-overridable: ``'a' * 3`` ⇒
    ``str``, ``b'x' * 3`` ⇒ ``bytes``, ``[0] * 3`` ⇒ ``list``, ``(0,) * 2`` ⇒
    ``tuple`` are PROVABLE (a non-positive count yields the same type, empty).
    REFUSED: any non-literal operand (a name/call/attr — a value, not a type
    bound), and ``int * int`` (the same-type rule owns it, not this one)."""
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Mult):
        return None
    left = _literal_type(node.left)
    right = _literal_type(node.right)
    if left in _SEQUENCE_MULT_TYPES and right == "int":
        return left
    if right in _SEQUENCE_MULT_TYPES and left == "int":
        return right
    return None


_CERTAIN_BOOL_CMP_OPS: tuple[type[ast.cmpop], ...] = (
    ast.Is, ast.IsNot, ast.In, ast.NotIn,
)


def _is_certain_bool(node: ast.expr) -> bool:
    """True only when ``node`` PROVABLY evaluates to a ``bool``.

    Certain: ``not x`` (``UnaryOp``/``Not`` — always a ``bool``), and an
    IDENTITY/MEMBERSHIP comparison whose every operator is ``is``/``is not``/
    ``in``/``not in`` (these operators always yield a ``bool`` and cannot be
    overridden to return otherwise — ``in``/``not in`` coerce ``__contains__``
    to ``bool``; ``is``/``is not`` are identity checks).

    NOT certain (and so excluded): a RICH comparison containing any of
    ``==``/``!=``/``<``/``<=``/``>``/``>=`` — each dispatches to an overridable
    rich-comparison dunder (``__eq__``/``__lt__``/...) that may return any type
    (e.g. a sentinel's ``__eq__`` or a numpy array), so ``a == b`` is not
    provably a ``bool``; ``a and b`` / ``a or b`` (``BoolOp`` returns one of its
    OPERANDS, e.g. ``1 and 2 == 2``); and any ``bool(...)`` call (a call is not
    statically certain here)."""
    if isinstance(node, ast.Compare):
        return all(isinstance(op, _CERTAIN_BOOL_CMP_OPS) for op in node.ops)
    return isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)


# Built-in callables whose result type is FIXED regardless of the arguments
# passed — ``builtin name -> the type name it always returns``. Grouped by
# result type for readability; flattened into one lookup. Each entry is verified
# to return the named type for EVERY argument it accepts (it may raise on bad
# args, but if it RETURNS, the type is fixed):
#   - int:  ``len``/``ord``/``id``/``hash`` always return a plain ``int``, and
#           ``int(...)`` always returns an ``int`` (``int('5')``/``int(3.9)``).
#   - float: ``float(...)`` always returns a ``float`` (``float('1.5')``/
#           ``float(2)``) — both are callable-fixed regardless of the argument.
#   - str:  ``str``/``repr``/``ascii``/``hex``/``oct``/``bin``/``chr`` always
#           return a ``str`` (``hex(255)`` ⇒ ``'0xff'``, ``chr(65)`` ⇒ ``'A'``).
#   - bool: ``bool``/``callable``/``issubclass``/``isinstance``/``hasattr`` ALWAYS
#           return a ``bool`` regardless of the argument(s) — each is a C-slot
#           predicate (``isinstance(x, T)``/``issubclass(C, B)``/``callable(x)``/
#           ``hasattr(o, n)``). A bad class arg (e.g. ``isinstance(x, 1)``) raises,
#           which is a never-returns path and so leaves a ``-> bool`` sound (it
#           only constrains a value that IS returned).
#   - container: ``list``/``dict``/``set``/``tuple``/``frozenset``/``bytearray``
#           each return their own type; ``sorted`` always returns a ``list`` and
#           ``divmod`` always returns a ``tuple`` (a 2-tuple, regardless of args).
#   - complex: ``complex`` always returns a ``complex`` (``complex(1, 2)`` /
#           ``complex('1j')`` ⇒ ``complex``), independent of the argument values.
#
# Deliberately EXCLUDED — result type is NOT fixed by the callable alone:
#   - ``min``/``max``/``sum``/``abs``/``round``/``next`` (type depends on the
#     argument values), ``open``/``iter``/``map``/``filter``/``range``/
#     ``enumerate``/``zip``/``reversed`` (iterator/handle).
# A bare-``ast.Name`` callee is required (an attribute like ``obj.len(...)`` or
# ``m.sorted(...)`` is a DIFFERENT callable and must refuse).
_BUILTIN_CALL_RETURN_TYPES: dict[str, str] = {
    "len": "int", "ord": "int", "id": "int", "hash": "int", "int": "int",
    "float": "float",
    "str": "str", "repr": "str", "ascii": "str", "hex": "str",
    "oct": "str", "bin": "str", "chr": "str",
    "bool": "bool", "callable": "bool", "issubclass": "bool",
    "isinstance": "bool", "hasattr": "bool",
    "complex": "complex",
    "list": "list", "dict": "dict", "set": "set", "tuple": "tuple",
    "frozenset": "frozenset", "sorted": "list", "divmod": "tuple",
    "bytearray": "bytearray",
}


def _builtin_call_returns_type(node: ast.expr, assigned_names: frozenset[str]) -> str | None:
    """The provable return type NAME for ``<builtin>(...)`` (``ast.Call``), or
    ``None`` when not provable.

    Returns a type name ONLY when ALL hold:
      1. ``node`` is an ``ast.Call`` whose ``func`` is a bare ``ast.Name`` (an
         ``ast.Attribute`` callee like ``obj.list(...)`` is a DIFFERENT,
         user-defined method ⇒ refuse; any non-Name callee ⇒ refuse).
      2. ``func.id`` is in :data:`_BUILTIN_CALL_RETURN_TYPES` — a builtin whose
         result type is FIXED regardless of args. A user call (``user_fn(x)``)
         is not in the set ⇒ refuse.
      3. ``func.id`` is NOT in ``assigned_names`` — the SHADOWING GUARD. If the
         function rebinds the name in its own scope (``len = ...`` then
         ``return len(x)``), the call no longer resolves to the builtin, so its
         result type is unknown ⇒ refuse. This keeps the inference SOUND even
         when a local shadows a builtin.

    Sound because a non-shadowed builtin's result type is fixed by the callable
    itself (``len(...)`` ⇒ ``int``, ``sorted(...)`` ⇒ ``list``), independent of
    the argument values; arguments are therefore not inspected (the call raises
    on bad args, but a ``-> T`` only constrains a value that IS returned)."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Name):
        return None
    if func.id in assigned_names:
        return None  # shadowed in this scope — no longer the builtin
    return _BUILTIN_CALL_RETURN_TYPES.get(func.id)


def _own_returns(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Return]:
    """Every ``return`` that belongs to ``fn`` itself — descending into the body
    but NOT into a nested function/lambda, whose returns are their own."""
    out: list[ast.Return] = []

    def walk(body: list[ast.stmt]) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue  # a nested function's returns are not ours
            if isinstance(stmt, ast.Return):
                out.append(stmt)
            for child in ast.iter_child_nodes(stmt):
                if isinstance(child, ast.stmt):
                    walk([child])
                elif isinstance(child, ast.excepthandler):
                    walk(child.body)

    walk(fn.body)
    return out


def _assigned_names_in_scope(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    """Every NAME bound (``ast.Store``) in ``fn``'s OWN body — assignments,
    ``for`` targets, ``with ... as`` targets, walrus, etc. — descending into the
    body but NOT into a nested function/lambda (whose bindings are their own,
    mirroring :func:`_own_returns`).

    Used as the SHADOWING GUARD for :func:`_builtin_call_returns_type`: if a name
    like ``len`` is rebound here, a ``len(...)`` call no longer resolves to the
    builtin, so its result type is unknown and inference must refuse. Parameters
    are intentionally NOT included — a parameter binding is not an ``ast.Store``
    Name in the body; we treat the body's Store names as the shadow set, the
    conservative, deterministic over-approximation a guard wants. A nested
    function/lambda's OWN bindings are not ours (mirroring :func:`_own_returns`),
    but a name bound directly in our body still shadows for the whole scope."""
    names: set[str] = set()

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue  # a nested scope's bindings are its own
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.add(child.id)
            walk(child)

    walk(fn)
    return frozenset(names)


def _has_own_yield(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if ``fn`` itself is a generator — a ``yield``/``yield from`` that
    belongs to it, not to a nested function/lambda (whose yields are their own).
    A generator's runtime return is an iterator, so it must never be inferred."""
    found = False

    def walk(node: ast.AST) -> None:
        nonlocal found
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue  # a nested scope's yields are not ours
            if isinstance(child, (ast.Yield, ast.YieldFrom)):
                found = True
                return
            walk(child)

    walk(fn)
    return found


def _body_terminates(body: list[ast.stmt]) -> bool:
    """True when control provably CANNOT fall off the end of ``body`` — every
    path ends in a ``return``/``raise`` (or an infinite ``while True`` with no
    break, or an ``if``/``try``/``with`` whose every branch terminates).

    Conservative by design: anything not provably terminating returns ``False``
    (treated as "may fall through", i.e. an implicit ``return None``). A loop
    that can complete normally, a ``for`` (it may run zero times), or a bare
    statement at the tail all count as non-terminating."""
    if not body:
        return False
    last = body[-1]
    if isinstance(last, (ast.Return, ast.Raise)):
        return True
    if isinstance(last, ast.If):
        return _if_terminates(last)
    if isinstance(last, ast.With):
        return _body_terminates(last.body)
    if isinstance(last, ast.While):
        return _while_terminates(last)
    if isinstance(last, ast.Try):
        return _try_terminates(last)
    return False


def _if_terminates(node: ast.If) -> bool:
    """Both arms must terminate; a missing ``else`` falls through."""
    if not node.orelse:
        return False
    return _body_terminates(node.body) and _body_terminates(node.orelse)


def _while_terminates(node: ast.While) -> bool:
    """A ``while True:`` with no reachable ``break`` never completes normally, so
    the loop body always runs to a ``return``/``raise`` (or loops forever)."""
    test = node.test
    if not (isinstance(test, ast.Constant) and bool(test.value)):
        return False
    return not _has_own_break(node.body)


def _try_terminates(node: ast.Try) -> bool:
    """A ``finally`` that terminates dominates everything. Otherwise the body (or
    ``else`` if present) and EVERY ``except`` handler must each terminate."""
    if node.finalbody and _body_terminates(node.finalbody):
        return True
    if not all(_body_terminates(h.body) for h in node.handlers):
        return False
    tail = node.orelse or node.body
    return _body_terminates(tail)


def _has_own_break(body: list[ast.stmt]) -> bool:
    """True when ``body`` contains a ``break`` that belongs to its own innermost
    loop — i.e. not nested inside a deeper ``for``/``while`` (whose break is its
    own) and not inside a nested function. Used to prove ``while True`` cannot
    complete normally."""
    for stmt in body:
        if isinstance(stmt, (ast.For, ast.While, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.Lambda)):
            continue  # a deeper loop's / nested scope's break is not ours
        if isinstance(stmt, ast.Break):
            return True
        for child in ast.iter_child_nodes(stmt):
            if isinstance(child, ast.stmt) and _has_own_break([child]):
                return True
            if isinstance(child, ast.excepthandler) and _has_own_break(child.body):
                return True
    return False


# Builtin generic CONTAINERS join with another of the SAME base by keeping a
# precise parameter ONLY when both sides match exactly, else WIDENING to the
# sound bare base. A non-base (``int``/``str``/...) has no ``[``, so it only ever
# joins with an identical self — never a lossy widen — which keeps cross-base and
# container-vs-scalar pairs correctly un-joinable.
def _type_base(name: str) -> str:
    """The bare container/base of a (possibly parametrized) type NAME — the text
    before the first ``[`` (``list[int]`` ⇒ ``list``, ``int`` ⇒ ``int``)."""
    return name.split("[", 1)[0]


def _join_types(a: str, b: str) -> str | None:
    """The least-upper-bound annotation of two provable type NAMES, or ``None``
    when they do not agree.

    - IDENTICAL types keep their exact (possibly parametrized) form:
      ``list[int]`` ⊔ ``list[int]`` = ``list[int]``, ``int`` ⊔ ``int`` = ``int``.
    - SAME base but DIFFERING parameters (or one side bare) WIDEN to the sound
      bare base: ``list[int]`` ⊔ ``list`` = ``list``, ``list[int]`` ⊔ ``list[str]``
      = ``list``, ``tuple[int, str]`` ⊔ ``tuple[int, int]`` = ``tuple``.
    - DIFFERENT bases (or a container vs a non-container like ``list[int]`` vs
      ``int``) do NOT agree ⇒ ``None`` (refuse, unchanged).

    Sound because the join only ever WIDENS a precise type to its OWN bare base
    (every value of ``list[int]`` is a ``list``), so a folded annotation stays
    true of every return; a single type folds to itself, retaining precision."""
    if a == b:
        return a  # identical (parametrized or scalar) — keep the exact form
    base = _type_base(a)
    if base == _type_base(b):
        return base  # same container, differing params / a bare side -> widen
    return None  # different base or container-vs-scalar — no agreement


def _join_all_types(types: list[str]) -> str | None:
    """Fold ``types`` (in collection order) under :func:`_join_types`, or
    ``None`` if any pair fails to agree. ``types`` is never empty at the call
    sites (each has at least one provable type); a single type folds to itself,
    so its precise parametrized form is retained."""
    if not types:
        return None
    joined = types[0]
    for t in types[1:]:
        result = _join_types(joined, t)
        if result is None:
            return None
        joined = result
    return joined


# Decorators that provably do NOT transform a function's return value, so the
# type inferred from the body's ``return`` statements is still SOUND when one is
# present. EVERYTHING ELSE — an unknown user decorator, ``@contextmanager``, a
# ``@functools.wraps``-built wrapper, ``str``-casting wrappers like the
# denetçi's ``@make_str`` — may REPLACE the return with a value of another type,
# so a body-inferred ``-> T`` would be a verified LIE.
#   - ``property`` / ``cached_property``: the descriptor returns the getter's own
#     value unchanged (``cached_property`` memoises identity, not type).
#   - ``staticmethod`` / ``classmethod``: rebind ``self``/``cls`` only; the
#     underlying call returns the body's value untouched.
#   - ``functools.cache`` / ``functools.lru_cache``: memoise — first call returns
#     the body's value; cached calls replay that SAME object.
#   - ``functools.wraps``: copies metadata onto a wrapper; it does not itself wrap
#     a return (it is applied to the inner wrapper, whose body we read directly).
#   - ``abstractmethod`` / ``final`` / ``override``: pure typing/ABC markers — no
#     runtime call interposition at all.
#
# NAME-COLLISION TIGHTENING (denetçi a4f889fe): a LAST-NAME-only match re-opened
# the lie when a user SHADOWS a trusted name with a return-TRANSFORMING callable
# — a local ``def property(fn): return str(fn())`` then ``@property``, an
# ``import wrap as lru_cache`` then ``@lru_cache``, or a dotted ``@x.property``
# whose ``x`` is some object. Each matches the bare/last name yet does NOT denote
# the trusted builtin/stdlib member, so the body-inferred type would again be a
# verified LIE. The trust rule is therefore tightened to a FORM check
# (:func:`_decorator_is_type_transparent`), refuse-only (it can only narrow what
# was trusted, never widen — so no honest landing breaks):
#   - a BARE ``ast.Name`` allow-list member (``@property``, ``@lru_cache``) is
#     trusted ONLY when that name is NOT bound at MODULE top level (a ``def`` /
#     ``class`` / assignment / ``import ... as`` creating it = shadowed → refuse);
#   - a DOTTED ``ast.Attribute`` allow-list member is trusted ONLY when its ROOT
#     name is literally ``functools`` / ``typing`` / ``abc``
#     (:data:`_TRANSPARENT_DECORATOR_ROOTS`) — so ``@functools.lru_cache`` and
#     ``@abc.abstractmethod`` stay trusted while ``@x.property`` / ``@a.b.cache``
#     refuse;
#   - the ``Call`` forms (``@lru_cache(maxsize=…)``) unwrap to the same checks.
_TYPE_TRANSPARENT_DECORATORS: frozenset[str] = frozenset({
    "property",
    "cached_property",
    "staticmethod",
    "classmethod",
    "cache",
    "lru_cache",
    "wraps",
    "abstractmethod",
    "final",
    "override",
})


# The ONLY dotted ROOT names a trusted decorator member may resolve through. A
# dotted decorator whose root is anything else (``@x.property``, ``@a.b.cache``)
# denotes an attribute of some user object, NOT the stdlib member, so it is
# refused. ``cached_property``/``cache``/``lru_cache``/``wraps`` live in
# ``functools``; ``final``/``override`` in ``typing``; ``abstractmethod`` in
# ``abc`` (``property``/``staticmethod``/``classmethod`` are builtins, used bare).
_TRANSPARENT_DECORATOR_ROOTS: frozenset[str] = frozenset({
    "functools", "typing", "abc",
})


def _decorator_last_name(node: ast.expr) -> str | None:
    """The LAST identifier of a decorator expression, or ``None`` when it is not a
    plain name/attribute reference (e.g. a subscript or lambda).

    Unwraps a ``Call`` first (``@lru_cache(maxsize=8)`` → the ``lru_cache``
    reference), then reads a bare ``Name`` (``@property`` → ``"property"``) or the
    final attribute of a dotted path (``@functools.lru_cache`` → ``"lru_cache"``).
    A non-reference decorator (a ``Subscript``, a ``Call`` of a non-reference, etc.)
    has no resolvable name and yields ``None`` — which the caller treats as
    non-transparent (refuse)."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _decorator_root_name(node: ast.expr) -> str | None:
    """The LEFTMOST identifier of a DOTTED decorator (``@functools.lru_cache`` →
    ``"functools"``, ``@a.b.cache`` → ``"a"``), or ``None`` when the decorator is
    not a dotted ``ast.Attribute`` reference.

    Unwraps a ``Call`` first, then — only for an ``ast.Attribute`` — walks the
    ``.value`` chain to its base ``ast.Name``. A bare ``Name`` decorator
    (``@property``) is NOT dotted, so it yields ``None`` here (the caller routes a
    bare name through the module-shadow check instead)."""
    if isinstance(node, ast.Call):
        node = node.func
    if not isinstance(node, ast.Attribute):
        return None
    cur: ast.expr = node.value
    while isinstance(cur, ast.Attribute):
        cur = cur.value
    return cur.id if isinstance(cur, ast.Name) else None


def _decorator_is_type_transparent(
    node: ast.expr, module_bound_names: frozenset[str]
) -> bool:
    """True when ONE decorator is a trusted return-preserving form (see the
    :data:`_TYPE_TRANSPARENT_DECORATORS` block) under the name-collision
    tightening, else ``False`` (refuse).

    The last identifier must be in the allow-list AND the FORM must denote the
    real builtin/stdlib member, not a same-named user shadow:
      - a BARE ``ast.Name`` (``@property``/``@lru_cache``, possibly ``Call``-wrapped)
        is trusted ONLY when its name is NOT in ``module_bound_names`` — a module
        top-level ``def``/``class``/assignment/``import ... as`` that creates the
        name has SHADOWED the builtin/import, so the decorator may transform the
        return ⇒ refuse;
      - a DOTTED ``ast.Attribute`` is trusted ONLY when its ROOT name is one of
        :data:`_TRANSPARENT_DECORATOR_ROOTS` (``functools``/``typing``/``abc``) —
        ``@x.property`` / ``@a.b.cache`` resolve through a user object, not the
        stdlib, ⇒ refuse;
      - any other shape (a ``Subscript``, a non-reference ``Call``) has no
        allow-listed name ⇒ refuse."""
    last = _decorator_last_name(node)
    if last not in _TYPE_TRANSPARENT_DECORATORS:
        return False
    root = _decorator_root_name(node)
    if root is not None:
        # Dotted form: trusted only through a known stdlib root.
        return root in _TRANSPARENT_DECORATOR_ROOTS
    # Bare-name form: trusted only when NOT shadowed at module scope.
    return last not in module_bound_names


def _has_only_type_transparent_decorators(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    module_bound_names: frozenset[str],
) -> bool:
    """True when EVERY decorator on ``fn`` is a trusted return-preserving form
    (:func:`_decorator_is_type_transparent`), so a body-inferred return type stays
    sound. An undecorated function is trivially transparent (``all`` over an empty
    list). A single decorator that is an arbitrary user wrapper — or a same-named
    SHADOW of a trusted name (a local ``def property`` / an ``import ... as
    lru_cache`` / a dotted ``@x.property``) — makes this ``False`` (refuse)."""
    return all(
        _decorator_is_type_transparent(dec, module_bound_names)
        for dec in fn.decorator_list
    )


def _infer_return_type(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    class_name: str | None = None,
    module_bound_names: frozenset[str] = frozenset(),
) -> str | None:
    """The provable return type for ``fn``, or ``None`` if not provable.

    - A decorator that may TRANSFORM the return value (anything outside the
      type-transparent allow-list :data:`_TYPE_TRANSPARENT_DECORATORS` — an
      unknown user wrapper, ``@contextmanager``, a ``str``-casting wrapper, or a
      same-named SHADOW of a trusted name) makes the body's return type unsound,
      so the function is refused. Only provably return-preserving decorators
      (``property``/``staticmethod``/``classmethod``/``cached_property``/``cache``/
      ``lru_cache``/``wraps``/``abstractmethod``/``final``/``override``) are
      inferred through, and only in the trusted FORM (a bare name not shadowed at
      module scope, or a dotted ``functools``/``typing``/``abc`` member) —
      :func:`_has_only_type_transparent_decorators`, threaded
      ``module_bound_names`` from :func:`infer_annotations`.
    - A generator (own ``yield``) is never inferred (its return is an iterator).
    - ``-> None`` when there is no value return (``return`` with no value, or no
      return at all) — a pure procedure.
    - Otherwise every value return must be of the SAME concrete type — either a
      literal (:func:`_literal_type`) or a FIXED-result ``<builtin>(...)`` call
      (:func:`_builtin_call_returns_type`, guarded against a shadowed builtin via
      the function's own bound names). A bare ``return`` mixed with value
      returns, differing types, or any non-provable return is ambiguous →
      ``None`` (skip).
    - And the body must PROVABLY terminate (cannot fall off the end): a function
      that can reach the end without an explicit ``return`` implicitly returns
      ``None``, so its true type is ``T | None``. Rather than guess the union we
      REFUSE (return ``None``) — the honest under-claim this module promises.
    - As a LAST resort, when the literal/builtin join above proves nothing, a
      ``self`` / ``cls(...)`` return earns the forward-ref ``"<class_name>"``
      (:func:`_infer_self_return_type`, fed the enclosing ``class_name`` the
      caller resolved). This fires ONLY after every shared precondition above has
      passed, so it can never override or widen a literal landing."""
    if not _has_only_type_transparent_decorators(fn, module_bound_names):
        return None  # a non-transparent decorator may replace the return value
    if fn.returns is not None:
        return None  # already annotated — never overwrite
    if _has_own_yield(fn):
        return None

    returns = _own_returns(fn)
    value_returns = [r for r in returns if r.value is not None]
    has_bare = any(r.value is None for r in returns)

    if not value_returns:
        # No value ever returned: a pure procedure returns None.
        return "None"

    if has_bare:
        # Mixes ``return`` (=> None) with ``return <expr>`` — ambiguous union.
        return None

    if not _body_terminates(fn.body):
        # Can fall off the end → implicit ``return None`` → true type is
        # ``T | None``. Refuse rather than land a wrong bare ``-> T``.
        return None

    assigned = _assigned_names_in_scope(fn)
    types: list[str] = []
    for r in value_returns:
        t = _return_value_type(r.value, assigned)  # r.value is not None here
        if t is None:
            # No LITERAL/builtin type for this return. Before giving up, try the
            # language-contract ``self``/``cls(...)`` case (a Name/Call the
            # literal oracle deliberately refuses) — sound only as a WHOLE-body
            # property, so it inspects every value-return itself.
            return _infer_self_return_type(
                fn, value_returns, class_name, assigned)
        types.append(t)
    # JOIN the (source-ordered) return types to a single least-upper-bound: a
    # set of returns sharing one container agrees on the precise parametrized
    # type when identical, else WIDENS to the bare base (``list[int]`` +
    # bare ``list`` -> ``list``); differing bases still refuse (``None``).
    return _join_all_types(types)


def _is_classmethod(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when ``fn`` carries a ``@classmethod`` decorator — accepted as a bare
    ``classmethod`` name or a dotted ``...classmethod`` (e.g. ``@builtins.classmethod``).

    Used to gate the ``cls(...)`` self-return case: a ``cls(...)`` body is a sound
    ``-> "<Class>"`` ONLY under ``@classmethod`` (there ``cls`` is the class object
    by language contract). A plain method whose first parameter merely happens to
    be named ``cls`` carries NO such guarantee, so it must refuse."""
    return any(
        _decorator_last_name(dec) == "classmethod" for dec in fn.decorator_list
    )


def _has_receiver_breaking_decorator(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """True when ``fn`` carries ``@staticmethod`` or ``@property`` — decorators
    that BREAK the ``self``/``cls`` receiver contract the self-return case relies
    on. A ``@staticmethod`` has no receiver at all; a ``@property``'s call returns
    the ATTRIBUTE value, not the instance, so ``-> "<Class>"`` would be wrong even
    if the body literally ``return self``. Both refuse the self-return case
    (the literal path already handles a ``@property``/``@staticmethod`` returning a
    provable literal — this guard only suppresses the self/cls fallback)."""
    return any(
        _decorator_last_name(dec) in ("staticmethod", "property")
        for dec in fn.decorator_list
    )


def _all_value_returns_are(
    value_returns: list[ast.Return], predicate
) -> bool:
    """True when ``value_returns`` is non-empty and EVERY return value satisfies
    ``predicate`` — the "every value-return path" check the self-return soundness
    argument requires (one non-matching arm makes the union unprovable)."""
    return bool(value_returns) and all(
        predicate(r.value) for r in value_returns
    )


def _returns_self(node: ast.expr | None) -> bool:
    """True when ``node`` is exactly the bare name ``self``."""
    return isinstance(node, ast.Name) and node.id == "self"


def _returns_cls_call(node: ast.expr | None) -> bool:
    """True when ``node`` is a ``cls(...)`` call — the callee is the bare name
    ``cls`` (args are irrelevant; ``cls(n)`` constructs the same class as
    ``cls()``). A ``cls.method()`` (callee is an ``Attribute``) or a bare ``cls``
    (not called) is NOT this shape."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "cls"
    )


def _infer_self_return_type(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    value_returns: list[ast.Return],
    class_name: str | None,
    assigned: frozenset[str],
) -> str | None:
    """The forward-ref ``"<class_name>"`` for a method whose EVERY value-return is
    the receiver, or ``None`` (refuse).

    Two sound shapes — the receiver is, by Python's language contract, an instance
    of the enclosing class (or a subclass, and is-a holds, so ``-> "<Class>"`` is a
    SOUND UPPER BOUND):
      - a plain instance method whose every value-return is exactly ``self``;
      - a ``@classmethod`` whose every value-return is ``cls(...)`` (constructs an
        instance of the class/subclass — same bound).

    The result is the forward-ref STRING ``f'"{class_name}"'`` (NOT ``typing.Self``)
    so there is no import and no version gate; a string annotation is never
    evaluated at runtime and changes no value — behaviour-identical.

    REFUSES (returns ``None``) when ANY holds — the full refusal set:
      - no single resolvable enclosing ``ClassDef`` (``class_name is None``: a
        module-level function or a nested-function-in-method returning ``self``);
      - ``@staticmethod`` / ``@property`` (receiver contract broken —
        :func:`_has_receiver_breaking_decorator`);
      - the receiver name (``self`` for the instance shape, ``cls`` for the
        classmethod shape) is REASSIGNED in the body (``receiver in assigned`` via
        :func:`_assigned_names_in_scope`) — the returned name may no longer be the
        receiver;
      - instance shape: any value-return is NOT exactly ``self`` (an attribute
        ``self.x``, another name, a call, a new object) — mixed ⇒ refuse;
      - classmethod shape: any value-return is NOT ``cls(...)`` — a bare ``cls``, a
        ``cls.method()``, an ``OtherClass(...)`` ⇒ refuse;
      - a ``cls(...)`` body NOT under ``@classmethod`` ⇒ refuse (no class-object
        guarantee for ``cls``).
    The shared preconditions (already-annotated, generator, bare-return mix,
    non-terminating body) are enforced by :func:`_infer_return_type` before this
    is ever reached."""
    if class_name is None:
        return None  # not inside exactly one resolvable enclosing ClassDef
    if _has_receiver_breaking_decorator(fn):
        return None  # @staticmethod / @property breaks the receiver contract

    if _is_classmethod(fn):
        # Classmethod shape: every value-return must be ``cls(...)`` and ``cls``
        # must not have been rebound in the body.
        if "cls" in assigned:
            return None
        if not _all_value_returns_are(value_returns, _returns_cls_call):
            return None
        return f'"{class_name}"'

    # Instance shape: every value-return must be exactly ``self`` and ``self``
    # must not have been rebound in the body. (A ``cls(...)`` body that is NOT a
    # ``@classmethod`` falls here and fails the ``self`` predicate ⇒ refuse,
    # which is the "cls(...) without @classmethod" refusal.)
    if "self" in assigned:
        return None
    if not _all_value_returns_are(value_returns, _returns_self):
        return None
    return f'"{class_name}"'


def _return_value_type(node: ast.expr, assigned_names: frozenset[str]) -> str | None:
    """The provable type NAME for a single ``return <expr>`` value, or ``None``.

    A fully-LITERAL display is PARAMETRIZED here first
    (:func:`_parametrized_display_type` — ``[1, 2]`` ⇒ ``list[int]``, ``(1, 'a')``
    ⇒ ``tuple[int, str]``), so the return surface lands the precise generic while
    the bare-container fallback below still covers empty/mixed/comprehension
    displays. Failing that, a literal/display/etc. (:func:`_literal_type`, the
    pure context-free oracle — the BARE container for a display); failing that, a
    FIXED-result ``<builtin>(...)`` call (:func:`_builtin_call_returns_type`, with
    the shadowing guard ``assigned_names`` from the function's own scope); failing
    that, a SAME-TYPE conditional expression (:func:`_ifexp_same_type`, a ``X if C
    else Y`` whose branches both prove to the SAME type by recursing through this
    very resolver — so a ternary of two ``list[int]`` branches lands ``list[int]``
    while a ``list[int]`` vs bare-``list`` ternary disagrees and refuses).

    Parametrization is deliberately confined to THIS return-value surface, NOT
    pushed into :func:`_literal_type`: ``_literal_type`` stays the pure
    context-free literal oracle reused recursively by the binop/str-method/
    sequence-mult rules (which classify by the BARE container kind and compare
    operand types), so those rules are unchanged; and a builtin call is NOT a
    literal there (so ``len(x) + 1`` correctly stays unprovable — the binop
    recursion never sees this builtin-call rule)."""
    parametrized = _parametrized_display_type(node)
    if parametrized is not None:
        return parametrized  # a fully-literal display -> ``list[int]`` etc.
    literal = _literal_type(node)
    if literal is not None:
        return literal  # empty/mixed/comprehension display -> bare container
    builtin = _builtin_call_returns_type(node, assigned_names)
    if builtin is not None:
        return builtin
    return _ifexp_same_type(node, assigned_names)


def _ifexp_same_type(node: ast.expr, assigned_names: frozenset[str]) -> str | None:
    """The provable type NAME for a conditional expression ``X if C else Y``
    (``ast.IfExp``), or ``None`` when not provable.

    A ternary's runtime value is EXACTLY one of its two branches — never the
    condition — so its concrete type is provable IFF both branches PROVABLY
    share the SAME type. Each branch (``node.body`` = ``X``, ``node.orelse`` =
    ``Y``) is resolved by RECURSING through :func:`_return_value_type`, the same
    full return-value oracle, so every existing soundness rule applies to each
    branch unchanged and nested ternaries compose by recursion: ``a if c else
    (b if d else e)`` proves only when every leaf agrees on type.

    Returns that shared type ONLY when BOTH branches are non-``None`` AND equal;
    otherwise ``None`` (refuse). The condition ``C`` is intentionally NOT
    inspected — it does not contribute to the result's type. The LOCKED refusals
    therefore hold automatically through the recursion: a branch that is an
    unsound ``==`` comparison, a ``/``/``**`` binop, a bare name, or an unknown
    call yields ``None`` for that branch and so refuses the whole ternary; and
    two branches of DIFFERENT provable types (``1 if c else 'x'`` ⇒ ``int`` vs
    ``str``) refuse as well."""
    if not isinstance(node, ast.IfExp):
        return None
    body_type = _return_value_type(node.body, assigned_names)
    if body_type is None:
        return None
    else_type = _return_value_type(node.orelse, assigned_names)
    if else_type is None:
        return None
    # JOIN the two branch types: identical parametrized branches keep the precise
    # form (``[1] if c else [2]`` -> ``list[int]``), a parametrized vs a bare /
    # differing-param branch of the SAME container WIDENS to the bare base
    # (``[1] if c else []`` -> ``list``), and DIFFERENT bases still refuse.
    return _join_types(body_type, else_type)


# Bare type NAMES accepted as an isinstance guard's class. A guard is a runtime-
# ENFORCED bound, so the inferred annotation is PROVABLE — but only when the
# class is a well-known builtin type: a bare ``Name`` that is NOT a builtin could
# be a locally rebound or user alias whose identity we cannot resolve from the
# AST alone, so we refuse it (conservative, deterministic). ``bool`` is included
# (``isinstance(x, bool)`` enforces the precise ``bool``, unlike a return-side
# bool subtlety). A MULTI-element tuple-of-classes (``(int, float)``) would need a
# ``Union`` and is refused by :func:`_isinstance_single_class`, but a STRICT
# one-element tuple (``(int,)``) is just that single class and is accepted there.
_GUARD_CLASS_NAMES: frozenset[str] = frozenset({
    "int", "float", "str", "bytes", "bool", "bytearray", "complex",
    "list", "dict", "set", "frozenset", "tuple", "type", "object",
})


def _isinstance_single_class(call: ast.expr) -> tuple[str, str] | None:
    """``(param_name, class_name)`` for ``isinstance(<Name>, <BareName>)``, else
    ``None``.

    Accepts ONLY the SINGLE-class shape: the first arg is a bare parameter
    ``ast.Name`` and the second arg names exactly ONE known builtin type in
    :data:`_GUARD_CLASS_NAMES` — either a bare ``ast.Name`` (``isinstance(x,
    int)``) or a strict ONE-element tuple of one bare ``ast.Name``
    (``isinstance(x, (int,))`` ≡ ``isinstance(x, int)``, a single bound). REFUSED
    conservatively:
      - a non-``isinstance`` call, or wrong arg count / any keyword/star arg;
      - a MULTI-element tuple second arg (``isinstance(x, (int, float))``) — that
        is a Union of types, not a single bound, so we cannot name one type (an
        EMPTY tuple ``()`` binds nothing either) — strict ``len == 1``;
      - a one-element tuple whose sole element is NOT a bare ``ast.Name``
        (``isinstance(x, (numbers.Integral,))``);
      - a DOTTED / complex class expr (``numbers.Integral``) — an
        ``ast.Attribute``/``ast.Subscript``/call is not a bare type Name;
      - a class Name outside the known-builtin set (could be a user alias whose
        identity is not AST-resolvable)."""
    if not isinstance(call, ast.Call) or call.keywords:
        return None
    func = call.func
    if not (isinstance(func, ast.Name) and func.id == "isinstance"):
        return None
    if len(call.args) != 2:
        return None
    obj, cls = call.args
    # A strict ONE-element tuple ``(int,)`` is exactly the single class ``int``;
    # any other tuple length (0, or 2+ ⇒ Union) stays refused below.
    if isinstance(cls, ast.Tuple):
        if len(cls.elts) != 1:
            return None
        cls = cls.elts[0]
    if not (isinstance(obj, ast.Name) and isinstance(cls, ast.Name)):
        return None
    if cls.id not in _GUARD_CLASS_NAMES:
        return None
    return obj.id, cls.id


def _guard_test_bindings(test: ast.expr) -> list[tuple[str, str]]:
    """Every ``(param_name, class_name)`` a guard's TEST expression PROVES, or
    ``[]`` when the test is not a recognised single-class isinstance guard
    (possibly conjoined). The shared splitter behind the assert and the
    ``if not (...): raise`` paths.

    Two recognised shapes:
      - a SINGLE ``isinstance(p, Cls)`` (the existing leaf,
        :func:`_isinstance_single_class`) ⇒ ``[(p, Cls)]``;
      - a CONJUNCTION ``isinstance(a, A) and isinstance(b, B) and ...`` (an
        ``ast.BoolOp`` with an ``ast.And`` op) ⇒ the concatenation of EACH
        operand's single-class binding, in source order. EVERY operand must be a
        recognised single-class isinstance guard; if ANY operand is not (an
        ``or`` sub-term, a tuple-of-classes isinstance, a non-isinstance
        comparison, ...), the WHOLE conjunction yields ``[]`` — no partial bind.

    SOUND for ``and`` because the guard raises unless EVERY conjunct holds, so a
    path that continues past it has PROVEN each conjoined parameter's type —
    identical runtime enforcement to the single-guard leaf. ``or`` is REFUSED
    (an ``ast.BoolOp``/``ast.Or`` falls through here to ``[]``): an ``or`` guard
    proves NEITHER operand's type, so it binds nothing. A MULTI-element
    tuple-second-arg isinstance stays a Union (refused by the leaf), so a conjunct
    using it contributes no binding and thus refuses the whole conjunction (a
    strict one-element tuple is the single class and binds via the leaf)."""
    leaf = _isinstance_single_class(test)
    if leaf is not None:
        return [leaf]
    if not (isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And)):
        return []  # not a single guard and not an `and` — e.g. `or` ⇒ no bind
    out: list[tuple[str, str]] = []
    for operand in test.values:
        operand_leaf = _isinstance_single_class(operand)
        if operand_leaf is None:
            return []  # any non-single-class conjunct voids the whole guard
        out.append(operand_leaf)
    return out


def _if_negation_bindings(stmt: ast.stmt) -> list[tuple[str, str]]:
    """Every ``(param, class)`` for ``if not (<guard test>): raise ...`` (the
    if-body raises on the NEGATION of a recognised single-class isinstance guard,
    possibly conjoined via :func:`_guard_test_bindings`), or ``[]``.

    SOUND only when ALL hold: the test is ``not <guard>`` (a single
    ``UnaryOp``/``Not`` over an accepted single-class isinstance or an ``and`` of
    them), there is NO ``else`` branch, and the if-body is EXACTLY a single
    ``raise``. Requiring the body to be one bare ``raise`` is conservative — it
    cannot fall through to code that runs with a parameter of the wrong type — so
    reaching past the guard PROVES every bound conjunct held. ``not (a or b)``
    proves NEITHER (the splitter refuses ``or``), so it binds nothing."""
    if not isinstance(stmt, ast.If) or stmt.orelse:
        return []
    test = stmt.test
    if not (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)):
        return []
    if len(stmt.body) != 1 or not isinstance(stmt.body[0], ast.Raise):
        return []
    return _guard_test_bindings(test.operand)


def _entry_guard_bindings(stmt: ast.stmt) -> list[tuple[str, str]]:
    """Every ``(param, class)`` when ``stmt`` is an accepted runtime type guard,
    or ``[]``.

    Two forms, both of which ENFORCE the type(s) at run time so a path that
    reaches past the guard PROVES every bound parameter is an instance of its
    class:
      - ``assert <guard test>`` (an optional message is ignored — the
        ``Assert``'s ``msg`` does not affect the bound);
      - ``if not (<guard test>): raise <...>`` (see
        :func:`_if_negation_bindings`).

    The ``<guard test>`` is a single ``isinstance(p, Cls)`` OR an ``and`` of
    such single-class isinstance guards (split by :func:`_guard_test_bindings`),
    so ``assert isinstance(x, A) and isinstance(y, B)`` binds both ``x`` and
    ``y``. An ``or`` test binds nothing (it proves neither operand)."""
    if isinstance(stmt, ast.Assert):
        return _guard_test_bindings(stmt.test)
    return _if_negation_bindings(stmt)


def _if_negation_raises(stmt: ast.stmt) -> tuple[str, str] | None:
    """``(param, class)`` for a SINGLE ``if not isinstance(p, Cls): raise ...``,
    else ``None``. The single-binding view kept for backward compatibility;
    :func:`_if_negation_bindings` is the conjunction-aware form the prologue
    uses. Returns the lone binding only when the guard test binds EXACTLY one
    parameter (a bare single-class isinstance)."""
    bindings = _if_negation_bindings(stmt)
    return bindings[0] if len(bindings) == 1 else None


def _entry_guard_binding(stmt: ast.stmt) -> tuple[str, str] | None:
    """``(param, class)`` when ``stmt`` is an accepted SINGLE-parameter runtime
    type guard, else ``None``. The single-binding view kept for backward
    compatibility (and direct unit checks); :func:`_entry_guard_bindings` is the
    conjunction-aware form the prologue uses. Returns the lone binding only when
    the guard binds EXACTLY one parameter."""
    bindings = _entry_guard_bindings(stmt)
    return bindings[0] if len(bindings) == 1 else None


def _guard_prologue_bindings(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, str]:
    """``{param_name: class_name}`` from the UNCONDITIONAL guard prologue — the
    contiguous run of entry guards that opens the body (an optional leading
    docstring may precede them).

    Walks ``fn.body`` top-level statements in order, skipping ONE leading
    docstring, and stops at the FIRST statement that is not an accepted guard
    (:func:`_entry_guard_bindings`). Stopping there is what makes the result
    sound: every collected guard runs UNCONDITIONALLY at entry (it is a direct
    body statement, never nested under another ``if``/``for``/``try``), and no
    non-guard statement has executed before it — so the parameter has NOT been
    reassigned or used and the guard binds the ORIGINAL parameter. The FIRST
    binding for a name wins (a later re-guard cannot loosen it).

    A SINGLE statement may bind MULTIPLE parameters when its guard test is a
    CONJUNCTION (``assert isinstance(x, A) and isinstance(y, B)`` ⇒ both ``x``
    and ``y``); :func:`_entry_guard_bindings` returns each conjunct's binding in
    source order, and within that one statement the first occurrence of a name
    still wins."""
    bindings: dict[str, str] = {}
    body = fn.body
    start = 0
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        start = 1  # skip a leading docstring; it may precede the first guard
    for stmt in body[start:]:
        stmt_bindings = _entry_guard_bindings(stmt)
        if not stmt_bindings:
            break  # prologue ends — anything after is not an entry guard
        for name, class_name in stmt_bindings:
            if name not in bindings:
                bindings[name] = class_name
    return bindings


def _all_args(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    """Every ``ast.arg`` of ``fn`` across all parameter kinds (posonly, normal,
    ``*vararg``, kw-only, ``**kwarg``) — the candidates a guard might bind."""
    args = fn.args
    out: list[ast.arg] = [*args.posonlyargs, *args.args]
    if args.vararg is not None:
        out.append(args.vararg)
    out.extend(args.kwonlyargs)
    if args.kwarg is not None:
        out.append(args.kwarg)
    return out


def _annotatable_params(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[ast.arg, str]]:
    """``(arg, type_name)`` for each parameter whose type is PROVABLE from an
    UNCONDITIONAL runtime ``isinstance`` guard at function entry.

    A guard is a runtime-ENFORCED type bound — unlike a default value, which is
    NOT a bound (``def f(x=0)`` is legitimately called ``f("s")``; inferring
    ``x: int`` from ``x=0`` is the UNSOUND, wrong-but-verified landing this
    module exists to avoid, so the default-value path stays REMOVED). A guard is
    different: when

      - ``assert isinstance(x, str)`` or
      - ``if not isinstance(x, int): raise TypeError``

    appears UNCONDITIONALLY at entry, every path that continues past it has
    PROVEN ``x`` is an instance of that class. The annotation merely RECORDS that
    runtime-enforced fact; it changes no runtime value, so it cannot contradict
    the project's tests (any value the guard would reject already raises today).
    A SINGLE CONJOINED guard binds EACH conjoined parameter
    (``assert isinstance(x, A) and isinstance(y, B)`` ⇒ both), sound because the
    guard raises unless EVERY conjunct holds (see :func:`_guard_test_bindings`);
    an ``or`` guard proves neither operand and so binds nothing.

    Soundness — all enforced by :func:`_guard_prologue_bindings`,
    :func:`_guard_test_bindings`, and :func:`_isinstance_single_class`:
      - the guard is UNCONDITIONAL (a direct body statement in the contiguous
        entry prologue — never nested under another ``if``/``for``/``try``);
      - each bound class is a SINGLE bare-``Name`` builtin (a tuple
        ``(int, float)`` would need a ``Union`` ⇒ refuse; a dotted/complex class
        ⇒ refuse), and a conjunction binds only when EVERY conjunct is one;
      - the parameter is NOT reassigned or used before its guard (the prologue is
        only guards, so the guard binds the ORIGINAL parameter);
      - the parameter has NO existing annotation (we never overwrite — checked
        here against ``arg.annotation``).

    Returns ``[]`` when no such guard is present (the honest no-op)."""
    bindings = _guard_prologue_bindings(fn)
    if not bindings:
        return []
    out: list[tuple[ast.arg, str]] = []
    for arg in _all_args(fn):
        if arg.annotation is not None:
            continue  # never overwrite an existing annotation
        class_name = bindings.get(arg.arg)
        if class_name is not None:
            out.append((arg, class_name))
    return out


def _function_edits(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    source: str,
    line_starts: list[int],
    class_name: str | None = None,
    module_bound_names: frozenset[str] = frozenset(),
) -> list[tuple[int, int, str]]:
    """The ``(start, end, text)`` splice edits for one function: a ``: T`` after
    each parameter whose type is PROVABLE from an entry ``isinstance`` guard
    (:func:`_annotatable_params`), plus a `` -> T`` before the header colon when
    the return is provable. Offsets are absolute into ``source``.

    ``class_name`` is the enclosing ``ClassDef`` name (or ``None`` for a non-method
    function), and ``module_bound_names`` the module's top-level bound names — both
    resolved by :func:`infer_annotations` (an ``ast.FunctionDef`` carries no parent
    pointer) and threaded into :func:`_infer_return_type` for the ``self``/``cls``
    forward-ref case and the name-collision decorator-trust tightening."""
    edits: list[tuple[int, int, str]] = []
    for arg, type_name in _annotatable_params(fn):
        off = _end_offset(arg, line_starts)
        if off is not None:
            edits.append((off, off, f": {type_name}"))

    ret = _infer_return_type(fn, class_name, module_bound_names)
    if ret is not None:
        colon = _header_colon_offset(fn, source, line_starts)
        if colon is not None:
            edits.append((colon, colon, f" -> {ret}"))
    return edits


def _module_bound_names(tree: ast.Module) -> frozenset[str]:
    """Every NAME bound at the MODULE top level — a ``def``/``class`` name, an
    ``import``/``from`` import name (the ``as`` alias when present, else the
    leftmost component), and any assignment/walrus/``for``/``with`` Store target in
    a top-level statement.

    The decorator name-collision tightening uses this as the SHADOW set: a bare
    ``@property`` / ``@lru_cache`` is trusted only when its name is NOT here, so a
    local ``def property(...)`` or an ``import wrap as lru_cache`` (which binds the
    trusted name to a return-TRANSFORMING callable) correctly disqualifies the bare
    form. A conservative, deterministic over-approximation: only TOP-LEVEL bindings
    matter (a name bound inside a function is that function's local, not a module
    shadow of the decorator)."""
    names: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(stmt.name)
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for alias in stmt.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign,
                               ast.For, ast.AsyncFor, ast.With, ast.AsyncWith)):
            for node in ast.walk(stmt):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    names.add(node.id)
    return frozenset(names)


def _method_class_names(tree: ast.Module) -> dict[int, str]:
    """Map ``id(method_FunctionDef)`` → its enclosing ``ClassDef`` name, for every
    method DIRECTLY in a class body (recursing into nested classes, so a method of
    an inner class maps to the INNER class name).

    Only methods that are a DIRECT statement of a ``ClassDef.body`` are paired —
    a function nested inside a method is not class-bound (its ``self``/``cls`` would
    be the inner function's parameters, not the class's), so it is absent and the
    self-return case refuses it (``class_name is None``). Keyed by ``id(node)``
    because an ``ast.FunctionDef`` carries no parent pointer; the resolved name is
    threaded to :func:`_infer_self_return_type`."""
    out: dict[int, str] = {}

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                for stmt in child.body:
                    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        out[id(stmt)] = child.name
                walk(child)  # recurse for nested classes / inner methods
            else:
                walk(child)

    walk(tree)
    return out


def infer_annotations(source: str) -> str | None:
    """Return ``source`` with every provable annotation added, or ``None`` when
    nothing provable changes (or the source does not parse).

    Edits are applied by byte offset, right-to-left, so earlier offsets stay
    valid as later ones are spliced in. Pure AST → text; deterministic.

    Before walking functions, two module-wide facts an ``ast.FunctionDef`` cannot
    carry alone are resolved once: :func:`_method_class_names` pairs each method
    with its enclosing class (for the ``self``/``cls`` forward-ref case), and
    :func:`_module_bound_names` collects the top-level bound names (the shadow set
    for the decorator name-collision tightening). Both are threaded into
    :func:`_function_edits`; a non-method function simply gets ``class_name=None``,
    so its behaviour is unchanged."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError, ValueError):
        return None

    func_nodes = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    # Deterministic order (source order) — offsets are absolute so order only
    # affects which edits we collect, not their application.
    func_nodes.sort(key=lambda n: (n.lineno, n.col_offset))

    class_names = _method_class_names(tree)
    module_bound = _module_bound_names(tree)
    line_starts = _line_start_offsets(source.splitlines(keepends=True))
    edits: list[tuple[int, int, str]] = []
    for fn in func_nodes:
        edits.extend(_function_edits(
            fn, source, line_starts, class_names.get(id(fn)), module_bound))

    if not edits:
        return None

    # Apply right-to-left so offsets stay valid.
    edits.sort(key=lambda e: e[0], reverse=True)
    out = source
    for start, end, text in edits:
        out = out[:start] + text + out[end:]

    if out == source:
        return None
    # The result must still parse — a defensive guard; provable edits always do.
    try:
        ast.parse(out)
    except (SyntaxError, ValueError):
        return None
    return out


def _line_start_offsets(lines: list[str]) -> list[int]:
    """Absolute byte offset where each 1-based line begins (index 0 unused)."""
    offsets = [0, 0]
    acc = 0
    for line in lines:
        acc += len(line)
        offsets.append(acc)
    return offsets


def _abs_offset(lineno: int, col: int, line_starts: list[int]) -> int | None:
    if 0 < lineno < len(line_starts):
        return line_starts[lineno] + col
    return None


def _end_offset(node: ast.AST, line_starts: list[int]) -> int | None:
    """Absolute offset just past ``node`` (uses end_lineno/end_col_offset)."""
    end_lineno = getattr(node, "end_lineno", None)
    end_col = getattr(node, "end_col_offset", None)
    if end_lineno is None or end_col is None:
        return None
    return _abs_offset(end_lineno, end_col, line_starts)


def _header_scan_start(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, line_starts: list[int]
) -> int | None:
    """Where to begin scanning for the header ``:`` — just past the LAST
    parameter (so the first top-level colon is the header's), or, with no
    parameters, the function's own header position. (The *function* node's end
    is the body's end, which would find the wrong colon.)"""
    args = fn.args
    anchor: ast.AST | None = (
        args.kwarg
        or (args.kwonlyargs[-1] if args.kwonlyargs else None)
        or args.vararg
        or (args.args[-1] if args.args else None)
        or (args.posonlyargs[-1] if args.posonlyargs else None)
    )
    start = _end_offset(anchor, line_starts) if anchor is not None else None
    if start is None:
        start = _abs_offset(fn.lineno, fn.col_offset, line_starts)
    return start


def _scan_top_level_colon(source: str, start: int) -> int | None:
    """Offset of the first ``:`` at bracket-depth 0 from ``start``, skipping
    string literals and ``#`` comments. None if none is found."""
    depth = 0
    i = start
    n = len(source)
    quote: str | None = None
    while i < n:
        ch = source[i]
        if quote is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "#":
            nl = source.find("\n", i)
            if nl == -1:
                return None
            i = nl
            continue
        elif ch == ":" and depth <= 0:
            return i
        i += 1
    return None


def _header_colon_offset(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, source: str, line_starts: list[int]
) -> int | None:
    """Offset of the ``:`` that ends the def header (where ``-> T`` is inserted).

    Scans from just past the parameter list and returns the first top-level
    ``:``; ``-> T`` is then spliced immediately before that colon."""
    start = _header_scan_start(fn, line_starts)
    if start is None:
        return None
    return _scan_top_level_colon(source, start)


# --- Develop-objective plan --------------------------------------------------

def plan_type_annotations(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the provable-type-hint plan for one module, or an empty no-op plan.

    Annotates every function in ``module_rel`` whose return type is provable
    from the AST, plus each parameter whose type is provable from an
    unconditional entry ``isinstance`` guard (a default value is still NOT a
    sound bound; see :func:`_annotatable_params`), via :func:`infer_annotations`.
    The shared single-file-rewrite plumbing — refuse a test/fixture file, read the
    module, record the single rewrite with its original for rollback (or a no-op
    when nothing is provable) — is delegated to :func:`plan_source_rewrite`."""
    return plan_source_rewrite(
        project_root, module_rel, "infer-type-hints", infer_annotations)


def plan_annotate_self_returns(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the self/cls forward-ref return-type plan for one module, or an empty
    no-op plan — the ``annotate-self-returns`` develop-objective surface.

    Shares the SAME engine (:func:`infer_annotations`) as
    :func:`plan_type_annotations`: the self/cls forward-ref case is a branch INSIDE
    that engine, fired only where the literal oracle proves nothing. The two
    objectives therefore land complementary annotations from one transform — a
    literal-returning function gets ``-> int`` from ``infer-type-hints``, a
    ``return self`` method gets ``-> "<Class>"`` here — and never collide (they act
    on disjoint return shapes). A distinct plan LABEL (``"annotate-self-returns"``)
    is passed so this objective has its own observable plan provenance. The
    test/fixture-file refusal, the single-rewrite record with rollback, and the
    no-op-when-nothing-provable behaviour are delegated to
    :func:`plan_source_rewrite`."""
    return plan_source_rewrite(
        project_root, module_rel, "annotate-self-returns", infer_annotations)
