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


def _generalize(nodes: list[ast.AST], sources: list[str], holes: _Holes) -> ast.AST:
    """The common skeleton of ``nodes`` with metavariable holes at mismatches."""
    first = nodes[0]
    if any(type(n) is not type(first) for n in nodes):
        return _hole(nodes, sources, holes)
    try:
        out = type(first)()
        for fname, fvalue in ast.iter_fields(first):
            values = [getattr(n, fname) for n in nodes]
            if isinstance(fvalue, list):
                if any(not isinstance(v, list) or len(v) != len(fvalue) for v in values):
                    return _hole(nodes, sources, holes)
                items = []
                for group in zip(*values):
                    if isinstance(group[0], ast.AST):
                        items.append(_generalize(list(group), sources, holes))
                    elif any(g != group[0] for g in group):
                        raise _MustHole
                    else:
                        items.append(group[0])
                setattr(out, fname, items)
            elif isinstance(fvalue, ast.AST):
                if any(not isinstance(v, ast.AST) for v in values):
                    return _hole(nodes, sources, holes)
                setattr(out, fname, _generalize(values, sources, holes))
            elif any(v != fvalue for v in values):
                # A scalar mismatch (a Name's id, a Constant's value, an
                # operator choice) can only generalize at expression level.
                return _hole(nodes, sources, holes)
            else:
                setattr(out, fname, fvalue)
        return out
    except _MustHole:
        return _hole(nodes, sources, holes)


def _to_display(template_tree: ast.AST) -> str:
    """unparse, with placeholder identifiers back in ``$x`` spelling."""
    return ast.unparse(template_tree).replace(_MV_PREFIX, "$")


def learn_rule(examples: list[tuple[str, str]]) -> LearnedRule:
    """Anti-unify ``(before, after)`` example pairs into a verified rule."""
    rule = LearnedRule()
    if not examples:
        rule.blockers.append("teach needs at least one BEFORE/AFTER example pair")
        return rule

    befores, afters = [], []
    for i, (b, a) in enumerate(examples, 1):
        try:
            befores.append(ast.parse(b, mode="eval").body)
            afters.append(ast.parse(a, mode="eval").body)
        except SyntaxError:
            rule.blockers.append(f"example {i} is not a pair of valid expressions")
            return rule

    if len(examples) == 1:
        rule.pattern, rule.replacement = examples[0]
        rule.notes.append("one example → an exact-match rule (no metavariables); "
                          "teach with a second example to generalize")
    else:
        holes = _Holes()
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
            return rule
        pattern_pairs = set(holes.by_pair)

        after_sources = [a for _, a in examples]
        try:
            repl_tree = _generalize(list(afters), after_sources, holes)
        except _MustHole:
            rule.blockers.append("the AFTER examples don't share a structure")
            return rule
        unbound = set(holes.by_pair) - pattern_pairs
        if unbound:
            rule.blockers.append(
                "the change uses values the pattern doesn't capture — the "
                "AFTER sides differ where the BEFORE sides agree")
            return rule
        rule.pattern = _to_display(pattern_tree)
        rule.replacement = _to_display(repl_tree)

    # SELF-CHECK: the learned rule must reproduce every example, structurally.
    from app.execution.pattern_rewrite import _encode_metavars

    p_tree = ast.parse(_encode_metavars(rule.pattern), mode="eval").body
    for i, (b, a) in enumerate(examples, 1):
        node = ast.parse(b, mode="eval").body
        bindings: dict[str, str] = {}
        if not _match(node, p_tree, b, bindings):
            rule.blockers.append(f"self-check failed: the rule doesn't match example {i}")
            return rule
        produced = _render(rule.replacement, bindings)
        try:
            same = ast.dump(ast.parse(produced, mode="eval")) == ast.dump(
                ast.parse(a, mode="eval"))
        except SyntaxError:
            same = False
        if not same:
            rule.blockers.append(
                f"self-check failed: applying the rule to example {i} gives "
                f"{produced!r}, not the taught AFTER")
            return rule
    rule.notes.append(f"self-check passed on {len(examples)} example(s)")
    return rule
