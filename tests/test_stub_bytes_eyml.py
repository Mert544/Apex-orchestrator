"""Value-free BYTES / BYTEARRAY materializer shapes for implement-stub synthesis.

This suite covers the NEW value-free 1-arg builtins (R2): ``bytes(a)`` and
``bytearray(a)`` — materializing an iterable-of-ints (or a str) into a bytes
container. They sit in the iterable / str branch right after ``list(a)`` / ``tuple(a)``
and are VALUE-FREE and order-PRESERVING for a list/tuple/str argument, so they carry
NO overfit floor (the gate's type-exact accept keeps the right one — ``bytes`` and
``bytearray`` differ only in result type). ``to_bytes([1, 2, 3]) == b'\\x01\\x02\\x03'``
lands ``return xs[...]`` -> ``bytes(xs)``; the same shape lands a ``bytearray``.

HASHSEED gate — the never-fake-green determinism guard. ``bytes``/``bytearray`` share
the ``_has_set_arg`` gate with ``list``/``tuple``: a ``set`` / ``frozenset`` argument
would order its elements by HASH, making the bytes value PYTHONHASHSEED-dependent (the
same non-determinism that withholds ``set(a)`` / ``list(a)`` for a set witness), so the
shapes are WITHHELD whenever a witnessed argument is a set. A list/tuple/str witness
keeps a deterministic order, so the shapes are offered there.

``frozenset(a)`` is DELIBERATELY NOT offered as a stub BODY for ANY kind — it is the
SAME hash-iteration-order determinism class as the forbidden ``set(a)`` (sound only as
an INFERRED type name, never as a value-returning stub). This suite pins that exclusion.

Plus a determinism check and template-order / gate unit tests.
"""

from __future__ import annotations

from pathlib import Path


# --- helpers -----------------------------------------------------------------

def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _plan_body(tmp_path: Path, module: str, src: str, test_src: str) -> str | None:
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / module).write_text(src, encoding="utf-8")
    (tmp_path / "tests" / f"test_{module}").write_text(test_src, encoding="utf-8")
    rel = f"app/{module}"
    return plan_implement_stub(str(tmp_path), rel).new_contents.get(rel)


# --- LANDED: bytes / bytearray (list / tuple of ints) ------------------------

def test_bytes_list_of_ints_lands(tmp_path: Path):
    # to_bytes([1, 2, 3]) == b'\x01\x02\x03', to_bytes([255, 0]) == b'\xff\x00' ->
    # bytes(xs). A list of ints is a deterministic ordered input, so the value is
    # PYTHONHASHSEED-independent; bytes(...) is the only shape that spells a bytes value.
    body = _plan_body(
        tmp_path, "tb.py",
        "def to_bytes(xs):\n    raise NotImplementedError\n",
        "from app.tb import to_bytes\n"
        "def test():\n"
        "    assert to_bytes([1, 2, 3]) == b'\\x01\\x02\\x03'\n"
        "    assert to_bytes([255, 0]) == b'\\xff\\x00'\n")
    assert body is not None and "return bytes(xs)" in body


def test_bytes_tuple_of_ints_lands(tmp_path: Path):
    # to_bytes((1, 2, 3)) == b'\x01\x02\x03', to_bytes((255, 0)) == b'\xff\x00' ->
    # bytes(xs). A tuple is ordered/deterministic just like a list.
    body = _plan_body(
        tmp_path, "tt.py",
        "def to_bytes(xs):\n    raise NotImplementedError\n",
        "from app.tt import to_bytes\n"
        "def test():\n"
        "    assert to_bytes((1, 2, 3)) == b'\\x01\\x02\\x03'\n"
        "    assert to_bytes((255, 0)) == b'\\xff\\x00'\n")
    assert body is not None and "return bytes(xs)" in body


def test_bytearray_contract_lands_a_bytes_materializer(tmp_path: Path):
    # to_ba([1, 2, 3]) == bytearray(b'\x01\x02\x03'), ... : a ``bytearray`` expected is
    # VALUE-EQUAL to the same ``bytes`` (Python compares ``bytes == bytearray`` by
    # content), so the simpler ``bytes(xs)`` — offered FIRST in source order — already
    # satisfies the pinned test and wins. A bytes/bytearray materializer lands either
    # way; the point is the family fires for an int-iterable contract and is verified
    # against the real assertion (never-fake-green: the landed body genuinely passes it).
    body = _plan_body(
        tmp_path, "ba.py",
        "def to_ba(xs):\n    raise NotImplementedError\n",
        "from app.ba import to_ba\n"
        "def test():\n"
        "    assert to_ba([1, 2, 3]) == bytearray(b'\\x01\\x02\\x03')\n"
        "    assert to_ba([255, 0]) == bytearray(b'\\xff\\x00')\n")
    assert body is not None and (
        "return bytes(xs)" in body or "return bytearray(xs)" in body)


# --- REFUSAL: set argument -> hashseed-unsafe, withheld ----------------------

def test_set_arg_bytes_refused(tmp_path: Path):
    # to_bytes({1, 2, 3}) == b'\x01\x02\x03': the witnessed argument is a SET literal,
    # whose iteration order is PYTHONHASHSEED-dependent, so materializing it into bytes
    # has a non-deterministic value oracle. _has_set_arg fires -> bytes/bytearray (and
    # list/tuple) are WITHHELD, so no bytes body is landed over a set arg (never-fake-
    # green: the determinism invariant forbids it). A sorted-then-bytes body is also not
    # offered, so the contract is honestly REFUSED.
    body = _plan_body(
        tmp_path, "sb.py",
        "def to_bytes(xs):\n    raise NotImplementedError\n",
        "from app.sb import to_bytes\n"
        "def test():\n"
        "    assert to_bytes({1, 2, 3}) == b'\\x01\\x02\\x03'\n"
        "    assert to_bytes({255, 0}) == b'\\xff\\x00'\n")
    assert body is None or "bytes(" not in body


# --- honesty: non-literal arg ------------------------------------------------

def test_non_literal_arg_is_honest_no_op(tmp_path: Path):
    # The witness arg is a module-level name, not a literal: no literal is mined for
    # kind detection / the set gate, so nothing is guessed. No crash.
    body = _plan_body(
        tmp_path, "nl.py",
        "def to_bytes(xs):\n    raise NotImplementedError\n",
        "from app.nl import to_bytes\n"
        "XS = [1, 2, 3]\n"
        "def test():\n    assert to_bytes(XS) == b'\\x01\\x02\\x03'\n")
    assert body is None or isinstance(body, str)


# --- DETERMINISM -------------------------------------------------------------

def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "tb.py").write_text(
        "def to_bytes(xs):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_tb.py").write_text(
        "from app.tb import to_bytes\n"
        "def test():\n"
        "    assert to_bytes([1, 2, 3]) == b'\\x01\\x02\\x03'\n"
        "    assert to_bytes([255, 0]) == b'\\xff\\x00'\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/tb.py").new_contents.get("app/tb.py")
    second = plan_implement_stub(str(tmp_path), "app/tb.py").new_contents.get("app/tb.py")
    assert first is not None and "return bytes(xs)" in first
    assert first == second


# --- template-order + gate units ---------------------------------------------

def test_bytes_templates_after_list_tuple_in_fixed_order():
    from app.execution.stub_synthesis import _one_arg_builtin_templates

    # For an iterable kind (no set witness) bytes/bytearray are offered AFTER list/tuple
    # in fixed source order (determinism): list -> tuple -> bytes -> bytearray.
    out = _one_arg_builtin_templates("xs", "iterable", [("[1, 2]", "b'\\x01\\x02'")])
    names = [name for name, _expr in out]
    assert ("bytes", "bytes(xs)") in out
    assert ("bytearray", "bytearray(xs)") in out
    assert (names.index("list") < names.index("bytes")
            and names.index("tuple") < names.index("bytes"))
    assert names.index("bytes") < names.index("bytearray")


def test_bytes_withheld_for_set_witness():
    from app.execution.stub_synthesis import _one_arg_builtin_templates

    # A set witness fires _has_set_arg, so bytes/bytearray (and list/tuple) are not
    # offered — the hashseed determinism gate. The remaining shapes stay.
    out = _one_arg_builtin_templates("xs", "iterable", [("{1, 2, 3}", "b'\\x01\\x02\\x03'")])
    names = [name for name, _expr in out]
    for forbidden in ("bytes", "bytearray", "list", "tuple"):
        assert forbidden not in names, forbidden
    assert "first" in names and "reverse" in names  # value-free survivors remain


def test_bytes_pruned_for_pure_numeric_kind():
    from app.execution.stub_synthesis import _one_arg_builtin_templates

    # An int/float kind is not a sequence, so bytes/bytearray are not offered there.
    for kind in ("int", "float"):
        names = [n for n, _e in _one_arg_builtin_templates("n", kind, None)]
        assert "bytes" not in names and "bytearray" not in names, kind


def test_frozenset_never_offered_as_a_body():
    from app.execution.stub_synthesis import _one_arg_builtin_templates

    # frozenset(a) is the SAME hash-iteration-order determinism class as the forbidden
    # set(a), so it is NEVER offered as a stub BODY for ANY kind / witness shape.
    fixtures = [
        (None, None),
        ("int", [("3", "3")]),
        ("str", [("'a'", "'a'")]),
        ("iterable", [("[1, 2]", "[1, 2]")]),
        ("iterable", [("{1, 2}", "{1, 2}")]),
    ]
    for kind, witnesses in fixtures:
        out = _one_arg_builtin_templates("a", kind, witnesses)
        assert all("frozenset" not in expr for _name, expr in out), (kind, witnesses)
        # set(a) is likewise never a body here (only its cardinality len(set(a)) may be).
        assert all("set(" not in expr or "len(set(" in expr for _name, expr in out)
