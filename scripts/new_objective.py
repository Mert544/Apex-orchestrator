#!/usr/bin/env python3
"""Scaffold a new self-registering develop objective — the 3-file pattern.

The auto-registry (app/engine/develop_registry.py) lets a develop objective ship
as ONE self-contained set of files with no hub edit. This stamps that set out
from the canonical template so every objective is created uniformly and a new
contributor (human or agent) starts from a working, discoverable skeleton
instead of copying an existing module by hand:

    python scripts/new_objective.py collapse-foo
    python scripts/new_objective.py collapse-foo --summary "collapse foo into bar"

It writes three files (refusing to overwrite):
  - app/execution/<snake>.py             the plan_<snake> transform (no-op stub)
  - app/execution/objectives/<snake>.py  the self-registering ObjectiveSpec
  - tests/test_<snake>.py                 skeleton tests incl. self-registration

The skeleton is a registered NO-OP: it discovers and grades at fitness 0 until
you fill in the rewrite. Fill in the TODO in the transform, following the house
pattern in app/execution/bool_return.py, then run `python scripts/verify.py`.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def to_snake(name: str) -> str:
    return name.replace("-", "_")


def to_title(name: str) -> str:
    return name.replace("-", " ")


def render_transform(name: str, summary: str) -> str:
    snake = to_snake(name)
    return f'''"""{to_title(name)} — {summary}.

TODO: implement the rewrite. This skeleton returns an empty (no-op) plan, so the
objective is registered and discoverable but lands no moves until it is filled
in. Follow the house pattern in app/execution/bool_return.py: read -> ast.parse
-> collect line/column-span rewrites -> apply (bottom-up) -> re-parse-or-block.

Deterministic, stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_{snake}"]


def _is_fixture_path(path: str) -> bool:
    """Example/fixture/test code is excluded as a subject."""
    p = path.replace("\\\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


def plan_{snake}(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the single-module {name} plan, or its blockers. An empty plan
    (no new_contents, no blockers) means nothing matched — a no-op, not a
    failure."""
    plan = RenamePlan(old=module_rel, new="{name}")
    if _is_fixture_path(module_rel):
        return plan
    path = Path(project_root) / module_rel
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        plan.blockers.append(f"cannot read {{module_rel}}")
        return plan
    try:
        ast.parse(source)
    except SyntaxError as e:
        plan.blockers.append(f"{{module_rel}} doesn't parse: {{e}}")
        return plan

    # TODO: detect the target shape and build `new_source`, then:
    #   try:
    #       ast.parse(new_source)
    #   except SyntaxError as e:
    #       plan.blockers.append(f"{{module_rel}}: would not re-parse ({{e}})")
    #       return plan
    #   plan.originals[module_rel] = source
    #   plan.new_contents[module_rel] = new_source
    #   plan.edits_by_file[module_rel] = <count>
    return plan  # empty no-op until implemented
'''


def render_spec(name: str) -> str:
    snake = to_snake(name)
    return f'''"""Self-registering objective: {name}.

The transform lives in :mod:`app.execution.{snake}`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective {name}` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.objective_compiler import _own_modules
    from app.execution.{snake} import plan_{snake}

    return [rel for rel, _src in _own_modules(project_root)
            if plan_{snake}(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still match {name} (lower is better)."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.{snake} import plan_{snake}

    return [Move(
        operator="{snake}",
        target=f"{{rel}}:{name}",
        description=f"apply {name} in {{rel}}",
        build_plan=lambda r=rel: plan_{snake}(project_root, r),
    ) for rel in _modules(project_root)]


register(ObjectiveSpec(name="{name}", fitness=fitness, moves=moves))
'''


def render_test(name: str) -> str:
    snake = to_snake(name)
    return f'''from __future__ import annotations

from app.execution.{snake} import plan_{snake}


def _project(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("x = 1\\n", encoding="utf-8")
    return tmp_path


def test_noop_on_clean_module(tmp_path):
    _project(tmp_path)
    plan = plan_{snake}(str(tmp_path), "app/m.py")
    assert not plan.new_contents and not plan.blockers  # empty no-op, not a failure


def test_missing_module_blocks(tmp_path):
    plan = plan_{snake}(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_fixture_subject_is_skipped(tmp_path):
    plan = plan_{snake}(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "{name}" in available_objectives()  # discovered via the registry


# TODO: once the transform is implemented, add a real before/after test that
# builds a tmp project matching the target shape and asserts plan.new_contents
# rewrites it (and that the result re-parses).
'''


def target_paths(name: str) -> tuple[Path, Path, Path]:
    snake = to_snake(name)
    return (
        ROOT / "app" / "execution" / f"{snake}.py",
        ROOT / "app" / "execution" / "objectives" / f"{snake}.py",
        ROOT / "tests" / f"test_{snake}.py",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scaffold a new develop objective")
    parser.add_argument("name", help="objective name in kebab-case, e.g. collapse-foo")
    parser.add_argument("--summary", default="",
                        help="one-line description for the docstring")
    args = parser.parse_args(argv)

    name = args.name.strip()
    if not _NAME_RE.match(name):
        print(f"⛔ '{name}' is not a valid kebab-case objective name "
              "(lowercase letters/digits/hyphens, e.g. collapse-foo)")
        return 2

    transform_p, spec_p, test_p = target_paths(name)
    existing = [p for p in (transform_p, spec_p, test_p) if p.exists()]
    if existing:
        print("⛔ refusing to overwrite existing file(s):")
        for p in existing:
            print(f"   {p.relative_to(ROOT)}")
        return 1

    summary = args.summary or f"the {name} develop move"
    transform_p.write_text(render_transform(name, summary), encoding="utf-8")
    spec_p.write_text(render_spec(name), encoding="utf-8")
    test_p.write_text(render_test(name), encoding="utf-8")

    print(f"✅ scaffolded objective '{name}' (a registered no-op):")
    for p in (transform_p, spec_p, test_p):
        print(f"   {p.relative_to(ROOT)}")
    print("\nNext: implement the TODO in the transform (see app/execution/bool_return.py),")
    print("then `python scripts/verify.py --chunk 1` and add a real before/after test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
