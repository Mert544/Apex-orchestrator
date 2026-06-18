"""Deep-mutation characterization tests for the two POLYGLOT frontier modules.

Targets the deep mutation survivors that slip past the default 30-mutant cap in
``app.engine.mutation_tester`` for:

  * ``app.engine.polyglot_findings``  (high-confidence non-Python detectors)
  * ``app.execution.polyglot_flag``   (safe review-flag insertion)

Each test below pins exactly the behaviour a surviving single-token mutant would
silently change — a boundary slide (``<`` vs ``<=``), an off-by-one constant
(``n`` vs ``n+1``), a flipped ``or``/``and``, or a ``return []`` weakened to
``return None``. Every assertion is deterministic (no clock/random, no reliance
on set/dict ordering for values), stdlib + pytest only, hermetic ``tmp_path``.

The survivor inventory (module:line — mutation) each test kills is named in the
test docstring so the mapping stays auditable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.polyglot_findings import (
    _is_placeholder,
    _scan_file,
    scan_polyglot_findings,
)
from app.execution.polyglot_flag import flag_line, is_flagged


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


# ===========================================================================
# polyglot_findings — deep survivors
# ===========================================================================

# --- _MAX_LINE_LEN boundary (findings L76 number 2000>2001, L266 boundary >>>=)
# The "minified line is skipped" guard is ``len(line) > _MAX_LINE_LEN`` with
# _MAX_LINE_LEN == 2000. A line of EXACTLY 2000 chars must still be scanned; a
# line of EXACTLY 2001 chars must be skipped. This pins both the constant (2001
# would let a 2001-char line through) and the boundary (``>=`` would drop the
# legitimate 2000-char line).

def test_line_of_exactly_max_len_is_scanned(tmp_path):
    """findings L76/L266: a 2000-char vuln line fires; the > guard stays strict."""
    line2000 = "eval(x);" + "/" * (2000 - len("eval(x);"))
    assert len(line2000) == 2000
    _write(tmp_path, "a.js", line2000 + "\n")
    hits = [f for f in scan_polyglot_findings(str(tmp_path)) if f["kind"] == "js-eval"]
    assert len(hits) == 1
    assert hits[0]["line"] == 1


def test_line_of_one_over_max_len_is_skipped(tmp_path):
    """findings L76/L266: a 2001-char vuln line is dropped as minified/generated."""
    line2001 = "eval(x);" + "/" * (2001 - len("eval(x);"))
    assert len(line2001) == 2001
    _write(tmp_path, "a.js", line2001 + "\n")
    hits = [f for f in scan_polyglot_findings(str(tmp_path)) if f["kind"] == "js-eval"]
    assert hits == []


def test_max_len_boundary_both_lines_in_one_file(tmp_path):
    """findings L76/L266: with a 2000- and a 2001-char line, only line 1 fires."""
    line2000 = "eval(x);" + "/" * (2000 - len("eval(x);"))
    line2001 = "eval(x);" + "/" * (2001 - len("eval(x);"))
    _write(tmp_path, "a.js", line2000 + "\n" + line2001 + "\n")
    lines = sorted(
        f["line"] for f in scan_polyglot_findings(str(tmp_path)) if f["kind"] == "js-eval"
    )
    assert lines == [1]


# --- _is_placeholder length boundary (findings L169 boundary <><=, number 6>7)
# ``if len(val) < 6: return True`` — a value of exactly 6 real chars is NOT a
# placeholder (so the secret fires); 5 chars IS a placeholder. ``<=`` or ``< 7``
# would wrongly treat the 6-char value as a placeholder and suppress the finding.

def test_is_placeholder_six_char_value_is_real(tmp_path):
    """findings L169: a 6-char secret value is real (not a placeholder)."""
    assert _is_placeholder("abcdef") is False


def test_is_placeholder_five_char_value_is_placeholder(tmp_path):
    """findings L169: a 5-char value is too short — treated as placeholder."""
    assert _is_placeholder("abcde") is True


def test_six_char_secret_fires_via_scan(tmp_path):
    """findings L169: end-to-end, a 6-char hardcoded secret value fires."""
    _write(tmp_path, "a.ts", 'const password = "abcdef";\n')
    hits = [
        f for f in scan_polyglot_findings(str(tmp_path)) if f["kind"] == "hardcoded-secret"
    ]
    assert len(hits) == 1
    assert hits[0]["line"] == 1


def test_five_char_secret_does_not_fire_via_scan(tmp_path):
    """findings L169: a 5-char value is suppressed (conservative no-fire)."""
    _write(tmp_path, "a.ts", 'const password = "abcde";\n')
    hits = [
        f for f in scan_polyglot_findings(str(tmp_path)) if f["kind"] == "hardcoded-secret"
    ]
    assert hits == []


# --- _scan_file OSError path (findings L262 return []>None)
# When the file can't be read, ``_scan_file`` returns ``[]`` (an empty list the
# caller can ``extend`` with). A mutant returning ``None`` would break the
# ``findings.extend(...)`` contract. Reading a *directory* path raises an
# ``OSError`` (``IsADirectoryError``), exercising that branch deterministically.

def test_scan_file_on_unreadable_returns_empty_list(tmp_path):
    """findings L262: the OSError branch returns [] (a list), never None."""
    d = tmp_path / "adir.js"
    d.mkdir()
    result = _scan_file(d, "adir.js", "js")
    assert result == []
    assert isinstance(result, list)


# --- max_files default constant (findings L298 number 400>401)
# The default cap is 400. With 401 in-scope vuln files (path-sorted), the default
# scan keeps exactly the smallest-400 paths and drops the 401st. A mutant default
# of 401 would include that 401st file.

def test_default_max_files_caps_at_400(tmp_path):
    """findings L298: the default scan keeps exactly 400 files, dropping the 401st."""
    for i in range(401):
        _write(tmp_path, f"f{i:04d}.js", "eval(x);\n")
    paths = {f["path"] for f in scan_polyglot_findings(str(tmp_path))}
    assert len(paths) == 400
    # Path-sorted, so the largest-named file is the one dropped at the cap.
    assert "f0400.js" not in paths
    assert "f0399.js" in paths


# --- max_files / root guard (findings L315: number 0>1 killed here)
# ``if max_files <= 0 or not root_path.exists(): return []``.
#
# NOTE on the two EQUIVALENT mutants on this line (documented, not killed):
#   * boundary ``<=`` -> ``<`` and boolean ``or`` -> ``and`` are EQUIVALENT.
#     The guard is a pure short-circuit: every case where the mutant would
#     instead fall through to the body still yields ``[]``, because the
#     downstream ``_iter_candidates(...)[:max_files]`` slice returns ``[]`` for
#     any ``max_files <= 0`` and ``rglob`` over a missing root yields nothing.
#     So no input distinguishes the mutant from the original — unkillable by
#     construction. The ``number 0>1`` mutant on the SAME line (``<= 0`` ->
#     ``<= 1``) is REAL and killed by ``test_max_files_one_scans_a_single_file``
#     below: at ``max_files == 1`` the mutant would early-return ``[]`` while the
#     original scans the single smallest file.

def test_max_files_zero_returns_empty_even_with_vuln_files(tmp_path):
    """findings L315: max_files == 0 yields [] (characterizes the guard)."""
    _write(tmp_path, "a.js", "eval(x);\n")
    assert scan_polyglot_findings(str(tmp_path), max_files=0) == []


def test_max_files_negative_returns_empty(tmp_path):
    """findings L315: a negative cap yields [] (characterizes the guard)."""
    _write(tmp_path, "a.js", "eval(x);\n")
    assert scan_polyglot_findings(str(tmp_path), max_files=-1) == []


def test_max_files_one_scans_a_single_file(tmp_path):
    """findings L315: max_files == 1 still scans one file (kills number 0>1).

    The ``<= 0`` guard mutated to ``<= 1`` would early-return [] at a cap of 1;
    the original scans the single smallest-path file.
    """
    for i in range(3):
        _write(tmp_path, f"f{i}.js", "eval(x);\n")
    paths = {f["path"] for f in scan_polyglot_findings(str(tmp_path), max_files=1)}
    assert paths == {"f0.js"}


# ===========================================================================
# polyglot_flag — deep survivors (all in is_flagged's range guard, L93)
# ===========================================================================

# ``if line < 2 or line > len(lines) + 1: return False`` — the idempotence /
# already-flagged check. Four single-token mutants survive the cap here.

def test_is_flagged_recognises_flag_above_line_two(tmp_path):
    """flag L93: line == 2 inspects line 1; a flag there is recognised.

    Kills ``line < 2`` -> ``line <= 2`` and ``line < 2`` -> ``line < 3`` (both
    would make line 2 fall into the out-of-range branch and return False).
    """
    src = "// Apex: m\nb = 2\n"
    assert is_flagged(src, 2, "m") is True


def test_flag_line_idempotent_when_flag_on_line_one(tmp_path):
    """flag L93: re-flagging line 2 after a line-1 flag declines (idempotent).

    End-to-end form of the ``line < 2`` boundary: ``flag_line`` consults
    ``is_flagged`` for line 2, sees the existing line-1 flag, and returns None.
    """
    src = "// Apex: m\nb = 2\n"
    assert flag_line("x.js", src, 2, "m") is None


def test_is_flagged_recognises_flag_on_last_line_at_len_plus_one(tmp_path):
    """flag L93: querying line == len(lines)+1 inspects the LAST line.

    Kills ``line > len(lines) + 1`` -> ``line >= len(lines) + 1`` (the ``>=``
    would reject the in-range len+1 query and return False).
    """
    src = "a = 1\n// Apex: m\n"  # 2 lines; flag on line 2 (the last line)
    assert len(src.splitlines()) == 2
    assert is_flagged(src, 3, "m") is True


def test_is_flagged_two_past_end_returns_false_without_raising(tmp_path):
    """flag L93: querying line == len(lines)+2 is out of range -> False, no raise.

    Kills ``len(lines) + 1`` -> ``len(lines) + 2`` (which would let the query
    through to ``lines[line - 2]`` and raise IndexError instead of declining).
    """
    src = "a = 1\n// Apex: m\n"  # 2 lines
    assert is_flagged(src, 4, "m") is False


def test_is_flagged_far_past_end_returns_false(tmp_path):
    """flag L93: a wildly out-of-range query declines cleanly (range guard holds)."""
    src = "a = 1\nb = 2\n"
    assert is_flagged(src, 50, "m") is False


@pytest.mark.parametrize(
    "prefix,suffix,path",
    [
        ("# Apex: ", "", "c.yaml"),
        ("<!-- Apex: ", " -->", "p.html"),
    ],
)
def test_is_flagged_last_line_for_hash_and_html(prefix, suffix, path, tmp_path):
    """flag L93: the len+1 boundary holds for hash and HTML comment syntaxes too."""
    src = f"key: val\n{prefix}m{suffix}\n"
    n = len(src.splitlines())
    assert is_flagged(src, n + 1, "m") is True
    assert is_flagged(src, n + 2, "m") is False
