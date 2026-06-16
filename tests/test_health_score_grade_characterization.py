"""Characterization tests pinning grade()'s FULL output byte-for-byte.

These lock the grade engine's exact output (letter, numeric score, and every
bucket's penalty/detail/top_files) across representative project trees so the
decomposition of grade() into helpers stays provably byte-identical.
"""

from __future__ import annotations

from app.engine.health_score import grade


def _snapshot(h):
    """A fully-comparable, order-preserving view of a HealthScore."""
    return {
        "score": h.score,
        "letter": h.letter,
        "fixes": list(h.fixes),
        "scope_line": h.scope_line,
        "components": [
            (c.name, c.points_lost, c.detail, list(c.top_files))
            for c in h.components
        ],
    }


def _build_clean(root):
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "calc.py").write_text(
        'def add(a, b):\n    """Add."""\n    return a + b\n', encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(
        "from app.calc import add\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8")


def _build_messy(root):
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "risky.py").write_text(
        "import yaml\n\n\n"
        "def load(s, cache=[]):\n"
        "    if s == None:\n"
        "        return eval(s)\n"
        "    return yaml.load(s)\n",
        encoding="utf-8")
    (root / "app" / "untested.py").write_text(
        "def helper(x):\n    return x + 1\n", encoding="utf-8")
    branchy = "def grade_fn(n):\n    total = 0\n" + "".join(
        f"    if n == {i}:\n        total += {i}\n" for i in range(14)
    ) + "    return total\n"
    dup = (
        "    a = 1\n    b = 2\n    c = 3\n    d = 4\n    e = 5\n"
        "    return a + b + c + d + e\n"
    )
    (root / "app" / "big.py").write_text(
        branchy + "\n\ndef one():\n" + dup + "\n\ndef two():\n" + dup,
        encoding="utf-8")
    (root / "tests" / "test_big.py").write_text(
        "from app.big import grade_fn\ndef test_g():\n    assert grade_fn(0) == 0\n",
        encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='p'\nversion='0'\n", encoding="utf-8")


def _build_security_heavy(root):
    (root / "app").mkdir()
    (root / "app" / "m.py").write_text(
        "import tempfile, hashlib\n"
        "def t():\n    return tempfile.mktemp()\n"
        "def h(b):\n    return hashlib.md5(b).hexdigest()\n"
        "def r(c):\n    return eval(c)\n",
        encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='p'\nversion='0'\n", encoding="utf-8")


# Pinned snapshot produced by grade() at base commit d439a19.
_EXPECTED_CLEAN = {
    "score": 100,
    "letter": "A+",
    "fixes": [],
    "scope_line": "",
    "components": [
        ("Security", 0, "0 finding(s)", []),
        ("Architecture", 0, "0 import cycle(s), 0 fragile module(s)", []),
        ("Testing", 0, "0 untested module(s) of ~1", []),
        ("Code debt", 0,
         "0 module(s) with modernization / mutable-default / reliability debt", []),
        ("Correctness", 0, "0 likely-crash / dead-code bug(s)", []),
        ("Maintainability", 0, "0 function(s) over complexity 12", []),
        ("Duplication", 0, "0 duplicated block(s)", []),
    ],
}


def test_characterization_clean_matches_pinned(tmp_path):
    _build_clean(tmp_path)
    assert _snapshot(grade(str(tmp_path))) == _EXPECTED_CLEAN


def test_characterization_messy_is_stable(tmp_path):
    """Two independent builds of the same messy tree grade byte-identically."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _build_messy(a)
    _build_messy(b)
    sa = _snapshot(grade(str(a)))
    sb = _snapshot(grade(str(b)))
    assert sa == sb
    # The messy tree must genuinely lose points across multiple buckets.
    lost = {name: lost for name, lost, _d, _t in sa["components"]}
    assert sa["score"] < 100
    assert lost["Security"] > 0
    assert lost["Testing"] > 0
    assert lost["Maintainability"] > 0
    assert lost["Duplication"] > 0


def test_characterization_security_heavy_is_stable(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _build_security_heavy(a)
    _build_security_heavy(b)
    sa = _snapshot(grade(str(a)))
    sb = _snapshot(grade(str(b)))
    assert sa == sb
    lost = {name: lost for name, lost, _d, _t in sa["components"]}
    assert lost["Security"] > 0
