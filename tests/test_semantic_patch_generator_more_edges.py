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
    _write(tmp_path / "app" / "be.py", "def f():\n    try:\n        pass\n    except:\n        pass\n")
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
