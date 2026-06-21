"""Hash-seed determinism for the LIST/TUPLE value-oracle (P0 fix, eyml).

The prior fix (``test_set_oracle_determinism_eyml``) sorted a top-level ``set`` so
its landed literal is byte-stable. But a function whose returned LIST/TUPLE order
comes from SET ITERATION — ``return list({"x", "y", "z"})`` or a dict-comprehension
key order over a set — captured THAT order verbatim into the landed assertion. List
equality is order-SENSITIVE, so ``fn() == ['y', 'x', ...]`` PASSED at generation
(seed 0) yet FAILED under a different ``PYTHONHASHSEED`` in the user's CI: a FLAKY
test landed into a real repo — a never-fake-green + determinism violation.

This module pins the two-part fix:

1. **dict** — ``_canonical_repr`` now renders a dict with its keys SORTED (dict eq
   ignores order, so the bytes become deterministic with NO change to the
   assertion's validity).
2. **list / tuple** — order is semantically meaningful (cannot be sorted), so the
   value-capture site RE-CAPTURES the producing call in a subprocess under a
   DIFFERENT fixed ``PYTHONHASHSEED`` and DECLINES the value oracle unless the
   re-rendered canonical literal is byte-identical. A set-iteration-order list is
   declined (smoke fallback); a deterministically-ordered list still lands.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

from app.execution.test_shield import (
    _canonical_repr,
    _contains_list_or_tuple,
    _order_is_reproducible,
    _recapture_canonical,
    generate_characterization_test,
)

# The repo root, so a child subprocess can import ``app.execution.test_shield``.
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_pkg(root: Path, pkg: str, body: str) -> str:
    """Write ``root/pkg/m.py`` with ``body`` as an importable package; return rel."""
    (root / pkg).mkdir(parents=True, exist_ok=True)
    (root / pkg / "__init__.py").write_text("", encoding="utf-8")
    (root / pkg / "m.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return f"{pkg}/m.py"


def _child_env(root: Path) -> dict[str, str]:
    """Env where a child can import BOTH the repo's ``app`` and the fixture ``root``."""
    return {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join(
            [str(_REPO_ROOT), str(root), os.environ.get("PYTHONPATH", "")]
        ),
    }


# --- Part 1: dict key order is canonicalized (sorted), eq still holds ---------


def test_dict_from_set_iteration_renders_with_sorted_keys():
    # A dict whose KEY ORDER comes from set iteration. Build the SAME logical dict
    # from two different key insertion orders -> identical canonical bytes.
    one = {k: len(k) for k in ["banana", "apple", "cherry"]}
    two = {k: len(k) for k in ["cherry", "banana", "apple"]}
    out_one = _canonical_repr(one)
    out_two = _canonical_repr(two)
    assert out_one == out_two
    # Keys are sorted by their canonical repr (values are each key's length).
    assert out_one == "{'apple': 5, 'banana': 6, 'cherry': 6}"


def test_dict_canonical_literal_is_byte_stable_across_hash_seeds():
    # Render a dict-from-set's canonical literal in fresh interpreters under
    # several PYTHONHASHSEED values; the SORTED-key rendering must be identical.
    probe = (
        "from app.execution.test_shield import _canonical_repr\n"
        "print(_canonical_repr({k: len(k) for k in "
        "{'apple', 'banana', 'cherry', 'date', 'elderberry'}}))\n"
    )
    outs = {}
    for seed in ("0", "1", "12345", "777"):
        env = {**os.environ, "PYTHONHASHSEED": seed,
               "PYTHONPATH": str(_REPO_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")}
        proc = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True,
            env=env, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        outs[seed] = proc.stdout.strip()
    assert len(set(outs.values())) == 1, outs


def test_dict_with_int_keys_round_trips_and_equals():
    import ast

    d = {3: "c", 1: "a", 2: "b"}
    out = _canonical_repr(d)
    # Sorted by key canonical repr ('1' < '2' < '3' as strings == ints here).
    assert out == "{1: 'a', 2: 'b', 3: 'c'}"
    rebuilt = ast.literal_eval(out)
    assert rebuilt == d  # dict eq is order-insensitive -> assertion stays valid


# --- _contains_list_or_tuple (the cheap pre-filter) --------------------------


def test_contains_list_or_tuple_detects_nested_order_sensitive_values():
    assert _contains_list_or_tuple([1, 2, 3]) is True
    assert _contains_list_or_tuple((1, 2)) is True
    assert _contains_list_or_tuple({"a": [1]}) is True  # list hidden in a dict value
    assert _contains_list_or_tuple({(1, 2)}) is True    # tuple hidden in a set
    # Pure scalar / sorted-set / sorted-dict-of-scalars: no order-sensitive child.
    assert _contains_list_or_tuple(42) is False
    assert _contains_list_or_tuple("hello") is False
    assert _contains_list_or_tuple({"a", "b"}) is False
    assert _contains_list_or_tuple({"a": 1, "b": 2}) is False


# --- Part 2: set-iteration list oracle is DECLINED (the P0 repro) -------------


def test_set_order_list_oracle_is_declined(tmp_path):
    rel = _write_pkg(
        tmp_path, "pkgdecl",
        'def set_to_list():\n    return list({"x", "y", "z", "w", "v", "u"})\n',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # The flaky equality oracle MUST NOT be landed; a smoke assertion is.
    assert "== [" not in shield.content
    assert "Shape check only" in shield.content
    assert "callable and runs" in shield.content


def test_p0_repro_generated_test_passes_under_multiple_hash_seeds(tmp_path):
    # End-to-end: generate the test for a set-order-list function, write it, then
    # RUN it under several PYTHONHASHSEED values. The OLD code landed
    # ``assert set_to_list() == ['y', 'x', ...]`` which fails under a different
    # seed; the fix declines it, so the file is green under every seed.
    rel = _write_pkg(
        tmp_path, "pkge2e",
        'def set_to_list():\n    return list({"a", "b", "c", "d", "e", "f"})\n',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    test_file = tmp_path / shield.test_path
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(shield.content, encoding="utf-8")

    for seed in ("0", "1", "12345", "777"):
        env = {**_child_env(tmp_path), "PYTHONHASHSEED": seed}
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file), "-q", "-p", "no:cacheprovider"],
            cwd=str(tmp_path), capture_output=True, text=True, env=env, timeout=120,
        )
        assert proc.returncode == 0, (
            f"generated test FAILED under PYTHONHASHSEED={seed}:\n"
            f"{proc.stdout}\n{proc.stderr}"
        )


# --- Part 2: deterministic lists are NOT over-declined -----------------------


def test_deterministic_lists_still_land_their_value_oracle(tmp_path):
    rel = _write_pkg(
        tmp_path, "pkgdet",
        """
        def literal_list():
            return [1, 2, 3]

        def sorted_from_set():
            return sorted({"gamma", "alpha", "beta"})

        def range_list():
            return list(range(3))

        def comp_list():
            return [x * 2 for x in (1, 2, 3)]
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    content = shield.content
    # Every deterministic list keeps its value oracle (the re-capture matched).
    assert "assert fn() == [1, 2, 3]" in content
    assert "assert fn() == ['alpha', 'beta', 'gamma']" in content
    assert "assert fn() == [0, 1, 2]" in content
    assert "assert fn() == [2, 4, 6]" in content


def test_deterministic_tuple_still_lands_its_value_oracle(tmp_path):
    rel = _write_pkg(
        tmp_path, "pkgtup",
        'def fixed_tuple():\n    return (1, "x", 2.5)\n',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "assert fn() == (1, 'x', 2.5)" in shield.content


# --- _order_is_reproducible / _recapture_canonical direct unit gates ---------


def test_order_is_reproducible_true_for_scalar_without_subprocess():
    # No list/tuple anywhere -> trivially True, NO subprocess spawned (project_root
    # is a bogus path; if it were consulted the call would fail/decline).
    assert _order_is_reproducible(
        Path("/nonexistent"), "no.such.mod", "f", "", 42, "42"
    ) is True
    assert _order_is_reproducible(
        Path("/nonexistent"), "no.such.mod", "f", "", {"a", "b"}, "{'a', 'b'}"
    ) is True


def test_order_is_reproducible_declines_set_order_list(tmp_path):
    rel = _write_pkg(
        tmp_path, "pkgord",
        'def f():\n    return list({"x", "y", "z", "w", "v", "u"})\n',
    )
    dotted = ".".join(Path(rel).with_suffix("").parts)
    value = list({"x", "y", "z", "w", "v", "u"})
    in_proc = _canonical_repr(value)
    # The child renders a (likely) different order -> declined.
    assert _order_is_reproducible(tmp_path, dotted, "f", "", value, in_proc) is False


def test_order_is_reproducible_accepts_deterministic_list(tmp_path):
    rel = _write_pkg(tmp_path, "pkgordok", "def f():\n    return [10, 20, 30]\n")
    dotted = ".".join(Path(rel).with_suffix("").parts)
    value = [10, 20, 30]
    assert _order_is_reproducible(
        tmp_path, dotted, "f", "", value, _canonical_repr(value)
    ) is True


def test_set_order_list_declined_even_when_generation_runs_under_seed_1(tmp_path):
    # SOUNDNESS of the multi-seed gate: run the WHOLE characterization generation
    # in a child pinned to PYTHONHASHSEED=1 (which equals one of the re-capture
    # seeds). A single-seed gate could be fooled into accepting the set-order list
    # here (parent order == that child's order); the multi-seed gate still DECLINES
    # because the OTHER seeds diverge. Proven by generating + writing the test in
    # that seeded child, then running it under several seeds: it must be green.
    rel = _write_pkg(
        tmp_path, "pkgseed1",
        'def set_to_list():\n    return list({"k", "l", "m", "n", "o", "p"})\n',
    )
    gen = (
        "from app.execution.test_shield import "
        "generate_characterization_test, write_shield_test\n"
        f"s = generate_characterization_test({str(tmp_path)!r}, {rel!r})\n"
        "assert s is not None\n"
        "# Must NOT have landed an equality oracle on the set-order list.\n"
        "assert '== [' not in s.content, s.content\n"
        "write_shield_test({0!r}, s)\n".format(str(tmp_path))
    )
    env = {**_child_env(tmp_path), "PYTHONHASHSEED": "1"}
    proc = subprocess.run(
        [sys.executable, "-c", gen], cwd=str(tmp_path),
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # The generated file exists and is green under multiple seeds.
    test_file = tmp_path / "tests" / "test_m.py"
    assert test_file.exists()
    for seed in ("0", "1", "12345", "777"):
        renv = {**_child_env(tmp_path), "PYTHONHASHSEED": seed}
        rproc = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file), "-q", "-p", "no:cacheprovider"],
            cwd=str(tmp_path), capture_output=True, text=True, env=renv, timeout=120,
        )
        assert rproc.returncode == 0, (
            f"seed={seed}:\n{rproc.stdout}\n{rproc.stderr}")


def test_recapture_canonical_returns_none_on_unimportable(tmp_path):
    # A dotted path that does not exist in the child -> decline (None), never crash.
    assert _recapture_canonical(tmp_path, "totally.missing.mod", "f", "", "1") is None


def test_recapture_canonical_matches_in_process_for_deterministic_list(tmp_path):
    rel = _write_pkg(tmp_path, "pkgmatch", "def f():\n    return [7, 8, 9]\n")
    dotted = ".".join(Path(rel).with_suffix("").parts)
    # Identical under every pinned child seed (deterministic list order).
    for seed in ("1", "2", "424242"):
        child = _recapture_canonical(tmp_path, dotted, "f", "", seed)
        assert child == _canonical_repr([7, 8, 9]) == "[7, 8, 9]"


# --- determinism: same input -> same decision twice --------------------------


def test_decision_is_deterministic_across_repeats(tmp_path):
    rel = _write_pkg(
        tmp_path, "pkgrep",
        """
        def flaky():
            return list({"p", "q", "r", "s", "t"})

        def stable():
            return [4, 5, 6]
        """,
    )
    first = generate_characterization_test(tmp_path, rel)
    second = generate_characterization_test(tmp_path, rel)
    assert first is not None and second is not None
    # Byte-identical content twice (the subprocess check is itself deterministic).
    assert first.content == second.content
    # And the decisions are the expected ones.
    assert "assert fn() == [4, 5, 6]" in first.content   # stable list landed
    # flaky() got a smoke assertion, not an equality oracle on its set-order list.
    assert "list({" not in first.content  # never echoes the producing call
    assert first.content.count("Shape check only") == 1  # exactly flaky() declined


# --- the prior set-of-strings fix still holds --------------------------------


def test_prior_set_of_strings_canonicalization_still_holds():
    from app.execution.test_shield import _captured_oracle

    s = {"b", "a", "c"}
    oracle = _captured_oracle(repr(s), s)
    assert oracle == "{'a', 'b', 'c'}"
    assert _canonical_repr({"z", "y", "x"}) == "{'x', 'y', 'z'}"
