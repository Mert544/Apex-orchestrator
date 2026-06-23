"""infer-type-hints — sound ``bytes`` (and bytes-from-str) RETURN inference, the
analog of the LOCKED str-method rule, layered on the existing return-value oracle.

A method call's runtime result type is provable IFF the receiver's type is itself
provable AND the method's result type is INVARIANT of its arguments for that
receiver type. Three sound shapes are added, each requiring a PROVABLE LITERAL
receiver (resolved recursively via the literal oracle, so chains compose):

  - ``<str-literal>.encode(...)`` ⇒ ``bytes`` — ``str.encode`` ALWAYS returns
    ``bytes`` regardless of its codec/errors args (the mirror, on the bytes side,
    of the existing ``str.<method>`` ⇒ ``str`` rule);
  - ``<bytes-literal>.decode(...)`` ⇒ ``str`` — ``bytes.decode`` ALWAYS returns
    ``str`` regardless of args;
  - a ``<bytes-literal>.<method>(...)`` whose ``<method>`` is a bytes method that
    ALWAYS returns ``bytes`` (``upper``/``strip``/``replace``/...) ⇒ ``bytes``,
    so a chain ``b'a'.upper().strip()`` proves because each step's receiver
    proves ``bytes``.

The LOCKED soundness refusals are preserved through the same machinery: a bare
``ast.Name`` receiver (``x.encode()`` where ``x`` is a parameter of UNKNOWN type)
refuses — never assume a receiver's type; a ``.decode()`` on a non-bytes/unknown
receiver refuses; and any method whose result type depends on args (``split`` ⇒
list, ``hex`` ⇒ str, ``count`` ⇒ int, predicates ⇒ bool) is NOT in the
bytes-returning set and so refuses. Because the rule routes through the same
return-value oracle, it composes with ternary/recursion: a ternary whose BOTH
branches are provably ``bytes`` lands ``-> bytes``. A fake-green canary proves the
accept path annotates the REAL inferred type (``bytes`` vs ``str`` produce
DISTINCT annotations, never a hardcoded one), and a determinism + byte-identical
check pins input → output stability.
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


# --- bytes returns land ``-> bytes`` / bytes-from-str / decode -> str ---------

def test_infers_bytes_from_bytes_literal():
    src = 'def f():\n    return b"x"\n'
    assert infer_annotations(src) == 'def f() -> bytes:\n    return b"x"\n'


def test_infers_bytes_from_str_encode():
    # ``str.encode`` ALWAYS returns bytes (the str -> bytes mirror of the
    # str-method rule); the receiver is a str literal so it proves.
    src = 'def f():\n    return "x".encode()\n'
    assert infer_annotations(src) == 'def f() -> bytes:\n    return "x".encode()\n'


def test_infers_bytes_from_str_encode_with_args():
    # Call ARGUMENTS are not inspected: ``encode`` returns bytes regardless of
    # its codec/errors args.
    src = 'def f():\n    return "x".encode("utf-8", "strict")\n'
    assert infer_annotations(src) == (
        'def f() -> bytes:\n    return "x".encode("utf-8", "strict")\n')


def test_infers_str_from_bytes_decode():
    # ``bytes.decode`` ALWAYS returns str; the receiver is a bytes literal.
    src = 'def f():\n    return b"x".decode()\n'
    assert infer_annotations(src) == 'def f() -> str:\n    return b"x".decode()\n'


def test_infers_bytes_from_bytes_method():
    src = 'def f():\n    return b"a".upper()\n'
    assert infer_annotations(src) == 'def f() -> bytes:\n    return b"a".upper()\n'


def test_infers_bytes_from_bytes_strip():
    src = 'def f():\n    return b" x ".strip()\n'
    assert infer_annotations(src) == (
        'def f() -> bytes:\n    return b" x ".strip()\n')


def test_infers_bytes_from_bytes_replace_with_args():
    # ``replace`` returns bytes regardless of its (bytes) args.
    src = 'def f():\n    return b"a".replace(b"a", b"b")\n'
    assert infer_annotations(src) == (
        'def f() -> bytes:\n    return b"a".replace(b"a", b"b")\n')


def test_infers_bytes_from_bytes_method_chain():
    # A chain proves by recursion: each step's receiver proves bytes.
    src = 'def f():\n    return b"a".upper().strip()\n'
    assert infer_annotations(src) == (
        'def f() -> bytes:\n    return b"a".upper().strip()\n')


def test_infers_bytes_from_ternary_with_both_bytes_branches():
    # Composition: each branch recurses through the FULL return-value oracle, so
    # two provably-bytes branches prove the ternary -> bytes (a bytes literal and
    # a bytes-method call).
    src = 'def f(c):\n    return b"a" if c else b"b".upper()\n'
    out = infer_annotations(src)
    assert out is not None
    assert out.startswith("def f(c) -> bytes:")


# --- refusals (the LOCKED soundness rules, preserved) ------------------------

def test_refuses_bare_name_encode_receiver():
    # ``x`` is a parameter of UNKNOWN type — never assume a receiver is a str,
    # so ``x.encode()`` is unprovable and refuses.
    src = "def f(x):\n    return x.encode()\n"
    assert infer_annotations(src) is None


def test_refuses_decode_on_unknown_receiver():
    # ``x`` is unknown — ``.decode()`` on a non-bytes/unprovable receiver refuses.
    src = "def f(x):\n    return x.decode()\n"
    assert infer_annotations(src) is None


def test_refuses_bytes_method_whose_type_is_not_provable():
    # ``hex`` returns a str, ``count`` an int — neither is in the bytes-returning
    # set NOR the sequence-returning set, so each refuses (a method whose type we
    # cannot prove to be invariant of args for the receiver). (``split`` ⇒ a BARE
    # ``list`` is now PROVABLE on a str/bytes receiver — see
    # ``test_infer_type_hints_split_partition_eyml`` — so it is no longer here.)
    for src in (
        'def f():\n    return b"a".hex()\n',
        'def f():\n    return b"a".count(b"a")\n',
    ):
        assert infer_annotations(src) is None


def test_refuses_decode_on_str_literal_receiver():
    # ``str`` has no ``decode``; the receiver proves ``str`` (not ``bytes``), so
    # the decode/bytes-method rules require a bytes receiver and refuse.
    src = 'def f():\n    return "x".decode()\n'
    assert infer_annotations(src) is None


def test_refuses_encode_on_bytes_literal_receiver():
    # ``bytes`` has no ``encode``; the encode rule requires a STR receiver, and a
    # bytes literal is not str, so it refuses.
    src = 'def f():\n    return b"x".encode()\n'
    assert infer_annotations(src) is None


# --- direct helper unit checks -----------------------------------------------

def test_bytes_method_helper_accepts_str_encode():
    node = ast.parse('"x".encode()', mode="eval").body
    assert _bytes_method_call_returns_type(node) == "bytes"


def test_bytes_method_helper_accepts_bytes_decode():
    node = ast.parse('b"x".decode()', mode="eval").body
    assert _bytes_method_call_returns_type(node) == "str"


def test_bytes_method_helper_accepts_bytes_returning_method():
    node = ast.parse('b"a".upper()', mode="eval").body
    assert _bytes_method_call_returns_type(node) == "bytes"


def test_bytes_method_helper_refuses_name_receiver():
    node = ast.parse("x.encode()", mode="eval").body
    assert _bytes_method_call_returns_type(node) is None
    node2 = ast.parse("x.decode()", mode="eval").body
    assert _bytes_method_call_returns_type(node2) is None


def test_bytes_method_helper_refuses_non_call():
    node = ast.parse('b"x"', mode="eval").body
    assert _bytes_method_call_returns_type(node) is None


def test_literal_type_routes_bytes_method():
    # The new rule lives behind _literal_type so it composes with binop/chain.
    node = ast.parse('b"a".upper()', mode="eval").body
    assert _literal_type(node) == "bytes"


def test_return_value_type_routes_bytes_method():
    node = ast.parse('"x".encode()', mode="eval").body
    assert _return_value_type(node, frozenset()) == "bytes"


def test_infer_return_type_uses_bytes_method():
    fn = ast.parse('def f():\n    return b"a".strip()\n').body[0]
    assert _infer_return_type(fn) == "bytes"


# --- fake-green canary + soundness made concrete -----------------------------

def test_bytes_vs_str_annotations_are_distinct_not_hardcoded():
    # FAKE-GREEN CANARY: the accept path must annotate the ACTUAL inferred type,
    # not a hardcoded constant. ``str.encode`` -> bytes and ``bytes.decode`` ->
    # str therefore produce DIFFERENT annotations (bytes vs str).
    bytes_src = 'def f():\n    return "x".encode()\n'
    str_src = 'def f():\n    return b"x".decode()\n'
    bytes_out = infer_annotations(bytes_src)
    str_out = infer_annotations(str_src)
    assert bytes_out is not None and "-> bytes:" in bytes_out
    assert str_out is not None and "-> str:" in str_out
    assert bytes_out != str_out  # not a single hardcoded annotation


def test_bytes_annotation_preserves_parse_and_runtime_value():
    # The annotation adds `-> T` TEXT only and never changes runtime behaviour.
    # The annotated source must still parse, and the runtime return value must be
    # byte-identical to the original's.
    src = 'def f():\n    return "x".encode()\n'
    out = infer_annotations(src)
    assert out is not None and out.startswith("def f() -> bytes:")

    orig_ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), orig_ns)
    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)  # parses (canary) + runs

    assert orig_ns["f"]() == new_ns["f"]() == b"x"
    assert "return" in new_ns["f"].__annotations__
    assert "bytes" in str(new_ns["f"].__annotations__.get("return"))


def test_bytes_return_inference_is_deterministic():
    for src in (
        'def f():\n    return b"x"\n',
        'def f():\n    return "x".encode()\n',
        'def f():\n    return b"a".upper().strip()\n',
    ):
        assert infer_annotations(src) == infer_annotations(src)
    # And a refused shape is stably refused.
    refused = "def f(x):\n    return x.encode()\n"
    assert infer_annotations(refused) == infer_annotations(refused) is None


def test_file_without_qualifying_bytes_call_is_byte_identical():
    # A module with NO qualifying provable annotation is unchanged (None). A
    # bare-name encode alone adds nothing.
    src = "def f(x):\n    return x.encode()\n"
    assert infer_annotations(src) is None
    # An already-annotated bytes return is never overwritten.
    annotated = 'def f() -> object:\n    return "x".encode()\n'
    assert infer_annotations(annotated) is None


def test_bytes_empty_and_unparseable_paths():
    # Edge/empty paths: an empty module and an unparseable one both yield None.
    assert infer_annotations("") is None
    assert infer_annotations('def f():\n    return b"x".encode(\n') is None
