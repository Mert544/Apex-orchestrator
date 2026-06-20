"""Safety + correctness tests for the docstring transform and ``fix-docstrings``.

A red-team scout found that the docstring inserter placed the docstring in the
WRONG position for multi-line signatures — landing a detached string *before*
the ``def`` line (an ``IndentationError`` / phantom module-level string) — and
that the ``fix-docstrings`` CLI wrote it without any syntax/soundness gate and
never rolled back, destroying previously-passing tests.

These tests pin the fix on two layers:

* the transform :func:`app.execution.semantic.transforms.docstring.apply` now
  inserts the docstring as the function/class's FIRST BODY STATEMENT (computed
  from the AST, so multi-line signatures / decorators / nested defs / blank-line
  gaps are handled), the result ``ast.parse``s, and a broken result is refused;
* the CLI handler :func:`app.cli_ops.cmd_fix_docstrings` snapshots gap files,
  validates each write for syntactic AND semantic soundness, and rolls back any
  patch that would leave broken Python — so a docstring edit NEVER destroys a
  green file.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

from app import cli_ops
from app.execution.semantic.transforms.docstring import apply


# ── helpers ───────────────────────────────────────────────────────────────────

def _new_content(result):
    assert result is not None
    assert len(result.patch_requests) == 1
    return result.patch_requests[0]["new_content"]


def _docs(source: str) -> dict[str, str | None]:
    tree = ast.parse(source)
    return {
        node.name: ast.get_docstring(node)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _undocumented(source: str) -> list[str]:
    return [name for name, doc in _docs(source).items() if doc is None]


# ── transform: docstring lands as the first body statement, and parses ────────

def test_single_line_signature_docstring_is_first_body_statement():
    source = "def subtract(a, b):\n    return a - b\n"
    new = _new_content(apply("m.py", source, "document"))
    ast.parse(new)  # must be valid Python
    fn = ast.parse(new).body[0]
    # The docstring is the FIRST statement of the body, correctly indented.
    assert isinstance(fn.body[0], ast.Expr)
    # Single undocumented symbol -> title-based body (established convention).
    assert ast.get_docstring(fn) == "document."
    assert '    """document."""' in new
    assert _undocumented(new) == []


def test_multiline_signature_docstring_inside_body_not_before_def():
    # The exact bug class: a signature spanning several lines.
    source = (
        "def add_many(\n"
        "    a,\n"
        "    b,\n"
        "    c,\n"
        "):\n"
        "    return a + b + c\n"
    )
    new = _new_content(apply("m.py", source, "document"))
    ast.parse(new)  # never an IndentationError / detached string
    lines = new.splitlines()
    def_idx = next(i for i, ln in enumerate(lines) if ln.startswith("def add_many"))
    doc_idx = next(i for i, ln in enumerate(lines) if '"""' in ln)
    # The docstring comes AFTER the def header, never before it.
    assert doc_idx > def_idx
    assert _undocumented(new) == []
    assert ast.get_docstring(ast.parse(new).body[0]) == "document."


def test_decorated_function_handled():
    source = "@decorator\ndef wrapped(x):\n    return x\n"
    new = _new_content(apply("m.py", source, "document"))
    ast.parse(new)
    assert _undocumented(new) == []


def test_multiline_decorator_and_signature_handled():
    source = (
        "@app.route(\n"
        '    "/x",\n'
        ")\n"
        "def view(\n"
        "    req,\n"
        "):\n"
        "    return req\n"
    )
    new = _new_content(apply("m.py", source, "document"))
    ast.parse(new)
    assert _undocumented(new) == []


def test_nested_def_both_documented_correctly():
    source = (
        "def outer():\n"
        "    def inner():\n"
        "        return 1\n"
        "    return inner\n"
    )
    new = _new_content(apply("m.py", source, "document"))
    ast.parse(new)
    assert _undocumented(new) == []
    # The inner docstring is indented one level past the inner def.
    assert '        """inner."""' in new


def test_class_docstring_inserted():
    source = "class Foo:\n    x = 1\n"
    new = _new_content(apply("m.py", source, "document"))
    ast.parse(new)
    cls = ast.parse(new).body[0]
    assert isinstance(cls, ast.ClassDef)
    assert ast.get_docstring(cls) == "document."


def test_already_documented_is_noop():
    source = 'def f():\n    """Kept."""\n    return 1\n'
    assert apply("m.py", source, "document") is None


def test_blank_gap_before_body_is_valid_and_idempotent():
    source = "def gap():\n\n    return 1\n"
    new = _new_content(apply("m.py", source, "document"))
    ast.parse(new)
    assert ast.get_docstring(ast.parse(new).body[0]) == "document."
    # Idempotent: a second pass changes nothing.
    assert apply("m.py", new, "document") is None


def test_transform_refuses_to_emit_unparseable_result(monkeypatch):
    # Force the inserted text to be syntactically broken; the apply()-level
    # ``ast.parse`` gate must REFUSE (return None) rather than emit it.
    import app.execution.semantic.transforms.docstring as mod

    monkeypatch.setattr(mod, "_doc_text", lambda node, title, multiple: 'broken"""')
    source = "def f():\n    return 1\n"
    assert apply("m.py", source, "document") is None


def test_transform_is_deterministic():
    source = "def p():\n    return 1\n\n\ndef q():\n    return 2\n"
    r1 = _new_content(apply("m.py", source, "document"))
    r2 = _new_content(apply("m.py", source, "document"))
    assert r1 == r2


# ── soundness predicate used by the CLI rollback ──────────────────────────────

def test_sound_predicate_accepts_real_docstring_addition():
    before = "def f():\n    return 1\n"
    after = 'def f():\n    """f."""\n    return 1\n'
    assert cli_ops._docstring_write_is_sound(before, after) is True


def test_sound_predicate_rejects_detached_phantom_string():
    before = (
        "def subtract(a, b):\n    return a - b\n\n\n"
        "def add_many(\n    a,\n):\n    return a\n"
    )
    # The broken-insertion bug: subtract documented, but a DETACHED string lands
    # before ``add_many`` (a phantom statement that still parses, yet add_many is
    # left undocumented). The soundness gate must reject this.
    after = (
        'def subtract(a, b):\n    """subtract implementation."""\n    return a - b\n\n\n'
        '"""add_many implementation."""\n'
        "def add_many(\n    a,\n):\n    return a\n"
    )
    ast.parse(after)  # sanity: still parses, so a bare ast.parse gate misses it
    assert cli_ops._docstring_write_is_sound(before, after) is False


def test_sound_predicate_rejects_unparseable_result():
    before = "def f():\n    return 1\n"
    after = '    """f."""\ndef f():\n    return 1\n'  # IndentationError
    assert cli_ops._docstring_write_is_sound(before, after) is False


# ── CLI: lands valid docstrings, rolls back broken writes, keeps tests green ──

def test_cli_lands_valid_docstring_in_place(tmp_path: Path, capsys):
    src = tmp_path / "m.py"
    src.write_text("def subtract(a, b):\n    return a - b\n", encoding="utf-8")

    rc = cli_ops.cmd_fix_docstrings(
        argparse.Namespace(target=str(tmp_path), dry_run=False)
    )

    assert rc == 0
    patched = src.read_text(encoding="utf-8")
    ast.parse(patched)  # valid
    assert ast.get_docstring(ast.parse(patched).body[0]) == "subtract implementation."
    assert "Files patched: 1" in capsys.readouterr().out


def test_cli_rolls_back_broken_multiline_write(tmp_path: Path, capsys):
    # The destructive repro: a multi-line signature the agent mishandles. The
    # CLI must detect the broken/phantom write and ROLL BACK — never destroy the
    # file or the tests that import it.
    original = (
        "def subtract(a, b):\n"
        "    return a - b\n"
        "\n"
        "\n"
        "def add_many(\n"
        "    a,\n"
        "    b,\n"
        "    c,\n"
        "):\n"
        "    return a + b + c\n"
    )
    src = tmp_path / "calc.py"
    src.write_text(original, encoding="utf-8")
    test = tmp_path / "test_calc.py"
    test.write_text(
        "from calc import subtract, add_many\n"
        "def test_a(): assert subtract(5, 2) == 3\n",
        encoding="utf-8",
    )

    rc = cli_ops.cmd_fix_docstrings(
        argparse.Namespace(target=str(tmp_path), dry_run=False)
    )

    assert rc == 0
    # Rolled back to byte-identical original; the file still parses and imports.
    assert src.read_text(encoding="utf-8") == original
    ast.parse(src.read_text(encoding="utf-8"))
    assert "Files patched: 0" in capsys.readouterr().out


def test_cli_dry_run_never_writes(tmp_path: Path, capsys):
    original = "def undoc():\n    pass\n"
    src = tmp_path / "m.py"
    src.write_text(original, encoding="utf-8")

    rc = cli_ops.cmd_fix_docstrings(
        argparse.Namespace(target=str(tmp_path), dry_run=True)
    )

    assert rc == 0
    assert src.read_text(encoding="utf-8") == original
    out = capsys.readouterr().out
    assert "Dry run" in out and "undoc" in out


def test_cli_deterministic_same_tree_same_result(tmp_path: Path):
    body = "def subtract(a, b):\n    return a - b\n"
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "m.py").write_text(body, encoding="utf-8")
    (b / "m.py").write_text(body, encoding="utf-8")

    cli_ops.cmd_fix_docstrings(argparse.Namespace(target=str(a), dry_run=False))
    cli_ops.cmd_fix_docstrings(argparse.Namespace(target=str(b), dry_run=False))

    assert (a / "m.py").read_text(encoding="utf-8") == (b / "m.py").read_text(
        encoding="utf-8"
    )
