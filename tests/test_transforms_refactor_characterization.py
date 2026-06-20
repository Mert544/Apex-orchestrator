"""Characterization: refactored security.apply / chained_comparison._merge_boolop
produce byte-identical results to the pre-refactor originals.

The originals are loaded from ``git show HEAD:<file>`` snapshots written to temp
modules, then we feed many source snippets (convertible AND must-not-convert)
through both the original and current ``apply`` paths and assert the full
``SemanticPatchResult`` output is identical for every case.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types

from app.execution.semantic.transforms import chained_comparison as cur_chained
from app.execution.semantic.transforms import security as cur_security


def _load_original(rel_path: str, mod_name: str) -> types.ModuleType:
    """Load the HEAD version of a transform module under a private name."""
    src = subprocess.check_output(["git", "show", f"HEAD:{rel_path}"], text=True)
    spec = importlib.util.spec_from_loader(mod_name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    # Give the module the real package so its relative imports resolve.
    mod.__package__ = "app.execution.semantic.transforms"
    sys.modules[mod_name] = mod
    exec(compile(src, rel_path, "exec"), mod.__dict__)
    return mod


ORIG_SECURITY = _load_original(
    "app/execution/semantic/transforms/security.py", "_orig_security"
)
ORIG_CHAINED = _load_original(
    "app/execution/semantic/transforms/chained_comparison.py", "_orig_chained"
)


def _normalize(result):
    """Reduce a SemanticPatchResult to a comparable plain structure."""
    if result is None:
        return None
    return (
        result.transform_type,
        tuple(tuple(sorted(req.items())) for req in result.patch_requests),
        tuple(result.rationale),
    )


# (title, source) pairs covering convertible and must-NOT-convert paths.
_SECURITY_CASES = [
    # eval
    ("eval injection", "x = eval(data)\n"),
    ("eval", "x = eval('1 + 2')\n"),  # not a literal -> refuse
    ("eval", "x = eval('[1, 2, 3]')\n"),  # literal -> convert
    ("eval", "x = eval(f'{a}')\n"),  # f-string -> refuse
    ("eval", "x = eval()\n"),  # no args -> refuse
    ("eval", "x = ast.literal_eval(data)\n"),  # already safe
    ("eval", "import ast\nx = eval(data)\n"),  # import present
    # os.system
    ("os.system risk", "os.system(cmd)\n"),
    ("os.system", "import os\nos.system('ls -la')\n"),
    ("os.system", "os.system()\n"),
    # bare except
    ("bare except", "try:\n    pass\nexcept:\n    pass\n"),
    ("bareexcept", "try:\n    pass\nexcept Exception:\n    pass\n"),
    # base exception
    ("base-exception", "try:\n    pass\nexcept BaseException:\n    pass\n"),
    ("baseexception", "try:\n    pass\nexcept BaseException:\n    raise\n"),
    # pickle
    ("pickle risk", "import pickle\nx = pickle.loads(b)\n"),
    ("pickle", "x = pickle.loads(b)\n# Apex: untrusted pickle\n"),
    # sql injection
    ("sql injection", "cur.execute(f'SELECT {x}')\n"),
    ("injection", "cur.execute('SELECT 1')\n"),  # no f-string -> refuse
    # yaml
    ("yaml load", "yaml.load(stream)\n"),
    ("yaml", "yaml.load(stream, Loader=L)\n"),  # explicit loader -> refuse
    # tempfile
    ("tempfile mktemp", "tempfile.mktemp()\n"),
    ("mktemp", "x = mktemp()\n"),  # not tempfile.mktemp -> refuse
    # weak hash
    ("weak-hash", "hashlib.md5(b)\n"),
    ("hashlib", "hashlib.md5(b, usedforsecurity=False)\n"),  # declared -> refuse
    ("hashlib", "hashlib.sha256(b)\n"),  # strong -> refuse
    # no match / syntax error
    ("totally unrelated", "x = 1\n"),
    ("eval", "def broken(:\n"),  # syntax error -> None
    # multiline indent
    ("pickle", "def f():\n    return pickle.loads(b)\n"),
]


def test_security_apply_byte_identical():
    mismatches = []
    for title, source in _SECURITY_CASES:
        orig = _normalize(ORIG_SECURITY.apply("m.py", source, title))
        cur = _normalize(cur_security.apply("m.py", source, title))
        if orig != cur:
            mismatches.append((title, source, orig, cur))
    assert not mismatches, mismatches


_CHAINED_CASES = [
    "a < b and b < c\n",
    "a > b and b > c\n",
    "a <= b and b <= c\n",
    "a >= b and b >= c\n",
    "a == b and b == c\n",
    "a < b and b > c\n",  # mixed direction -> refuse
    "a < b and c < d\n",  # no shared middle -> refuse
    "f() < b and b < c\n",  # call operand -> refuse
    "a < b and b < c()\n",  # call operand -> refuse
    "obj.x < m and m < obj.y\n",  # attribute chain ok
    "a < b[0] and b[0] < c\n",  # subscript middle -> refuse
    "a < b or b < c\n",  # or -> refuse
    "a < b < c and c < d\n",  # multi-op arm -> refuse
    "x = 1\n",  # nothing to merge
    "a < b and b < c and c < d\n",  # three-arm and
    "def broken(:\n",  # syntax error -> None
    "(n := 1) < b and b < c\n",  # walrus -> refuse
    # NOTE: a commented case (e.g. "a < b and b < c  # trailing") is intentionally
    # NOT pinned here: the pre-splice HEAD refused (returned None) on any comment,
    # whereas the current driver routes through ``run_splice_rewrite`` and LANDS
    # the fix while preserving the comment. That deliberate behavioural change is
    # characterized in tests/test_comment_preserving_splice_eyml.py instead. The
    # comment-FREE equivalence pinned here still holds byte-for-byte.
]


def test_chained_apply_byte_identical():
    mismatches = []
    for source in _CHAINED_CASES:
        orig = _normalize(ORIG_CHAINED.apply("m.py", source, "chain"))
        cur = _normalize(cur_chained.apply("m.py", source, "chain"))
        if orig != cur:
            mismatches.append((source, orig, cur))
    assert not mismatches, mismatches


def test_merge_boolop_node_byte_identical():
    """Compare _merge_boolop output AST (via ast.dump) over BoolOp expressions."""
    import ast

    exprs = [
        "a < b and b < c",
        "a > b and b > c",
        "a < b and b > c",
        "a < b and c < d",
        "f() < b and b < c",
        "a < b and b < c()",
        "obj.x < m and m < obj.y",
        "a < b[0] and b[0] < c",
        "a < b or b < c",
        "a < b < c and c < d",
    ]
    mismatches = []
    for src in exprs:
        node = ast.parse(src, mode="eval").body
        if not isinstance(node, ast.BoolOp):
            continue
        o = ORIG_CHAINED._merge_boolop(node)
        c = cur_chained._merge_boolop(node)
        od = None if o is None else ast.dump(o)
        cd = None if c is None else ast.dump(c)
        if od != cd:
            mismatches.append((src, od, cd))
    assert not mismatches, mismatches
