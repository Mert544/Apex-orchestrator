"""Learn a rewrite rule FROM EXAMPLES — deterministic anti-unification.

``apex teach 'len(xs) == 0' 'not xs'  'len(a.b) == 0' 'not a.b'`` aligns the
two BEFORE expressions structurally; every subtree where they disagree
becomes a ``$v…`` metavariable (the classic anti-unification move), and the
AFTER expressions are generalized the same way — with the constraint that
every hole in the replacement must reuse a value the pattern captured.

No ML, no LLM: the generalization is algebra, and the learned rule is
**self-checked** before it is ever shown — applying it back to each BEFORE
must reproduce the matching AFTER (structurally), or the teach refuses.

One example pair is allowed and yields an exact-match rule (no holes) —
honest, just narrow. Mismatches that can't become an expression hole (two
different operators, say) generalize the nearest enclosing expression; if
that swallows the whole pattern, the examples simply don't share a
structure, and that is a blocker, not a guess.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from app.execution.pattern_rewrite import _match, _render, _MV_PREFIX

__all__ = ["learn_rule", "LearnedRule"]


@dataclass
class LearnedRule:
    pattern: str = ""
    replacement: str = ""
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blockers and bool(self.pattern)


class _MustHole(Exception):
    """A mismatch below expression level — the nearest expr must generalize."""


class _Holes:
    """Capture-pair → metavariable assignment (same pair = same variable)."""

    def __init__(self) -> None:
        self.by_pair: dict[tuple[str, ...], str] = {}

    def name_for(self, segs: tuple[str, ...]) -> str:
        if segs not in self.by_pair:
            self.by_pair[segs] = f"v{len(self.by_pair) + 1}"
        return self.by_pair[segs]


def _hole(nodes: list[ast.AST], sources: list[str], holes: _Holes) -> ast.expr:
    if not all(isinstance(n, ast.expr) for n in nodes):
        raise _MustHole
    segs = tuple(ast.get_source_segment(src, n) or "" for n, src in zip(nodes, sources))
    if any(not s for s in segs):
        raise _MustHole
    return ast.Name(id=f"{_MV_PREFIX}{holes.name_for(segs)}", ctx=ast.Load())


def _generalize_list_field(values: list, sources: list[str], holes: _Holes) -> list:
    """Generalize a list-valued field; raises ``_MustHole`` on a scalar mismatch."""
    if any(not isinstance(v, list) or len(v) != len(values[0]) for v in values):
        raise _MustHole
    items = []
    for group in zip(*values):
        if isinstance(group[0], ast.AST):
            items.append(_generalize(list(group), sources, holes))
        elif any(g != group[0] for g in group):
            raise _MustHole
        else:
            items.append(group[0])
    return items


def _generalize_field(fvalue, values: list, sources: list[str], holes: _Holes):
    """Generalize one field across ``nodes``; raises ``_MustHole`` to force a hole."""
    if isinstance(fvalue, list):
        return _generalize_list_field(values, sources, holes)
    if isinstance(fvalue, ast.AST):
        if any(not isinstance(v, ast.AST) for v in values):
            raise _MustHole
        return _generalize(values, sources, holes)
    if any(v != fvalue for v in values):
        # A scalar mismatch (a Name's id, a Constant's value, an operator
        # choice) can only generalize at expression level.
        raise _MustHole
    return fvalue


def _generalize(nodes: list[ast.AST], sources: list[str], holes: _Holes) -> ast.AST:
    """The common skeleton of ``nodes`` with metavariable holes at mismatches."""
    first = nodes[0]
    if any(type(n) is not type(first) for n in nodes):
        return _hole(nodes, sources, holes)
    try:
        out = type(first)()
        for fname, fvalue in ast.iter_fields(first):
            values = [getattr(n, fname) for n in nodes]
            setattr(out, fname, _generalize_field(fvalue, values, sources, holes))
        return out
    except _MustHole:
        return _hole(nodes, sources, holes)


def _to_display(template_tree: ast.AST) -> str:
    """unparse, with placeholder identifiers back in ``$x`` spelling."""
    return ast.unparse(template_tree).replace(_MV_PREFIX, "$")


def _parse_examples(examples, rule: LearnedRule):
    """Parse every ``(before, after)`` pair; append a blocker and return ``None``
    on the first syntactically invalid example."""
    befores, afters = [], []
    for i, (b, a) in enumerate(examples, 1):
        try:
            befores.append(ast.parse(b, mode="eval").body)
            afters.append(ast.parse(a, mode="eval").body)
        except (SyntaxError, RecursionError, MemoryError):
            rule.blockers.append(f"example {i} is not a pair of valid expressions")
            return None
    return befores, afters


def _learn_pattern(befores, examples, holes: _Holes, rule: LearnedRule):
    """Anti-unify the BEFORE trees; append a blocker and return ``None`` if the
    only shared skeleton is a single bare metavariable."""
    sources = [b for b, _ in examples]
    try:
        pattern_tree = _generalize(list(befores), sources, holes)
    except _MustHole:
        pattern_tree = None
    if pattern_tree is None or (isinstance(pattern_tree, ast.Name)
                                and pattern_tree.id.startswith(_MV_PREFIX)):
        rule.blockers.append(
            "the BEFORE examples don't share a structure — the whole "
            "pattern would be one metavariable, which matches everything")
        return None
    return pattern_tree


def _learn_replacement(afters, examples, holes: _Holes,
                       pattern_pairs, rule: LearnedRule):
    """Anti-unify the AFTER trees reusing the pattern's captures; append a
    blocker and return ``None`` if they don't share a structure or introduce a
    hole the pattern never captured."""
    after_sources = [a for _, a in examples]
    try:
        repl_tree = _generalize(list(afters), after_sources, holes)
    except _MustHole:
        rule.blockers.append("the AFTER examples don't share a structure")
        return None
    if set(holes.by_pair) - pattern_pairs:
        rule.blockers.append(
            "the change uses values the pattern doesn't capture — the "
            "AFTER sides differ where the BEFORE sides agree")
        return None
    return repl_tree


def _generalize_rule(befores, afters, examples, rule: LearnedRule) -> bool:
    """Fill ``rule.pattern``/``rule.replacement`` from multiple examples; return
    ``False`` (with a blocker appended) when generalization fails."""
    holes = _Holes()
    pattern_tree = _learn_pattern(befores, examples, holes, rule)
    if pattern_tree is None:
        return False
    pattern_pairs = set(holes.by_pair)
    repl_tree = _learn_replacement(afters, examples, holes, pattern_pairs, rule)
    if repl_tree is None:
        return False
    rule.pattern = _to_display(pattern_tree)
    rule.replacement = _to_display(repl_tree)
    return True


def _reproduces(replacement: str, after: str, bindings: dict[str, str]) -> bool:
    """Does rendering ``replacement`` with ``bindings`` match ``after`` structurally?"""
    produced = _render(replacement, bindings)
    try:
        return ast.dump(ast.parse(produced, mode="eval")) == ast.dump(
            ast.parse(after, mode="eval"))
    except (SyntaxError, RecursionError, MemoryError):
        return False


def _self_check(rule: LearnedRule, examples) -> bool:
    """The learned rule must reproduce every taught AFTER; append a blocker and
    return ``False`` on the first example it fails."""
    from app.execution.pattern_rewrite import _encode_metavars

    p_tree = ast.parse(_encode_metavars(rule.pattern), mode="eval").body
    for i, (b, a) in enumerate(examples, 1):
        node = ast.parse(b, mode="eval").body
        bindings: dict[str, str] = {}
        if not _match(node, p_tree, b, bindings):
            rule.blockers.append(f"self-check failed: the rule doesn't match example {i}")
            return False
        if not _reproduces(rule.replacement, a, bindings):
            produced = _render(rule.replacement, bindings)
            rule.blockers.append(
                f"self-check failed: applying the rule to example {i} gives "
                f"{produced!r}, not the taught AFTER")
            return False
    return True


def learn_rule(examples: list[tuple[str, str]]) -> LearnedRule:
    """Anti-unify ``(before, after)`` example pairs into a verified rule."""
    rule = LearnedRule()
    if not examples:
        rule.blockers.append("teach needs at least one BEFORE/AFTER example pair")
        return rule

    parsed = _parse_examples(examples, rule)
    if parsed is None:
        return rule
    befores, afters = parsed

    if len(examples) == 1:
        rule.pattern, rule.replacement = examples[0]
        rule.notes.append("one example → an exact-match rule (no metavariables); "
                          "teach with a second example to generalize")
    elif not _generalize_rule(befores, afters, examples, rule):
        return rule

    if _self_check(rule, examples):
        rule.notes.append(f"self-check passed on {len(examples)} example(s)")
    return rule
