"""1-arg REVERSE-SLICE shape for implement-stub synthesis.

This suite covers the NEW value-free reverse-slice shape: ``return a[::-1]`` — the
whole sequence reversed. ``backwards('abc') == 'cba', backwards('xy') == 'yx'`` lands
``return s[::-1]``; the same shape lands a reversed ``list`` / ``tuple``. It is
TYPE-PRESERVING (``str[::-1]`` -> ``str``, ``list[::-1]`` -> ``list``), so the
type-exact accept-gate keeps the right kind, and VALUE-FREE (no witness literal, no
overfit floor) just like the ``first`` / ``last`` / ``sorted`` builtins beside it.

Discrimination is by the existing off-witness canary machinery, NOT a new floor:

* a ``list`` / ``tuple`` arg routes to the sequence canary, whose REVERSED probe
  splits ``a[::-1]`` from passthrough / ``sorted`` / ``list``;
* a ``str`` arg routes to the ``str`` canary, whose whitespace-padded probe
  (``"  " + s + "  "``) splits ``s[::-1]`` from passthrough / ``.lower()`` (they
  agree on the bare witness but diverge once the string is reversed).

A palindrome-only ``str`` (``s[::-1] == s``) and a descending-monotonic ``list``
where ``a[::-1] == sorted(a)`` are honestly REFUSED — the reverse coincides with a
competing shape on every witness AND on the canaries, so the contract is
under-specified and nothing lands (never-fake-green). Because reverse is VALUE-FREE
(no baked literal, no overfit floor — unlike the witness-mining slice family), a
SINGLE discriminating witness DOES land it, exactly like the sibling first / last /
sorted builtins; a non-literal arg mines nothing. Plus a determinism check and a
template-order unit test pinning the fixed ``first/last/reverse`` order.

CRITICAL: the sequence canary's reversed probe is ``type(seq)(reversed(seq))``,
which is BROKEN for a ``str`` (``str(reversed('abc'))`` is ``'<reversed object>'``),
but a ``str`` arg never reaches it — it routes to the ``str`` canary — so the
str-reverse landing rests SOLELY on the whitespace probe, which this suite pins.
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


# --- LANDED: str reverse (rests SOLELY on the whitespace canary) -------------

def test_str_reverse_lands(tmp_path: Path):
    # backwards('abc') == 'cba', backwards('xyz') == 'zyx' -> s[::-1]. Non-palindrome
    # witnesses so reverse != passthrough; the str whitespace canary ("  abc  " ->
    # "  cba  ") splits s[::-1] from a plain passthrough / .lower(). This is the exact
    # str path the broken sequence reversed probe does NOT serve.
    body = _plan_body(
        tmp_path, "br.py",
        "def backwards(s):\n    raise NotImplementedError\n",
        "from app.br import backwards\n"
        "def test():\n"
        "    assert backwards('abc') == 'cba'\n"
        "    assert backwards('xyz') == 'zyx'\n")
    assert body is not None and "return s[::-1]" in body


# --- LANDED: list reverse (sequence reversed canary) -------------------------

def test_list_reverse_lands(tmp_path: Path):
    # flip([1, 2, 3]) == [3, 2, 1], flip([7, 4]) == [4, 7] -> xs[::-1]. UNSORTED
    # witnesses so reverse != sorted (sorted([1,2,3])==[1,2,3]) and != passthrough;
    # the reversed sequence-canary probe splits xs[::-1] from list/passthrough/sorted.
    body = _plan_body(
        tmp_path, "fl.py",
        "def flip(xs):\n    raise NotImplementedError\n",
        "from app.fl import flip\n"
        "def test():\n"
        "    assert flip([1, 2, 3]) == [3, 2, 1]\n"
        "    assert flip([7, 4]) == [4, 7]\n")
    assert body is not None and "return xs[::-1]" in body


# --- LANDED: tuple reverse (type-preserving) ---------------------------------

def test_tuple_reverse_lands(tmp_path: Path):
    # flip((1, 2, 3)) == (3, 2, 1), flip((7, 4)) == (4, 7) -> xs[::-1]. tuple[::-1] is a
    # tuple, so the type-exact gate keeps it distinct from list(xs)/sorted(xs).
    body = _plan_body(
        tmp_path, "ft.py",
        "def flip(xs):\n    raise NotImplementedError\n",
        "from app.ft import flip\n"
        "def test():\n"
        "    assert flip((1, 2, 3)) == (3, 2, 1)\n"
        "    assert flip((7, 4)) == (4, 7)\n")
    assert body is not None and "return xs[::-1]" in body


# --- REFUSALS ----------------------------------------------------------------

def test_palindrome_str_is_ambiguous_refused(tmp_path: Path):
    # same('aba') == 'aba', same('xyx') == 'xyx': each input is a palindrome, so
    # s[::-1] == s on every witness AND on the symmetric "  aba  " whitespace probe.
    # reverse coincides with passthrough everywhere -> under-specified -> REFUSE (no
    # reverse body stamped over an identity the witnesses cannot tell apart).
    body = _plan_body(
        tmp_path, "pl.py",
        "def same(s):\n    raise NotImplementedError\n",
        "from app.pl import same\n"
        "def test():\n"
        "    assert same('aba') == 'aba'\n"
        "    assert same('xyx') == 'xyx'\n")
    assert body is None or "[::-1]" not in body


def test_descending_monotonic_list_reverse_equals_sorted_refused(tmp_path: Path):
    # order([3, 2, 1]) == [1, 2, 3], order([9, 5]) == [5, 9]: each input is sorted
    # DESCENDING, so xs[::-1] == sorted(xs) on every witness. reverse and sorted
    # coincide on the witnesses and on the reversed canary of a descending sequence ->
    # the contract cannot tell reverse from sorted -> REFUSE the reverse shape (sorted
    # may still land, but never a reverse body the witnesses don't pin).
    body = _plan_body(
        tmp_path, "dm.py",
        "def order(xs):\n    raise NotImplementedError\n",
        "from app.dm import order\n"
        "def test():\n"
        "    assert order([3, 2, 1]) == [1, 2, 3]\n"
        "    assert order([9, 5]) == [5, 9]\n")
    assert body is None or "[::-1]" not in body


def test_single_discriminating_witness_reverse_lands(tmp_path: Path):
    # A LONE flip([1, 2, 3]) == [3, 2, 1] LANDS xs[::-1]: reverse is VALUE-FREE (no
    # baked literal), so it carries no overfit floor — exactly like the sibling
    # first/last/sorted builtins, which also land on a single DISCRIMINATING witness.
    # Here the witness is discriminating: passthrough/list/sorted all give [1,2,3] !=
    # [3,2,1], so ONLY xs[::-1] reproduces it and there is no competing intent to
    # refuse (honest — the witness genuinely pins the reverse, not a fake-green guess).
    body = _plan_body(
        tmp_path, "s1.py",
        "def flip(xs):\n    raise NotImplementedError\n",
        "from app.s1 import flip\n"
        "def test():\n    assert flip([1, 2, 3]) == [3, 2, 1]\n")
    assert body is not None and "return xs[::-1]" in body


# --- honesty: non-literal arg ------------------------------------------------

def test_non_literal_arg_is_honest_no_op(tmp_path: Path):
    # The witness arg is a module-level name, not a literal: no literal witness is
    # mined for kind detection, so nothing is guessed. No crash; any body must be
    # gate-verified, never a fake-green reverse.
    body = _plan_body(
        tmp_path, "nl.py",
        "def flip(xs):\n    raise NotImplementedError\n",
        "from app.nl import flip\n"
        "XS = [1, 2, 3]\n"
        "def test():\n    assert flip(XS) == [3, 2, 1]\n")
    assert body is None or isinstance(body, str)


# --- DETERMINISM -------------------------------------------------------------

def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "br.py").write_text(
        "def backwards(s):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_br.py").write_text(
        "from app.br import backwards\n"
        "def test():\n"
        "    assert backwards('abc') == 'cba'\n"
        "    assert backwards('xyz') == 'zyx'\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/br.py").new_contents.get("app/br.py")
    second = plan_implement_stub(str(tmp_path), "app/br.py").new_contents.get("app/br.py")
    assert first is not None and "return s[::-1]" in first
    assert first == second


# --- template-order unit: first/last/reverse in fixed source order -----------

def test_reverse_template_in_fixed_order():
    from app.execution.stub_synthesis import _one_arg_builtin_templates

    # The reverse shape is offered for sequence/str kinds, AFTER first/last and BEFORE
    # the list/tuple materializers, in fixed source order (determinism).
    out = _one_arg_builtin_templates("xs", "iterable", [("[1, 2]", "[2, 1]")])
    names = [name for name, _expr in out]
    assert "reverse" in names
    assert names.index("first") < names.index("last") < names.index("reverse")
    assert names.index("reverse") < names.index("list")
    assert ("reverse", "xs[::-1]") in out
    # NOT offered for a pure numeric kind (int/float cannot be reverse-sliced).
    int_names = [n for n, _e in _one_arg_builtin_templates("n", "int", [("3", "-3")])]
    assert "reverse" not in int_names
