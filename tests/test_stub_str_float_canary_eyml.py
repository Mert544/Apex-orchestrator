"""Off-witness ambiguity canaries for single-str / single-float contracts, plus
the set-arg ``list``/``tuple`` determinism withhold.

Closes a CONFIRMED fake-green: ``_off_witness_probes`` previously emitted probes
only for single-int, single-sequence, and >=2-arg contracts, so a single ``str``
or ``float`` argument fell through to ``[]``. The ambiguity guard then fingerprinted
competing templates ONLY on the witnessed tuples (where they coincide), declared
NOT ambiguous, and landed an arbitrary pick stamped "verified".

Repro (deterministic across seeds):
  * ``f("Hello")=="hello", f("World")=="world"`` is matched by BOTH ``s.lower()``
    and ``s.lower().strip()`` — they DIVERGE on a whitespace-padded probe
    (``'  hi '`` -> ``'  hi '`` vs ``'hi'``). Under-specified -> must REFUSE.
  * ``f(2.5)==2.5, f(3.5)==3.5`` is matched by ``x``, ``abs(x)`` AND ``round(x, 1)``
    — they DIVERGE on ``-v`` / ``v + 0.5``. Under-specified -> must REFUSE.

The new canaries ONLY ADD refusals for genuinely-ambiguous thin contracts; a
str/float contract that pins exactly one shape STILL lands.

Also covers P2: a ``set``/``frozenset`` witnessed argument withholds ``list(a)`` /
``tuple(a)`` (PYTHONHASHSEED-dependent materialization order for non-int elements,
the same non-determinism that already excludes ``set(a)``).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.stub_synthesis import (
    _float_canary_probes,
    _has_set_arg,
    _one_arg_builtin_templates,
    _str_canary_probes,
    find_stub_functions,
    pinned_test_files,
    synthesize_expr_from_witnesses,
)


def _write(root: Path, rel: str, src: str) -> None:
    (root / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(src, encoding="utf-8")


def _synth(root: Path, mod_src: str, test_src: str) -> str | None:
    """End-to-end in-process synth: write a stub module + its pinned test, return
    the body Apex would land (or ``None`` when it REFUSES)."""
    _write(root, "app/m.py", mod_src)
    _write(root, "tests/test_m.py", test_src)
    stub = find_stub_functions(mod_src)[0]
    test_files = pinned_test_files(root, "app/m.py", stub.name)
    return synthesize_expr_from_witnesses(root, test_files, stub)


# --- P1: single-str ambiguity now REFUSES (was a fake-green) ------------------

def test_str_lower_vs_lower_strip_now_refuses(tmp_path: Path):
    # No surrounding whitespace in the witnesses, so ``s.lower()`` and
    # ``s.lower().strip()`` AGREE on every witness yet diverge on a padded probe.
    body = _synth(
        tmp_path,
        "def f(s):\n    raise NotImplementedError\n",
        "from app.m import f\n"
        "def test_it():\n"
        "    assert f('Hello') == 'hello'\n"
        "    assert f('World') == 'world'\n",
    )
    assert body is None  # under-specified -> honest refusal, no verified guess


def test_str_upper_genuine_single_shape_still_lands(tmp_path: Path):
    body = _synth(
        tmp_path,
        "def up(s):\n    raise NotImplementedError\n",
        "from app.m import up\n"
        "def test_it():\n"
        "    assert up('a') == 'A'\n"
        "    assert up('bc') == 'BC'\n",
    )
    assert body == "s.upper()"


def test_str_lower_genuine_single_shape_still_lands(tmp_path: Path):
    # A whitespace-PRESERVING witness pins ``s.lower()`` against ``s.lower().strip()``
    # (strip would drop the surrounding spaces the witness keeps).
    body = _synth(
        tmp_path,
        "def lo(s):\n    raise NotImplementedError\n",
        "from app.m import lo\n"
        "def test_it():\n"
        "    assert lo(' Ab ') == ' ab '\n"
        "    assert lo('Cd') == 'cd'\n",
    )
    assert body == "s.lower()"


def test_str_strip_genuine_single_shape_still_lands(tmp_path: Path):
    # Mixed-case witnesses pin ``s.strip()`` against ``s.strip().lower()`` (lower
    # would fold the kept casing).
    body = _synth(
        tmp_path,
        "def st(s):\n    raise NotImplementedError\n",
        "from app.m import st\n"
        "def test_it():\n"
        "    assert st('  Ab  ') == 'Ab'\n"
        "    assert st(' Cd ') == 'Cd'\n",
    )
    assert body == "s.strip()"


# --- P1: single-float ambiguity now REFUSES -----------------------------------

def test_float_identity_trio_now_refuses(tmp_path: Path):
    # ``x`` / ``abs(x)`` / ``round(x, 1)`` all pass these witnesses but diverge on
    # the off-witness ``-v`` / ``v + 0.5`` probes.
    body = _synth(
        tmp_path,
        "def f(x):\n    raise NotImplementedError\n",
        "from app.m import f\n"
        "def test_it():\n"
        "    assert f(2.5) == 2.5\n"
        "    assert f(3.5) == 3.5\n",
    )
    assert body is None


def test_float_round_genuine_single_shape_still_lands(tmp_path: Path):
    # Witnesses that round to a 2-place value distinct from the input pin
    # ``round(x, 2)`` against a passthrough / abs / int.
    body = _synth(
        tmp_path,
        "def r(x):\n    raise NotImplementedError\n",
        "from app.m import r\n"
        "def test_it():\n"
        "    assert r(2.345) == 2.35\n"
        "    assert r(3.118) == 3.12\n",
    )
    assert body == "round(x, 2)"


# --- P1: probe helpers are deterministic and discriminating -------------------

def test_str_canary_probes_emit_whitespace_and_caseflip(tmp_path: Path):
    probes = _str_canary_probes([(("Hello",), "hello"), (("World",), "world")])
    flat = [p[0] for p in probes]
    # surrounding-whitespace variant distinguishes ``.strip()`` from ``.lower()``
    assert "  Hello  " in flat
    # case-flipped variant distinguishes ``.upper()`` / ``.lower()`` / ``.title()``
    assert "hELLO" in flat
    # fixed empty / whitespace anchors
    assert "" in flat and " " in flat
    # deterministic: repr-sorted, deduped (same call -> identical output)
    assert probes == _str_canary_probes([(("Hello",), "hello"), (("World",), "world")])
    assert flat == sorted(flat)


def test_str_canary_probes_inject_separator_when_present(tmp_path: Path):
    probes = _str_canary_probes([(("a,b",), "a,b")])
    flat = [p[0] for p in probes]
    # a separator-injection variant distinguishes ``.replace``/``.split`` shapes
    assert "aXb" in flat


def test_float_canary_probes_emit_negation_and_perturbations(tmp_path: Path):
    probes = _float_canary_probes([((2.5,), 2.5), ((3.5,), 3.5)])
    flat = [p[0] for p in probes]
    assert -2.5 in flat  # distinguishes abs(x) from passthrough
    assert 3.0 in flat   # 2.5 + 0.5, distinguishes round precision / int trunc
    assert 0.0 in flat and -1.5 in flat
    # deterministic: sorted, stable across calls
    assert probes == _float_canary_probes([((2.5,), 2.5), ((3.5,), 3.5)])
    assert flat == sorted(flat)


def test_canary_probes_empty_witnesses_are_safe(tmp_path: Path):
    # Edge/empty path: no witnesses -> only fixed anchors, never a crash.
    assert _str_canary_probes([]) == [("",), (" ",)]
    assert _float_canary_probes([]) == [(-1.5,), (0.0,)]


# --- P2: set/frozenset arg withholds list(a)/tuple(a) (determinism) -----------

def test_set_arg_as_tuple_does_not_land_order_dependent_body(tmp_path: Path):
    # tuple({'b','a'}) materializes in PYTHONHASHSEED-dependent order for str
    # elements -> non-deterministic value oracle -> must NOT land.
    body = _synth(
        tmp_path,
        "def as_tuple(a):\n    raise NotImplementedError\n",
        "from app.m import as_tuple\n"
        "def test_it():\n"
        "    assert as_tuple({'b', 'a'}) == ('a', 'b')\n"
        "    assert as_tuple({'d', 'c'}) == ('c', 'd')\n",
    )
    assert body != "tuple(a)"
    assert body != "list(a)"


def test_one_arg_builtin_withholds_list_tuple_for_set_witness():
    labels = [
        lbl
        for lbl, _expr in _one_arg_builtin_templates(
            "a", "iterable", [("{'b', 'a'}", "('a', 'b')")]
        )
    ]
    assert "list" not in labels
    assert "tuple" not in labels
    # first/last/str/not/bool stay offered (they are order-stable / type-agnostic)
    assert "first" in labels and "last" in labels


def test_one_arg_builtin_keeps_list_tuple_for_list_witness():
    labels = [
        lbl
        for lbl, _expr in _one_arg_builtin_templates(
            "a", "iterable", [("[1, 2, 3]", "[1, 2, 3]")]
        )
    ]
    assert "list" in labels and "tuple" in labels


def test_one_arg_builtin_no_witness_keeps_shapes():
    # Structural (gate-elsewhere) view with no witnesses must be unchanged.
    labels = [lbl for lbl, _expr in _one_arg_builtin_templates("a", "iterable", None)]
    assert "list" in labels and "tuple" in labels


def test_has_set_arg_edges():
    assert _has_set_arg(None) is False
    assert _has_set_arg([]) is False
    assert _has_set_arg([("[1, 2]", "[1, 2]")]) is False
    assert _has_set_arg([("{1, 2}", "(1, 2)")]) is True
    # a frozenset()/set() CALL is not a literal -> literal_eval refuses it, so it
    # is treated conservatively (non-literal witness, no withhold decision made).
    assert _has_set_arg([("frozenset({1})", "(1,)")]) is False
    # mixed: one set-literal witness is enough to withhold
    assert _has_set_arg([("[1]", "[1]"), ("{1}", "(1,)")]) is True
