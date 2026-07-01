"""js_project_profile — the JS/TS PROJECT-SCOPE structural analyzer (rank 5, the
multi-language foundation item). Covers the import/module graph edges, per-module
fan-in / fan-out, jest test->module linkage, and the derived untested-module +
dependency-hub (and untested-hub) signals; determinism (same input -> identical
profile); a mixed TS + JS + mjs project; and the graceful-empty paths (missing /
empty package.json, JS-less tree, nonexistent root).

The graph-building tests spawn the deterministic ``ts_driver`` (they RUN when node
+ global ``typescript`` are present, and gate on that sentinel rather than silently
passing when absent). The resolution / linkage / graceful-empty tests are pure
(no driver) and ALWAYS run.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.execution.js.js_tool import global_node_modules, module_imports
from app.tools.js_project_profile import (
    JsProjectProfile,
    JsProjectProfiler,
    _norm_relposix,
    _test_links_module,
    profile_js_project,
)

# --- environment guard (the driver-spawning path is opt-in by availability) ----


def _node_ok() -> bool:
    """True when ``node`` is on PATH and the global ``typescript`` resolves — the
    minimum for the LLM-free ``ts_driver`` (the ``imports`` command) to run. The
    graph tests gate on THIS rather than skipping silently."""
    if shutil.which("node") is None:
        return False
    nm = global_node_modules()
    return bool(nm) and (Path(nm) / "typescript").is_dir()


_needs_node = pytest.mark.skipif(
    not _node_ok(), reason="node + global typescript not available")


def _write(root: Path, rel: str, src: str) -> None:
    (root / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(src, encoding="utf-8")


def _pkg(root: Path) -> None:
    (root / "package.json").write_text(
        '{ "name": "demo", "version": "1.0.0" }\n', encoding="utf-8")


def _make_project(root: Path) -> None:
    """A small mixed TS+JS+mjs project: a shared ``core`` barrel two modules import
    (the hub), a ``math`` module a jest test links, and an ``orphan`` nobody imports
    or tests. Exercises TS/JS/mjs parsing, ``import``/``require``/dynamic-``import``/
    directory-barrel resolution, and every derived signal."""
    _pkg(root)
    _write(root, "src/core/index.ts",
           "export function core(x: number): number { return x; }\n")
    # a.ts imports the core barrel by DIRECTORY (`./core` -> core/index.ts)
    _write(root, "src/a.ts",
           'import { core } from "./core";\n'
           "export const a = () => core(1);\n")
    # b.js: CJS require of core + a dynamic import of a.ts (both are edges)
    _write(root, "src/b.js",
           'const { core } = require("./core");\n'
           'const lazy = () => import("./a");\n'
           "module.exports.b = () => core(2) + lazy;\n")
    # c.mjs imports the core barrel by EXPLICIT index path + an external package
    _write(root, "src/c.mjs",
           'import { core } from "./core/index.ts";\n'
           'import _ from "lodash";\n'
           "export const c = () => core(3);\n")
    # math.ts: linked by a jest test; imports the util helper
    _write(root, "src/util/helper.ts",
           "export function helper(x: number): number { return x + 1; }\n")
    _write(root, "src/math.ts",
           'import { helper } from "./util/helper";\n'
           "export function add(a: number, b: number): number "
           "{ return helper(a) + b; }\n")
    # orphan.ts: no importer, no test
    _write(root, "src/orphan.ts", "export function orphan() { return 1; }\n")
    # the ONE jest test — links math.ts (imports ../src/math + references `math`)
    _write(root, "__tests__/math.test.ts",
           'import { add } from "../src/math";\n'
           'test("add", () => { expect(add(1, 2)).toBe(3); });\n')


# --- graceful-empty (pure, ALWAYS run — no driver) ----------------------------


def test_missing_package_json_yields_empty_profile(tmp_path: Path):
    # A JS tree with NO package.json fails the single-project gate -> empty profile,
    # and the driver is NEVER spawned (nothing to graph).
    _write(tmp_path, "src/a.ts", 'import { b } from "./b";\nexport const a = 1;\n')
    p = profile_js_project(str(tmp_path))
    assert p.modules == [] and p.dependency_edges == []
    assert p.module_fanin == {} and p.dependency_hubs == []
    assert p.untested_modules == [] and p.hub_untested_modules == []
    assert p.untested_count == 0
    assert p.root == str(tmp_path)  # the profile still reports the root it was given


def test_empty_package_json_still_graceful(tmp_path: Path):
    # An empty package.json exists (the gate passes) but the tree has NO JS/TS
    # module -> empty profile, no crash, no driver spawn.
    (tmp_path / "package.json").write_text("", encoding="utf-8")
    _write(tmp_path, "src/m.py", "def f():\n    return 1\n")
    p = profile_js_project(str(tmp_path))
    assert p.modules == [] and p.dependency_edges == [] and p.module_to_tests == {}


def test_js_less_project_with_package_json_is_empty(tmp_path: Path):
    # A pure-Python project WITH a package.json but no JS sources -> empty profile
    # (the no-op-on-Python guarantee at the project-scope level).
    _pkg(tmp_path)
    _write(tmp_path, "app/mod.py", "def g():\n    return 2\n")
    p = profile_js_project(str(tmp_path))
    assert p == JsProjectProfile(root=str(tmp_path))  # byte-identical empty


def test_nonexistent_root_yields_empty_profile(tmp_path: Path):
    p = profile_js_project(str(tmp_path / "does_not_exist"))
    assert p.modules == [] and p.dependency_edges == []


# --- pure resolution / linkage helpers (ALWAYS run — no driver) ---------------


def test_norm_relposix_collapses_and_rejects_escape():
    assert _norm_relposix("src/./a") == "src/a"
    assert _norm_relposix("src/util/../a") == "src/a"
    assert _norm_relposix("a/b/../../c") == "c"
    assert _norm_relposix("../escape") is None  # escapes the root
    assert _norm_relposix("") is None
    assert _norm_relposix("./") is None


def test_resolution_candidates_ordering_and_index_barrel():
    # From `src/a.ts` importing `./core`: verbatim, each extension, then the barrel.
    cands = JsProjectProfiler._resolution_candidates(Path("src/a.ts").parent, "./core")
    assert cands[0] == "src/core"  # verbatim first
    assert "src/core.ts" in cands and "src/core.js" in cands  # extension candidates
    assert "src/core/index.ts" in cands  # the directory barrel
    # .ts is tried before .js (TS wins over a co-located build artifact)
    assert cands.index("src/core.ts") < cands.index("src/core.js")


def test_test_links_module_requires_import_and_reference():
    text = ('import { add } from "../src/math";\n'
            'test("add", () => { expect(add(1,2)).toBe(3); });\n').lower()
    assert _test_links_module(text, "math")  # imports math + references it
    # a test that imports a DIFFERENT module does not link `math`
    other = 'import { sub } from "../src/other";\nsub(1);\n'.lower()
    assert not _test_links_module(other, "math")
    # word-boundary: `math` must not match inside `mathutils`
    boundary = 'import { z } from "../src/mathutils";\nz();\n'.lower()
    assert not _test_links_module(boundary, "math")
    assert not _test_links_module(text, "")  # empty stem never links


# --- the import graph + fan-in/out (needs node) -------------------------------


@_needs_node
def test_module_imports_reads_all_specifier_forms(tmp_path: Path):
    _pkg(tmp_path)
    _write(tmp_path, "src/x.ts",
           'import a from "./a";\n'
           'import { b } from "../pkg/b";\n'
           'export { c } from "./c";\n'
           'const fs = require("fs");\n'
           'const dyn = () => import("./dyn");\n')
    specs = module_imports(tmp_path, "src/x.ts")
    # sorted, de-duplicated, covers import / re-export / require / dynamic-import
    assert specs == ["../pkg/b", "./a", "./c", "./dyn", "fs"]


@_needs_node
def test_module_imports_none_on_parse_error_vs_empty_on_no_imports(tmp_path: Path):
    _pkg(tmp_path)
    _write(tmp_path, "broken.ts", "export function ( {\n")  # syntax error
    assert module_imports(tmp_path, "broken.ts") is None  # None, not []
    _write(tmp_path, "clean.ts", "export const x = 1;\n")  # parses, no imports
    assert module_imports(tmp_path, "clean.ts") == []  # [], distinct from None


@_needs_node
def test_import_graph_edges_and_external_split(tmp_path: Path):
    _make_project(tmp_path)
    p = profile_js_project(str(tmp_path))
    # every INTERNAL resolved edge (importer, imported), sorted; barrel + dynamic +
    # require + relative all resolved; the external `lodash` is NOT an edge.
    assert p.dependency_edges == [
        ("src/a.ts", "src/core/index.ts"),          # ./core (directory barrel)
        ("src/b.js", "src/a.ts"),                    # import("./a") dynamic edge
        ("src/b.js", "src/core/index.ts"),           # require("./core")
        ("src/c.mjs", "src/core/index.ts"),          # ./core/index.ts explicit
        ("src/math.ts", "src/util/helper.ts"),       # ./util/helper
    ]
    assert p.external_dependencies == ["lodash"]  # the one bare package (from c.mjs)


@_needs_node
def test_fan_in_and_fan_out(tmp_path: Path):
    _make_project(tmp_path)
    p = profile_js_project(str(tmp_path))
    # core/index.ts is imported by a.ts, b.js, c.mjs -> fan-in 3 (the hub); a.ts is
    # dynamically imported by b.js -> fan-in 1; helper by math -> 1.
    assert p.module_fanin == {
        "src/a.ts": 1,
        "src/core/index.ts": 3,
        "src/util/helper.ts": 1,
    }
    # fan-out: the internal modules each importer pulls, sorted.
    assert p.module_fanout["src/b.js"] == ["src/a.ts", "src/core/index.ts"]
    assert p.module_fanout["src/a.ts"] == ["src/core/index.ts"]
    assert p.module_fanout["src/math.ts"] == ["src/util/helper.ts"]
    # orphan imports nothing -> not a fan-out key
    assert "src/orphan.ts" not in p.module_fanout


@_needs_node
def test_dependency_hub_and_untested_hub_signals(tmp_path: Path):
    _make_project(tmp_path)
    p = profile_js_project(str(tmp_path))
    # only core/index.ts clears the fan-in >= 2 hub floor.
    assert p.dependency_hubs == ["src/core/index.ts"]
    # the hub has no linked test -> it is the highest-leverage untested-hub target.
    assert p.hub_untested_modules == [{"module": "src/core/index.ts", "fan_in": 3}]


@_needs_node
def test_jest_test_to_module_linkage(tmp_path: Path):
    _make_project(tmp_path)
    p = profile_js_project(str(tmp_path))
    # the ONE jest test links exactly math.ts (imports ../src/math + references it).
    assert p.module_to_tests["src/math.ts"] == ["__tests__/math.test.ts"]
    assert p.test_files == ["__tests__/math.test.ts"]
    # every other module is unlinked.
    for mod in ("src/a.ts", "src/b.js", "src/c.mjs", "src/core/index.ts",
                "src/orphan.ts", "src/util/helper.ts"):
        assert p.module_to_tests[mod] == []


@_needs_node
def test_untested_modules_and_true_count(tmp_path: Path):
    _make_project(tmp_path)
    p = profile_js_project(str(tmp_path))
    # every module except math.ts is untested (6 of 7); the display list is capped
    # at 5 while untested_count carries the TRUE total.
    assert "src/math.ts" not in p.untested_modules
    assert p.untested_count == 6
    assert len(p.untested_modules) == 5  # capped display
    assert p.untested_modules == sorted(p.untested_modules)  # sorted


@_needs_node
def test_profile_is_deterministic(tmp_path: Path):
    _make_project(tmp_path)
    first = profile_js_project(str(tmp_path))
    second = profile_js_project(str(tmp_path))
    # same input -> byte-identical profile (the determinism invariant).
    assert first == second


@_needs_node
def test_ts_and_js_files_both_parsed(tmp_path: Path):
    # A minimal TWO-language project: one .ts and one .js, the .js importing the .ts.
    _pkg(tmp_path)
    _write(tmp_path, "lib.ts", "export function lib() { return 1; }\n")
    _write(tmp_path, "use.js", 'const { lib } = require("./lib");\nmodule.exports.u = () => lib();\n')
    p = profile_js_project(str(tmp_path))
    assert set(p.modules) == {"lib.ts", "use.js"}  # both languages discovered
    assert p.dependency_edges == [("use.js", "lib.ts")]  # cross-language edge resolved
    assert p.module_fanin == {"lib.ts": 1}


@_needs_node
def test_dangling_relative_import_is_not_an_edge(tmp_path: Path):
    # A relative import of a module that does not exist resolves to nothing -> it is
    # neither an internal edge NOR an external dependency (refuse-on-uncertainty).
    _pkg(tmp_path)
    _write(tmp_path, "a.ts", 'import { gone } from "./missing";\nexport const a = 1;\n')
    p = profile_js_project(str(tmp_path))
    assert p.dependency_edges == []
    assert p.external_dependencies == []  # a dangling relative is NOT external


@_needs_node
def test_test_file_is_not_a_graph_node(tmp_path: Path):
    # The jest test file is a test_files entry, never a module node, and never an
    # import-graph target even though a module could import it.
    _make_project(tmp_path)
    p = profile_js_project(str(tmp_path))
    assert "__tests__/math.test.ts" not in p.modules
    assert all(t != "__tests__/math.test.ts"
               for _s, t in p.dependency_edges)
