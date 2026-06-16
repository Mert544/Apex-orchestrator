"""Byte-identical characterization of cmd_signature and cmd_teach.

Pins the exact (return code, normalized stdout, stderr) transcript of both CLI
commands across a broad matrix of arg/input combinations. The golden transcript
below was captured from the pre-refactor implementation; the post-refactor code
must reproduce it byte-for-byte. Deterministic and offline: every apply path
runs with no_verify=True (no pytest subprocess), --from-git is monkeypatched,
and the tmp project root is normalized to <ROOT> so output is stable.
"""

from __future__ import annotations

import argparse
import contextlib
import io
from pathlib import Path

import app.engine.git_rule_miner as grm
from app.cli_refactor import cmd_signature, cmd_teach


def _ns(**kw) -> argparse.Namespace:
    return argparse.Namespace(**kw)


def _project(tmp_path: Path, files: dict) -> Path:
    (tmp_path / "app").mkdir(exist_ok=True)
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


def _run(fn, namespace, root: str):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(namespace)
    return rc, out.getvalue().replace(root, "<ROOT>"), err.getvalue().replace(root, "<ROOT>")


def _block(kind: str, label: str, rc, out: str, err: str) -> str:
    return (f"=== {kind} {label} rc={rc} ===\n--out--\n{out}\n--err--\n{err}")


_SRC_UNUSED = "def f(a, b):\n    return a\n"
_SRC_CALLER = "def f(a, b):\n    return a\n\nx = f(1, 2)\n"
_SRC_G = "def g(a):\n    return a\n"
_SRC_G2 = "def g(a, b):\n    return a + b\n\ny = g(1, 2)\n"
_SRC_GAB = "def g(a, b):\n    return a + b\n"
_SIG_BASE = dict(default="None", dry_run=False, no_verify=True, json=False)


def _sig_cases():
    def c(op, function, param="", files=None, **over):
        kw = dict(_SIG_BASE)
        kw.update(dict(op=op, function=function, param=param))
        kw.update(over)
        return files or {"app/m.py": _SRC_UNUSED}, kw

    return [
        ("drop_apply", *c("drop", "f", "b")),
        ("drop_no_param", *c("drop", "f", "")),
        ("drop_dry", *c("drop", "f", "b", dry_run=True)),
        ("drop_json", *c("drop", "f", "b", json=True)),
        ("drop_blocked_positional", *c("drop", "f", "b", files={"app/m.py": _SRC_CALLER})),
        ("drop_json_blocked", *c("drop", "f", "b", files={"app/m.py": _SRC_CALLER}, json=True)),
        ("drop_dry_blocked", *c("drop", "f", "b", files={"app/m.py": _SRC_CALLER}, dry_run=True)),
        ("add_dry", *c("add", "g", "b", files={"app/m.py": _SRC_G}, default="0", dry_run=True)),
        ("add_apply", *c("add", "g", "b", files={"app/m.py": _SRC_G}, default="0")),
        ("add_apply_json", *c("add", "g", "b", files={"app/m.py": _SRC_G}, default="0", json=True)),
        ("add_default_empty", *c("add", "g", "b", files={"app/m.py": _SRC_G}, default="")),
        ("add_no_default_attr", *_c_no_default()),
        ("keywordify_dry", *c("keywordify", "g", files={"app/m.py": _SRC_G2}, dry_run=True)),
        ("keywordify_apply", *c("keywordify", "g", files={"app/m.py": _SRC_G2})),
        ("keywordify_json", *c("keywordify", "g", files={"app/m.py": _SRC_G2}, json=True)),
        ("reorder_dry", *c("reorder", "g", "b,a", files={"app/m.py": _SRC_GAB}, dry_run=True)),
        ("reorder_apply", *c("reorder", "g", "b,a", files={"app/m.py": _SRC_GAB})),
        ("reorder_empty_order", *c("reorder", "g", "", files={"app/m.py": _SRC_GAB})),
        ("reorder_spaces", *c("reorder", "g", " b , a ", files={"app/m.py": _SRC_GAB}, dry_run=True)),
        ("drop_unknown_fn", *c("drop", "nope", "b")),
        ("add_unknown_fn", *c("add", "nope", "b", default="0")),
    ]


def _c_no_default():
    # 'add' with the 'default' attribute entirely absent -> getattr fallback.
    kw = dict(op="add", function="g", param="b", dry_run=False, no_verify=True, json=False)
    return {"app/m.py": _SRC_G}, kw


_TEACH_BASE = dict(save="", from_git=False, commits=50)


def _teach_cases():
    def c(examples, files=None, **over):
        kw = dict(_TEACH_BASE)
        kw.update(dict(examples=examples))
        kw.update(over)
        return (files or {}), kw

    learn = ["len(xs) == 0", "not xs", "len(a.b) == 0", "not a.b"]
    match = {"app/m.py": "def c(xs):\n    return len(xs) == 0\n"}
    return [
        ("learn_basic", *c(learn)),
        ("learn_with_match", *c(learn, files=match)),
        ("odd_examples", *c(["a", "b", "c"])),
        ("no_pairs", *c([])),
        ("unlearnable", *c(["1 + 1", "garbage("])),
        ("save", *c(learn, files=match, save="empties")),
        ("save_with_match", *c(learn, files=match, save="r1")),
        ("single_pair", *c(["len(xs) == 0", "not xs"])),
        ("examples_none", *c(None)),
        ("save_no_match", *c(learn, save="r2")),
    ]


def _transcript(tmp_path_factory, monkeypatch) -> str:
    blocks = []
    for label, files, kw in _sig_cases():
        root = tmp_path_factory.mktemp("sig")
        _project(root, files)
        rc, out, err = _run(cmd_signature, _ns(target=str(root), **kw), str(root))
        blocks.append(_block("SIG", label, rc, out, err))
    for label, files, kw in _teach_cases():
        root = tmp_path_factory.mktemp("teach")
        _project(root, files)
        rc, out, err = _run(cmd_teach, _ns(target=str(root), **kw), str(root))
        blocks.append(_block("TEACH", label, rc, out, err))

    # --from-git scenarios via monkeypatched miner (deterministic, offline).
    def teach_git(label, miner, files, commits):
        root = tmp_path_factory.mktemp("git")
        _project(root, files)
        monkeypatch.setattr(grm, "mine_git_pairs", miner)
        ns = _ns(target=str(root), examples=[], save="", from_git=True, commits=commits)
        rc, out, err = _run(cmd_teach, ns, str(root))
        blocks.append(_block("TEACH", label, rc, out, err))

    teach_git("from_git_empty", lambda root, n: [], {}, 7)
    teach_git("from_git_pairs",
              lambda root, n: [("len(xs) == 0", "not xs"), ("len(a.b) == 0", "not a.b")],
              {"app/m.py": "def c(xs):\n    return len(xs) == 0\n"}, 5)
    teach_git("from_git_many",
              lambda root, n: [(f"len(x{i}) == 0", f"not x{i}") for i in range(8)], {}, 99)
    teach_git("from_git_commits0",
              lambda root, n: ([] if n == 50 else [("a", "b")]), {}, 0)
    return "\n".join(blocks)


GOLDEN = '=== SIG drop_apply rc=0 ===\n--out--\n✅ Signature changed — drop `b` from `f()`: 1 edit(s) in 1 file(s): app/m.py\n\n--err--\n\n=== SIG drop_no_param rc=1 ===\n--out--\n# Signature change blocked: `drop` needs a PARAM argument\n\n--err--\n\n=== SIG drop_dry rc=0 ===\n--out--\n# Signature change (dry run): drop `b` from `f()` — 1 edit(s) across 1 file(s)\n\n```diff\n--- a/app/m.py\n+++ b/app/m.py\n@@ -1,2 +1,2 @@\n-def f(a, b):\n+def f(a):\n     return a\n```\n\n--err--\n\n=== SIG drop_json rc=0 ===\n--out--\n{\n  "applied": true,\n  "changed_files": [\n    "app/m.py"\n  ],\n  "edits": 1,\n  "warnings": []\n}\n\n--err--\n\n=== SIG drop_blocked_positional rc=1 ===\n--out--\n# Signature change blocked: drop `b` from `f()`\n\n- ⛔ app/m.py:4: passes \'b\' POSITIONALLY — convert that call to keywords first, then re-run\n\n--err--\n\n=== SIG drop_json_blocked rc=1 ===\n--out--\n# Signature change blocked: drop `b` from `f()`\n\n- ⛔ app/m.py:4: passes \'b\' POSITIONALLY — convert that call to keywords first, then re-run\n\n--err--\n\n=== SIG drop_dry_blocked rc=1 ===\n--out--\n# Signature change blocked: drop `b` from `f()`\n\n- ⛔ app/m.py:4: passes \'b\' POSITIONALLY — convert that call to keywords first, then re-run\n\n--err--\n\n=== SIG add_dry rc=0 ===\n--out--\n# Signature change (dry run): add `b=0` to `g()` — 1 edit(s) across 1 file(s)\n\n```diff\n--- a/app/m.py\n+++ b/app/m.py\n@@ -1,2 +1,2 @@\n-def g(a):\n+def g(a, b=0):\n     return a\n```\n\n--err--\n\n=== SIG add_apply rc=0 ===\n--out--\n✅ Signature changed — add `b=0` to `g()`: 1 edit(s) in 1 file(s): app/m.py\n\n--err--\n\n=== SIG add_apply_json rc=0 ===\n--out--\n{\n  "applied": true,\n  "changed_files": [\n    "app/m.py"\n  ],\n  "edits": 1,\n  "warnings": []\n}\n\n--err--\n\n=== SIG add_default_empty rc=0 ===\n--out--\n✅ Signature changed — add `b=None` to `g()`: 1 edit(s) in 1 file(s): app/m.py\n\n--err--\n\n=== SIG add_no_default_attr rc=0 ===\n--out--\n✅ Signature changed — add `b=None` to `g()`: 1 edit(s) in 1 file(s): app/m.py\n\n--err--\n\n=== SIG keywordify_dry rc=0 ===\n--out--\n# Signature change (dry run): convert positional calls of `g()` to keywords — 2 edit(s) across 1 file(s)\n\n```diff\n--- a/app/m.py\n+++ b/app/m.py\n@@ -1,4 +1,4 @@\n def g(a, b):\n     return a + b\n \n-y = g(1, 2)\n+y = g(a=1, b=2)\n```\n\n--err--\n\n=== SIG keywordify_apply rc=0 ===\n--out--\n✅ Signature changed — convert positional calls of `g()` to keywords: 2 edit(s) in 1 file(s): app/m.py\n\n--err--\n\n=== SIG keywordify_json rc=0 ===\n--out--\n{\n  "applied": true,\n  "changed_files": [\n    "app/m.py"\n  ],\n  "edits": 2,\n  "warnings": []\n}\n\n--err--\n\n=== SIG reorder_dry rc=0 ===\n--out--\n# Signature change (dry run): reorder `g()` parameters to (b, a) — 1 edit(s) across 1 file(s)\n\n```diff\n--- a/app/m.py\n+++ b/app/m.py\n@@ -1,2 +1,2 @@\n-def g(a, b):\n+def g(b, a):\n     return a + b\n```\n\n--err--\n\n=== SIG reorder_apply rc=0 ===\n--out--\n✅ Signature changed — reorder `g()` parameters to (b, a): 1 edit(s) in 1 file(s): app/m.py\n\n--err--\n\n=== SIG reorder_empty_order rc=1 ===\n--out--\n# Signature change blocked: reorder `g()` parameters to ()\n\n- ⛔ the new order must be a permutation of g()\'s regular parameters (a, b)\n\n--err--\n\n=== SIG reorder_spaces rc=0 ===\n--out--\n# Signature change (dry run): reorder `g()` parameters to (b, a) — 1 edit(s) across 1 file(s)\n\n```diff\n--- a/app/m.py\n+++ b/app/m.py\n@@ -1,2 +1,2 @@\n-def g(a, b):\n+def g(b, a):\n     return a + b\n```\n\n--err--\n\n=== SIG drop_unknown_fn rc=1 ===\n--out--\n# Signature change blocked: drop `b` from `nope()`\n\n- ⛔ \'nope\' must be defined exactly once at top level (found 0)\n\n--err--\n\n=== SIG add_unknown_fn rc=1 ===\n--out--\n# Signature change blocked: add `b=0` to `nope()`\n\n- ⛔ \'nope\' must be defined exactly once at top level (found 0)\n\n--err--\n\n=== TEACH learn_basic rc=0 ===\n--out--\n# Learned rule: `len($v1) == 0` → `not $v1`\n- self-check passed on 2 example(s)\n\nNo match in the project right now (the rule still guards the future).\n\n--err--\n\n=== TEACH learn_with_match rc=0 ===\n--out--\n# Learned rule: `len($v1) == 0` → `not $v1`\n- self-check passed on 2 example(s)\n\nWould rewrite 1 match(es) across 1 file(s) — preview:\n\n```diff\n--- a/app/m.py\n+++ b/app/m.py\n@@ -1,2 +1,2 @@\n def c(xs):\n-    return len(xs) == 0\n+    return not xs\n```\n\n--err--\n\n=== TEACH odd_examples rc=1 ===\n--out--\n⛔ teach takes BEFORE/AFTER pairs (an even number of expressions)\n\n--err--\n\n=== TEACH no_pairs rc=1 ===\n--out--\n⛔ no example pairs to learn from\n\n--err--\n\n=== TEACH unlearnable rc=1 ===\n--out--\n# Teach blocked\n\n- ⛔ example 1 is not a pair of valid expressions\n\n--err--\n\n=== TEACH save rc=0 ===\n--out--\n# Learned rule: `len($v1) == 0` → `not $v1`\n- self-check passed on 2 example(s)\n\nWould rewrite 1 match(es) across 1 file(s) — preview:\n\n```diff\n--- a/app/m.py\n+++ b/app/m.py\n@@ -1,2 +1,2 @@\n def c(xs):\n-    return len(xs) == 0\n+    return not xs\n```\n💾 rule \'empties\' saved — apply with: apex rewrite --rule empties\n\n--err--\n\n=== TEACH save_with_match rc=0 ===\n--out--\n# Learned rule: `len($v1) == 0` → `not $v1`\n- self-check passed on 2 example(s)\n\nWould rewrite 1 match(es) across 1 file(s) — preview:\n\n```diff\n--- a/app/m.py\n+++ b/app/m.py\n@@ -1,2 +1,2 @@\n def c(xs):\n-    return len(xs) == 0\n+    return not xs\n```\n💾 rule \'r1\' saved — apply with: apex rewrite --rule r1\n\n--err--\n\n=== TEACH single_pair rc=0 ===\n--out--\n# Learned rule: `len(xs) == 0` → `not xs`\n- one example → an exact-match rule (no metavariables); teach with a second example to generalize\n- self-check passed on 1 example(s)\n\nNo match in the project right now (the rule still guards the future).\n\n--err--\n\n=== TEACH examples_none rc=1 ===\n--out--\n⛔ no example pairs to learn from\n\n--err--\n\n=== TEACH save_no_match rc=0 ===\n--out--\n# Learned rule: `len($v1) == 0` → `not $v1`\n- self-check passed on 2 example(s)\n\nNo match in the project right now (the rule still guards the future).\n💾 rule \'r2\' saved — apply with: apex rewrite --rule r2\n\n--err--\n\n=== TEACH from_git_empty rc=0 ===\n--out--\nNo single-line expression changes found in the last 7 commit(s).\n\n--err--\n\n=== TEACH from_git_pairs rc=0 ===\n--out--\nMined 2 single-line change(s) from the last 5 commit(s).\n  `len(xs) == 0` → `not xs`\n  `len(a.b) == 0` → `not a.b`\n# Learned rule: `len($v1) == 0` → `not $v1`\n- self-check passed on 2 example(s)\n\nWould rewrite 1 match(es) across 1 file(s) — preview:\n\n```diff\n--- a/app/m.py\n+++ b/app/m.py\n@@ -1,2 +1,2 @@\n def c(xs):\n-    return len(xs) == 0\n+    return not xs\n```\n\n--err--\n\n=== TEACH from_git_many rc=0 ===\n--out--\nMined 8 single-line change(s) from the last 99 commit(s).\n  `len(x0) == 0` → `not x0`\n  `len(x1) == 0` → `not x1`\n  `len(x2) == 0` → `not x2`\n  `len(x3) == 0` → `not x3`\n  `len(x4) == 0` → `not x4` …\n# Learned rule: `len($v1) == 0` → `not $v1`\n- self-check passed on 8 example(s)\n\nNo match in the project right now (the rule still guards the future).\n\n--err--\n\n=== TEACH from_git_commits0 rc=0 ===\n--out--\nNo single-line expression changes found in the last 50 commit(s).\n\n--err--\n'


def test_signature_and_teach_byte_identical(tmp_path_factory, monkeypatch):
    assert _transcript(tmp_path_factory, monkeypatch) == GOLDEN

