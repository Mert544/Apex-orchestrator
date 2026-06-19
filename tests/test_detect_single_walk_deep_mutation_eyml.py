"""Deep-mutation hardening for ``detect``'s single-walk + per-source memo.

The Batch-B perf fix made ``detect(source)`` (a) materialize ONE whole-tree
``ast.walk`` shared across every logical pass (was four), and (b) memoize on the
exact source string. Both must be strictly OUTPUT-PRESERVING. These tests pin the
mutation-killing invariants:

  * exactly ONE ``Module``-level ``ast.walk`` per UNCACHED ``detect`` (a warm
    call walks ZERO times — it is a pure cache lookup);
  * ``_DETECT_CACHE`` returns an EQUAL-but-INDEPENDENT list — mutating the
    returned list (append/clear) never poisons the cache;
  * the cache is keyed on the EXACT source string — a one-character change MISSES
    (does not return the neighbour's findings);
  * the cache is bounded at ``_DETECT_CACHE_MAX`` and CLEARS WHOLESALE when full
    (the entry that overflows it triggers a full clear, not an eviction);
  * findings are BYTE-IDENTICAL cold vs warm over a battery of real sources.

Finding *content* is owned by ``test_detectors.py``; this file pins that the
optimization changed nothing observable except speed.
"""

from __future__ import annotations

import ast

import app.engine.detectors as det
from app.engine.detectors import Issue, detect


_SAMPLE = (
    "import subprocess\n"
    "def q(conn, name):\n"
    "    s = f\"select * from t where n = {name}\"\n"
    "    conn.execute(s)\n"
    "    return 1\n"
    "    dead = 2\n"
)


def _findings(src: str):
    return [(i.line, i.category, i.severity, i.message, i.fix_kind) for i in detect(src)]


def _count_module_walks(src: str) -> int:
    """Whole-tree ``ast.walk`` calls (those handed a ``Module``) for one detect()."""
    real = ast.walk
    seen: list[str] = []

    def spy(tree):
        seen.append(type(tree).__name__)
        return real(tree)

    det.ast.walk = spy
    try:
        det.detect(src)
    finally:
        det.ast.walk = real
    return seen.count("Module")


# --------------------------------------------------------------------------- #
# ONE whole-tree walk per uncached detect; ZERO on a warm (cached) call.       #
# --------------------------------------------------------------------------- #


def test_uncached_detect_does_exactly_one_module_walk():
    """The shared-walk collapse: a cold detect walks the Module exactly once,
    not four times (the unreachable, dispatch, SQL-map, and SQL-sink passes all
    share the single materialized ``ast.walk``)."""
    det._DETECT_CACHE.clear()
    assert _count_module_walks(_SAMPLE) == 1


def test_warm_detect_does_zero_module_walks():
    """A cached repeat is a pure dict lookup — it must not re-walk at all. Pins
    that the memo short-circuits BEFORE ``_detect_uncached`` runs."""
    det._DETECT_CACHE.clear()
    detect(_SAMPLE)  # prime
    assert _count_module_walks(_SAMPLE) == 0


def test_sql_and_unreachable_shapes_still_single_walk():
    """The SQL and unreachable passes used to add extra full-tree walks; confirm
    each shape stays at exactly one Module walk when cold."""
    det._DETECT_CACHE.clear()
    assert _count_module_walks("def q(c, n):\n    s = f\"select {n}\"\n    c.execute(s)\n") == 1
    det._DETECT_CACHE.clear()
    assert _count_module_walks("def f():\n    return 1\n    x = 2\n") == 1


# --------------------------------------------------------------------------- #
# Cache independence: a mutated result never poisons the cache.                #
# --------------------------------------------------------------------------- #


def test_memo_returns_equal_but_independent_lists():
    det._DETECT_CACHE.clear()
    first = detect(_SAMPLE)
    second = detect(_SAMPLE)
    assert first == second
    assert first is not second  # a fresh list copy each call


def test_appending_to_result_does_not_poison_cache():
    """Mutating the returned list (append) must not change a later detect()."""
    det._DETECT_CACHE.clear()
    baseline = detect(_SAMPLE)
    leaked = detect(_SAMPLE)
    leaked.append(Issue(1, "bug", "low", "POISON", ""))
    fresh = detect(_SAMPLE)
    assert fresh == baseline
    assert all(i.message != "POISON" for i in fresh)
    assert len(fresh) == len(baseline)


def test_clearing_result_does_not_empty_cache():
    """Mutating the returned list (clear) must not empty the cached entry."""
    det._DETECT_CACHE.clear()
    baseline = detect(_SAMPLE)
    assert baseline  # the sample has findings to lose
    detect(_SAMPLE).clear()
    again = detect(_SAMPLE)
    assert again == baseline
    assert len(again) == len(baseline)


def test_cached_entry_itself_is_not_the_returned_object():
    """The object stored in ``_DETECT_CACHE`` is distinct from what ``detect``
    hands back, so a caller can never reach the cache's own list."""
    det._DETECT_CACHE.clear()
    returned = detect(_SAMPLE)
    assert returned is not det._DETECT_CACHE[_SAMPLE]
    assert returned == det._DETECT_CACHE[_SAMPLE]


# --------------------------------------------------------------------------- #
# Exact-source keying: a one-character change misses.                          #
# --------------------------------------------------------------------------- #


def test_one_char_change_misses_the_cache():
    """Two sources differing by a single character get DISTINCT cache entries;
    neither returns the other's findings. Kills a mutant that keys on something
    coarser than the exact string (e.g. a hash collision / length)."""
    det._DETECT_CACHE.clear()
    a = "def f():\n    return 1\n    x = 2\n"
    b = "def f():\n    return 1\n    x = 3\n"  # one char different
    fa = detect(a)
    fb = detect(b)
    assert a in det._DETECT_CACHE
    assert b in det._DETECT_CACHE
    # A repeat returns each source's OWN findings, not the neighbour's.
    assert detect(a) == fa
    assert detect(b) == fb


def test_whitespace_variant_is_a_distinct_key():
    """A trailing-newline difference is a different exact string -> distinct
    entry (the memo never normalizes the source before keying)."""
    det._DETECT_CACHE.clear()
    base = "x = eval(y)\n"
    spaced = "x = eval(y)\n\n"
    detect(base)
    detect(spaced)
    assert base in det._DETECT_CACHE
    assert spaced in det._DETECT_CACHE
    assert det._DETECT_CACHE[base] == det._DETECT_CACHE[spaced]  # same findings, two keys


# --------------------------------------------------------------------------- #
# Bound: clears wholesale when full.                                           #
# --------------------------------------------------------------------------- #


def test_cache_never_exceeds_max():
    det._DETECT_CACHE.clear()
    for i in range(det._DETECT_CACHE_MAX + 50):
        detect(f"x{i} = 1\n")
    assert len(det._DETECT_CACHE) <= det._DETECT_CACHE_MAX


def test_full_cache_clears_wholesale_then_holds_the_new_entry():
    """At exactly ``_DETECT_CACHE_MAX`` entries the next NEW source clears the
    whole cache before inserting, so the cache drops to a single entry. Pins the
    ``>=``-then-``clear()`` boundary (an eviction mutant would leave it full)."""
    det._DETECT_CACHE.clear()
    # Fill to exactly the cap with distinct sources.
    for i in range(det._DETECT_CACHE_MAX):
        detect(f"y{i} = 1\n")
    assert len(det._DETECT_CACHE) == det._DETECT_CACHE_MAX
    # One more NEW source triggers the wholesale clear, leaving only itself.
    overflow = "z_overflow = 1\n"
    detect(overflow)
    assert len(det._DETECT_CACHE) == 1
    assert overflow in det._DETECT_CACHE


def test_repeat_at_cap_does_not_trigger_clear():
    """A repeated (already-cached) source at the cap is a hit — it must NOT clear
    the cache, because the early ``return list(cached)`` runs before the bound
    check. Pins that only a genuine MISS can clear."""
    det._DETECT_CACHE.clear()
    for i in range(det._DETECT_CACHE_MAX):
        detect(f"k{i} = 1\n")
    assert len(det._DETECT_CACHE) == det._DETECT_CACHE_MAX
    detect("k0 = 1\n")  # a cache HIT at full capacity
    assert len(det._DETECT_CACHE) == det._DETECT_CACHE_MAX


# --------------------------------------------------------------------------- #
# Byte-identical cold vs warm over a battery of real sources.                  #
# --------------------------------------------------------------------------- #


def _battery() -> dict[str, str]:
    import glob

    sources = {
        "__sample__": _SAMPLE,
        "__empty__": "",
        "__comment__": "# nothing\n",
        "__syntax_error__": "def f(:\n    pass\n",
        "__clean__": "def documented():\n    \"\"\"Doc.\"\"\"\n    return 1\n",
        "__eval__": "x = eval(src)\n",
        "__bare_except__": "try:\n    pass\nexcept:\n    pass\n",
    }
    for path in sorted(glob.glob("app/**/*.py", recursive=True))[:40]:
        try:
            with open(path, encoding="utf-8") as fh:
                sources[path] = fh.read()
        except OSError:
            pass
    return sources


def test_findings_byte_identical_cold_vs_warm():
    """Cold (cache cleared) vs warm (cache primed) findings are byte-for-byte
    equal over a real-source battery — the memo changed nothing observable."""
    battery = _battery()
    det._DETECT_CACHE.clear()
    cold = {k: _findings(v) for k, v in battery.items()}
    warm = {k: _findings(v) for k, v in battery.items()}  # all hits now
    assert cold == warm


def test_syntax_error_path_cached_independently():
    """The SyntaxError marker is cached too — a warm repeat returns an equal,
    independent list (mutating it does not poison the cache)."""
    det._DETECT_CACHE.clear()
    src = "def f(:\n    pass\n"
    err = detect(src)
    assert len(err) == 1 and err[0].category == "bug" and err[0].severity == "high"
    again = detect(src)
    assert again == err
    assert again is not err
    again.append(Issue(9, "bug", "low", "POISON", ""))
    assert detect(src) == err
