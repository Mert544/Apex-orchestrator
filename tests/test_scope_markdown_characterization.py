"""Characterization: render_scope_markdown must be byte-identical to the
pre-refactor implementation across every branch (all-python, headline, the
breakdown / files / cross-links sections present-or-absent, singular/plural
wording, untested flags, and the optional TODO/FIXME debt clause)."""

import itertools

from app.cli_insight import render_scope_markdown


def _orig_render_scope_markdown(rep: dict) -> str:
    """Verbatim copy of the original function (HEAD), the oracle."""
    lines = ["# Apex analysis scope", ""]

    if rep["all_python"]:
        lines.append("Apex analyses 100% of this repo (all Python).")
        lines.append("")
        lines.append(
            "_Every source-bearing file here is Python — the subset Apex deep-"
            "analyses — so its grade speaks for the whole repo._"
        )
        return "\n".join(lines)

    analysed = rep["analyzed_pct"]
    out_pct = rep["out_of_scope_pct"]
    lines.append(
        f"Apex analyses {analysed}% of this repo (Python). "
        f"{out_pct}% is outside its analysis scope."
    )
    lines.append("")

    breakdown = rep["language_breakdown"]
    if breakdown:
        lines += ["## Outside analysis scope", "",
                  "The non-Python remainder, by language:", ""]
        for row in breakdown:
            n = row["files"]
            f_word = "file" if n == 1 else "files"
            lines.append(f"- {row['language']} — {n} {f_word}")
        lines.append("")

    files = rep["files"]
    if files:
        lines += ["## Largest / most-active out-of-scope files", "",
                  "Where the non-Python risk concentrates — Apex can name these "
                  "but can't deep-analyse them yet:", ""]
        for f in files:
            commit_word = "commit" if f["churn"] == 1 else "commits"
            flag = "" if f["has_test"] else " — no test found"
            debt = f.get("debt_markers", 0) or 0
            debt_clause = f" — {debt} TODO/FIXME" if debt > 0 else ""
            lines.append(
                f"- `{f['path']}` ({f['language']}, {f['loc']} LOC, "
                f"{f['churn']} {commit_word}){flag}{debt_clause}"
            )
        lines.append("")

    cross = rep.get("cross_links") or []
    if cross:
        lines += ["## Cross-language coupling (keep in sync)", "",
                  "Files git shows changing together across the Python boundary — "
                  "Apex can't deep-analyse the non-Python side, but they move as a "
                  "unit, so a change to one likely needs the other:", ""]
        for c in cross:
            cw = "co-change" if c["cochanges"] == 1 else "co-changes"
            lines.append(
                f"- `{c['py']}` ↔ `{c['other']}` ({c['language']}, "
                f"{c['cochanges']} {cw})"
            )
        lines.append("")

    lines.append(
        "_Apex names its own limits: it grades only Python, and says so. Every "
        "number here is read from its own deterministic profile of this repo — "
        "zero-token, no model in the loop._"
    )
    return "\n".join(lines)


# Building blocks covering both wording branches (singular/plural) and flags.
_BREAKDOWNS = [
    [],
    [{"language": "JS", "files": 1}],
    [{"language": "JS", "files": 3}, {"language": "Go", "files": 1}],
]
_FILE_SETS = [
    [],
    [{"path": "a.js", "language": "JS", "loc": 10, "churn": 1, "has_test": True}],
    [
        {"path": "a.js", "language": "JS", "loc": 10, "churn": 1, "has_test": True},
        {"path": "b.go", "language": "Go", "loc": 99, "churn": 5, "has_test": False},
        {"path": "c.rs", "language": "Rust", "loc": 7, "churn": 2,
         "has_test": False, "debt_markers": 4},
        {"path": "d.ts", "language": "TS", "loc": 1, "churn": 1,
         "has_test": True, "debt_markers": 0},
    ],
]
_CROSS_SETS = [
    None,
    [],
    [{"py": "x.py", "other": "x.js", "language": "JS", "cochanges": 1}],
    [
        {"py": "x.py", "other": "x.js", "language": "JS", "cochanges": 1},
        {"py": "y.py", "other": "y.go", "language": "Go", "cochanges": 9},
    ],
]


def _polyglot_cases():
    for analysed, out_pct in [(0, 100), (42, 58), (99, 1)]:
        for bd, fs, cs in itertools.product(_BREAKDOWNS, _FILE_SETS, _CROSS_SETS):
            rep = {
                "all_python": False,
                "analyzed_pct": analysed,
                "out_of_scope_pct": out_pct,
                "language_breakdown": bd,
                "files": fs,
            }
            if cs is not None:
                rep["cross_links"] = cs
            yield rep


def test_all_python_branch_byte_identical():
    rep = {"all_python": True}
    assert render_scope_markdown(rep) == _orig_render_scope_markdown(rep)


def test_polyglot_branches_byte_identical():
    cases = list(_polyglot_cases())
    assert len(cases) > 100  # broad coverage of every section combination
    for rep in cases:
        assert render_scope_markdown(rep) == _orig_render_scope_markdown(rep)


def test_cross_links_key_absent_byte_identical():
    rep = {
        "all_python": False,
        "analyzed_pct": 50,
        "out_of_scope_pct": 50,
        "language_breakdown": [],
        "files": [],
    }
    assert render_scope_markdown(rep) == _orig_render_scope_markdown(rep)
