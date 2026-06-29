"""Autonomous-39 W5: the ``incomplete-protocol`` seeder fact is now an EXECUTABLE
eq/hash completion, not a human ``design_task``.

A half-built Python contract used to be devolved to a person ("you decide the
implementation"). The signal covers TWO gap shapes and only ONE is
deterministically completable, so this is a SPLIT-honesty flip:

  * (a) an ``__eq__``-WITHOUT-``__hash__`` class is the CANONICAL gap — defining
    ``__eq__`` implicitly sets ``__hash__ = None`` (instances raise
    ``TypeError: unhashable`` as a ``set`` member / ``dict`` key), and
    ``seal_hashable_eq`` restores the canonical ``def __hash__`` over the SAME
    pure-copy field set ``__eq__`` ranges over (a RUNTIME-ADDITIVE completion that
    re-enables what currently raises, never a ``__hash__`` that disagrees with
    ``__eq__``). So the fact is flipped to the delegated ``seal_hashable_eq``
    action: the bridge strips the ``::Class`` suffix to the own-module rel and lands
    the seal through ``apply_rename(impact_scope=True)`` with auto-rollback.

  * (b) a ``__enter__``/``__exit__`` (or async) CONTEXT-MANAGER gap has NO
    deterministic completion (what does ``__exit__`` release? = a DESIGN decision),
    so it routes to ``seal_hashable_eq``, finds NO eligible eq/hash class, and stays
    an HONEST no-op (empty plan, disclosed reason) — never a fabricated ``__exit__``
    body.

So incomplete-protocol becomes autonomous for the eq/hash gap and stays honest
(advisory) for context-manager gaps.

These tests lock:
  * the flip (action_type ``seal_hashable_eq``, executable True, target is the
    module rel — the ``::Class`` suffix stripped);
  * a real eq-without-hash class LANDS the ``__hash__`` suite GREEN, with the
    ``__hash__`` now defined AND consistent with the ``__eq__`` fields;
  * a CONTEXT-MANAGER-only gap is an HONEST no-op (writes nothing, never
    fake-green) carrying the disclosed reason;
  * the SCOPE note: the lander runs over the MODULE, so it may seal OTHER eligible
    eq/hash classes too — broader but suite-gated + auto-rolled-back;
  * suffix-strip edge cases (``module::Class`` resolves to the module rel; a plain
    module is unchanged) and an unreadable / non-``.py`` target is an empty no-op;
  * the existing idea-types stay byte-identical (only incomplete-protocol flipped).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge, _FACT_ACTIONS
from app.models.idea import IdeaNode

# An eq-without-hash class: a plain ``object`` class with a body ``def __eq__`` and
# NO ``__hash__`` — so its instances are UNHASHABLE until the canonical ``__hash__``
# is restored. The ``__init__`` is a pure ``self.<p> = <p>`` copy set, so the proven
# field set the hash ranges over is ``(self.amount, self.currency)`` — exactly the
# fields ``__eq__`` compares.
_EQ_SRC = (
    "class Money:\n"
    "    def __init__(self, amount, currency):\n"
    "        self.amount = amount\n"
    "        self.currency = currency\n"
    "    def __eq__(self, o):\n"
    "        return (isinstance(o, Money)\n"
    "                and (self.amount, self.currency) == (o.amount, o.currency))\n"
)

# A context-manager-only gap: ``__enter__`` without ``__exit__`` and NO ``__eq__``.
# There is no eq/hash class to seal here, so seal-hashable-eq refuses (an honest
# no-op) — completing the ``__exit__`` is a DESIGN decision, never auto-written.
_CTX_SRC = (
    "class Res:\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def use(self):\n"
    "        return 1\n"
)


def _eq_fields(source: str, cls: str) -> list[str]:
    """The ordered ``self.<p> = <p>`` pure-copy field names of ``cls`` in
    ``source`` — the field set the canonical ``__eq__``/``__hash__`` pair ranges
    over. A local, self-contained read so the "hash agrees with eq" assertion does
    not couple to a private extractor helper."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for stmt in node.body:
                if isinstance(stmt, ast.FunctionDef) and stmt.name == "__init__":
                    out: list[str] = []
                    for asn in stmt.body:
                        if (isinstance(asn, ast.Assign) and len(asn.targets) == 1
                                and isinstance(asn.targets[0], ast.Attribute)
                                and isinstance(asn.targets[0].value, ast.Name)
                                and asn.targets[0].value.id == "self"
                                and isinstance(asn.value, ast.Name)):
                            out.append(asn.targets[0].attr)
                    return out
    raise AssertionError(f"class {cls} not found")


def _hash_tuple_names(source: str, cls: str) -> list[str]:
    """The ``self.<name>`` attributes the landed ``def __hash__`` of ``cls`` hashes
    over (the ``hash((self.a, self.b, ...))`` tuple), in order — so a test can prove
    the restored hash ranges over EXACTLY the ``__eq__`` field set, never a
    disagreeing key."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for stmt in node.body:
                if isinstance(stmt, ast.FunctionDef) and stmt.name == "__hash__":
                    names: list[str] = []
                    for sub in ast.walk(stmt):
                        if (isinstance(sub, ast.Attribute)
                                and isinstance(sub.value, ast.Name)
                                and sub.value.id == "self"):
                            names.append(sub.attr)
                    return names
    raise AssertionError(f"class {cls} has no __hash__")


def _proto_idea(subject: str, protocol: str, have: str, missing: str) -> IdeaNode:
    """An ``incomplete-protocol`` root, exactly as the seeder emits it
    (``idea_seeder._seed_incomplete_protocols``): a ``"<module_rel>::<Class>"``
    subject and the fact label on ``source_facts[0]`` (``_root_action`` reads
    ``fact.split(":")[0]``)."""
    return IdeaNode(
        id="n", title=f"Complete the {protocol} protocol on `{subject}`",
        subject=subject, operator="root",
        source_facts=[f"incomplete-protocol: {subject} ({protocol}: has {have}, "
                      f"missing {missing} — a half-built contract to finish)"],
    )


def _project(root: Path, module_rel: str, source: str,
             test_body: str | None = None) -> None:
    """A minimal importable project carrying ``source`` at ``module_rel``."""
    (root / "app").mkdir(exist_ok=True)
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / module_rel).write_text(source, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    if test_body is not None:
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / "test_m.py").write_text(test_body, encoding="utf-8")


# ── 1. the flip itself: the fact row is now executable ────────────────────────

def test_fact_action_is_executable_seal_hashable_eq():
    action_type, _desc, executable = _FACT_ACTIONS["incomplete-protocol"]
    assert action_type == "seal_hashable_eq"
    assert executable is True


def test_plan_idea_surfaces_executable_seal():
    step = IdeaActionBridge().plan_idea(
        _proto_idea("app/money.py::Money", "equality/hash", "__eq__", "__hash__"))
    assert step.action_type == "seal_hashable_eq"
    assert step.executable is True
    # The subject is "module::Class"; the surfaced target is the own-module rel
    # (the lander strips the suffix), NOT silently dropped to "".
    assert step.target == "app/money.py"
    assert "app/money.py::Money" in step.description


def test_seal_hashable_eq_is_registered_delegated():
    # The flip is only autonomous if the action type actually routes to the
    # delegated apply path — pin both the table entry and the routing frozenset.
    assert "seal_hashable_eq" in IdeaActionBridge._DELEGATED_SYNTHESIS
    assert "seal_hashable_eq" in IdeaActionBridge._DELEGATED_ACTIONS
    lander_name, reason = IdeaActionBridge._DELEGATED_SYNTHESIS["seal_hashable_eq"]
    assert lander_name == "_plan_seal_hashable_eq_lander"
    # The disclosed default reason names BOTH halves of the honesty boundary.
    assert "eq-without-hash" in reason and "context-manager" in reason


# ── 2. it LANDS the __hash__ on a real eq-without-hash class, suite GREEN ──────

def test_applies_and_lands_hash_suite_green(tmp_path: Path):
    _project(
        tmp_path, "app/money.py", _EQ_SRC,
        test_body=("from app.money import Money\n\n"
                   "def test_money():\n"
                   "    assert Money(1, 'usd') == Money(1, 'usd')\n"
                   "    assert hash(Money(1, 'usd')) == hash(Money(1, 'usd'))\n"
                   "    assert len({Money(1, 'usd'), Money(1, 'usd')}) == 1\n"))

    step = IdeaActionBridge().plan_idea(
        _proto_idea("app/money.py::Money", "equality/hash", "__eq__", "__hash__"))
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised",
                                        verify=True)
    assert res["applied"] is True, res
    assert res["transform_type"] == "seal_hashable_eq"
    assert res.get("suite_green") is True
    assert res["changed_files"] == ["app/money.py"]

    after = (tmp_path / "app" / "money.py").read_text()
    # The canonical __hash__ is now DEFINED on the class.
    assert "def __hash__(self)" in after
    # And it is CONSISTENT with __eq__: it hashes EXACTLY the field set __eq__ is
    # built over (the __init__ pure-copy fields) — never a disagreeing key.
    eq_fields = _eq_fields(_EQ_SRC, "Money")
    assert eq_fields == ["amount", "currency"]
    assert _hash_tuple_names(after, "Money") == eq_fields


def test_landed_hash_makes_instances_dict_key_usable(tmp_path: Path):
    # The buyer-visible capability: instances were UNHASHABLE (a hard TypeError as a
    # set member / dict key) and are now usable — and equal instances collide, the
    # canonical eq/hash contract.
    _project(tmp_path, "app/money.py", _EQ_SRC)
    plan = IdeaActionBridge._plan_seal_hashable_eq_lander()(
        str(tmp_path), "app/money.py::Money")
    after = plan.new_contents["app/money.py"]
    ns: dict = {}
    exec(compile(after, "app/money.py", "exec"), ns)
    money = ns["Money"]
    # Before, hash(money(...)) raised TypeError; now it is a dict key and equal
    # instances share a slot.
    seen = {money(1, "usd"): "a"}
    seen[money(1, "usd")] = "b"
    assert seen == {money(1, "usd"): "b"}
    assert hash(money(1, "usd")) == hash(money(1, "usd"))


# ── 3. a CONTEXT-MANAGER-only gap is an HONEST no-op (writes nothing) ──────────

def test_context_manager_gap_is_honest_noop_writes_nothing(tmp_path: Path):
    _project(tmp_path, "app/res.py", _CTX_SRC)
    step = IdeaActionBridge().plan_idea(
        _proto_idea("app/res.py::Res", "context-manager", "__enter__", "__exit__"))
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised",
                                        verify=True)
    assert res["applied"] is False
    assert res["transform_type"] == "seal_hashable_eq"
    # A disclosed reason is carried (no silent success, never a fabricated __exit__).
    assert res.get("reason")
    assert "no protocol completion" in res["reason"]
    # NOTHING was written — the module is byte-identical to before (the __exit__ is
    # NOT auto-synthesized; completing it stays a DESIGN decision).
    assert (tmp_path / "app" / "res.py").read_text() == _CTX_SRC


def test_lander_noop_plan_on_context_manager(tmp_path: Path):
    # The lander itself returns an empty no-op RenamePlan for a context-manager-only
    # module (no eligible eq/hash class), not a fabricated rewrite.
    _project(tmp_path, "app/res.py", _CTX_SRC)
    plan = IdeaActionBridge._plan_seal_hashable_eq_lander()(
        str(tmp_path), "app/res.py::Res")
    assert not plan.new_contents


def test_lander_noop_plan_on_already_hashable(tmp_path: Path):
    # A class that ALREADY defines __hash__ alongside __eq__ is a complete contract
    # — the lander refuses it (idempotent honest no-op), never re-writes the hash.
    src = ("class C:\n"
           "    def __init__(self, x):\n"
           "        self.x = x\n"
           "    def __eq__(self, o):\n"
           "        return isinstance(o, C) and self.x == o.x\n"
           "    def __hash__(self):\n"
           "        return hash(self.x)\n")
    _project(tmp_path, "app/c.py", src)
    plan = IdeaActionBridge._plan_seal_hashable_eq_lander()(
        str(tmp_path), "app/c.py::C")
    assert not plan.new_contents


# ── 4. the SCOPE note: the lander runs over the MODULE (broader but safe) ──────

def test_lander_seals_module_scope_other_classes(tmp_path: Path):
    # The subject names ONE class but the lander runs over the whole module, so a
    # SECOND eligible eq-without-hash class in the same module is sealed too —
    # broader than the named class (suite-gated + auto-rolled-back upstream).
    two = (
        "class A:\n"
        "    def __init__(self, x):\n"
        "        self.x = x\n"
        "    def __eq__(self, o):\n"
        "        return isinstance(o, A) and self.x == o.x\n"
        "\n"
        "class B:\n"
        "    def __init__(self, y):\n"
        "        self.y = y\n"
        "    def __eq__(self, o):\n"
        "        return isinstance(o, B) and self.y == o.y\n"
    )
    _project(tmp_path, "app/m.py", two)
    plan = IdeaActionBridge._plan_seal_hashable_eq_lander()(
        str(tmp_path), "app/m.py::A")
    assert plan.new_contents
    after = plan.new_contents["app/m.py"]
    # BOTH classes gained a __hash__, not just the named one.
    assert _hash_tuple_names(after, "A") == ["x"]
    assert _hash_tuple_names(after, "B") == ["y"]


# ── 5. suffix-strip edge cases + an unreadable / non-.py target ───────────────

def test_strips_class_suffix_to_module_rel(tmp_path: Path):
    # The lander resolves "module::Class" → the module rel (the suffix is dropped),
    # and a plain module target (no "::") is unchanged — both seal identically.
    _project(tmp_path, "app/money.py", _EQ_SRC)
    lander = IdeaActionBridge._plan_seal_hashable_eq_lander()
    via_subject = lander(str(tmp_path), "app/money.py::Money")
    via_module = lander(str(tmp_path), "app/money.py")
    assert via_subject.new_contents == via_module.new_contents
    assert via_module.new_contents  # the eligible module seals


def test_lander_missing_target_is_empty_noop_plan(tmp_path: Path):
    # A module rel that does not exist is unreadable → the single-file lander returns
    # an empty plan (an honest no-op, never a raise). (Unlike the cross-file dedup
    # landers, plan_source_rewrite no-ops silently on an unreadable rel, so the
    # disclosed reason rides the _DELEGATED_SYNTHESIS default downstream.)
    _project(tmp_path, "app/money.py", _EQ_SRC)
    plan = IdeaActionBridge._plan_seal_hashable_eq_lander()(
        str(tmp_path), "app/absent.py::Nope")
    assert not plan.new_contents


def test_lander_dataclass_is_empty_noop_plan(tmp_path: Path):
    # A @dataclass owns its own eq=/hash story, so the refusal set blocks it — the
    # lander no-ops (never overwrites a framework-generated hash).
    src = ("from dataclasses import dataclass\n\n\n"
           "@dataclass\n"
           "class D:\n"
           "    x: int\n"
           "    def __eq__(self, o):\n"
           "        return isinstance(o, D) and self.x == o.x\n")
    _project(tmp_path, "app/d.py", src)
    plan = IdeaActionBridge._plan_seal_hashable_eq_lander()(
        str(tmp_path), "app/d.py::D")
    assert not plan.new_contents


# ── 6. the existing idea-types stay byte-identical (only incomplete-protocol) ──

def test_other_fact_actions_unchanged():
    # Only the incomplete-protocol row's (action_type, executable) flipped; a sample
    # of the neighbouring fact rows must be byte-identical to their pre-flip shape.
    assert _FACT_ACTIONS["coordinator"] == (
        "design_task",
        "Decouple the coordinator module {s} — it imports many "
        "internal modules; split its responsibilities (Apex names "
        "the god-module, you design the seams)", False)
    # god-class was design_task at W5 time; Autonomous-39 W3a later flipped it to
    # the executable promote_staticmethod lander (self-free-method → @staticmethod
    # decoupling; full split stays a design task) — assert that current reality.
    assert _FACT_ACTIONS["god-class"][0] == "promote_staticmethod"
    assert _FACT_ACTIONS["god-class"][2] is True
    # The W2 sibling stays as W2 left it (this wave touches only incomplete-protocol).
    assert _FACT_ACTIONS["deep-nesting"][0] == "extract_guard_clause"
    assert _FACT_ACTIONS["deep-nesting"][2] is True
    # The W1 sibling is untouched too.
    assert _FACT_ACTIONS["generalizable-duplication"][0] == "dedup_parameterized"
    # The polyglot-hotspot recommend-only neighbour is unchanged.
    assert _FACT_ACTIONS["polyglot-hotspot"][0] == "design_task"
    assert _FACT_ACTIONS["polyglot-hotspot"][2] is False
