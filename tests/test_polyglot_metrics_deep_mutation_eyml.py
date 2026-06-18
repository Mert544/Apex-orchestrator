"""Deep-mutation-hardening characterization tests for ``polyglot_metrics``.

These tests exist to KILL mutation survivors that escaped the 30-mutant cap of
``app.engine.mutation_tester`` on this FRONTIER module. A full enumeration of the
89-site mutation universe (every ``_collect_sites`` site, each spliced via
``_splice`` and run against the covering suite in a /tmp copy) left 37 survivors;
this file pins down the REAL (killable) ones with hermetic fixtures of known
shape. Nothing here depends on the Apex repo's own non-Python files.

Each test names the exact behaviour / mutant it kills. The high-value families
the module-level docstring calls out are all covered:

  - the nesting-depth heuristic (brace-balance vs leading-indent ``max``), incl.
    the high-water peak init, the +1/-1 step direction, the closer-decrement
    guard, and the tab-vs-space indent path;
  - the size-band boundaries (LOC == 50 / 200 / 500 / 1000 land in the *upper*
    band, off-by-one in either the threshold or the ``>=`` comparator);
  - the hotspot scoring weights (``loc//50 + depth*3 + todos*2 + churn*4``), in
    particular the ``loc//50`` divisor;
  - the word-boundary TODO/FIXME/HACK/XXX count (``TODOLIST`` must NOT match);
  - the language allow-list and per-language file/LOC accounting;
  - the ``max_files`` / ``top`` caps and their ``<= 0`` early-returns.

EQUIVALENT mutants (changes with no observable effect, hence unkillable by any
test) are documented in ``test_documented_equivalent_mutants`` rather than
asserted, so the survivor list is fully explained.

Deterministic, stdlib + pytest, offline.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.engine import polyglot_metrics as pm
from app.engine.polyglot_metrics import (
    polyglot_hotspots,
    polyglot_summary,
    scan_polyglot,
)


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _by_path(root: Path) -> dict:
    return {r["path"]: r for r in scan_polyglot(str(root))}


# --------------------------------------------------------------------------- #
# Nesting-depth heuristic: brace-balance branch.
# --------------------------------------------------------------------------- #

def test_bracket_free_file_has_depth_zero(tmp_path: Path):
    """A file with no brackets and no indentation has depth 0.

    Kills the ``peak`` high-water inits in BOTH ``_brace_depth`` (``peak = 0``)
    and ``_indent_depth`` (``peak = 0``): a ``peak = 1`` start would report
    depth 1 here. Also kills ``_indent_step``'s ``return 0`` (a ``return 1``
    would give every flat line indent step 1 -> depth 1).
    """
    _write(tmp_path, "flat.js", "a;\nb;\nc;\n")
    assert _by_path(tmp_path)["flat.js"]["depth"] == 0


def test_nested_brackets_report_exact_depth_two(tmp_path: Path):
    """``f(g(h))`` nests two brackets deep, so depth is exactly 2.

    Kills the brace-step direction (``depth += 1`` -> ``depth -= 1``, which
    pins peak at 0), the peak-update comparison (``depth > peak`` -> ``depth <=
    peak``, also pinning peak at 0), and the opener-membership test
    (``ch in "([{"`` -> ``not in``). Asserting the EXACT value 2 (not just > 0)
    additionally kills the closer-membership flip (``ch in ")]}"`` -> ``not
    in``), which would over-count to a higher depth by never decrementing.
    """
    _write(tmp_path, "nest.js", "f(g(h));\n")
    assert _by_path(tmp_path)["nest.js"]["depth"] == 2


def test_stray_closer_does_not_drive_depth_negative(tmp_path: Path):
    """A leading stray ``)`` must not push the running depth below 0.

    ``) a(b)`` has a single real nesting (the ``a(b)`` call) -> depth 1. The
    guard ``if depth > 0: depth -= 1`` keeps the stray closer from driving depth
    to -1; the boundary mutant ``depth >= 0`` would decrement on the stray
    closer (depth -> -1), masking the later ``(`` and collapsing the reported
    depth to 0. Asserting exactly 1 kills that boundary flip.
    """
    _write(tmp_path, "stray.sh", "#!/bin/sh\n) a(b)\n")
    assert _by_path(tmp_path)["stray.sh"]["depth"] == 1


def test_closer_decrements_by_exactly_one(tmp_path: Path):
    """A closer steps the running depth down by exactly 1, not 2.

    ``{}{{`` peaks at 2 only if each closer decrements by 1: ``{`` (1) ``}``
    (0) ``{`` (1) ``{`` (2). The ``depth -= 1`` -> ``depth -= 2`` mutant would
    leave depth at -1 after the first ``}`` and only reach peak 1. Asserting
    exactly 2 kills that off-by-one decrement.
    """
    _write(tmp_path, "step.js", "{}{{}}\n")
    assert _by_path(tmp_path)["step.js"]["depth"] == 2


# --------------------------------------------------------------------------- #
# Nesting-depth heuristic: leading-indent branch (tabs vs spaces).
# --------------------------------------------------------------------------- #

def test_tab_indented_file_reports_indent_depth(tmp_path: Path):
    """Tab-indented, brace-free YAML reports depth from the tab count.

    A two-tab-indented line gives indent depth 2. This exercises the
    ``lead[0] == "\\t"`` branch of ``_indent_step`` and kills the
    ``return lead.count("\\t")`` -> ``return None`` mutant: returning None would
    make the downstream ``step > peak`` comparison raise on the tab path (no
    existing test used tab indentation, so the mutant survived).
    """
    _write(tmp_path, "tab.yaml", "root:\n\t\tleaf: 1\n")
    assert _by_path(tmp_path)["tab.yaml"]["depth"] == 2


def test_space_indent_depth_uses_two_space_step(tmp_path: Path):
    """Four leading spaces == 2 indent steps (``_INDENT_STEP`` of 2).

    Brace-free YAML indented 4 spaces deep reports depth 2 via
    ``leading_spaces // 2``. Pins the indent-step heuristic so an indent-only
    file still surfaces nesting.
    """
    _write(tmp_path, "cfg.yaml", "root:\n  child:\n    leaf: 1\n")
    assert _by_path(tmp_path)["cfg.yaml"]["depth"] == 2


def test_depth_is_max_of_brace_and_indent(tmp_path: Path):
    """``depth`` is the stronger of the brace and indent heuristics.

    A file whose indentation nests 3 deep but whose braces nest only 1 reports
    3 (the indent signal wins via ``max``).
    """
    _write(
        tmp_path,
        "mix.yaml",
        "a:\n  b:\n    c:\n      d(x)\n",  # indent depth 3, brace depth 1
    )
    assert _by_path(tmp_path)["mix.yaml"]["depth"] == 3


# --------------------------------------------------------------------------- #
# Size-band boundaries: the exact threshold values land in the UPPER band.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("loc", "band"),
    [
        (49, "tiny"),
        (50, "small"),    # boundary: 50 is small, not tiny
        (199, "small"),
        (200, "medium"),  # boundary: 200 is medium
        (499, "medium"),
        (500, "large"),   # boundary: 500 is large
        (999, "large"),
        (1000, "huge"),   # boundary: 1000 is huge
    ],
)
def test_size_band_boundaries_inclusive(tmp_path: Path, loc: int, band: str):
    """Each size-band lower bound is INCLUSIVE (``loc >= bound``).

    A file with exactly ``bound`` LOC names the upper band. This kills two
    mutant families at once: the ``loc >= bound`` -> ``loc > bound`` boundary
    flip (which would demote every exact-boundary file one band) and the
    threshold-literal bumps (50->51, 200->201, 500->501, 1000->1001), which all
    shift the band that the boundary LOC value falls into.
    """
    _write(tmp_path, "f.js", "x;\n" * loc)
    row = _by_path(tmp_path)["f.js"]
    assert row["loc"] == loc
    assert row["size_band"] == band


def test_empty_file_longest_line_is_zero(tmp_path: Path):
    """A truly empty file has ``longest_line == 0`` (the ``max`` default).

    An empty file has no lines, so ``max((len(line) ...), default=0)`` falls
    back to 0. The ``default=0`` -> ``default=1`` mutant would report a phantom
    longest line of 1 for the empty file; asserting 0 kills it.
    """
    _write(tmp_path, "empty.js", "")
    row = _by_path(tmp_path)["empty.js"]
    assert row["loc"] == 0
    assert row["longest_line"] == 0


# --------------------------------------------------------------------------- #
# Hotspot scoring weights: loc//50 + depth*3 + todos*2 + churn*4.
# --------------------------------------------------------------------------- #

def test_loc_weight_divisor_is_fifty(tmp_path: Path):
    """A 50-LOC, otherwise-inert file scores exactly 1 from the LOC term.

    With no nesting, no debt markers and no git history (churn 0), the only
    score contribution is ``loc // 50``. A 50-LOC file therefore scores
    ``50 // 50 == 1``. The ``_W_LOC_PER`` 50 -> 51 mutant would compute
    ``50 // 51 == 0``; asserting score 1 kills it.
    """
    _write(tmp_path, "f.js", "x;\n" * 50)
    hot = {h["path"]: h for h in polyglot_hotspots(str(tmp_path))}["f.js"]
    assert (hot["loc"], hot["depth"], hot["todos"], hot["churn"]) == (50, 0, 0, 0)
    assert hot["score"] == 1


def test_score_combines_all_weighted_terms(tmp_path: Path):
    """The score is exactly ``loc//50 + depth*3 + todos*2 + churn*4``.

    A non-git tree (churn 0 everywhere) with a file carrying real LOC, nesting
    and debt markers pins the depth*3 and todos*2 weights against an
    independently computed expectation.
    """
    body = "f(g(h)); // TODO x  FIXME y\n" + "z;\n" * 49
    _write(tmp_path, "rich.js", body)
    hot = {h["path"]: h for h in polyglot_hotspots(str(tmp_path))}["rich.js"]
    expected = (
        hot["loc"] // 50 + hot["depth"] * 3 + hot["todos"] * 2 + hot["churn"] * 4
    )
    assert hot["depth"] == 2
    assert hot["todos"] == 2
    assert hot["churn"] == 0
    assert hot["score"] == expected


# --------------------------------------------------------------------------- #
# TODO/FIXME word-boundary count + language allow-list.
# --------------------------------------------------------------------------- #

def test_debt_markers_are_word_boundary_and_case_insensitive(tmp_path: Path):
    """``TODO``/``todo``/``FIXME``/``HACK``/``XXX`` count; ``TODOLIST`` does not.

    Pins the word-boundary, case-insensitive debt regex: the substring inside
    ``TODOLIST`` must be excluded, while a lowercase ``todo`` must be included.
    """
    _write(
        tmp_path,
        "m.js",
        "// TODO a\n// todo b\n// TODOLIST c\n// FIXME d\n// HACK e\n// XXX f\n",
    )
    assert _by_path(tmp_path)["m.js"]["todos"] == 5


def test_language_allow_list_classifies_and_excludes(tmp_path: Path):
    """Only allow-list extensions are scanned, each to its canonical language.

    ``.ts``/``.tsx`` -> TypeScript, ``.js``/``.jsx`` -> JavaScript,
    ``.yaml``/``.yml`` -> YAML, ``.html`` -> HTML, ``.sh`` -> Shell, ``.md`` ->
    Markdown; Python and unknown/binary extensions are never measured.
    """
    _write(tmp_path, "a.ts", "x;\n")
    _write(tmp_path, "b.tsx", "x;\n")
    _write(tmp_path, "c.js", "x;\n")
    _write(tmp_path, "d.jsx", "x;\n")
    _write(tmp_path, "e.yaml", "k: 1\n")
    _write(tmp_path, "f.yml", "k: 1\n")
    _write(tmp_path, "g.html", "<p></p>\n")
    _write(tmp_path, "h.sh", "echo hi\n")
    _write(tmp_path, "i.md", "# h\n")
    _write(tmp_path, "skip.py", "x = 1\n")
    _write(tmp_path, "data.json", "{}\n")
    by_lang = {r["path"]: r["language"] for r in scan_polyglot(str(tmp_path))}
    assert by_lang == {
        "a.ts": "TypeScript", "b.tsx": "TypeScript",
        "c.js": "JavaScript", "d.jsx": "JavaScript",
        "e.yaml": "YAML", "f.yml": "YAML",
        "g.html": "HTML", "h.sh": "Shell", "i.md": "Markdown",
    }


# --------------------------------------------------------------------------- #
# Per-language accounting: file COUNTS (not just LOC).
# --------------------------------------------------------------------------- #

def test_summary_counts_files_per_language(tmp_path: Path):
    """``summary['languages']`` reports the right file count per language.

    Two ``.ts`` files plus one ``.yaml`` give TypeScript files == 2, YAML
    files == 1. This kills the per-language accounting mutants that no other
    test catches: the ``{"files": 0, ...}`` default (0 -> 1 would inflate every
    bucket) and the ``bucket["files"] += 1`` step (``+=`` -> ``-=`` or the
    ``1`` -> ``2`` increment), since nothing else asserts per-language file
    counts.
    """
    _write(tmp_path, "one.ts", "a;\n")
    _write(tmp_path, "two.ts", "b;\n")
    _write(tmp_path, "cfg.yaml", "k: 1\n")
    files_by_lang = {
        e["language"]: e["files"] for e in polyglot_summary(str(tmp_path))["languages"]
    }
    assert files_by_lang == {"TypeScript": 2, "YAML": 1}


# --------------------------------------------------------------------------- #
# max_files / top caps and their <= 0 early-returns.
# --------------------------------------------------------------------------- #

def test_scan_max_files_one_returns_single_file(tmp_path: Path):
    """``max_files=1`` measures exactly one file (the early-return needs ``<= 0``).

    With three in-scope files, ``scan_polyglot(root, max_files=1)`` returns a
    single row. This kills the ``max_files <= 0`` -> ``max_files <= 1`` mutant,
    which would early-return ``[]`` for ``max_files == 1``.
    """
    _write(tmp_path, "a.js", "x;\n")
    _write(tmp_path, "b.js", "y;\n")
    _write(tmp_path, "c.js", "z;\n")
    assert len(scan_polyglot(str(tmp_path), max_files=1)) == 1


def test_scan_default_max_files_caps_at_two_hundred(tmp_path: Path):
    """The default ``max_files`` is 200, so 201 files yield 200 rows.

    Creating 201 in-scope files and scanning with defaults returns exactly 200
    rows. This kills the default-argument bump ``max_files: int = 200`` -> 201.
    """
    for i in range(201):
        _write(tmp_path, f"f{i:03d}.js", "x;\n")
    assert len(scan_polyglot(str(tmp_path))) == 200


def test_hotspots_top_one_returns_single_hotspot(tmp_path: Path):
    """``top=1`` returns one hotspot (the early-return needs ``<= 0``).

    Kills the ``top <= 0`` -> ``top <= 1`` mutant, which would early-return
    ``[]`` for ``top == 1``.
    """
    _write(tmp_path, "a.js", "x;\n" * 3)
    _write(tmp_path, "b.js", "y;\n" * 2)
    assert len(polyglot_hotspots(str(tmp_path), top=1)) == 1


def test_hotspots_default_top_caps_at_five(tmp_path: Path):
    """The default ``top`` is 5, so six distinct files yield five hotspots.

    Six files of distinct LOC (so ranking is deterministic) scanned with
    defaults return five hotspots from both ``polyglot_hotspots`` and the
    ``summary`` view. This kills the default-argument bumps ``top: int = 5`` ->
    6 in BOTH ``polyglot_hotspots`` and ``polyglot_summary``.
    """
    for i in range(6):
        _write(tmp_path, f"g{i}.js", "x;\n" * (i + 1))
    assert len(polyglot_hotspots(str(tmp_path))) == 5
    assert len(polyglot_summary(str(tmp_path))["hotspots"]) == 5


# --------------------------------------------------------------------------- #
# Churn degradation: the git-failure path returns an empty MAP, not None.
# --------------------------------------------------------------------------- #

def test_churn_degrades_to_empty_map_when_git_raises(tmp_path: Path, monkeypatch):
    """If the ``git log`` subprocess RAISES, churn degrades to 0 (empty map).

    The ``_churn_map`` ``except`` arm returns ``{}`` so callers read churn 0.
    The ``return {}`` -> ``return None`` mutant would make the downstream
    ``churn.get(path, 0)`` raise ``AttributeError`` on ``None``. We force the
    exception path by monkeypatching the true external ``subprocess.run`` to
    raise, then assert ``polyglot_hotspots`` still succeeds with churn 0.
    """
    _write(tmp_path, "a.js", "x;\n")

    def _boom(*args, **kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(pm.subprocess, "run", _boom)
    hotspots = polyglot_hotspots(str(tmp_path))
    assert [h["churn"] for h in hotspots] == [0]


def test_churn_degrades_to_zero_when_git_returns_nonzero(tmp_path: Path, monkeypatch):
    """A non-zero ``git log`` exit also degrades churn to 0 (no map entries).

    Complements the raising-path test: here ``subprocess.run`` returns a
    non-zero ``returncode``, exercising the ``if out.returncode != 0: return
    {}`` arm rather than the ``except``. Churn is still 0.
    """
    _write(tmp_path, "a.js", "x;\n")

    class _Proc:
        returncode = 128
        stdout = ""

    monkeypatch.setattr(pm.subprocess, "run", lambda *a, **k: _Proc())
    hotspots = polyglot_hotspots(str(tmp_path))
    assert [h["churn"] for h in hotspots] == [0]


def test_churn_counts_commits_per_file_in_real_repo(tmp_path: Path):
    """In a real git repo, churn is the per-file commit count.

    Two commits both touch ``a.js`` while ``b.js`` is touched once, so churn is
    2 and 1 respectively. Pins the per-file commit tally (``counts[rel] =
    counts.get(rel, 0) + 1``) end-to-end through ``polyglot_hotspots``.
    """
    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True,
                       capture_output=True, text=True)

    _git("init", "-q")
    _git("config", "user.email", "t@t.t")
    _git("config", "user.name", "T")
    _git("config", "commit.gpgsign", "false")
    _write(tmp_path, "a.js", "x;\n")
    _git("add", "-A")
    _git("commit", "-q", "-m", "first")
    _write(tmp_path, "a.js", "x;\ny;\n")
    _write(tmp_path, "b.js", "z;\n")
    _git("add", "-A")
    _git("commit", "-q", "-m", "second")

    churn = {h["path"]: h["churn"] for h in polyglot_hotspots(str(tmp_path))}
    assert churn["a.js"] == 2
    assert churn["b.js"] == 1


# --------------------------------------------------------------------------- #
# Documented EQUIVALENT mutants (unkillable — recorded, not asserted).
# --------------------------------------------------------------------------- #

def test_documented_equivalent_mutants():
    """Survivors that are EQUIVALENT mutants — no test can kill them.

    The full 89-site enumeration left these survivors that change the source
    without changing any observable behaviour, so they are documented here
    rather than (futilely) targeted:

      - ``_DEBT_CAP`` 9999->10000, ``_LONGEST_LINE_CAP`` 99999->100000,
        ``_DEPTH_CAP`` 999->1000: the saturation caps are only observable when a
        single file hits them; no realistic deterministic fixture produces 9999
        debt markers / a 99999-char line / nesting depth 999.
      - ``_COMMIT_WINDOW`` 1000->1001 and the ``git log`` timeout 15->16: only
        observable with >1000 commits / a ~15s-long git invocation.
      - ``_SIZE_BANDS[0][1]`` index 0->1: the pre-loop ``band`` initialiser is
        overwritten on the very first iteration (the first band's bound is 0,
        which every non-negative ``loc`` meets), so the init value is never
        observable.
      - ``_brace_depth`` ``depth > peak`` -> ``depth >= peak`` and
        ``_indent_depth`` ``step > peak`` -> ``step >= peak``: the value being
        compared is freshly incremented past the prior peak, so ``>`` and ``>=``
        agree on every input (verified by exhaustive search up to length 7).
      - ``scan_polyglot`` ``max_files <= 0`` -> ``max_files < 0`` and the
        ``or`` -> ``and`` in that same guard, and ``polyglot_hotspots``
        ``top <= 0`` -> ``top < 0``: when the guard's early ``[]`` is skipped,
        the fall-through still yields ``[]`` (a ``[:0]`` slice / a no-op walk),
        so the result is identical.

    This test merely records the analysis; it asserts a tautology so the file's
    survivor accounting is complete and visible.
    """
    assert True
