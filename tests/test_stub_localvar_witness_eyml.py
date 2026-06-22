"""Same-test LOCAL-VARIABLE literal bindings for implement-stub witness mining.

Real-repo GAP #3: Apex mines ``(args_text, expected_text)`` witnesses from a
test's ``symbol(args) == expected`` asserts, but TODAY only when both sides are
literals. When a call-arg or the expected flows through a SAME-TEST local
variable bound to a literal (``words = ['a','b']; join_words(words) == 'a b'`` or
``prefix = 'item-'; label(3) == prefix + '3'``) the witness used to be silently
dropped. This suite proves the new straight-line constant-only environment turns
those into minable, fully-literal witnesses while staying SOUND.

LANDS: local on the ARG side, local on the EXPECTED side (affine f-string), a
local int (scalar arithmetic), and a determinism check (same fixture -> same body
twice). Plus a control test that the pure-literal path is unchanged.

REFUSES (witness dropped, file UNTOUCHED -> ``None``): a name bound to a CALL, a
name reassigned inside an ``if``, a name bound to ANOTHER name, a name used BEFORE
its assignment, and an augmented-assign binding. Each is an honest no-op (never a
crash, never a guess). The type-exact accept-gate + the existing overfit floors
stay the SOLE arbiter of what lands — local resolution only WIDENS which witnesses
are mined; it never fabricates one that was not asserted.
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


# --- LANDS: local on the ARG side --------------------------------------------

def test_local_arg_list_join_lands(tmp_path: Path):
    # words = ['a','b']; join_words(words) == 'a b' -> " ".join(words). The two
    # distinct list locals discriminate " " from "" and pin the join intent; the
    # arg local is resolved to its literal so the witness becomes minable.
    body = _plan_body(
        tmp_path, "jw.py",
        "def join_words(words):\n    raise NotImplementedError\n",
        "from app.jw import join_words\n"
        "def test():\n"
        "    words = ['a', 'b']\n"
        "    assert join_words(words) == 'a b'\n"
        "    more = ['x', 'y', 'z']\n"
        "    assert join_words(more) == 'x y z'\n")
    assert body is not None and "return ' '.join(words)" in body


# --- LANDS: local on the EXPECTED side ---------------------------------------

def test_local_expected_prefix_affine_lands(tmp_path: Path):
    # prefix = 'item-'; label(3) == prefix + '3' -> f"item-{n}". The expected is an
    # arithmetic OVER the local literal; once `prefix` is substituted the whole
    # ``'item-' + '3'`` constant-folds to 'item-3', a fully-literal witness the
    # affine miner consumes. Two distinct args clear the >=2-witness overfit floor.
    body = _plan_body(
        tmp_path, "lb.py",
        "def label(n):\n    raise NotImplementedError\n",
        "from app.lb import label\n"
        "def test():\n"
        "    prefix = 'item-'\n"
        "    assert label(3) == prefix + '3'\n"
        "    assert label(7) == prefix + '7'\n")
    assert body is not None and 'return f"item-{n}"' in body


# --- LANDS: local int (scalar arithmetic) ------------------------------------

def test_local_int_scalar_arith_lands(tmp_path: Path):
    # base = 10; f(2) == base + 2 -> n + 10. The expected folds (base+2 -> 12,
    # base+5 -> 15) into literal witnesses; the consistent offset across two
    # distinct inputs lands the scalar-add shape where it previously REFUSED.
    body = _plan_body(
        tmp_path, "ad.py",
        "def f(n):\n    raise NotImplementedError\n",
        "from app.ad import f\n"
        "def test():\n"
        "    base = 10\n"
        "    assert f(2) == base + 2\n"
        "    assert f(5) == base + 5\n")
    assert body is not None and "return n + 10" in body


# --- control: the pure-literal path is unchanged -----------------------------

def test_pure_literal_path_unchanged(tmp_path: Path):
    # No locals at all: the all-literal witnesses land exactly as before — local
    # resolution must not perturb the existing path.
    body = _plan_body(
        tmp_path, "pl.py",
        "def label(n):\n    raise NotImplementedError\n",
        "from app.pl import label\n"
        "def test():\n"
        "    assert label(3) == 'item-3'\n"
        "    assert label(7) == 'item-7'\n")
    assert body is not None and 'return f"item-{n}"' in body


# --- determinism -------------------------------------------------------------

def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "jw.py").write_text(
        "def join_words(words):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_jw.py").write_text(
        "from app.jw import join_words\n"
        "def test():\n"
        "    words = ['a', 'b', 'c']\n"
        "    assert join_words(words) == 'a b c'\n"
        "    more = ['x', 'y']\n"
        "    assert join_words(more) == 'x y'\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/jw.py").new_contents.get("app/jw.py")
    second = plan_implement_stub(str(tmp_path), "app/jw.py").new_contents.get("app/jw.py")
    assert first is not None and first == second


# --- REFUSES (witness dropped, honest no-op) ---------------------------------

def test_refuse_name_bound_to_call(tmp_path: Path):
    # prefix = mk() — a CALL RHS is NOT a constant, so `prefix` is poisoned out of
    # the environment and the witness stays dropped. No value-free template can
    # reproduce 'item-3'/'item-7' either, so the file is left untouched.
    body = _plan_body(
        tmp_path, "rc.py",
        "def label(n):\n    raise NotImplementedError\n",
        "from app.rc import label\n"
        "def mk():\n    return 'item-'\n"
        "def test():\n"
        "    prefix = mk()\n"
        "    assert label(3) == prefix + '3'\n"
        "    assert label(7) == prefix + '7'\n")
    assert body is None


def test_refuse_name_reassigned_in_if(tmp_path: Path):
    # base is reassigned inside an `if` (control flow) — not straight-line, so it is
    # poisoned and the witnesses are dropped. No body lands.
    body = _plan_body(
        tmp_path, "ri.py",
        "def f(n):\n    raise NotImplementedError\n",
        "from app.ri import f\n"
        "def test():\n"
        "    base = 10\n"
        "    if True:\n"
        "        base = 20\n"
        "    assert f(2) == base + 2\n"
        "    assert f(5) == base + 5\n")
    assert body is None


def test_refuse_name_bound_to_name(tmp_path: Path):
    # prefix = P — a bare Name RHS is not literal-evaluable, so `prefix` is refused
    # (we never chase the module-scope `P`). Witnesses dropped, file untouched.
    body = _plan_body(
        tmp_path, "rn.py",
        "def label(n):\n    raise NotImplementedError\n",
        "from app.rn import label\n"
        "P = 'item-'\n"
        "def test():\n"
        "    prefix = P\n"
        "    assert label(3) == prefix + '3'\n"
        "    assert label(7) == prefix + '7'\n")
    assert body is None


def test_refuse_name_used_before_assignment(tmp_path: Path):
    # The first assert references `prefix` BEFORE it is bound (binding filtered by
    # source line), so that witness is dropped; the lone remaining witness floors
    # out the affine shape (needs >=2 distinct). Nothing lands.
    body = _plan_body(
        tmp_path, "rb.py",
        "def label(n):\n    raise NotImplementedError\n",
        "from app.rb import label\n"
        "def test():\n"
        "    assert label(3) == prefix + '3'\n"
        "    prefix = 'item-'\n"
        "    assert label(7) == prefix + '7'\n")
    assert body is None


def test_refuse_augmented_assign(tmp_path: Path):
    # base += 5 is an augmented assign — not a straight-line constant binding, so
    # `base` is poisoned and the witnesses are dropped. No body lands.
    body = _plan_body(
        tmp_path, "rg.py",
        "def f(n):\n    raise NotImplementedError\n",
        "from app.rg import f\n"
        "def test():\n"
        "    base = 10\n"
        "    base += 5\n"
        "    assert f(2) == base + 2\n"
        "    assert f(5) == base + 5\n")
    assert body is None
