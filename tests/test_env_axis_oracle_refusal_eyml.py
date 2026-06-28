"""Environment/run-axis determinism for the value-oracle (latent fake-green fix).

The prior fixes (``test_set_oracle_determinism_eyml`` / ``test_list_order_oracle_eyml``)
closed the ``PYTHONHASHSEED`` axis for set/dict/list ORDER. But the value-capture
sites pinned a scalar value VERBATIM with no env re-check, so a function that reads
the ENVIRONMENT or the CLOCK — ``os.getcwd()``, ``tempfile.mkdtemp()``,
``int(time.time())``, ``os.path.expanduser('~')`` / ``$HOME`` — got its build-machine
value LANDED as a suite-enforced assertion: green here, RED on another machine or the
next run. A float arithmetic result (``0.1 + 0.2`` -> ``0.30000000000000004``) is a
portability hazard too. All are now REFUSED (smoke fallback), while a genuinely
STABLE scalar still lands its oracle.

This module pins that refusal for BOTH cover-gaps (``generate_characterization_test``)
and strengthen-tests (``plan_strengthen_tests``), and unit-tests the shared gate
(:func:`app.execution.test_shield._env_is_reproducible`) and the imprecise-float
guard (:func:`app.execution.test_shield._is_fragile_float`).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from app.execution.strengthen_tests import plan_strengthen_tests
from app.execution.test_shield import (
    _captured_oracle,
    _contains_fragile_float,
    _env_is_reproducible,
    _is_fragile_float,
    generate_characterization_test,
)

# The five empirically-confirmed fragile captures + the float case. Each is a
# top-level public function returning a value that is NOT honest to pin.
_FRAGILE_BODIES = {
    "getcwd": "import os\ndef f():\n    return os.getcwd()\n",
    "mkdtemp": "import tempfile\ndef f():\n    return tempfile.mkdtemp()\n",
    "epoch": "import time\ndef f():\n    return int(time.time())\n",
    "expanduser": "import os\ndef f():\n    return os.path.expanduser('~')\n",
    "home_env": "import os\ndef f():\n    return os.environ.get('HOME', '')\n",
    "float_imprecise": "def f():\n    return 0.1 + 0.2\n",
}


def _write_pkg(root: Path, pkg: str, body: str) -> str:
    (root / pkg).mkdir(parents=True, exist_ok=True)
    (root / pkg / "__init__.py").write_text("", encoding="utf-8")
    (root / pkg / "m.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return f"{pkg}/m.py"


# --- cover-gaps: each fragile capture is REFUSED (smoke fallback) -------------


def test_cover_gaps_refuses_every_fragile_capture(tmp_path):
    for label, body in _FRAGILE_BODIES.items():
        pkg = f"pkgcg_{label}"
        rel = _write_pkg(tmp_path / label, pkg, body)
        shield = generate_characterization_test(tmp_path / label, rel)
        assert shield is not None, label
        content = shield.content
        # NO pinned equality oracle landed for the fragile value.
        assert "Value oracle" not in content, f"{label} landed a value oracle"
        assert "assert fn() ==" not in content, f"{label} pinned a value"
        # The honest smoke fallback IS present.
        assert "Shape check only" in content, label
        assert "callable and runs" in content, label


def test_cover_gaps_never_pins_imprecise_float_literal(tmp_path):
    rel = _write_pkg(tmp_path, "pkgflt", "def f():\n    return 0.1 + 0.2\n")
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "0.30000000000000004" not in shield.content


# --- cover-gaps: a genuinely STABLE scalar STILL lands its oracle -------------


def test_cover_gaps_still_lands_stable_int(tmp_path):
    rel = _write_pkg(tmp_path, "pkgint", "def f():\n    return 42\n")
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "assert fn() == 42" in shield.content


def test_cover_gaps_still_lands_stable_str(tmp_path):
    rel = _write_pkg(tmp_path, "pkgstr", "def f():\n    return 'ok'\n")
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "assert fn() == 'ok'" in shield.content


def test_cover_gaps_still_lands_deterministic_computed_value(tmp_path):
    rel = _write_pkg(tmp_path, "pkgcalc", "def f():\n    return sum(range(10))\n")
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "assert fn() == 45" in shield.content


def test_cover_gaps_still_lands_clean_float(tmp_path):
    # A clean, short-decimal float is NOT fragile and still pins.
    rel = _write_pkg(tmp_path, "pkgcf", "def f():\n    return 2.5\n")
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "assert fn() == 2.5" in shield.content


def test_cover_gaps_decision_is_deterministic_across_repeats(tmp_path):
    rel = _write_pkg(
        tmp_path, "pkgrep",
        "import os\n"
        "def stable():\n    return 7\n\n"
        "def fragile():\n    return os.getcwd()\n",
    )
    first = generate_characterization_test(tmp_path, rel)
    second = generate_characterization_test(tmp_path, rel)
    assert first is not None and second is not None
    assert first.content == second.content  # byte-identical: gate is deterministic
    assert "assert fn() == 7" in first.content      # stable landed
    assert first.content.count("Shape check only") == 1  # exactly fragile() declined


# --- strengthen-tests: a fragile-valued survivor yields NO pinned oracle ------


def _setup_strengthen(root: Path, modbody: str, testbody: str) -> str:
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "m.py").write_text(textwrap.dedent(modbody), encoding="utf-8")
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "test_m.py").write_text(textwrap.dedent(testbody), encoding="utf-8")
    return "pkg/m.py"


# A function whose EVERY return path is the fragile value, with a boundary mutant
# the thin test misses. The double-gate could pick a killing input, but the env
# gate (or the float guard) refuses the value -> no assertion is landed.
_STRENGTHEN_FRAGILE = {
    "getcwd": (
        "import os\n"
        "def classify(n):\n"
        "    if n > 0:\n"
        "        return os.getcwd()\n"
        "    return os.getcwd() + 'x'\n"
    ),
    "epoch": (
        "import time\n"
        "def classify(n):\n"
        "    if n > 0:\n"
        "        return int(time.time())\n"
        "    return int(time.time()) + 1000000\n"
    ),
    "expanduser": (
        "import os\n"
        "def classify(n):\n"
        "    if n > 0:\n"
        "        return os.path.expanduser('~')\n"
        "    return os.path.expanduser('~') + 'x'\n"
    ),
    "float_only": (
        "def classify(n):\n"
        "    if n > 0:\n"
        "        return 0.1 + 0.2\n"
        "    return 0.2 + 0.4\n"
    ),
}

_STRENGTHEN_TEST = (
    "from pkg.m import classify\n"
    "def test_c():\n"
    "    assert classify(5) is not None\n"
)


def test_strengthen_tests_refuses_every_fragile_survivor(tmp_path):
    for label, modbody in _STRENGTHEN_FRAGILE.items():
        sub = tmp_path / label
        rel = _setup_strengthen(sub, modbody, _STRENGTHEN_TEST)
        plan = plan_strengthen_tests(str(sub), rel)
        # The output is Apex's own collision-proof file; on a refusal it is absent.
        content = plan.new_contents.get("tests/test_m_apex_mutants.py", "")
        # No pinned classify(...) == <fragile> assertion landed (called via alias).
        assert "_apex_fn_classify(" not in content, f"{label} pinned a fragile value"
        assert "0.30000000000000004" not in content, label


def test_strengthen_tests_still_lands_stable_survivor(tmp_path):
    # A boundary mutant the thin test misses, returning a STABLE str on each path.
    modbody = (
        "def classify(n):\n"
        "    if n > 0:\n"
        "        return 'pos'\n"
        "    return 'nonpos'\n"
    )
    rel = _setup_strengthen(tmp_path, modbody, _STRENGTHEN_TEST)
    plan = plan_strengthen_tests(str(tmp_path), rel)
    # The stable oracle lands in Apex's own collision-proof generated file.
    content = plan.new_contents.get("tests/test_m_apex_mutants.py", "")
    # A stable value oracle IS landed (the boundary mutant is killed honestly),
    # addressed through the self-contained submodule alias import.
    assert "_apex_fn_classify(" in content
    assert "== 'pos'" in content or "== 'nonpos'" in content


# --- the shared gate, unit-tested directly ------------------------------------


def test_env_is_reproducible_declines_cwd_scalar(tmp_path):
    rel = _write_pkg(tmp_path, "pkgenvcwd", "import os\ndef f():\n    return os.getcwd()\n")
    dotted = ".".join(Path(rel).with_suffix("").parts)
    import os as _os

    in_proc = repr(_os.getcwd())  # the parent's cwd, what cover-gaps would emit
    assert _env_is_reproducible(tmp_path, dotted, "f", "", in_proc) is False


def test_env_is_reproducible_declines_epoch_scalar(tmp_path):
    rel = _write_pkg(tmp_path, "pkgenvtime", "import time\ndef f():\n    return int(time.time())\n")
    dotted = ".".join(Path(rel).with_suffix("").parts)
    import time as _time

    in_proc = repr(int(_time.time()))
    assert _env_is_reproducible(tmp_path, dotted, "f", "", in_proc) is False


def test_env_is_reproducible_accepts_stable_scalar(tmp_path):
    rel = _write_pkg(tmp_path, "pkgenvok", "def f():\n    return 42\n")
    dotted = ".".join(Path(rel).with_suffix("").parts)
    assert _env_is_reproducible(tmp_path, dotted, "f", "", "42") is True


def test_env_is_reproducible_accepts_stable_string(tmp_path):
    rel = _write_pkg(tmp_path, "pkgenvstr", "def f():\n    return 'ok'\n")
    dotted = ".".join(Path(rel).with_suffix("").parts)
    assert _env_is_reproducible(tmp_path, dotted, "f", "", "'ok'") is True


def test_env_is_reproducible_declines_when_unimportable(tmp_path):
    # A dotted path that does not exist in the child -> decline (refuse), never raise.
    assert _env_is_reproducible(tmp_path, "totally.missing.mod", "f", "", "1") is False


# --- the imprecise-float guard ------------------------------------------------


def test_is_fragile_float_flags_arithmetic_imprecision():
    assert _is_fragile_float(0.1 + 0.2) is True       # 0.30000000000000004
    assert _is_fragile_float(1 / 3) is True           # 0.3333333333333333
    assert _is_fragile_float(float("nan")) is True
    assert _is_fragile_float(float("inf")) is True


def test_is_fragile_float_accepts_clean_decimals():
    assert _is_fragile_float(42.0) is False
    assert _is_fragile_float(2.5) is False
    assert _is_fragile_float(0.1) is False            # a short literal, fine to pin
    assert _is_fragile_float(0.5) is False
    assert _is_fragile_float(-1.25) is False


def test_contains_fragile_float_recurses_into_containers():
    assert _contains_fragile_float([0.1 + 0.2]) is True
    assert _contains_fragile_float({"x": 1 / 3}) is True
    assert _contains_fragile_float((1, 2.5, "ok")) is False
    assert _contains_fragile_float({"a": 1, "b": 2}) is False


def test_captured_oracle_declines_imprecise_float_but_keeps_clean():
    assert _captured_oracle(repr(0.1 + 0.2), 0.1 + 0.2) is None
    assert _captured_oracle(repr(2.5), 2.5) == "2.5"
    assert _captured_oracle(repr(42), 42) == "42"
