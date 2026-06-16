"""Characterization: prove the refactored scripts/self_audit.py is byte-identical
to the committed HEAD snapshot across every branch of analyze_risks and main.

Both the current working-tree module and the HEAD snapshot are loaded by file
path via importlib, then driven with the same inputs/argv. Outputs (return
values, written report bytes, stdout, exit code) are compared 1:1.
"""
from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_PATH = REPO_ROOT / "scripts" / "self_audit.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def head_snapshot(tmp_path_factory) -> Path:
    snap = tmp_path_factory.mktemp("head_self_audit") / "self_audit_head.py"
    blob = subprocess.run(
        ["git", "show", "HEAD:scripts/self_audit.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout
    snap.write_bytes(blob)
    return snap


@pytest.fixture(scope="module")
def live_mod():
    return _load(LIVE_PATH, "self_audit_live")


@pytest.fixture(scope="module")
def head_mod(head_snapshot: Path):
    return _load(head_snapshot, "self_audit_head")


# --- corpus covering every analyze_risks branch ---------------------------
_SNIPPETS = [
    "eval('1')",
    "exec('x=1')",
    "os.system('ls')",
    "pickle.loads(b'')",
    "try:\n    pass\nexcept:\n    pass\n",
    "try:\n    pass\nexcept Exception:\n    pass\n",
    "foo.system('x')",            # attr value is Name but not os
    "pickle.dumps(x)",            # attr loads-miss
    "json.loads('x')",            # attr loads but not pickle
    "obj.method().chained()",     # attr.value not a Name
    "a.b.c.system('x')",          # nested attribute value
    "evaluate(1)",                # name miss
    "(lambda: 0)()",              # call func not Name/Attribute
    "x = 1\ny = 2\n",             # no risks at all
    "@dec\ndef f():\n    eval('z')\n",
    "this is not valid python )(",  # SyntaxError -> skipped
    "",                            # empty file
    "eval(eval(eval('x')))",       # repeated
    (
        "eval(exec(os.system('y')))\ntry:\n    pickle.loads(z)\nexcept:\n"
        "    pass\nexcept Exception:\n    pass\n"
    ),
]


def _make_files(base: Path) -> list[Path]:
    paths = []
    for i, src in enumerate(_SNIPPETS):
        p = base / f"snippet_{i}.py"
        p.write_text(src, encoding="utf-8")
        paths.append(p)
    return paths


def test_analyze_risks_byte_identical(tmp_path: Path, live_mod, head_mod):
    files = _make_files(tmp_path)
    # Whole list, and every individual file (exercises single-file paths).
    cases = [files, []]
    cases.extend([[f] for f in files])
    for case in cases:
        assert live_mod.analyze_risks(case) == head_mod.analyze_risks(case)


def _build_repo(base: Path) -> Path:
    """Create a mini repo tree that exercises every main/report branch."""
    repo = base / "repo"
    app = repo / "app" / "core"
    tests = repo / "tests"
    app.mkdir(parents=True)
    tests.mkdir(parents=True)
    # risky + missing docstrings + bare except + todos
    (app / "risky.py").write_text(
        "import os\n"
        "def run(c):\n"
        "    eval(c)\n"
        "    os.system(c)\n"
        "    try:\n        pass\n    except:\n        pass\n"
        "# TODO: clean this up\n"
        "class Bad:\n    def m(self):\n        pass\n",
        encoding="utf-8",
    )
    # long function (>50 lines)
    longsrc = ["def big():"] + [f"    a{i} = {i}" for i in range(60)] + ["    return a0"]
    (app / "long.py").write_text("\n".join(longsrc) + "\n", encoding="utf-8")
    # internal imports for the graph
    (app / "wired.py").write_text(
        "from app.core import risky\nimport app.long\n", encoding="utf-8"
    )
    # broken file -> SyntaxError path
    (app / "broken.py").write_text("def (:\n", encoding="utf-8")
    # tests referencing app modules for coverage gap
    (tests / "test_x.py").write_text(
        "from app.core import risky\nimport app.long\n# FIXME later\n",
        encoding="utf-8",
    )
    return repo


def _run_main(mod, repo_root: Path) -> tuple[str, bytes]:
    """Run mod.main() with __file__ pointed inside repo_root; return stdout+report."""
    original = mod.__file__
    mod.__file__ = str(repo_root / "scripts" / "self_audit.py")
    (repo_root / "scripts").mkdir(exist_ok=True)
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            ret = mod.main()
    finally:
        mod.__file__ = original
    assert ret is None
    report = (repo_root / ".apex" / "self-audit-report.md").read_bytes()
    return buf.getvalue(), report


def test_main_report_byte_identical(tmp_path: Path, live_mod, head_mod):
    # Drive BOTH modules against the exact same repo path so there is zero
    # path difference: the comparison is strictly byte-for-byte.
    repo = _build_repo(tmp_path)

    head_out, head_report = _run_main(head_mod, repo)
    live_out, live_report = _run_main(live_mod, repo)

    assert live_out == head_out
    assert live_report == head_report


def test_main_empty_repo_byte_identical(tmp_path: Path, live_mod, head_mod):
    """No risks / empty tables path (the 'No critical risks' branch)."""
    repo = tmp_path
    (repo / "app").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    (repo / "app" / "clean.py").write_text(
        '"""Doc."""\n\n\ndef ok():\n    """ok."""\n    return 1\n',
        encoding="utf-8",
    )
    head_out, head_report = _run_main(head_mod, repo)
    live_out, live_report = _run_main(live_mod, repo)
    assert live_out == head_out
    assert live_report == head_report


def test_live_script_runs_end_to_end():
    """The standard invocation still executes and writes a report."""
    proc = subprocess.run(
        [sys.executable, str(LIVE_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "Report written to" in proc.stdout
