"""``DocstringAgent`` lands docstrings on multi-line-signature functions.

Regression wave: the agent's ``_patch_file`` previously inserted a docstring at
``def.lineno + 1`` (one line after the ``def`` keyword). For a multi-line
signature that line is still *inside* the parameter list, so the inserted string
landed in the wrong place — for the CLI path it became a detached module-level
string that still ``ast.parse``d but left the function undocumented, and the CLI
soundness gate then rolled the whole write back. Net effect: multi-line-signature
functions never got a docstring.

The agent now computes insertion points via the body-accurate transform helper
``app.execution.semantic.transforms.docstring._body_insertion`` (derived from the
AST's first body statement), so multi-line signatures, decorators, nested defs,
and blank-line gaps all LAND a valid docstring as the function's first body
statement. The agent's public contract is unchanged: doc text stays
``"{name} implementation."`` and single-line signatures are byte-identical to the
prior behaviour. These tests pin the improved behaviour and its edge cases.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.agents.skills.docstring_agent import DocstringAgent


def _docs(source: str) -> dict[str, str | None]:
    tree = ast.parse(source)
    return {
        node.name: ast.get_docstring(node)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _patch(source: str) -> str:
    return DocstringAgent()._patch_file("m.py", source)


# ── multi-line signature: docstring LANDS as the first body statement ─────────

def test_multiline_signature_lands_valid_docstring():
    source = (
        "def add_many(\n"
        "    a,\n"
        "    b,\n"
        "    c,\n"
        "):\n"
        "    return a + b + c\n"
    )
    patched = _patch(source)
    assert patched != source
    ast.parse(patched)  # never an IndentationError / detached string
    fn = ast.parse(patched).body[0]
    # Docstring is the FIRST body statement, carrying the agent's text.
    assert isinstance(fn.body[0], ast.Expr)
    assert ast.get_docstring(fn) == "add_many implementation."
    # It lands AFTER the full header, never before the def line.
    lines = patched.splitlines()
    def_idx = next(i for i, ln in enumerate(lines) if ln.startswith("def add_many"))
    doc_idx = next(i for i, ln in enumerate(lines) if '"""' in ln)
    assert doc_idx > def_idx
    # Correct body indentation (one level in).
    assert '    """add_many implementation."""' in patched


# ── single-line signature: byte-identical to prior behaviour ──────────────────

def test_single_line_signature_unchanged_behaviour():
    source = "def hello():\n    pass\n"
    patched = _patch(source)
    assert patched == 'def hello():\n    """hello implementation."""\n    pass\n'


def test_single_line_method_indent_preserved():
    source = "class C:\n    def m(self):\n        return 1\n"
    patched = _patch(source)
    ast.parse(patched)
    # Method docstring is indented two levels (inside the class body's method).
    assert '        """m implementation."""' in patched
    assert _docs(patched)["m"] == "m implementation."
    # The class itself also gets one.
    assert _docs(patched)["C"] == "C implementation."


# ── decorated / multi-line-decorated functions ───────────────────────────────

def test_decorated_function_lands_docstring():
    source = "@decorator\ndef wrapped(x):\n    return x\n"
    patched = _patch(source)
    ast.parse(patched)
    assert _docs(patched)["wrapped"] == "wrapped implementation."


def test_multiline_decorator_and_signature_lands_docstring():
    source = (
        "@app.route(\n"
        '    "/x",\n'
        ")\n"
        "def view(\n"
        "    req,\n"
        "):\n"
        "    return req\n"
    )
    patched = _patch(source)
    ast.parse(patched)
    assert _docs(patched)["view"] == "view implementation."


# ── nested defs: outer and inner both documented at the right indent ──────────

def test_nested_def_both_documented():
    source = (
        "def outer():\n"
        "    def inner():\n"
        "        return 1\n"
        "    return inner\n"
    )
    patched = _patch(source)
    ast.parse(patched)
    docs = _docs(patched)
    assert docs["outer"] == "outer implementation."
    assert docs["inner"] == "inner implementation."
    assert '        """inner implementation."""' in patched


# ── blank-gap body ────────────────────────────────────────────────────────────

def test_blank_gap_before_body_lands_valid_docstring():
    source = "def gap():\n\n    return 1\n"
    patched = _patch(source)
    ast.parse(patched)
    assert _docs(patched)["gap"] == "gap implementation."


# ── idempotence: already-documented untouched, second pass is a no-op ─────────

def test_already_documented_is_noop():
    source = 'def f():\n    """Kept."""\n    return 1\n'
    assert _patch(source) == source


def test_second_pass_is_idempotent():
    source = (
        "def add_many(\n"
        "    a,\n"
        "    b,\n"
        "):\n"
        "    return a + b\n"
    )
    once = _patch(source)
    assert once != source
    assert _patch(once) == once


# ── determinism ───────────────────────────────────────────────────────────────

def test_patch_is_deterministic():
    source = "def p():\n    return 1\n\n\ndef q(\n    x,\n):\n    return x\n"
    assert _patch(source) == _patch(source)


# ── end-to-end through the agent run: multi-line file is patched (not skipped) ─

def test_agent_run_lands_multiline_in_place(tmp_path: Path):
    src = tmp_path / "calc.py"
    src.write_text(
        "def subtract(a, b):\n"
        "    return a - b\n"
        "\n\n"
        "def add_many(\n"
        "    a,\n"
        "    b,\n"
        "    c,\n"
        "):\n"
        "    return a + b + c\n",
        encoding="utf-8",
    )
    result = DocstringAgent().run(project_root=str(tmp_path), patch=True)
    assert "calc.py" in result["patched_files"]
    patched = src.read_text(encoding="utf-8")
    ast.parse(patched)
    docs = _docs(patched)
    assert docs["subtract"] == "subtract implementation."
    assert docs["add_many"] == "add_many implementation."


def test_agent_run_invalid_source_untouched(tmp_path: Path):
    bad = tmp_path / "broken.py"
    bad.write_text("def f(:\n    pass\n", encoding="utf-8")
    result = DocstringAgent().run(project_root=str(tmp_path), patch=True)
    assert result["patched_files"] == []
    assert bad.read_text(encoding="utf-8") == "def f(:\n    pass\n"
