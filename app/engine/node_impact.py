"""Node-level impacted-test selection — narrower than whole-FILE impact scope.

``app.engine.test_impact.impacted_test_files`` (reused here, never forked) maps
changed files to the whole test FILES whose imports reach them. That is the
right granularity for the push gate, but on the developer fast loop
(``scripts/verify.py --impacted``) a file with 200 tests reruns all 200 for a
one-symbol change. This module narrows FURTHER, to individual test NODE ids
(``path::test_fn`` / ``path::Class::test_method``), *strictly opt-in* and
*fail-closed*: narrowing only ever DROPS a node the AST can PROVE is
unrelated to the change. Anything it cannot prove — a star import, a literal
dynamic import, risky module-level OR class-body code, an unanalyzable
reference (getattr with a string, exec/eval/globals/locals, a starred
expression, a filtering comprehension), or an undefined (conftest) fixture —
sends the WHOLE file to ``fallback_files`` instead — and so does a file that
narrows to zero node ids: a file the file-level gate marked covering can
never simply vanish from both ``node_ids`` and ``fallback_files``. Never-
fake-green applies to node narrowing too.

Per-node matching compares a node's reference CLOSURE (the bound identifiers
its body uses, e.g. ``plan_ascend``, ``changed``) against the locally-bound
names of imports whose SOURCE reaches the change — never against the
change's dotted module path directly, since a closure never contains a
dotted path and so could never intersect one for a symbol reached only
transitively (``from app.engine.ascend import plan_ascend`` binds
``plan_ascend``, never ``app.engine.ascend``). See ``_risky_bound_names``.

Deterministic, stdlib-only. Not the push gate; not wired into the per-move
apply verifier — those keep running whole covering test files.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

__all__ = ["impacted_test_nodes"]

# Fixture names pytest (or common plugins) inject without any in-file
# definition — requesting one of these is never an "undefined conftest
# fixture", so it must not force a whole-file fallback.
_BUILTIN_FIXTURES = frozenset({
    "self", "cls", "request", "tmp_path", "tmp_path_factory", "tmpdir",
    "tmpdir_factory", "capsys", "capfd", "capsysbinary", "capfdbinary",
    "monkeypatch", "recwarn", "caplog", "pytestconfig", "cache",
    "doctest_namespace", "record_property", "record_testsuite_property",
    "record_xml_attribute", "testdir", "benchmark",
})

# Calls whose presence anywhere in a node's body makes its reference set
# unanalyzable — never best-effort parsed past these.
_UNANALYZABLE_CALLS = frozenset({"exec", "eval", "globals", "locals"})

_SAFE_TOPLEVEL = (ast.Import, ast.ImportFrom, ast.FunctionDef,
                 ast.AsyncFunctionDef, ast.ClassDef)


def impacted_test_nodes(root: str | Path,
                        changed_rel_files: Iterable[str],
                        ) -> tuple[list[str], list[str]]:
    """Node ids and fallback whole-files for ``changed_rel_files`` — the
    node-level refinement of :func:`app.engine.test_impact.impacted_test_files`.

    Returns ``(node_ids, fallback_files)``, both sorted and deterministic.
    ``node_ids`` are ``"rel::qualname"`` pytest node ids that the AST can
    PROVE are unrelated-to-nothing-else (their same-file reference closure
    hits the changed module). ``fallback_files`` are impacted test files where
    narrowing was not safe (or not attempted) — the WHOLE file must still run.
    A changed file that is itself a test file always lands in
    ``fallback_files`` (there is no target set to narrow its own change by).
    """
    from app.engine.mutation_tester import _import_targets, _under_any
    from app.engine.import_reach import reaching_import_names
    from app.engine.test_impact import impacted_test_files, _is_test_file

    project_root = Path(root)
    changed = [Path(rel).as_posix() for rel in changed_rel_files]
    changed_set = set(changed)
    impacted = impacted_test_files(project_root, changed)

    # ``targets`` stays the BROAD set (ancestor-prefix-decomposed) used only
    # to GATE whether a file is even attempted for narrowing, and to trip the
    # star/dynamic-import/risky-code whole-file fallbacks — over-triggering
    # any of those is always the safe direction. ``reaching`` is the NARROW,
    # atomic set (each entry a real module's own dotted name, never
    # decomposed into ancestor prefixes) used for the actual per-node
    # bound-name match — decomposed ancestor prefixes are not attributable to
    # a specific in-file name reference (the same soundness risk that already
    # excludes package-prefix hits below).
    targets: set[str] = set()
    reaching: set[str] = set()
    prefixes: set[str] = set()
    for rel in changed:
        if _is_test_file(rel):
            continue
        targets |= _import_targets(project_root, rel)
        reached, pkg_prefixes = reaching_import_names(project_root, rel)
        targets |= reached
        reaching |= reached
        prefixes.update(pkg_prefixes)
    prefixes_tuple = tuple(sorted(prefixes))

    node_ids: list[str] = []
    fallback_files: list[str] = []
    for rel in impacted:
        narrowed = _try_narrow(project_root, rel, changed_set, targets,
                               reaching, prefixes_tuple, _under_any)
        # A file that narrows to an EMPTY list is treated identically to
        # ``None`` (unproven, not "proven unrelated") — the safety floor: a
        # file the file-level gate marked covering must never silently
        # vanish from both lists.
        if not narrowed:
            fallback_files.append(rel)
        else:
            node_ids.extend(narrowed)
    return sorted(node_ids), sorted(fallback_files)


def _try_narrow(project_root: Path, rel: str, changed_set: set[str],
                targets: set[str], reaching: set[str],
                prefixes: tuple[str, ...], under_any) -> list[str] | None:
    """Attempt node narrowing for one impacted file, or ``None`` for
    whole-file fallback. A file changed directly, or whose own imports don't
    land an EXACT target hit (only a package-prefix hit, or no hit at all —
    e.g. it was pulled in only via conftest-fixture expansion), is never
    narrowed — soundness risk 3: prefix/package semantics are not attributable
    to a specific in-file name reference. ``targets`` (broad) only gates
    whether narrowing is attempted; ``reaching`` (narrow, atomic dotted
    module names) is what per-node bound-name matching actually uses."""
    from app.engine.mutation_tester import _imported_names

    if rel in changed_set:
        return None
    try:
        tree = ast.parse((project_root / rel).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    imported = _imported_names(tree)
    if not (imported & targets) or under_any(imported, prefixes):
        return None
    return _narrow_file(project_root, rel, targets, reaching, prefixes, tree,
                        under_any)


def _narrow_file(root: Path, rel: str, targets: set[str], reaching: set[str],
                 pkg_prefixes: tuple[str, ...], tree: ast.Module,
                 under_any) -> list[str] | None:
    """Node ids for one impacted file, or ``None`` for whole-file fallback —
    the fail-closed gate plus the transitive same-file closure per node,
    matched against the file's own RISKY BOUND NAMES (see
    ``_risky_bound_names``) rather than against ``targets`` directly."""
    if (_has_star_import_of(tree, targets, pkg_prefixes)
            or _has_dynamic_import_of(tree, targets)
            or _has_risky_module_code(tree)
            or _has_risky_class_body(tree)):
        return None
    risky = _risky_bound_names(tree, reaching, pkg_prefixes, under_any)
    if not risky:
        # No import in this file can be attributed to the change at all
        # (e.g. the file was pulled in only via an unattributable linkage
        # such as conftest expansion) — unprovable, not proven-unrelated.
        return None
    helper_defs = _helper_defs(tree)
    fixture_defs, autouse_names = _fixture_info(tree)
    autouse_refs: set[str] = set()
    for name in sorted(autouse_names):
        fdef = helper_defs.get(name)
        if fdef is None:
            return None
        refs = _closure(fdef, helper_defs, fixture_defs)
        if refs is None:
            return None
        autouse_refs.update(refs)

    nodes = _test_nodes(tree, helper_defs)
    if nodes is None:
        return None
    node_ids: list[str] = []
    for qualname, func, class_decorators in nodes:
        closure = _closure(func, helper_defs, fixture_defs, class_decorators)
        if closure is None:
            return None
        closure = closure | autouse_refs
        if closure & risky:
            node_ids.append(f"{rel}::{qualname}")
    return sorted(node_ids)


def _test_nodes(tree: ast.Module, helper_defs: dict[str, ast.AST],
                ) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef,
                                tuple[ast.expr, ...]]] | None:
    """Top-level ``test_*`` functions and ``Test*`` class methods — pytest's
    own default discovery shape — as ``(qualname, node, class_decorators)``
    triples. ``test_*`` methods a class inherits from a same-file base are
    included too (qualified under the SUBCLASS name, matching how pytest
    actually collects them — subclass overrides win by name). A class with a
    base that cannot be resolved in-file cannot be proven to add no further
    ``test_*`` methods, so ``None`` is returned to force whole-file
    fallback."""
    out: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef,
                    tuple[ast.expr, ...]]] = []
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name.startswith("test_"):
                out.append((item.name, item, ()))
        elif isinstance(item, ast.ClassDef) and item.name.startswith("Test"):
            methods = _class_test_methods(item, helper_defs, frozenset())
            if methods is None:
                return None
            for name, member in methods:
                out.append((f"{item.name}::{name}", member,
                            tuple(item.decorator_list)))
    return out


def _class_test_methods(cls: ast.ClassDef, helper_defs: dict[str, ast.AST],
                        seen: frozenset[int],
                        ) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] | None:
    """``(name, node)`` pairs for ``test_*`` methods defined directly on
    ``cls`` plus (recursively) any inherited from same-file base classes —
    subclass definitions win over inherited ones of the same name, matching
    Python's own MRO shadowing. A base that is not a same-file ``ClassDef``
    (an import, a dynamic expression, anything but bare ``object``) cannot be
    proven to contribute no more test methods, so ``None`` propagates to
    force fallback."""
    if id(cls) in seen:
        return []
    seen = seen | {id(cls)}
    inherited: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id == "object":
            continue
        if not isinstance(base, ast.Name) or base.id not in helper_defs:
            return None
        base_def = helper_defs[base.id]
        if not isinstance(base_def, ast.ClassDef):
            return None
        base_methods = _class_test_methods(base_def, helper_defs, seen)
        if base_methods is None:
            return None
        inherited.update(base_methods)
    inherited.update({
        member.name: member for member in cls.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
        and member.name.startswith("test_")
    })
    return sorted(inherited.items())


def _helper_defs(tree: ast.Module) -> dict[str, ast.AST]:
    """Module-level ``def``/``class`` bodies keyed by name — candidates for a
    node's transitive same-file closure (helpers AND fixtures alike)."""
    return {
        item.name: item
        for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _fixture_info(tree: ast.Module) -> tuple[set[str], set[str]]:
    """``(defined_fixture_names, autouse_fixture_names)`` among module-level
    functions decorated ``@pytest.fixture`` / ``@fixture`` (bare or called)."""
    defined: set[str] = set()
    autouse: set[str] = set()
    for item in tree.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in item.decorator_list:
            is_fixture, is_autouse = _decorator_is_fixture(dec)
            if is_fixture:
                defined.add(item.name)
                if is_autouse:
                    autouse.add(item.name)
    return defined, autouse


def _decorator_is_fixture(dec: ast.AST) -> tuple[bool, bool]:
    """Whether a decorator node is a pytest fixture marker, and whether it
    carries ``autouse=True``."""
    if isinstance(dec, ast.Call):
        callee = dec.func
        autouse = any(
            kw.arg == "autouse" and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in dec.keywords)
    else:
        callee = dec
        autouse = False
    name = (callee.attr if isinstance(callee, ast.Attribute)
            else callee.id if isinstance(callee, ast.Name) else None)
    return name == "fixture", autouse


def _fixture_params(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Parameter names of a test/fixture function — the fixtures it
    requests — excluding ``self``/``cls``."""
    a = func.args
    names = ([arg.arg for arg in a.posonlyargs] + [arg.arg for arg in a.args]
              + [arg.arg for arg in a.kwonlyargs])
    return [n for n in names if n not in ("self", "cls")]


def _parametrize_indirect(dec: ast.Call) -> bool | set[str] | None:
    """The resolved ``indirect=`` keyword of a ``parametrize`` decorator call:
    ``True``/``False`` for a literal bool, a ``set`` of literal string names
    for an ``indirect=[...]`` list/tuple, ``False`` when the keyword is
    absent, or ``None`` when its form cannot be resolved statically (a
    variable, a call, a non-literal element, ...). ``None`` is the
    conservative case — callers must NOT treat any of that decorator's names
    as literal parametrize values when it occurs, since some of them may in
    fact be genuine (indirect) fixture requests."""
    for kw in dec.keywords:
        if kw.arg != "indirect":
            continue
        val = kw.value
        if isinstance(val, ast.Constant) and isinstance(val.value, bool):
            return val.value
        if isinstance(val, (ast.List, ast.Tuple, ast.Set)):
            names: set[str] = set()
            for elt in val.elts:
                if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
                    return None
                names.add(elt.value)
            return names
        return None
    return False


def _parametrize_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Argument names supplied by ``@pytest.mark.parametrize("a,b", ...)`` AS
    LITERAL VALUES — these are decorator-supplied values, not fixture
    requests, so a matching parameter must not be treated as an undefined
    conftest fixture. A name marked ``indirect=True`` (or listed in an
    ``indirect=[...]``) is a genuine fixture request instead — pytest calls
    the same-named fixture with ``request.param`` — so it is excluded here
    and left subject to the normal undefined-fixture check. When the
    ``indirect=`` form itself cannot be resolved statically, NO name from
    that decorator is treated as a safe literal (fail-closed: better to
    over-flag a fixture-shaped name than silently miss a real one)."""
    names: set[str] = set()
    for dec in func.decorator_list:
        names.update(_parametrize_literal_names(dec))
    return names


def _parametrize_literal_names(dec: ast.expr) -> set[str]:
    """Literal-value argument names of ONE ``@pytest.mark.parametrize(...)``
    decorator call — empty when ``dec`` is not a parametrize call, its
    arg-name string cannot be read, or ``indirect=`` excludes all of them
    (a name request, not a literal value; see ``_parametrize_indirect``)."""
    if not isinstance(dec, ast.Call) or not dec.args:
        return set()
    callee = dec.func
    if not (isinstance(callee, ast.Attribute) and callee.attr == "parametrize"):
        return set()
    first = dec.args[0]
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        return set()
    arg_names = {n.strip() for n in first.value.split(",") if n.strip()}
    indirect = _parametrize_indirect(dec)
    if indirect is True or indirect is None:
        return set()
    if isinstance(indirect, set):
        arg_names -= indirect
    return arg_names


def _usefixtures_names(decorators: Iterable[ast.expr]) -> tuple[set[str], bool]:
    """Fixture names requested via ``@pytest.mark.usefixtures(...)`` anywhere
    in ``decorators`` (a function's own decorators, or its enclosing test
    class's), and whether an unresolvable (non-string-literal) argument was
    seen. An unresolvable argument means the requested set cannot be
    determined statically — callers must treat that as unanalyzable, not as
    "no extra fixtures requested"."""
    names: set[str] = set()
    unresolved = False
    for dec in decorators:
        if not isinstance(dec, ast.Call):
            continue
        callee = dec.func
        attr = callee.attr if isinstance(callee, ast.Attribute) else None
        if attr != "usefixtures":
            continue
        for arg in dec.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                names.add(arg.value)
            else:
                unresolved = True
    return names, unresolved


def _requested_fixture_names(func: ast.FunctionDef | ast.AsyncFunctionDef,
                             class_decorators: Iterable[ast.expr],
                             ) -> set[str] | None:
    """Every fixture ``func`` requests: its signature parameters plus any
    ``@pytest.mark.usefixtures(...)`` names from its own decorators and (for
    a test method) its enclosing class's decorators. ``None`` when a
    ``usefixtures(...)`` argument is not a string literal — the requested set
    cannot be proven, so the caller must fall back rather than guess."""
    func_names, func_unresolved = _usefixtures_names(func.decorator_list)
    class_names, class_unresolved = _usefixtures_names(class_decorators)
    if func_unresolved or class_unresolved:
        return None
    return set(_fixture_params(func)) | func_names | class_names


def _undefined_fixture_names(requested: set[str],
                             func: ast.FunctionDef | ast.AsyncFunctionDef,
                             fixture_defs: set[str]) -> set[str]:
    """Requested fixture names that name neither a same-file fixture, a
    pytest/plugin builtin, nor a parametrize literal — i.e. a conftest
    fixture this file does not define. Any hit forces whole-file fallback
    (never silently dropped as "unrelated")."""
    skip = _parametrize_names(func)
    return {p for p in requested
            if p not in fixture_defs and p not in _BUILTIN_FIXTURES and p not in skip}


def _referenced_names(node: ast.AST) -> set[str] | None:
    """Names a node's own body references — ``ast.Name`` loads and
    ``ast.Attribute`` roots — or ``None`` when unanalyzable: a starred
    expression, a filtering comprehension, or a call to ``getattr`` with a
    string literal / ``exec``/``eval``/``globals``/``locals`` anywhere inside.
    Decorator arguments (parametrize string exprs included) are covered too —
    ``ast.walk`` visits ``decorator_list`` like any other child field."""
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Starred):
            return None
        if (isinstance(sub, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
                and any(gen.ifs for gen in sub.generators)):
            return None
        if isinstance(sub, ast.Call) and _is_unanalyzable_call(sub):
            return None
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            names.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            root = _attribute_root(sub)
            if root is not None:
                names.add(root)
    return names


def _is_unanalyzable_call(call: ast.Call) -> bool:
    """``exec``/``eval``/``globals``/``locals`` (any callable spelling), or
    ``getattr(obj, "literal")`` — a dynamic attribute lookup a static AST scan
    cannot resolve to a name."""
    func = call.func
    callee = (func.id if isinstance(func, ast.Name)
              else func.attr if isinstance(func, ast.Attribute) else None)
    if callee in _UNANALYZABLE_CALLS:
        return True
    if callee == "getattr":
        return any(isinstance(a, ast.Constant) and isinstance(a.value, str)
                   for a in call.args)
    return False


def _attribute_root(node: ast.Attribute) -> str | None:
    """The base ``Name`` of a (possibly chained) attribute access."""
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        cur = cur.value
    return cur.id if isinstance(cur, ast.Name) else None


def _closure(node: ast.AST, helper_defs: dict[str, ast.AST],
            fixture_defs: set[str],
            class_decorators: Iterable[ast.expr] = ()) -> set[str] | None:
    """Transitive same-file reference closure of ``node``: its own referenced
    names, plus (recursively) the closures of any same-file helper it calls
    by name and any same-file fixture it requests (by parameter, or via
    ``@pytest.mark.usefixtures(...)`` on itself or — for ``node`` itself, if
    it is a test method — its enclosing class). ``None`` propagates up on any
    unanalyzable member or undefined (conftest) fixture."""
    out: set[str] = set()
    seen: set[str] = set()
    stack: list[ast.AST] = [node]
    while stack:
        cur = stack.pop()
        refs = _referenced_names(cur)
        if refs is None:
            return None
        out.update(refs)
        for name in refs:
            if name in helper_defs and name not in seen:
                seen.add(name)
                stack.append(helper_defs[name])
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cls_decs = class_decorators if cur is node else ()
            additions = _fixture_stack_additions(cur, cls_decs, helper_defs,
                                                 fixture_defs, seen)
            if additions is None:
                return None
            stack.extend(additions)
    return out


def _fixture_stack_additions(func: ast.FunctionDef | ast.AsyncFunctionDef,
                             class_decorators: Iterable[ast.expr],
                             helper_defs: dict[str, ast.AST],
                             fixture_defs: set[str],
                             seen: set[str]) -> list[ast.AST] | None:
    """Same-file fixture defs to push onto :func:`_closure`'s traversal stack
    for ``func``'s requested fixtures (marking each pushed name in ``seen``),
    or ``None`` when a request is unanalyzable or names an undefined
    (conftest) fixture — the caller must fall back rather than drop it."""
    requested = _requested_fixture_names(func, class_decorators)
    if requested is None or _undefined_fixture_names(requested, func, fixture_defs):
        return None
    additions: list[ast.AST] = []
    for p in sorted(requested):
        fdef = helper_defs.get(p)
        if p in fixture_defs and p not in seen and fdef is not None:
            seen.add(p)
            additions.append(fdef)
    return additions


def _risky_bound_names(tree: ast.Module, reaching: set[str],
                       prefixes: tuple[str, ...], under_any) -> set[str]:
    """Locally-bound identifiers introduced by an import whose SOURCE reaches
    the change — the sound basis for per-node matching.

    ``reaching`` holds the changed module's own dotted path plus every module
    that (transitively) imports it, each an ATOMIC dotted name — never
    decomposed into ancestor prefixes, so a coarse parent-package import
    cannot spuriously mark an unrelated sibling import's bound name as risky.
    A node's closure (:func:`_closure`) holds the NAMES its body references,
    not dotted import paths, so comparing a closure against dotted names
    directly can never intersect for a transitively-reached symbol — this
    bridges the two: for each import statement, the name it actually binds in
    the file's namespace, kept only when the imported source reaches the
    change: for ``import a.b [as c]``, the attribute root ``a`` (or the
    asname ``c``); for ``from M import x [as y]``, the asname ``y`` (or
    ``x``) when either ``M`` itself or the specific member ``M.x`` reaches
    the change (``M`` alone covers a package whose own import executes the
    change; ``M.x`` covers ``x`` naming a reaching submodule of ``M``)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= _risky_import_names(node, reaching, prefixes, under_any)
        elif isinstance(node, ast.ImportFrom):
            names |= _risky_import_from_names(node, reaching, prefixes, under_any)
    return names


def _risky_import_names(node: ast.Import, reaching: set[str],
                        prefixes: tuple[str, ...], under_any) -> set[str]:
    """Bound names from a plain ``import a.b [as c]`` whose full dotted path
    reaches the change — the attribute root ``a`` (or the asname ``c``)."""
    return {alias.asname or alias.name.split(".")[0]
           for alias in node.names
           if _reaches(alias.name, reaching, prefixes, under_any)}


def _risky_import_from_names(node: ast.ImportFrom, reaching: set[str],
                             prefixes: tuple[str, ...], under_any) -> set[str]:
    """Bound names from ``from M import x [as y]`` when ``M`` itself, or the
    specific member ``M.x``, reaches the change. A relative import has no
    absolute dotted path to match, so it contributes nothing here (the
    file-level gate's own conservative treatment of relative imports already
    covers the fail-closed side of that gap)."""
    if (node.level and node.level > 0) or not node.module:
        return set()
    names: set[str] = set()
    for alias in node.names:
        member = f"{node.module}.{alias.name}"
        if (_reaches(node.module, reaching, prefixes, under_any)
                or _reaches(member, reaching, prefixes, under_any)):
            names.add(alias.asname or alias.name)
    return names


def _reaches(dotted: str, reaching: set[str], prefixes: tuple[str, ...],
            under_any) -> bool:
    """Whether one dotted import source names, or sits under, the changed
    module's reaching set — an exact hit, or a descendant of a reaching
    package (importing it executes that package's ``__init__`` on the way)."""
    return dotted in reaching or under_any({dotted}, prefixes)


def _has_star_import_of(tree: ast.Module, targets: set[str],
                        pkg_prefixes: tuple[str, ...]) -> bool:
    """``from <changed-module> import *`` — every name it defines is opaque
    to a static scan, so the whole file must fall back."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ImportFrom) and node.module and not node.level):
            continue
        if not any(alias.name == "*" for alias in node.names):
            continue
        if node.module in targets or any(
                node.module.startswith(p) for p in pkg_prefixes):
            return True
    return False


def _has_dynamic_import_of(tree: ast.Module, targets: set[str]) -> bool:
    """A literal ``importlib.import_module``/``importorskip``/``__import__``
    of a changed module — the imported names are then opaque to a static scan."""
    from app.engine.mutation_tester import _dynamic_import_arg

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            dynamic = _dynamic_import_arg(node)
            if dynamic and dynamic in targets:
                return True
    return False


_CLASS_SAFE_BODY = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _has_risky_module_code(tree: ast.Module) -> bool:
    """Any top-level statement other than an import, a ``def``/``class``, a
    docstring, or a simple literal assignment — module-level code that could
    COMPUTE test inputs (a call, a loop, an ``if``, ...) makes node-level
    attribution unsound, so the whole file falls back."""
    return _body_is_risky(tree.body, _SAFE_TOPLEVEL)


def _has_risky_class_body(tree: ast.Module) -> bool:
    """Any class body anywhere in the file — a test class, or a same-file
    mixin/helper another test class inherits from — containing a statement
    beyond a def, a nested class, a docstring, or a simple literal
    assignment. A class body executes at IMPORT time exactly like module
    level (``X = compute(...)`` at class scope runs when the module is
    imported), invisibly to any per-node closure, so it forces the same
    whole-file fallback as risky module-level code."""
    return any(isinstance(node, ast.ClassDef)
              and _body_is_risky(node.body, _CLASS_SAFE_BODY)
              for node in ast.walk(tree))


def _body_is_risky(body: list[ast.stmt], safe_types: tuple[type, ...]) -> bool:
    """Shared scan for ``_has_risky_module_code``/``_has_risky_class_body``:
    any statement in ``body`` other than one of ``safe_types``, a docstring,
    or a simple literal assignment is risky — it could COMPUTE a value from
    the changed module invisibly to per-node closures."""
    for stmt in body:
        if isinstance(stmt, safe_types):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            if stmt.value is None or _is_simple_literal(stmt.value):
                continue
        return True
    return False


def _is_simple_literal(node: ast.AST) -> bool:
    """A constant, a signed constant, or a literal container of the same —
    never a call, so it cannot compute a test input from the change."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _is_simple_literal(node.operand)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_simple_literal(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(_is_simple_literal(k) for k in node.keys if k is not None) and all(
            _is_simple_literal(v) for v in node.values)
    return False
