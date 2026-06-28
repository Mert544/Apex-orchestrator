"""Deterministic COMPREHENSION — the zero-token "small-LLM" understanding layer.

Apex is LLM-free by design, yet a buyer wants to *talk to it* the way they'd talk
to a paid assistant: "add type hints and docstrings to the auth module", "what
should I improve next?", "just show me, don't change anything". This module maps
such a free-text request to the right capability — WITHOUT a model, a network
call, or a clock. It is the comprehension half of the develop loop: read the
intent, name the objective(s), pick the safety mode, locate the scope, and say
*why* — all from a stdlib, table-driven, fully deterministic pass.

It deliberately does NOT execute anything. :func:`comprehend` returns a
:class:`Comprehension` — a plan a human can read (or the new ``apex comprehend``
command prints) before any develop run touches the tree. Wiring it into the
actual develop/auto execution path is a later wave; here it is a transparent
PREVIEW and the shared-vocabulary upgrade that lifts ``resolve_objective`` too.

The vocabulary is the moat: :data:`CONCEPT_VOCAB` (a concept-phrase → objectives
map, EN + TR) plus every objective's own NAME (matched as a phrase) are the ONE
source of truth that both :func:`comprehend` and
``objective_compiler.resolve_objective`` consult, so improving the understanding
improves both at once (DRY). Pure, deterministic, no fuzzy/LLM matching: a phrase
matches only as a literal substring of the normalized request, and ties break by
declaration order — same input, same output, every time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# The shared matching machinery lives in the stdlib-only LEAF ``vocabulary`` so
# this module and ``objective_compiler`` can both use it WITHOUT an import cycle
# (this module imports the registry from ``objective_compiler``; the leaf imports
# nothing from either). Re-exported below so existing references to
# ``app.intent.comprehension.concept_matches`` / ``name_phrase_match`` /
# ``CONCEPT_VOCAB`` keep working — the real definitions live in the leaf.
from app.intent.vocabulary import (
    CONCEPT_VOCAB,
    concept_matches,
    is_removal_framed,
    name_phrase_match,
    normalize as _norm,
    phrase_in,
    suppress_removal,
    tokenize as _tokens,
)

__all__ = [
    "Comprehension", "comprehend", "CONCEPT_VOCAB",
    "concept_matches", "name_phrase_match", "phrase_in", "is_removal_framed",
    "suppress_removal", "render_comprehension_markdown",
]


@dataclass
class Comprehension:
    """A read-only understanding of one natural-language request.

    ``action`` is ``"develop"`` (do mechanical work), ``"question"`` (the user is
    asking, not commanding — route to analyze/explain, ``objectives`` stays empty)
    or ``"unknown"``. ``objectives`` is the RANKED, dedup'd, compound-capable list
    of develop objectives the request maps to (empty for question/unknown).
    ``mode`` is the safety posture (``"report"`` previews, ``"supervised"``
    applies-but-never-commits, ``"autonomous"`` applies-and-commits). ``scope`` is
    a best-effort target hint (a module/file/function name) or ``None``.
    ``confidence`` is ``"low"`` for a develop request that matched no objective —
    the caller can fall back to a project scan."""

    request: str
    action: str = "develop"             # "develop" | "question" | "unknown"
    objectives: list[str] = field(default_factory=list)  # ranked; [] for question
    mode: str = "supervised"            # "report" | "supervised" | "autonomous"
    scope: str | None = None            # best-effort target hint
    rationale: str = ""
    confidence: str = "high"            # "high" | "low"

    def to_dict(self) -> dict[str, object]:
        return {
            "request": self.request, "action": self.action,
            "objectives": list(self.objectives), "mode": self.mode,
            "scope": self.scope, "rationale": self.rationale,
            "confidence": self.confidence,
        }


# ``CONCEPT_VOCAB`` and the matching primitives now live in the stdlib-only
# leaf ``app.intent.vocabulary`` (re-exported above) — see the import at the
# top of this module. Only the ranking/orchestration stays here.


# Broad/generic concept phrases that always rank at the FAMILY tier even though
# they are multiword — a "clean up"/"refactor" ask is a vague surface tidy, so a
# SPECIFIC noun in the same request (e.g. "imports", "tests") must outrank it.
# Everything here is also a key in ``CONCEPT_VOCAB`` above.
_GENERIC_PHRASES: frozenset[str] = frozenset({
    "clean up", "cleanup", "clean code", "tidy", "kodu temizle", "temizle",
    "refactor",
})


# --- ACTION / MODE / SCOPE patterns ------------------------------------------
#
# ``_norm`` (normalize) and ``_tokens`` (tokenize) — plus the concept/name/removal
# matchers — are imported from the leaf ``app.intent.vocabulary`` above (one source
# of truth, shared with ``objective_compiler``). The constants below drive the
# parts that stay here: action classification, safety mode, and scope extraction.
# A scope is a module/file/function name: the FIRST capture of whichever of these
# ordered patterns matches first. Specific shapes (``the X module``, ``in a.py``)
# precede the bare-path fallback so "the auth module" yields ``auth``, not a file.
_SCOPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"the (\w+) module"),
    re.compile(r"module (\w+)"),
    re.compile(r"in ([\w/]+\.py)"),
    re.compile(r"([\w./]+\.py)"),
    re.compile(r"the (\w+) function"),
    re.compile(r"function (\w+)"),
    re.compile(r"the (\w+) class"),
)
# Question OPENERS — English interrogatives/auxiliaries that signal a question
# only when they LEAD the request (English word order: "what should I do",
# "should I refactor"). A request opening with one — or ending with "?" — is a
# question, not a command: it routes to analyze/explain, so ``objectives`` stays
# empty.
_QUESTION_OPENERS: frozenset[str] = frozenset({
    "what", "why", "how", "which", "who", "where", "when",
    "is", "are", "should", "can", "could", "does", "do", "will", "would",
})
# TR interrogative WORDS — Turkish word order is flexible, so these signal a
# question wherever they appear ("bu modül neden bağımlı"), not only when leading.
_TR_QUESTION_WORDS: frozenset[str] = frozenset({
    "ne", "neden", "niçin", "nasıl", "hangi", "kim", "nerede", "nezaman",
    "kaç", "kim",
})
# TR question particles — a request containing one as a standalone token is
# interrogative even without an interrogative word ("bu modül bağımlı mı").
_TR_QUESTION_PARTICLES: frozenset[str] = frozenset({"mı", "mi", "mu", "mü"})
# MODE trigger phrases. ``report`` (preview, never change) is checked first so an
# explicit "don't change" always wins; ``autonomous`` (no confirmation) next;
# otherwise the safe default ``supervised``.
_REPORT_TRIGGERS: tuple[str, ...] = (
    "just show", "don't change", "do not change", "dont change", "preview",
    "dry run", "dry-run", "only show", "show only", "report only", "no changes",
    "without changing", "sadece göster", "sadece rapor", "değiştirme", "dokunma",
)
_AUTONOMOUS_TRIGGERS: tuple[str, ...] = (
    "automatically", "no confirm", "no-confirm", "without confirm", "autonomous",
    "otonom", "otomatik", "onaysız", "kendi kendine",
)

# The removal/negation guard and the word-boundary concept-key matchers moved to
# the stdlib-only leaf ``app.intent.vocabulary`` (imported at the top) so this
# module and ``objective_compiler`` share them without an import cycle.


# ``name_phrase_match`` / ``concept_matches`` / ``phrase_in`` are defined in the
# leaf ``app.intent.vocabulary`` (imported + re-exported at the top of this
# module). They are used below exactly as before.


def _available() -> list[str]:
    """The objective names to rank against — the compiler's live registry,
    imported LAZILY so this module never forms an import cycle with the compiler
    (which consults this module's concept fallback in turn)."""
    from app.engine.objective_compiler import available_objectives

    return list(available_objectives())


def _synonym_table() -> tuple[tuple[str, str], ...]:
    """The compiler's hand-tuned phrase→objective synonym table (e.g. ``untangle``
    → shrink-functions, ``copy-paste`` → dedup) — reused here so comprehend()
    catches the family verbs that aren't a concept phrase or a literal name.
    Imported lazily for the same no-cycle reason as :func:`_available`."""
    from app.engine.objective_compiler import _OBJECTIVE_SYNONYMS

    return _OBJECTIVE_SYNONYMS


# --- ACTION / MODE / SCOPE detection -----------------------------------------

def _detect_action(request: str, tokens: list[str]) -> str:
    """``"question"`` when the request is interrogative, else ``"develop"``.

    A request is a question if it ends with ``?``, OR opens with an English
    interrogative/auxiliary word (English word order), OR contains a TR
    interrogative word anywhere (TR word order is flexible — "bu modül neden
    bağımlı"), OR contains a TR question particle (``mı/mi/mu/mü``) as a standalone
    token. Otherwise it is a develop command. A ``?`` always wins; but a
    removal/negation IMPERATIVE ("do not document this") is a command, not a
    question, even though "do" is an auxiliary opener — so lead-anchored removal
    framing overrides the bare-opener question heuristic."""
    if request.rstrip().endswith("?"):
        return "question"
    if is_removal_framed(tokens):
        return "develop"  # "do not …"/"don't …" is an imperative, not a question
    if tokens and tokens[0] in _QUESTION_OPENERS:
        return "question"
    if any(t in _TR_QUESTION_WORDS for t in tokens):
        return "question"
    if any(t in _TR_QUESTION_PARTICLES for t in tokens):
        return "question"
    return "develop"


def _detect_mode(request: str) -> str:
    """The safety posture: ``report`` (preview) > ``autonomous`` (no confirm) >
    ``supervised`` (the safe default). Matched against the RAW lowercased request
    (NOT the normalized token text) so triggers keep their apostrophes/hyphens —
    "don't change", "dry-run", "no-confirm" match verbatim. Report is checked
    first so an explicit "don't change anything" always pins preview even
    alongside other verbs."""
    low = request.lower()
    if any(t in low for t in _REPORT_TRIGGERS):
        return "report"
    if any(t in low for t in _AUTONOMOUS_TRIGGERS):
        return "autonomous"
    return "supervised"


def _detect_scope(request: str) -> str | None:
    """A best-effort target hint (module/file/function name) or ``None``.

    Runs the ordered scope patterns against the RAW request (paths keep their
    ``.py`` and ``/``) and returns the first capture of the first pattern that
    matches — so "document the auth module" yields ``auth`` and "fix app/x.py"
    yields ``app/x.py``. Deterministic: pattern order is fixed."""
    low = request.lower()
    for pattern in _SCOPE_PATTERNS:
        m = pattern.search(low)
        if m:
            return m.group(1)
    return None


# The removal/negation honesty guard (``is_removal_framed`` / ``suppress_removal``)
# lives in the leaf ``app.intent.vocabulary`` (imported + re-exported above) and is
# called from ``comprehend`` below. ``_detect_action`` also consults it so a
# "do not …" imperative is treated as a command, not a question.


# --- Ranking ------------------------------------------------------------------

# Source weights for the rank: an EXACT objective name typed verbatim is the
# strongest signal (3), a specific multiword concept/name phrase next (2), a
# single-word family/synonym verb weakest (1). Higher wins; declaration order
# breaks ties — so the ordering is total and deterministic.
_RANK_EXACT = 3
_RANK_SPECIFIC = 2
_RANK_FAMILY = 1


def _phrase_weight(phrase: str) -> int:
    """Tier a matched concept phrase: a SPECIFIC multiword phrase scores high; a
    single word OR a broad/generic phrase ("clean up", "refactor") scores at the
    family tier, so a precise noun in the same request outranks the vague verb."""
    specific = " " in phrase and phrase not in _GENERIC_PHRASES
    return _RANK_SPECIFIC if specific else _RANK_FAMILY


def _candidates(text: str, available: list[str]) -> list[tuple[str, int]]:
    """Every (objective, weight) candidate for ``text``, gathered from the four
    sources in a fixed order so first-seen rank ties break deterministically:
    (3) the whole request IS an exact slug; (2)/(1) concept phrases; (2)/(1)
    objective-NAME phrases; (1) hand-tuned family synonyms. Presence uses
    :func:`phrase_in` for the concept/name scans (short ambiguous keys are
    word-bounded); the synonym triggers keep their literal substring semantics."""
    available_set = set(available)
    out: list[tuple[str, int]] = []
    if text in available_set:                                   # (3) exact slug
        out.append((text, _RANK_EXACT))
    for phrase, objs in CONCEPT_VOCAB:                          # (2)/(1) concepts
        if phrase_in(phrase, text):
            weight = _phrase_weight(phrase)
            out.extend((obj, weight) for obj in objs)
    for name in name_phrase_match(text, available):             # (2)/(1) names
        out.append((name, _phrase_weight(name.replace("-", " "))))
    for phrase, obj in _synonym_table():                        # (1) synonyms
        if phrase in text and obj in available_set:
            out.append((obj, _RANK_FAMILY))
    return out


def _rank_objectives(text: str, available: list[str]) -> list[str]:
    """The ranked, dedup'd objective list for a develop request.

    Scores every candidate from :func:`_candidates` by its STRONGEST source
    weight; within a score, first-seen (discovery) order is preserved, giving a
    stable, deterministic ranking. Returns ``[]`` when nothing matched."""
    score: dict[str, int] = {}
    order: dict[str, int] = {}
    for obj, weight in _candidates(text, available):
        if obj not in order:
            order[obj] = len(order)
        score[obj] = max(score.get(obj, 0), weight)

    return sorted(score, key=lambda o: (-score[o], order[o]))


def _build_rationale(action: str, objectives: list[str], mode: str,
                     scope: str | None, suppressed: bool = False) -> str:
    """A grounded, human one-liner explaining the understanding — no jargon, the
    same facts the report shows, so a buyer can sanity-check the routing."""
    if action == "question":
        focus = f" about {scope}" if scope else ""
        return (f"Understood a QUESTION{focus} → analyze/explain "
                f"(no changes; ask routes to a scan).")
    if suppressed:
        # The request was removal/negation-framed and only matched ADD lenses —
        # honest refusal rather than inverting the user's intent.
        return ("Looks like a removal/negation request — Apex has no removal "
                "capability for that concept, so it proposes nothing (a "
                "matching ADD objective would invert your intent).")
    if not objectives:
        return ("Understood a DEVELOP request but matched no specific objective "
                f"({mode} mode) → fall back to a project scan.")
    shown = ", ".join(objectives[:3])
    more = f" (+{len(objectives) - 3} more)" if len(objectives) > 3 else ""
    where = f" on {scope}" if scope else ""
    return f"Understood a DEVELOP request{where} → {shown}{more} ({mode} mode)."


def comprehend(request: str, *,
               objectives: list[str] | None = None) -> Comprehension:
    """Map a natural-language ``request`` to a read-only :class:`Comprehension`.

    Deterministic, zero-token, offline: normalize → classify the ACTION
    (develop/question) → pick the safety MODE → for a develop request RANK the
    objectives against the shared vocabulary (exact name > specific phrase >
    family) → locate the SCOPE → explain. A question carries no objectives (it
    routes to analyze/explain). When ``objectives`` is given, the result is
    FILTERED to that allow-list (preserving rank), so a caller can constrain the
    understanding to a known menu. ``confidence`` is ``"low"`` for a develop
    request that matched nothing — the caller can fall back to a scan.

    This does NOT execute anything; it is the preview the ``apex comprehend``
    command prints and the foundation a later wave wires into develop."""
    text = _norm(request)
    if not text:
        return Comprehension(
            request=request, action="unknown", mode="supervised",
            rationale="Empty request — nothing to understand.", confidence="low")

    tokens = _tokens(request)
    action = _detect_action(request, tokens)
    mode = _detect_mode(request)
    scope = _detect_scope(request)

    if action == "question":
        # A question routes to analyze/explain later; it names no develop work.
        return Comprehension(
            request=request, action="question", objectives=[], mode=mode,
            scope=scope, rationale=_build_rationale("question", [], mode, scope),
            confidence="high")

    available = _available()
    ranked = _rank_objectives(text, available)
    # HONESTY GUARD: a removal/negation-framed request that matched ONLY additive
    # lenses (no real removal objective) would invert intent — Apex has no "un-add"
    # capability — so the matches are dropped and the result is low-confidence
    # (the caller falls back to a scan rather than ADDING what was asked removed).
    suppressed = suppress_removal(tokens, ranked)
    if suppressed:
        ranked = []
    if objectives is not None:
        # Constrain to the caller's allow-list, preserving the computed rank.
        allow = set(objectives)
        ranked = [o for o in ranked if o in allow]
    confidence = "high" if ranked else "low"
    return Comprehension(
        request=request, action="develop", objectives=ranked, mode=mode,
        scope=scope,
        rationale=_build_rationale("develop", ranked, mode, scope, suppressed),
        confidence=confidence)


def render_comprehension_markdown(c: Comprehension) -> str:
    """Render a :class:`Comprehension` as a short, readable block for the CLI.

    Plain text (not a heavy report): the action, the ranked objectives (or the
    question/empty note), the mode, the scope, and the grounded rationale — the
    transparency surface a buyer reads before any develop run."""
    lines = [f"Request:    {c.request}",
             f"Action:     {c.action}",
             f"Mode:       {c.mode}",
             f"Scope:      {c.scope if c.scope else '(whole project)'}",
             f"Confidence: {c.confidence}"]
    if c.objectives:
        lines.append("Objectives (ranked):")
        for i, obj in enumerate(c.objectives, 1):
            lines.append(f"  {i}. {obj}")
    elif c.action == "question":
        lines.append("Objectives: (none — a question routes to analyze/explain)")
    else:
        lines.append("Objectives: (none matched — fall back to a project scan)")
    lines.append("")
    lines.append(f"Why: {c.rationale}")
    return "\n".join(lines)
