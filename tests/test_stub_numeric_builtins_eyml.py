"""Value-free NUMERIC / codepoint builtin shapes for implement-stub synthesis.

This suite covers the NEW value-free 1-arg builtins (R4):

* ``hex(a)`` / ``oct(a)`` / ``bin(a)`` / ``chr(a)`` — offered ONLY for a pure ``int``
  argument (``kind in (None, "int")``). The three radix formatters and the
  codepoint->char map are pure TOTAL functions on the int domain (``hex``/``oct``/
  ``bin`` accept any int; ``chr`` accepts ``0..0x10FFFF`` and RAISES otherwise, which
  the accept-gate rejects). They carry NO overfit floor — exactly like ``neg`` — and
  they are MAXIMALLY discriminating: no two of them, nor ``str(n)`` / ``int(n)`` /
  passthrough, ever produce the same value on any int (the ``'0x'`` / ``'0o'`` / ``'0b'``
  prefixes and the char value all differ), so a SINGLE discriminating witness lands the
  right one and there is no competing value-free shape to confuse it with.
* ``ord(a)`` — offered ONLY for a ``str`` argument (``kind in (None, "str")``), the
  value-free inverse of ``chr`` mapping a length-1 str to its int codepoint. A
  non-length-1 str RAISES -> the gate rejects it.

WRONG-ARG-KIND prune: a ``float`` / ``iterable`` arg cannot radix-format and ``chr``
rejects a non-int, so hex/oct/bin/chr are pruned off those kinds; ``ord`` is pruned off
a non-``str`` kind. The ``kind`` gate (``_arg_kind``) never crashes — a pruned shape is
simply not offered.

REFUSALS — never-fake-green. Because these shapes bake NO witness literal, the
under-specified refusal is NOT an overfit floor but the AMBIGUITY GUARD plus the
gate: a NON-DISCRIMINATING contract whose expecteds DO NOT VARY collapses to the
witness-derived CONSTANT the constant-last fallback owns (it survives the
>=2-distinct floor), and the value-free radix body, which would diverge from that
constant on the int-canary probes, is honestly NOT landed (``hex(7) != '0xff'``, so it
also fails the gate). A wrong-arg-kind contract offers nothing of the family at all.

Plus a determinism check and template-order unit tests pinning the fixed source order
(``neg`` -> ``int`` -> ``hex`` -> ``oct`` -> ``bin`` -> ``chr`` for ints; ``ord`` before
the sequence projections for strings) and the kind-prune both directions.
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


# --- LANDED: hex / oct / bin (int radix formatters) --------------------------

def test_hex_lands(tmp_path: Path):
    # to_hex(255) == '0xff', to_hex(16) == '0x10' -> hex(n). Discriminating witnesses
    # (the values vary), and no other value-free int shape spells '0xff'/'0x10', so
    # hex is the unique match and lands without any overfit floor.
    body = _plan_body(
        tmp_path, "th.py",
        "def to_hex(n):\n    raise NotImplementedError\n",
        "from app.th import to_hex\n"
        "def test():\n"
        "    assert to_hex(255) == '0xff'\n"
        "    assert to_hex(16) == '0x10'\n")
    assert body is not None and "return hex(n)" in body


def test_oct_lands(tmp_path: Path):
    # to_oct(8) == '0o10', to_oct(64) == '0o100' -> oct(n). The '0o' prefix is spelled
    # by no other value-free int shape, so oct is the unique match.
    body = _plan_body(
        tmp_path, "to.py",
        "def to_oct(n):\n    raise NotImplementedError\n",
        "from app.to import to_oct\n"
        "def test():\n"
        "    assert to_oct(8) == '0o10'\n"
        "    assert to_oct(64) == '0o100'\n")
    assert body is not None and "return oct(n)" in body


def test_bin_lands(tmp_path: Path):
    # to_bin(5) == '0b101', to_bin(2) == '0b10' -> bin(n).
    body = _plan_body(
        tmp_path, "tb.py",
        "def to_bin(n):\n    raise NotImplementedError\n",
        "from app.tb import to_bin\n"
        "def test():\n"
        "    assert to_bin(5) == '0b101'\n"
        "    assert to_bin(2) == '0b10'\n")
    assert body is not None and "return bin(n)" in body


# --- LANDED: chr / ord (codepoint maps) --------------------------------------

def test_chr_lands(tmp_path: Path):
    # to_char(65) == 'A', to_char(97) == 'a' -> chr(n). chr maps a codepoint to its
    # single character; no other value-free int shape produces 'A'/'a'.
    body = _plan_body(
        tmp_path, "tc.py",
        "def to_char(n):\n    raise NotImplementedError\n",
        "from app.tc import to_char\n"
        "def test():\n"
        "    assert to_char(65) == 'A'\n"
        "    assert to_char(97) == 'a'\n")
    assert body is not None and "return chr(n)" in body


def test_ord_lands(tmp_path: Path):
    # code('A') == 65, code('z') == 122 -> ord(s). ord maps a length-1 str to its int
    # codepoint; for a varying codepoint no other value-free str shape (len is the
    # constant 1, int needs a digit str) reproduces it.
    body = _plan_body(
        tmp_path, "ts.py",
        "def code(s):\n    raise NotImplementedError\n",
        "from app.ts import code\n"
        "def test():\n"
        "    assert code('A') == 65\n"
        "    assert code('z') == 122\n")
    assert body is not None and "return ord(s)" in body


def test_single_discriminating_witness_hex_lands(tmp_path: Path):
    # A LONE to_hex(255) == '0xff' LANDS hex(n): the radix family bakes NO literal, so
    # it carries no overfit floor (like neg/first/last/reverse), and the witness is
    # discriminating — only hex(n) reproduces '0xff' (the derived constant '0xff' needs
    # >=2 distinct witnesses to clear its floor, so it does not compete here). Honest:
    # the witness genuinely pins hex, not a fake-green guess.
    body = _plan_body(
        tmp_path, "h1.py",
        "def to_hex(n):\n    raise NotImplementedError\n",
        "from app.h1 import to_hex\n"
        "def test():\n    assert to_hex(255) == '0xff'\n")
    assert body is not None and "return hex(n)" in body


# --- REFUSALS: under-specified / non-discriminating --------------------------

def test_non_varying_radix_collapses_to_constant_refused(tmp_path: Path):
    # weird(255) == '0xff', weird(7) == '0xff': the expecteds DO NOT VARY, so the
    # contract is a CONSTANT the constant-last fallback owns (it clears the >=2-distinct
    # floor). hex(n) would diverge on the int-canary probes (hex(7) == '0x7' != '0xff'),
    # so it ALSO fails the gate on the second witness -> the radix body is honestly NOT
    # landed; a constant '0xff' may land instead, never a fake-green hex.
    body = _plan_body(
        tmp_path, "nv.py",
        "def weird(n):\n    raise NotImplementedError\n",
        "from app.nv import weird\n"
        "def test():\n"
        "    assert weird(255) == '0xff'\n"
        "    assert weird(7) == '0xff'\n")
    assert body is None or "hex(" not in body


def test_wrong_arg_kind_float_no_radix(tmp_path: Path):
    # f(1.5) == ... : a float argument cannot radix-format (hex/oct/bin reject a float,
    # chr too), so none of the int->str family is OFFERED for a float kind. Whatever the
    # gate lands (or None), it never contains a radix/codepoint body over a float.
    body = _plan_body(
        tmp_path, "wf.py",
        "def f(x):\n    raise NotImplementedError\n",
        "from app.wf import f\n"
        "def test():\n"
        "    assert f(1.5) == 1.5\n"
        "    assert f(2.5) == 2.5\n")
    assert body is None or (
        "hex(" not in body and "oct(" not in body
        and "bin(" not in body and "chr(" not in body)


def test_ord_not_offered_for_int_arg(tmp_path: Path):
    # g(65) == 'A': the arg is an int, so ord(g) is NOT offered (ord needs a str). chr
    # is the int->str map that fits here; ord must never appear over an int arg.
    body = _plan_body(
        tmp_path, "wi.py",
        "def g(n):\n    raise NotImplementedError\n",
        "from app.wi import g\n"
        "def test():\n"
        "    assert g(65) == 'A'\n"
        "    assert g(97) == 'a'\n")
    assert body is not None and "ord(" not in body


# --- honesty: non-literal arg ------------------------------------------------

def test_non_literal_arg_is_honest_no_op(tmp_path: Path):
    # The witness arg is a module-level name, not a literal: kind detection mines no
    # literal, so nothing is guessed. No crash; any body must be gate-verified.
    body = _plan_body(
        tmp_path, "nl.py",
        "def to_hex(n):\n    raise NotImplementedError\n",
        "from app.nl import to_hex\n"
        "N = 255\n"
        "def test():\n    assert to_hex(N) == '0xff'\n")
    assert body is None or isinstance(body, str)


# --- DETERMINISM -------------------------------------------------------------

def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "th.py").write_text(
        "def to_hex(n):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_th.py").write_text(
        "from app.th import to_hex\n"
        "def test():\n"
        "    assert to_hex(255) == '0xff'\n"
        "    assert to_hex(16) == '0x10'\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/th.py").new_contents.get("app/th.py")
    second = plan_implement_stub(str(tmp_path), "app/th.py").new_contents.get("app/th.py")
    assert first is not None and "return hex(n)" in first
    assert first == second


# --- template-order + kind-prune units ---------------------------------------

def test_int_radix_templates_in_fixed_order():
    from app.execution.stub_synthesis import _one_arg_builtin_templates

    # For a pure int kind the radix/codepoint shapes are offered AFTER neg/int, in the
    # fixed source order hex -> oct -> bin -> chr (determinism), and NOT the str-only
    # ord. None of the sequence projections (first/list/bytes) appear for an int.
    out = _one_arg_builtin_templates("n", "int", [("255", "'0xff'")])
    names = [name for name, _expr in out]
    for nm, expr in (("hex", "hex(n)"), ("oct", "oct(n)"),
                     ("bin", "bin(n)"), ("chr", "chr(n)")):
        assert (nm, expr) in out
    assert names.index("neg") < names.index("hex")
    assert names.index("int") < names.index("hex")
    assert (names.index("hex") < names.index("oct")
            < names.index("bin") < names.index("chr"))
    assert "ord" not in names
    assert "first" not in names and "bytes" not in names


def test_ord_offered_only_for_str_kind():
    from app.execution.stub_synthesis import _one_arg_builtin_templates

    # ord is offered for a str arg (before the sequence projections) and NOT for an int
    # arg; conversely the radix family is offered for int and NOT for str.
    str_out = _one_arg_builtin_templates("s", "str", [("'A'", "65")])
    str_names = [n for n, _e in str_out]
    assert ("ord", "ord(s)") in str_out
    assert str_names.index("ord") < str_names.index("first")
    assert "hex" not in str_names and "chr" not in str_names
    int_names = [n for n, _e in _one_arg_builtin_templates("n", "int", [("3", "'0b11'")])]
    assert "ord" not in int_names


def test_radix_pruned_for_float_and_iterable_kinds():
    from app.execution.stub_synthesis import _one_arg_builtin_templates

    # A float or iterable kind offers NONE of hex/oct/bin/chr/ord (they cannot apply).
    for kind in ("float", "iterable"):
        names = [n for n, _e in _one_arg_builtin_templates("x", kind, None)]
        for forbidden in ("hex", "oct", "bin", "chr", "ord"):
            assert forbidden not in names, (kind, forbidden)


def test_structural_view_offers_radix_and_ord():
    from app.execution.stub_synthesis import _one_arg_builtin_templates

    # With kind=None (the pure structural view, no witnesses) every shape is offered so
    # the gate decides — the radix family AND ord both appear.
    names = [n for n, _e in _one_arg_builtin_templates("a", None, None)]
    for nm in ("hex", "oct", "bin", "chr", "ord"):
        assert nm in names
