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
    ``bytes`` constants and displays, an f-string (``JoinedStr`` ⇒ ``str``), a
    list/dict/set comprehension (⇒ ``list``/``dict``/``set``), a certainly-
    boolean expression (a comparison or ``not x`` ⇒ ``bool``), a SAME-TYPE-
    LITERAL binary op over a TYPE-CLOSED operator (``1 + 2`` ⇒ ``int``,
    ``'a' + 'b'`` ⇒ ``str`` — see :func:`_binop_same_type_literal`), and a
    FIXED-RESULT ``<builtin>(...)`` call whose builtin's result type does not
    depend on its args and is NOT shadowed in the function's scope (``len(x)`` ⇒
    ``int``, ``sorted(x)`` ⇒ ``list`` — see :func:`_builtin_call_returns_type`),
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

A parameter type from an UNCONDITIONAL runtime ``isinstance`` guard at entry:
when ``assert isinstance(x, str)`` or ``if not isinstance(x, int): raise``
opens a function body, every path that continues past it has PROVEN ``x`` is an
instance of that class, so ``x: str`` / ``x: int`` RECORDS a runtime-ENFORCED
fact (see :func:`_annotatable_params`). Strictly SINGLE bare-builtin class only
(a tuple ``(int, float)`` would need a ``Union`` ⇒ refuse); the guard must be
unconditional (not nested) and the parameter unused/unreassigned before it.

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

from app.execution.cross_file_rename import RenamePlan

from ..result import SemanticPatchResult

__all__ = ["apply", "plan_type_annotations", "infer_annotations"]


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
    ``int`` — we want the precise ``bool``)."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
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


def _literal_type(node: ast.expr) -> str | None:
    """The provable type NAME for a return expression, or ``None`` if the
    expression's type is not statically certain from the AST alone.

    Statically certain shapes (and ONLY these — never a guess):
      - constants: ``None``/``bool``/``int``/``float``/``str``/``bytes``;
      - an f-string (``JoinedStr``) ⇒ always ``str``;
      - a display/comprehension literal ⇒ its container type
        (``list``/``dict``/``set``/``tuple``, ``ListComp``/``DictComp``/
        ``SetComp``); a ``GeneratorExp`` yields a generator, NOT a concrete
        container, so it is refused;
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
    unary = _unaryop_numeric_literal(node)
    if unary is not None:
        return unary
    mixed = _mixed_sequence_int_mult(node)
    if mixed is not None:
        return mixed
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
#   - int:  ``len``/``ord``/``id``/``hash`` always return a plain ``int``.
#   - str:  ``str``/``repr``/``ascii``/``hex``/``oct``/``bin``/``chr`` always
#           return a ``str`` (``hex(255)`` ⇒ ``'0xff'``, ``chr(65)`` ⇒ ``'A'``).
#   - bool: ``bool`` always returns a ``bool``.
#   - container: ``list``/``dict``/``set``/``tuple``/``frozenset`` each return
#           their own type; ``sorted`` always returns a ``list``.
#
# Deliberately EXCLUDED — result type is NOT fixed by the callable alone:
#   - ``min``/``max``/``sum``/``abs``/``round``/``next`` (type depends on the
#     argument values), ``int(...)``/``float(...)`` (fixed, but omitted as a
#     conservative initial set; can be added later), ``open``/``iter``/``map``/
#     ``filter``/``range``/``enumerate``/``zip``/``reversed`` (iterator/handle).
# A bare-``ast.Name`` callee is required (an attribute like ``obj.len(...)`` or
# ``m.sorted(...)`` is a DIFFERENT callable and must refuse).
_BUILTIN_CALL_RETURN_TYPES: dict[str, str] = {
    "len": "int", "ord": "int", "id": "int", "hash": "int",
    "str": "str", "repr": "str", "ascii": "str", "hex": "str",
    "oct": "str", "bin": "str", "chr": "str",
    "bool": "bool",
    "list": "list", "dict": "dict", "set": "set", "tuple": "tuple",
    "frozenset": "frozenset", "sorted": "list",
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


def _infer_return_type(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The provable return type for ``fn``, or ``None`` if not provable.

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
      REFUSE (return ``None``) — the honest under-claim this module promises."""
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
    types: set[str] = set()
    for r in value_returns:
        t = _return_value_type(r.value, assigned)  # r.value is not None here
        if t is None:
            return None  # a non-provable return — not certain
        types.add(t)
    if len(types) != 1:
        return None  # disagreeing types — ambiguous
    return next(iter(types))


def _return_value_type(node: ast.expr, assigned_names: frozenset[str]) -> str | None:
    """The provable type NAME for a single ``return <expr>`` value, or ``None``.

    A literal/display/etc. (:func:`_literal_type`) takes precedence; failing
    that, a FIXED-result ``<builtin>(...)`` call (:func:`_builtin_call_returns_type`,
    with the shadowing guard ``assigned_names`` from the function's own scope);
    failing that, a SAME-TYPE conditional expression
    (:func:`_ifexp_same_type`, a ``X if C else Y`` whose branches both prove to
    the SAME type by recursing through this very resolver). Kept separate from
    :func:`_literal_type` on purpose: ``_literal_type`` is the pure context-free
    literal oracle reused recursively by the binop/str-method/ sequence-mult
    rules, and a builtin call is NOT a literal there (so ``len(x) + 1`` correctly
    stays unprovable — the binop recursion never sees this builtin-call rule)."""
    literal = _literal_type(node)
    if literal is not None:
        return literal
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
    return body_type if _return_value_type(node.orelse, assigned_names) == body_type else None


# Bare type NAMES accepted as an isinstance guard's class. A guard is a runtime-
# ENFORCED bound, so the inferred annotation is PROVABLE — but only when the
# class is a well-known builtin type: a bare ``Name`` that is NOT a builtin could
# be a locally rebound or user alias whose identity we cannot resolve from the
# AST alone, so we refuse it (conservative, deterministic). ``bool`` is included
# (``isinstance(x, bool)`` enforces the precise ``bool``, unlike a return-side
# bool subtlety). Tuple-of-classes (``(int, float)``) is a DIFFERENT node (it
# would need a ``Union``) and is refused by :func:`_isinstance_single_class`.
_GUARD_CLASS_NAMES: frozenset[str] = frozenset({
    "int", "float", "str", "bytes", "bool", "bytearray", "complex",
    "list", "dict", "set", "frozenset", "tuple", "type", "object",
})


def _isinstance_single_class(call: ast.expr) -> tuple[str, str] | None:
    """``(param_name, class_name)`` for ``isinstance(<Name>, <BareName>)``, else
    ``None``.

    Accepts ONLY the SINGLE-class shape: the first arg is a bare parameter
    ``ast.Name`` and the second arg is a bare ``ast.Name`` whose ``id`` is a
    known builtin type in :data:`_GUARD_CLASS_NAMES`. REFUSED conservatively:
      - a non-``isinstance`` call, or wrong arg count / any keyword/star arg;
      - a TUPLE second arg (``isinstance(x, (int, float))``) — that is a Union of
        types, not a single bound, so we cannot name one type;
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
    if not (isinstance(obj, ast.Name) and isinstance(cls, ast.Name)):
        return None
    if cls.id not in _GUARD_CLASS_NAMES:
        return None
    return obj.id, cls.id


def _if_negation_raises(stmt: ast.stmt) -> tuple[str, str] | None:
    """``(param, class)`` for ``if not isinstance(p, Cls): raise ...`` (the
    if-body raises on the NEGATION), else ``None``.

    SOUND only when ALL hold: the test is ``not isinstance(p, Cls)`` (a single
    ``UnaryOp``/``Not`` over an accepted single-class isinstance), there is NO
    ``else`` branch, and the if-body is EXACTLY a single ``raise``. Requiring the
    body to be one bare ``raise`` is conservative — it cannot fall through to
    code that runs with ``p`` of the wrong type — so reaching past the guard
    PROVES ``isinstance(p, Cls)`` held."""
    if not isinstance(stmt, ast.If) or stmt.orelse:
        return None
    test = stmt.test
    if not (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)):
        return None
    if len(stmt.body) != 1 or not isinstance(stmt.body[0], ast.Raise):
        return None
    return _isinstance_single_class(test.operand)


def _entry_guard_binding(stmt: ast.stmt) -> tuple[str, str] | None:
    """``(param, class)`` when ``stmt`` is an accepted runtime type guard, else
    ``None``.

    Two forms, both of which ENFORCE the type at run time so a path that reaches
    past the guard PROVES the parameter is an instance of the class:
      - ``assert isinstance(p, Cls)`` (an optional message is ignored — the
        ``Assert``'s ``msg`` does not affect the bound);
      - ``if not isinstance(p, Cls): raise <...>`` (see
        :func:`_if_negation_raises`)."""
    if isinstance(stmt, ast.Assert):
        return _isinstance_single_class(stmt.test)
    return _if_negation_raises(stmt)


def _guard_prologue_bindings(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, str]:
    """``{param_name: class_name}`` from the UNCONDITIONAL guard prologue — the
    contiguous run of entry guards that opens the body (an optional leading
    docstring may precede them).

    Walks ``fn.body`` top-level statements in order, skipping ONE leading
    docstring, and stops at the FIRST statement that is not an accepted guard
    (:func:`_entry_guard_binding`). Stopping there is what makes the result
    sound: every collected guard runs UNCONDITIONALLY at entry (it is a direct
    body statement, never nested under another ``if``/``for``/``try``), and no
    non-guard statement has executed before it — so the parameter has NOT been
    reassigned or used and the guard binds the ORIGINAL parameter. The FIRST
    guard for a name wins (a later re-guard cannot loosen it)."""
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
        binding = _entry_guard_binding(stmt)
        if binding is None:
            break  # prologue ends — anything after is not an entry guard
        name, class_name = binding
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

    Soundness — all enforced by :func:`_guard_prologue_bindings` and
    :func:`_isinstance_single_class`:
      - the guard is UNCONDITIONAL (a direct body statement in the contiguous
        entry prologue — never nested under another ``if``/``for``/``try``);
      - SINGLE bare-``Name`` builtin class only (a tuple ``(int, float)`` would
        need a ``Union`` ⇒ refuse; a dotted/complex class ⇒ refuse);
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
    fn: ast.FunctionDef | ast.AsyncFunctionDef, source: str, line_starts: list[int]
) -> list[tuple[int, int, str]]:
    """The ``(start, end, text)`` splice edits for one function: a ``: T`` after
    each parameter whose type is PROVABLE from an entry ``isinstance`` guard
    (:func:`_annotatable_params`), plus a `` -> T`` before the header colon when
    the return is provable. Offsets are absolute into ``source``."""
    edits: list[tuple[int, int, str]] = []
    for arg, type_name in _annotatable_params(fn):
        off = _end_offset(arg, line_starts)
        if off is not None:
            edits.append((off, off, f": {type_name}"))

    ret = _infer_return_type(fn)
    if ret is not None:
        colon = _header_colon_offset(fn, source, line_starts)
        if colon is not None:
            edits.append((colon, colon, f" -> {ret}"))
    return edits


def infer_annotations(source: str) -> str | None:
    """Return ``source`` with every provable annotation added, or ``None`` when
    nothing provable changes (or the source does not parse).

    Edits are applied by byte offset, right-to-left, so earlier offsets stay
    valid as later ones are spliced in. Pure AST → text; deterministic."""
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

    line_starts = _line_start_offsets(source.splitlines(keepends=True))
    edits: list[tuple[int, int, str]] = []
    for fn in func_nodes:
        edits.extend(_function_edits(fn, source, line_starts))

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

def _is_fixture_path(path: str) -> bool:
    """Example/test/fixture files are REFUSED — Apex never edits the suite it is
    gated by (mirrors the existing 'would edit a test/fixture file' block). A
    local copy on purpose: this transform stays a self-contained module."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_") or Path(p).name.endswith("_test.py")
        or Path(p).name == "conftest.py"
    )


def plan_type_annotations(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the provable-type-hint plan for one module, or an empty no-op plan.

    Annotates every function in ``module_rel`` whose return type is provable
    from the AST, plus each parameter whose type is provable from an
    unconditional entry ``isinstance`` guard (a default value is still NOT a
    sound bound; see :func:`_annotatable_params`). Test/fixture files are refused
    (empty plan). An empty plan means nothing provable to add — a no-op, not a
    failure.
    The single write goes in ``new_contents`` with the original in ``originals``
    so the verified-apply engine can roll it back if the suite fails."""
    plan = RenamePlan(old=module_rel, new="infer-type-hints")

    if _is_fixture_path(module_rel):
        return plan  # never touch a test/fixture file

    path = Path(project_root) / module_rel
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return plan  # unreadable — no-op

    new_source = infer_annotations(source)
    if new_source is None or new_source == source:
        return plan  # nothing provable to add — no-op

    plan.originals[module_rel] = source
    plan.new_contents[module_rel] = new_source
    plan.edits_by_file[module_rel] = 1
    return plan
