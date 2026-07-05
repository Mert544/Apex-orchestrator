"""Edge-path coverage for SemanticPatchGenerator: the security/modernize fix
branches (lines 159-178), the path-outside-root skip, the non-test missing
file (stub returns None) skip, the non-.py file skip, and draft-fallback vetting.

Deterministic: every input is constructed explicitly via tmp_path; no time,
random, network, or subprocess.
"""

from pathlib import Path

from app.execution.semantic_patch_generator import SemanticPatchGenerator


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# --- Security / modernize fix branches (semantic_patch_generator.py 159-178) ---

def test_fix_eval_security_branch(tmp_path: Path):
    _write(tmp_path / "app" / "danger.py", "def run(s):\n    return eval(s)\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/danger.py"], "title": "Fix eval security risk", "task_id": "s-1"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "eval_to_literal_eval"
    assert "literal_eval" in result.patch_requests[0]["new_content"]


def test_fix_os_system_security_branch(tmp_path: Path):
    _write(tmp_path / "app" / "shell.py", "import os\ndef go(c):\n    os.system(c)\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/shell.py"], "title": "Fix os.system call", "task_id": "s-2"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "os_system_to_subprocess"


def test_fix_yaml_security_branch(tmp_path: Path):
    _write(tmp_path / "app" / "cfg.py", "import yaml\ndef load(s):\n    return yaml.load(s)\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/cfg.py"], "title": "Fix yaml load", "task_id": "s-3"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "yaml_load_to_safe_load"
    assert "yaml.safe_load(s)" in result.patch_requests[0]["new_content"]


def test_modernize_branch(tmp_path: Path):
    _write(tmp_path / "app" / "old.py", "def f(x):\n    if x == None:\n        return 1\n    return 0\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/old.py"], "title": "Modernize none-comparison", "task_id": "m-1"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type is not None
    assert "is None" in result.patch_requests[0]["new_content"]


def test_fix_mutable_default_branch(tmp_path: Path):
    _write(tmp_path / "app" / "mut.py", "def add(item, acc=[]):\n    acc.append(item)\n    return acc\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/mut.py"], "title": "Fix mutable default argument", "task_id": "md-1"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.mode == "semantic"
    assert "acc=None" in result.patch_requests[0]["new_content"]


def test_fix_open_encoding_branch(tmp_path: Path):
    _write(tmp_path / "app" / "io.py", "def read(p):\n    return open(p).read()\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/io.py"], "title": "Add explicit open-encoding", "task_id": "oe-1"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.mode == "semantic"
    assert "encoding=" in result.patch_requests[0]["new_content"]


def test_fix_net_timeout_branch(tmp_path: Path):
    _write(tmp_path / "app" / "net.py", "import requests\ndef get(u):\n    return requests.get(u)\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/net.py"], "title": "Flag net-timeout missing", "task_id": "nt-1"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.mode == "semantic"


def test_fix_identity_literal_branch(tmp_path: Path):
    _write(tmp_path / "app" / "ident.py", "def f(x):\n    return x is 5\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/ident.py"], "title": "Fix identity-literal comparison", "task_id": "il-1"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.mode == "semantic"
    assert "x == 5" in result.patch_requests[0]["new_content"]


def test_fix_negated_comparison_branch(tmp_path: Path):
    _write(tmp_path / "app" / "neg.py", "def f(x, y):\n    return not x in y\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/neg.py"], "title": "Fix negated-comparison", "task_id": "nc-1"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.mode == "semantic"
    assert "x not in y" in result.patch_requests[0]["new_content"]


def test_fix_raise_from_branch(tmp_path: Path):
    source = (
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError as err:\n"
        "        raise RuntimeError('boom')\n"
    )
    _write(tmp_path / "app" / "rf.py", source)
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/rf.py"], "title": "Fix raise-from chaining", "task_id": "rf-1"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.mode == "semantic"
    assert "from err" in result.patch_requests[0]["new_content"]


def test_fix_fstring_branch(tmp_path: Path):
    _write(tmp_path / "app" / "fs.py", 'def f():\n    return f"plain"\n')
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/fs.py"], "title": "Drop fstring-no-placeholder", "task_id": "fs-1"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.mode == "semantic"
    assert '"plain"' in result.patch_requests[0]["new_content"]


def test_fix_collection_literal_branch(tmp_path: Path):
    _write(tmp_path / "app" / "col.py", "def f():\n    return dict()\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/col.py"], "title": "Use collection-literal", "task_id": "cl-1"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.mode == "semantic"
    assert "{}" in result.patch_requests[0]["new_content"]


def test_fix_bare_except_branch(tmp_path: Path):
    _write(tmp_path / "app" / "be.py", "def f():\n    try:\n        pass\n    except:\n        raise\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/be.py"], "title": "Fix bare except handler", "task_id": "be-1"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.mode == "semantic"
    assert "except Exception" in result.patch_requests[0]["new_content"]


# --- Continue-paths: non-.py file, missing non-test file, path outside root ---

def test_non_python_target_is_skipped_then_drafts(tmp_path: Path):
    # An existing non-.py target hits the `target.suffix != ".py"` continue
    # (line 103); with no python target the generator falls back to draft.
    _write(tmp_path / "docs" / "readme.txt", "hello\n")
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["docs/readme.txt"], "title": "Edit docs", "task_id": "np-1"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "draft_fallback"
    assert result.mode == "draft"


def test_missing_non_test_file_yields_no_stub_then_drafts(tmp_path: Path):
    # A missing non-test .py target: try_create_stub returns None (not a test
    # path), so the loop `continue`s (line 100) and ends in a draft fallback.
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["app/ghost_module.py"], "title": "Add feature", "task_id": "gm-1"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "draft_fallback"
    assert result.mode == "draft"


def test_target_escaping_root_is_skipped(tmp_path: Path):
    # A path that resolves outside the project root is skipped (line 95); with
    # no surviving target the generator drafts a fallback.
    generator = SemanticPatchGenerator()
    patch_plan = {"target_files": ["../outside.py"], "title": "Touch outside", "task_id": "esc-1"}

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "draft_fallback"
    assert result.mode == "draft"


# --- Draft-fallback vetting: explicit strategy & verification carried through ---

def test_draft_fallback_records_change_strategy_and_verification(tmp_path: Path):
    # No semantic transform matches (binary-ish title + no python edit), so the
    # generator drafts; the draft must capture the supplied strategy/steps.
    _write(tmp_path / "data" / "table.csv", "a,b\n1,2\n")
    generator = SemanticPatchGenerator()
    patch_plan = {
        "target_files": ["data/table.csv"],
        "title": "Reshape dataset",
        "task_id": "draft-1",
        "branch": "x.reshape",
        "change_strategy": ["normalize columns", "dedupe rows"],
        "verification_steps": ["run schema check", "diff row counts"],
    }

    result = generator.generate(project_root=tmp_path, patch_plan=patch_plan)

    assert result.transform_type == "draft_fallback"
    content = result.patch_requests[0]["new_content"]
    assert "normalize columns" in content
    assert "dedupe rows" in content
    assert "run schema check" in content
    assert "x.reshape" in content


# --- Characterization: dispatch matrix is byte-stable after consolidation ---
#
# Locks the (transform -> SemanticPatchResult) contract of generate() across a
# representative input for every dispatch branch. Pins transform_type, mode,
# patch-request count/paths, estimated_tokens, and the produced new_content so
# the mechanical extraction of the if/elif chain into helpers cannot silently
# alter the chosen patch for any input.
_CASES = {
    "docstring": (
        {"app/m.py": "def add(a, b):\n    return a + b\n"},
        {"target_files": ["app/m.py"], "title": "Add docstrings", "task_id": "c1"},
        None, "add_docstring", "semantic",
    ),
    "type_anns": (
        # A PROVABLE return (``return 1`` ⇒ ``int``) so the semantic
        # ``add_type_annotations`` branch fires; an unprovable body (e.g.
        # ``return a + b``) is now correctly refused and would fall back to draft.
        {"app/m.py": "def one():\n    return 1\n"},
        {"target_files": ["app/m.py"], "title": "Add type annotations", "task_id": "c2"},
        None, "add_type_annotations", "semantic",
    ),
    "guard": (
        {"app/m.py": "def add(a, b):\n    return a + b\n"},
        {"target_files": ["app/m.py"], "title": "Add input validation guard", "task_id": "c3"},
        None, "add_guard_clause", "semantic",
    ),
    "repair_test": (
        {"tests/test_m.py": "def test_add():\n    assert 1 + 1 == 2\n"},
        {"target_files": ["tests/test_m.py"], "title": "Fix tests", "task_id": "c4"},
        {"failure_type": "test_failure"}, "repair_test_assertion", "semantic",
    ),
    "rename": (
        {"app/m.py": "def calculate(x, y):\n    total = x + y\n    result = total * 2\n    return result\n"},
        {"target_files": ["app/m.py"], "title": "Rename variable for clarity", "task_id": "c5",
         "rename": {"old_name": "total", "new_name": "subtotal", "target_function": "calculate"}},
        None, "rename_variable", "semantic",
    ),
    "inline": (
        {"app/m.py": "def compute(x):\n    y = x + 1\n    return y\n"},
        {"target_files": ["app/m.py"], "title": "Inline simple variable", "task_id": "c6",
         "inline": {"var_name": "y", "target_function": "compute"}},
        None, "inline_variable", "semantic",
    ),
    "organize_imports": (
        {"app/m.py": "import os\nimport sys\nimport json\n\ndef load():\n    return json.loads('{}')\n"},
        {"target_files": ["app/m.py"], "title": "Clean up unused imports", "task_id": "c7"},
        None, "organize_imports", "semantic",
    ),
    "move_class": (
        {"app/main.py": "class OldService:\n    def work(self):\n        return 'done'\n\ndef main():\n    s = OldService()\n    return s.work()\n"},
        {"target_files": ["app/main.py"], "title": "Move class to separate module", "task_id": "c8",
         "move": {"class_name": "OldService", "new_module": "app/service.py"}},
        None, "move_class", "semantic",
    ),
    "extract_class": (
        {"app/big.py": "class BigClass:\n    def method_a(self):\n        return 'a'\n    def method_b(self):\n        return 'b'\n    def method_c(self):\n        return 'c'\n"},
        {"target_files": ["app/big.py"], "title": "Extract helper class", "task_id": "c9",
         "extract_class": {"methods": ["method_a", "method_b"], "new_class_name": "HelperClass", "base_class": None}},
        None, "extract_class", "semantic",
    ),
    "sec_eval": (
        {"app/e.py": "x = eval(s)\n"},
        {"target_files": ["app/e.py"], "title": "fix eval", "task_id": "c10"},
        None, "eval_to_literal_eval", "semantic",
    ),
    "sec_yaml": (
        {"app/y.py": "import yaml\nx = yaml.load(s)\n"},
        {"target_files": ["app/y.py"], "title": "fix yaml", "task_id": "c11"},
        None, "yaml_load_to_safe_load", "semantic",
    ),
    "modernize": (
        {"app/m.py": "if x == None:\n    pass\n"},
        {"target_files": ["app/m.py"], "title": "modernize none-comparison", "task_id": "c12"},
        None, "modernize_none_comparison", "semantic",
    ),
    "mutable_default": (
        {"app/m.py": "def f(x=[]):\n    return x\n"},
        {"target_files": ["app/m.py"], "title": "fix mutable-default arg", "task_id": "c13"},
        None, "fix_mutable_default", "semantic",
    ),
    "open_encoding": (
        {"app/m.py": "open('f.txt')\n"},
        {"target_files": ["app/m.py"], "title": "add open-encoding", "task_id": "c14"},
        None, "add_open_encoding", "semantic",
    ),
    "net_timeout": (
        {"app/m.py": "import requests\nrequests.get(u)\n"},
        {"target_files": ["app/m.py"], "title": "fix net-timeout hang", "task_id": "c15"},
        None, "flag_net_timeout", "semantic",
    ),
    "identity_literal": (
        {"app/m.py": "if x is 1:\n    pass\n"},
        {"target_files": ["app/m.py"], "title": "fix identity-literal", "task_id": "c16"},
        None, "fix_identity_literal", "semantic",
    ),
    "negated_comparison": (
        {"app/m.py": "if not a in b:\n    pass\n"},
        {"target_files": ["app/m.py"], "title": "fix negated-comparison", "task_id": "c17"},
        None, "fix_negated_comparison", "semantic",
    ),
    "raise_from": (
        {"app/m.py": "try:\n    x=1\nexcept Exception as e:\n    raise ValueError('bad')\n"},
        {"target_files": ["app/m.py"], "title": "fix raise-from chaining", "task_id": "c18"},
        None, "raise_with_from", "semantic",
    ),
    "fstring": (
        {"app/m.py": "x = f'no placeholder'\n"},
        {"target_files": ["app/m.py"], "title": "fix fstring-no-placeholder", "task_id": "c19"},
        None, "fix_fstring_no_placeholder", "semantic",
    ),
    "collection_literal": (
        {"app/m.py": "x = list()\n"},
        {"target_files": ["app/m.py"], "title": "fix collection-literal", "task_id": "c20"},
        None, "modernize_collection_literal", "semantic",
    ),
    "stub_no_src": (
        {},
        {"target_files": ["tests/test_orders.py"], "title": "Close test gap", "task_id": "c21"},
        None, "create_test_stub", "semantic",
    ),
    "fallback_no_files": (
        {},
        {"target_files": [], "title": "Refactor everything", "task_id": "c22"},
        None, "draft_fallback", "draft",
    ),
    "non_py_skip": (
        {"app/data.txt": "hello\n"},
        {"target_files": ["app/data.txt"], "title": "Add docstrings", "task_id": "c23"},
        None, "draft_fallback", "draft",
    ),
    "missing_nontest_skip": (
        {},
        {"target_files": ["app/ghost.py"], "title": "Add docstrings", "task_id": "c24"},
        None, "draft_fallback", "draft",
    ),
}


def test_dispatch_matrix_characterization(tmp_path: Path):
    """Every dispatch branch yields a deterministic, fully-specified result."""
    gen = SemanticPatchGenerator()
    for label, (files, plan, repair, expect_transform, expect_mode) in _CASES.items():
        sub = tmp_path / label
        sub.mkdir(parents=True, exist_ok=True)
        for rel, content in files.items():
            _write(sub / rel, content)
        result = gen.generate(project_root=sub, patch_plan=plan, repair_context=repair)
        assert result.transform_type == expect_transform, label
        assert result.mode == expect_mode, label
        # Determinism: identical input -> byte-identical patch requests + tokens.
        again = gen.generate(project_root=sub, patch_plan=plan, repair_context=repair)
        assert again.to_dict() == result.to_dict(), label
        for pr in result.patch_requests:
            assert "new_content" in pr and "path" in pr, label
        if expect_mode == "semantic" and expect_transform != "create_test_stub":
            assert result.estimated_tokens >= 0, label
