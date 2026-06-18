"""Hermetic tests for ``app.engine.polyglot_metrics``.

Every test builds its own tmp tree of known shape; nothing depends on the Apex
repo's own non-Python files. Determinism, best-effort skipping, the metric set,
hotspot scoring/ranking, the summary, and the empty paths are all asserted.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.engine.polyglot_metrics import (
    polyglot_hotspots,
    polyglot_summary,
    scan_polyglot,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True,
                   capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "T")
    _git(root, "config", "commit.gpgsign", "false")


def _commit(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


def _tree(root: Path) -> None:
    """A known polyglot tree: in-scope TS/JS/YAML/HTML/SH/MD files, plus a Python
    file, a binary asset, and a node_modules JS file that must all be excluded."""
    (root / "web").mkdir()
    (root / "cfg").mkdir()
    # app.ts: 4 non-blank lines (blank middle line not counted), nesting depth 2
    # via braces, one TODO, a long line.
    (root / "web" / "app.ts").write_text(
        "function f() {\n"
        "  if (x) {\n"  # depth 2
        "    return 1; // TODO refactor\n"
        "  }\n"
        "\n"            # blank — not counted in LOC
        "}\n",
        encoding="utf-8",
    )
    (root / "web" / "small.js").write_text("console.log(1);\n", encoding="utf-8")
    (root / "web" / "index.html").write_text(
        "<html>\n<body></body>\n</html>\n", encoding="utf-8"
    )
    # config.yaml: indent-based nesting depth 2 (4 leading spaces / step 2), no
    # braces — exercises the indent heuristic.
    (root / "cfg" / "config.yaml").write_text(
        "root:\n  child:\n    leaf: 1\n", encoding="utf-8"
    )
    (root / "deploy.sh").write_text(
        "#!/bin/sh\n# FIXME handle errors\nset -e\necho hi\n", encoding="utf-8"
    )
    (root / "README.md").write_text("# Title\n\ntext\n", encoding="utf-8")
    # Excluded: Python, binary, vendored JS.
    (root / "main.py").write_text("def run():\n    return True\n", encoding="utf-8")
    (root / "web" / "logo.png").write_bytes(b"\x89PNG\r\n")
    nm = root / "node_modules" / "left-pad"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("module.exports = 1;\n", encoding="utf-8")


def test_scans_only_in_scope_non_python_source(tmp_path: Path):
    rows = scan_polyglot(str(tmp_path / "missing"))
    assert rows == []  # missing root -> empty, never raises

    _tree(tmp_path)
    rows = scan_polyglot(str(tmp_path))
    paths = {r["path"] for r in rows}
    assert paths == {
        "web/app.ts", "web/small.js", "web/index.html",
        "cfg/config.yaml", "deploy.sh", "README.md",
    }
    assert not any(p.endswith(".py") for p in paths)
    assert not any("node_modules" in p for p in paths)
    assert not any(p.endswith(".png") for p in paths)


def test_metric_set_values(tmp_path: Path):
    _tree(tmp_path)
    by_path = {r["path"]: r for r in scan_polyglot(str(tmp_path))}

    ts = by_path["web/app.ts"]
    assert ts["language"] == "TypeScript"
    assert ts["loc"] == 5  # 5 non-blank lines; blank middle line not counted
    assert ts["depth"] == 2  # nested braces
    assert ts["todos"] == 1
    assert ts["size_band"] == "tiny"
    assert ts["longest_line"] >= len("    return 1; // TODO refactor")

    # YAML nesting comes from indentation, not braces.
    yaml = by_path["cfg/config.yaml"]
    assert yaml["language"] == "YAML"
    assert yaml["depth"] == 2

    sh = by_path["deploy.sh"]
    assert sh["language"] == "Shell"
    assert sh["todos"] == 1  # FIXME

    assert by_path["web/small.js"]["loc"] == 1
    assert by_path["README.md"]["language"] == "Markdown"


def test_size_bands(tmp_path: Path):
    (tmp_path / "big.js").write_text("x;\n" * 250, encoding="utf-8")
    (tmp_path / "mid.js").write_text("x;\n" * 60, encoding="utf-8")
    (tmp_path / "tiny.js").write_text("x;\n" * 3, encoding="utf-8")
    by_path = {r["path"]: r for r in scan_polyglot(str(tmp_path))}
    assert by_path["big.js"]["size_band"] == "medium"  # 250 in [200,500)
    assert by_path["mid.js"]["size_band"] == "small"   # 60 in [50,200)
    assert by_path["tiny.js"]["size_band"] == "tiny"   # 3 < 50


def test_scan_sorted_and_bounded(tmp_path: Path):
    _tree(tmp_path)
    rows = scan_polyglot(str(tmp_path))
    # Sorted by (-loc, path): non-increasing LOC, ties by path.
    keys = [(-r["loc"], r["path"]) for r in rows]
    assert keys == sorted(keys)

    capped = scan_polyglot(str(tmp_path), max_files=2)
    assert len(capped) <= 2
    assert scan_polyglot(str(tmp_path), max_files=0) == []


def test_scan_deterministic(tmp_path: Path):
    _tree(tmp_path)
    assert scan_polyglot(str(tmp_path)) == scan_polyglot(str(tmp_path))


def test_unreadable_file_skipped_not_raised(tmp_path: Path):
    # A directory whose name ends in .js is not a file -> never measured; a real
    # file with undecodable bytes is read with errors="ignore", never raising.
    (tmp_path / "weird.js").write_bytes(b"\xff\xfe bad bytes;\n")
    rows = scan_polyglot(str(tmp_path))
    assert {r["path"] for r in rows} == {"weird.js"}


def test_hotspots_shape_and_score(tmp_path: Path):
    _init_repo(tmp_path)
    _tree(tmp_path)
    _commit(tmp_path, "init")
    hotspots = polyglot_hotspots(str(tmp_path))
    assert hotspots
    first = hotspots[0]
    assert set(first) == {
        "path", "loc", "depth", "todos", "churn", "score", "why",
    }
    # score == loc//50 + depth*3 + todos*2 + churn*4 for each entry.
    for h in hotspots:
        expected = (
            h["loc"] // 50 + h["depth"] * 3 + h["todos"] * 2 + h["churn"] * 4
        )
        assert h["score"] == expected
    # With one commit touching everything, every file has churn 1.
    assert all(h["churn"] == 1 for h in hotspots)
    assert str(first["loc"]) in first["why"]


def test_hotspots_ranked_and_capped(tmp_path: Path):
    _tree(tmp_path)  # no git repo -> churn 0 everywhere, best-effort
    hotspots = polyglot_hotspots(str(tmp_path), top=3)
    assert len(hotspots) <= 3
    scores = [(-h["score"], -h["loc"], h["path"]) for h in hotspots]
    assert scores == sorted(scores)
    assert all(h["churn"] == 0 for h in hotspots)  # non-git: degrade to 0
    assert polyglot_hotspots(str(tmp_path), top=0) == []


def test_hotspots_empty_when_no_source(tmp_path: Path):
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    assert polyglot_hotspots(str(tmp_path)) == []
    assert scan_polyglot(str(tmp_path)) == []


def test_summary_structure(tmp_path: Path):
    _tree(tmp_path)
    summary = polyglot_summary(str(tmp_path))
    assert set(summary) == {"languages", "totals", "hotspots"}

    assert summary["totals"]["files"] == 6
    langs = {entry["language"] for entry in summary["languages"]}
    assert langs == {"TypeScript", "JavaScript", "YAML", "HTML", "Shell", "Markdown"}
    # Per-language LOC totals sum to the grand total.
    assert sum(e["loc"] for e in summary["languages"]) == summary["totals"]["loc"]
    # languages sorted by (-loc, language).
    keys = [(-e["loc"], e["language"]) for e in summary["languages"]]
    assert keys == sorted(keys)
    assert summary["hotspots"]


def test_summary_empty(tmp_path: Path):
    summary = polyglot_summary(str(tmp_path))
    assert summary == {
        "languages": [],
        "totals": {"files": 0, "loc": 0},
        "hotspots": [],
    }


def test_summary_deterministic(tmp_path: Path):
    _init_repo(tmp_path)
    _tree(tmp_path)
    _commit(tmp_path, "init")
    assert polyglot_summary(str(tmp_path)) == polyglot_summary(str(tmp_path))
