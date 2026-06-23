"""infer-type-hints — sound ``list``/``tuple`` RETURN inference for the
str/bytes splitter family, layered on the existing return-value oracle.

``split``/``rsplit``/``splitlines`` ALWAYS return a ``list`` and
``partition``/``rpartition`` ALWAYS return a ``tuple``, for EVERY accepted
argument and identically on a ``str`` OR a ``bytes`` receiver. So the result
type is provable IFF the receiver is itself PROVABLY ``str`` or ``bytes``
(resolved recursively via the literal oracle, so chains compose — e.g.
``'a,b'.strip().split(',')`` proves because ``'a,b'.strip()`` proves ``str``).

The BARE container is emitted (``list`` / ``tuple``), never an element type:
``'a,b'.split(',')`` is a ``list[str]`` but the same call on a ``bytes`` receiver
is ``list[bytes]`` and a non-literal receiver leaves elements unknowable — so the
rule matches how every other oracle here (displays, sequence-mult, binops) hands
the recursive layer a bare container kind, and NEVER over-claims elements.

The LOCKED soundness refusals are preserved through the same machinery: a bare
``ast.Name`` receiver (``x.split()`` where ``x`` is a parameter of UNKNOWN type)
refuses — never assume a receiver's type; a splitter on any receiver that is not
provably ``str``/``bytes`` refuses; and the comparison/Div/Pow/param-default
locks are untouched. A fake-green canary proves the accept path annotates the
REAL inferred container (``list`` vs ``tuple`` produce DISTINCT annotations, never
a hardcoded one), and a determinism + byte-identical check pins input → output.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms.type_annotations import (
    _bytes_method_call_returns_type,
    _infer_return_type,
    _literal_type,
    _return_value_type,
    infer_annotations,
)


# --- str splitters land ``-> list`` -------------------------------------------

def test_infers_list_from_str_split():
    src = 'def f():\n    return "a,b".split(",")\n'
    assert infer_annotations(src) == (
        'def f() -> list:\n    return "a,b".split(",")\n')


def test_infers_list_from_str_split_no_args():
    # Call ARGUMENTS are not inspected: ``split`` returns a list with or without
    # a separator/maxsplit.
    src = 'def f():\n    return "a b".split()\n'
    assert infer_annotations(src) == (
        'def f() -> list:\n    return "a b".split()\n')


def test_infers_list_from_str_rsplit():
    src = 'def f():\n    return "a.b.c".rsplit(".", 1)\n'
    assert infer_annotations(src) == (
        'def f() -> list:\n    return "a.b.c".rsplit(".", 1)\n')


def test_infers_list_from_str_splitlines():
    src = 'def f():\n    return "a\\nb".splitlines()\n'
    out = infer_annotations(src)
    assert out is not None and out.startswith("def f() -> list:")


def test_infers_list_from_str_splitlines_keepends():
    # ``splitlines(keepends=True)`` is still a list — args don't change the kind.
    src = 'def f():\n    return "a\\nb".splitlines(True)\n'
    out = infer_annotations(src)
    assert out is not None and out.startswith("def f() -> list:")


# --- str splitters land ``-> tuple`` ------------------------------------------

def test_infers_tuple_from_str_partition():
    src = 'def f():\n    return "a=b".partition("=")\n'
    assert infer_annotations(src) == (
        'def f() -> tuple:\n    return "a=b".partition("=")\n')


def test_infers_tuple_from_str_rpartition():
    src = 'def f():\n    return "a=b=c".rpartition("=")\n'
    assert infer_annotations(src) == (
        'def f() -> tuple:\n    return "a=b=c".rpartition("=")\n')


# --- bytes splitters: SAME result kinds on a bytes receiver -------------------

def test_infers_list_from_bytes_split():
    src = 'def f():\n    return b"a,b".split(b",")\n'
    assert infer_annotations(src) == (
        'def f() -> list:\n    return b"a,b".split(b",")\n')


def test_infers_list_from_bytes_rsplit():
    src = 'def f():\n    return b"a b".rsplit()\n'
    assert infer_annotations(src) == (
        'def f() -> list:\n    return b"a b".rsplit()\n')


def test_infers_list_from_bytes_splitlines():
    src = 'def f():\n    return b"a\\nb".splitlines()\n'
    out = infer_annotations(src)
    assert out is not None and out.startswith("def f() -> list:")


def test_infers_tuple_from_bytes_partition():
    src = 'def f():\n    return b"a=b".partition(b"=")\n'
    assert infer_annotations(src) == (
        'def f() -> tuple:\n    return b"a=b".partition(b"=")\n')


def test_infers_tuple_from_bytes_rpartition():
    src = 'def f():\n    return b"a=b".rpartition(b"=")\n'
    assert infer_annotations(src) == (
        'def f() -> tuple:\n    return b"a=b".rpartition(b"=")\n')


# --- composition: a chained PROVABLE receiver --------------------------------

def test_infers_list_from_chained_str_receiver():
    # The receiver ``"a,b".strip()`` itself proves ``str`` (str-method rule), so
    # the outer ``.split`` proves ``list`` by recursion.
    src = 'def f():\n    return "a,b".strip().split(",")\n'
    assert infer_annotations(src) == (
        'def f() -> list:\n    return "a,b".strip().split(",")\n')


def test_infers_tuple_from_chained_bytes_receiver():
    # ``b"a=b".upper()`` proves ``bytes``, so ``.partition`` proves ``tuple``.
    src = 'def f():\n    return b"a=b".upper().partition(b"=")\n'
    assert infer_annotations(src) == (
        'def f() -> tuple:\n    return b"a=b".upper().partition(b"=")\n')


def test_infers_str_from_indexing_off_a_splitter_is_not_claimed():
    # We emit a BARE container and do NOT prove element types, so subscripting a
    # split result (``"a,b".split(",")[0]`` — a str at runtime) is NOT provable
    # (a Subscript is not in the oracle) and refuses. No over-claim.
    src = 'def f():\n    return "a,b".split(",")[0]\n'
    assert infer_annotations(src) is None


# --- refusals (the LOCKED soundness rules, preserved) ------------------------

def test_refuses_bare_name_split_receiver():
    # ``x`` is a parameter of UNKNOWN type — never assume a receiver is str/bytes,
    # so ``x.split()`` is unprovable and refuses (mirrors the encode/decode lock).
    src = "def f(x):\n    return x.split(',')\n"
    assert infer_annotations(src) is None


def test_refuses_bare_name_partition_receiver():
    src = "def f(x):\n    return x.partition('=')\n"
    assert infer_annotations(src) is None


def test_refuses_splitlines_on_unknown_receiver():
    src = "def f(x):\n    return x.splitlines()\n"
    assert infer_annotations(src) is None


def test_refuses_split_on_non_str_bytes_literal_receiver():
    # A receiver that proves a DIFFERENT type (an int literal here) has no sound
    # ``split``; it is not str/bytes, so the rule refuses (never assume).
    src = "def f():\n    return (123).split()\n"
    assert infer_annotations(src) is None


def test_refuses_split_on_list_receiver():
    # ``[1, 2].split()`` — the receiver proves ``list``, which is neither str nor
    # bytes, so the splitter rule (str/bytes only) refuses.
    src = "def f():\n    return [1, 2].split()\n"
    assert infer_annotations(src) is None


def test_does_not_overclaim_element_types():
    # SOUNDNESS: the emitted annotation is the BARE container, never a
    # parametrized ``list[str]`` / ``tuple[str, str, str]`` — element types are
    # not proved (a bytes receiver would make them ``bytes``).
    for src in (
        'def f():\n    return "a,b".split(",")\n',
        'def f():\n    return b"a,b".split(b",")\n',
        'def f():\n    return "a=b".partition("=")\n',
    ):
        out = infer_annotations(src)
        assert out is not None
        assert "[" not in out.split("->", 1)[1].split(":", 1)[0]


# --- direct helper unit checks -----------------------------------------------

def test_helper_accepts_str_split_as_list():
    node = ast.parse('"a,b".split(",")', mode="eval").body
    assert _bytes_method_call_returns_type(node) == "list"


def test_helper_accepts_bytes_split_as_list():
    node = ast.parse('b"a,b".split(b",")', mode="eval").body
    assert _bytes_method_call_returns_type(node) == "list"


def test_helper_accepts_str_partition_as_tuple():
    node = ast.parse('"a=b".partition("=")', mode="eval").body
    assert _bytes_method_call_returns_type(node) == "tuple"


def test_helper_accepts_bytes_rpartition_as_tuple():
    node = ast.parse('b"a=b".rpartition(b"=")', mode="eval").body
    assert _bytes_method_call_returns_type(node) == "tuple"


def test_helper_refuses_name_split_receiver():
    node = ast.parse("x.split(',')", mode="eval").body
    assert _bytes_method_call_returns_type(node) is None
    node2 = ast.parse("x.partition('=')", mode="eval").body
    assert _bytes_method_call_returns_type(node2) is None


def test_helper_refuses_non_call():
    node = ast.parse('"a,b"', mode="eval").body
    assert _bytes_method_call_returns_type(node) is None


def test_literal_type_routes_splitters():
    # The new branches live behind _literal_type so they compose with the chain.
    assert _literal_type(ast.parse('"a,b".split(",")', mode="eval").body) == "list"
    assert _literal_type(
        ast.parse('b"a=b".partition(b"=")', mode="eval").body) == "tuple"


def test_return_value_type_routes_splitters():
    node = ast.parse('"a,b".split(",")', mode="eval").body
    assert _return_value_type(node, frozenset()) == "list"


def test_infer_return_type_uses_splitter():
    fn = ast.parse('def f():\n    return "a=b".partition("=")\n').body[0]
    assert _infer_return_type(fn) == "tuple"


# --- fake-green canary + soundness made concrete -----------------------------

def test_list_vs_tuple_annotations_are_distinct_not_hardcoded():
    # FAKE-GREEN CANARY: the accept path must annotate the ACTUAL inferred kind,
    # not a hardcoded constant. ``split`` -> list and ``partition`` -> tuple
    # therefore produce DIFFERENT annotations (list vs tuple).
    list_out = infer_annotations('def f():\n    return "a,b".split(",")\n')
    tuple_out = infer_annotations('def f():\n    return "a=b".partition("=")\n')
    assert list_out is not None and "-> list:" in list_out
    assert tuple_out is not None and "-> tuple:" in tuple_out
    assert list_out != tuple_out  # not a single hardcoded annotation


def test_splitter_annotation_preserves_parse_and_runtime_value():
    # The annotation adds `-> T` TEXT only and never changes runtime behaviour.
    # The annotated source must still parse, and the runtime value must be
    # byte-identical to the original's.
    src = 'def f():\n    return "a,b,c".split(",")\n'
    out = infer_annotations(src)
    assert out is not None and out.startswith("def f() -> list:")

    orig_ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), orig_ns)
    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)  # parses (canary) + runs

    assert orig_ns["f"]() == new_ns["f"]() == ["a", "b", "c"]
    assert "return" in new_ns["f"].__annotations__
    assert "list" in str(new_ns["f"].__annotations__.get("return"))


def test_splitter_return_inference_is_deterministic():
    for src in (
        'def f():\n    return "a,b".split(",")\n',
        'def f():\n    return b"a=b".partition(b"=")\n',
        'def f():\n    return "a,b".strip().split(",")\n',
    ):
        assert infer_annotations(src) == infer_annotations(src)
    # And a refused shape is stably refused.
    refused = "def f(x):\n    return x.split(',')\n"
    assert infer_annotations(refused) == infer_annotations(refused) is None


def test_splitter_empty_and_unparseable_and_already_annotated_paths():
    # Edge/empty paths: an empty module and an unparseable one both yield None.
    assert infer_annotations("") is None
    assert infer_annotations('def f():\n    return "a,b".split(\n') is None
    # An already-annotated return is never overwritten (byte-identical refusal).
    annotated = 'def f() -> object:\n    return "a,b".split(",")\n'
    assert infer_annotations(annotated) is None
