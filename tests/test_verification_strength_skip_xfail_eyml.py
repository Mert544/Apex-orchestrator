"""A change NO test runs must never grade as "verified".

`assess_strength` is a static name-matcher: it upgraded a change to coverage
level ``function`` whenever a referencing test file MENTIONED the changed
function's name in a code position — with zero awareness of whether that line
can actually execute and assert against the change. Two independent red-teams
plus a field-test located the lie precisely:

  * a ``@pytest.mark.skip``/``skipif`` test naming the fn was graded ``function``
    (the test never runs);
  * a ``@pytest.mark.xfail`` test was graded ``function`` even when it asserts the
    WRONG value (its failing assertion is the EXPECTED outcome, so the suite stays
    green) — the ``slugify(text) -> return text`` "verified" lie;
  * a name inside ``if False:`` / after a ``return``/``raise`` (statically
    unreachable) was graded ``function``.

``function``/``module`` coverage flips ``coverage_verified`` true and the develop
session labels the move ``verified`` — so a change no test executed was stamped
"verified". These tests pin the fix: a reference reachable ONLY from a
skip/xfail test or a statically-unreachable position is NOT coverage. The grader
demotes such a change to ``none``/``test-change`` (develop tier ``weak``/
``no-suite``), NEVER ``function``/``verified``. A genuinely asserting, reachable,
non-skipped test still grades ``function`` (no over-demotion). Deterministic;
strengthens never-fake-green (fewer false "verified", never more).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.verification_strength import (
    _names_changed_function,
    assess_strength,
)

# A changed function whose body actually flips behaviour (slugify lie repro).
_OLD = "def slugify(text):\n    return text.lower().replace(' ', '-')\n"
_NEW = "def slugify(text):\n    return text\n"


def _project(tmp_path: Path, test_body: str) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "svc.py").write_text(_OLD, encoding="utf-8")
    (tmp_path / "tests" / "test_x.py").write_text(test_body, encoding="utf-8")
    return tmp_path


def _assess(tmp_path: Path) -> dict:
    return assess_strength(
        tmp_path, ["app/svc.py"], {"app/svc.py": _OLD}, {"app/svc.py": _NEW})


# --------------------------------------------------------------------------- #
# The fake-green repros: a change covered ONLY by an inert/unreachable reference
# must NOT reach function-level coverage.
# --------------------------------------------------------------------------- #

def test_skip_only_reference_is_not_function_coverage(tmp_path: Path):
    # A skip test names the fn but never runs -> proves nothing.
    s = _project(tmp_path,
                 "import pytest\nfrom app.svc import slugify\n"
                 "@pytest.mark.skip(reason='wip')\n"
                 "def test_slug():\n    assert slugify('a b') == 'a-b'\n")
    out = _assess(s)
    assert out["level"] != "function"
    assert out["function_tests"] == []
    # The module IS imported, so it grades 'module' (a green suite imports it but
    # never asserts the change) -- still NOT 'verified'.
    assert out["level"] == "module"


def test_skipif_only_reference_is_not_function_coverage(tmp_path: Path):
    s = _project(tmp_path,
                 "import pytest\nfrom app.svc import slugify\n"
                 "@pytest.mark.skipif(True, reason='env')\n"
                 "def test_slug():\n    assert slugify('a b') == 'a-b'\n")
    out = _assess(s)
    assert out["level"] != "function"
    assert out["function_tests"] == []


def test_xfail_only_reference_is_not_function_coverage(tmp_path: Path):
    # The field-test repro: an xfail test asserting the WRONG value keeps the
    # suite green for the broken body -> must never be "verified".
    s = _project(tmp_path,
                 "import pytest\nfrom app.svc import slugify\n"
                 "@pytest.mark.xfail\n"
                 "def test_slug():\n    assert slugify('a b') == 'TOTALLY WRONG'\n")
    out = _assess(s)
    assert out["level"] != "function"
    assert out["function_tests"] == []


def test_if_false_body_reference_is_not_function_coverage(tmp_path: Path):
    s = _project(tmp_path,
                 "from app.svc import slugify\n"
                 "def test_slug():\n    if False:\n        slugify('a b')\n")
    out = _assess(s)
    assert out["level"] != "function"
    assert out["function_tests"] == []


def test_if_zero_body_reference_is_not_function_coverage(tmp_path: Path):
    s = _project(tmp_path,
                 "from app.svc import slugify\n"
                 "def test_slug():\n    if 0:\n        slugify('a b')\n")
    out = _assess(s)
    assert out["level"] != "function"


def test_after_return_reference_is_not_function_coverage(tmp_path: Path):
    s = _project(tmp_path,
                 "from app.svc import slugify\n"
                 "def test_slug():\n    return\n    slugify('a b')\n")
    out = _assess(s)
    assert out["level"] != "function"
    assert out["function_tests"] == []


def test_after_raise_reference_is_not_function_coverage(tmp_path: Path):
    s = _project(tmp_path,
                 "from app.svc import slugify\n"
                 "def test_slug():\n    raise RuntimeError()\n    slugify('a b')\n")
    assert _assess(s)["level"] != "function"


def test_after_break_in_loop_is_not_function_coverage(tmp_path: Path):
    s = _project(tmp_path,
                 "from app.svc import slugify\n"
                 "def test_slug():\n    for _ in range(2):\n"
                 "        break\n        slugify('a b')\n")
    assert _assess(s)["level"] != "function"


def test_skip_only_module_change_is_not_verified_tier(tmp_path: Path):
    # The whole point: the develop session keys "verified" off function/module
    # coverage. A skip-only reference must not let coverage_verified stand.
    s = _project(tmp_path,
                 "import pytest\nfrom app.svc import slugify\n"
                 "@pytest.mark.skip\n"
                 "def test_slug():\n    assert slugify('a b') == 'a-b'\n")
    out = _assess(s)
    # Function-level (the tier that flips coverage_verified) is withheld.
    assert out["level"] in ("module", "none", "test-change")
    assert out["level"] != "function"


# --------------------------------------------------------------------------- #
# No over-demotion: a real, reachable, non-skip/non-xfail asserting test still
# grades function-level -> verified.
# --------------------------------------------------------------------------- #

def test_real_asserting_reachable_test_still_function_verified(tmp_path: Path):
    s = _project(tmp_path,
                 "from app.svc import slugify\n"
                 "def test_slug():\n    assert slugify('a b') == 'a-b'\n")
    out = _assess(s)
    assert out["level"] == "function"
    assert out["function_tests"] == ["tests/test_x.py"]


def test_reference_in_else_of_if_false_still_counts(tmp_path: Path):
    # The body of `if False:` is dead, but its `else:` runs -> real coverage.
    s = _project(tmp_path,
                 "from app.svc import slugify\n"
                 "def test_slug():\n    if False:\n        pass\n"
                 "    else:\n        assert slugify('a b') == 'a-b'\n")
    assert _assess(s)["level"] == "function"


def test_reachable_call_before_a_skip_test_still_counts(tmp_path: Path):
    # One reachable test asserts; another skip test also names it. The reachable
    # one suffices -> function-level (a present skip sibling never demotes).
    s = _project(tmp_path,
                 "import pytest\nfrom app.svc import slugify\n"
                 "def test_real():\n    assert slugify('a b') == 'a-b'\n"
                 "@pytest.mark.skip\n"
                 "def test_skipped():\n    assert slugify('x') == 'x'\n")
    assert _assess(s)["level"] == "function"


def test_reference_inside_try_body_counts(tmp_path: Path):
    s = _project(tmp_path,
                 "from app.svc import slugify\n"
                 "def test_slug():\n    try:\n        assert slugify('a b') == 'a-b'\n"
                 "    except AssertionError:\n        raise\n")
    assert _assess(s)["level"] == "function"


# --------------------------------------------------------------------------- #
# Unit-level: the reachability/inert exclusion in _names_changed_function, plus
# empty/edge paths and determinism.
# --------------------------------------------------------------------------- #

def test_names_changed_function_excludes_inert_and_unreachable():
    skip = ("import pytest\nfrom app.svc import slugify\n"
            "@pytest.mark.skip\ndef t():\n    slugify('a')\n")
    xfail = ("import pytest\nfrom app.svc import slugify\n"
             "@pytest.mark.xfail\ndef t():\n    slugify('a')\n")
    dead = "from app.svc import slugify\ndef t():\n    return\n    slugify('a')\n"
    real = "from app.svc import slugify\ndef t():\n    slugify('a')\n"
    assert _names_changed_function(skip, ["slugify"]) is False
    assert _names_changed_function(xfail, ["slugify"]) is False
    assert _names_changed_function(dead, ["slugify"]) is False
    assert _names_changed_function(real, ["slugify"]) is True


def test_names_changed_function_empty_inputs():
    # No funcs to look for, and empty text: never a false positive.
    assert _names_changed_function("", ["slugify"]) is False
    assert _names_changed_function("def t():\n    slugify()\n", []) is False
    assert _names_changed_function("", []) is False


def test_unparsable_fallback_still_matches_whole_word():
    # An unparsable test still counts via the whole-word regex fallback (a real
    # syntax error shouldn't silently zero out coverage); the fallback cannot see
    # reachability OR comments, which is the documented, conservative limit — it
    # only ever errs toward MORE coverage on text it cannot parse, never less.
    broken = "from app.svc import slugify\ndef t(\n    slugify('a')\n"
    assert _names_changed_function(broken, ["slugify"]) is True
    # A non-matching whole word in unparsable text still yields False.
    assert _names_changed_function("def t(\n    other('a')\n", ["slugify"]) is False


def test_determinism_same_input_same_output(tmp_path: Path):
    s = _project(tmp_path,
                 "import pytest\nfrom app.svc import slugify\n"
                 "@pytest.mark.xfail\n"
                 "def test_slug():\n    assert slugify('a b') == 'nope'\n"
                 "def test_real():\n    assert slugify('c d') == 'c-d'\n")
    first = _assess(s)
    for _ in range(4):
        assert _assess(s) == first
    # The real test still wins -> function-level despite the xfail sibling.
    assert first["level"] == "function"
