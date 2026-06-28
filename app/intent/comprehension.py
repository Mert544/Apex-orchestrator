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

__all__ = [
    "Comprehension", "comprehend", "CONCEPT_VOCAB",
    "concept_matches", "name_phrase_match", "render_comprehension_markdown",
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


# --- The shared concept vocabulary -------------------------------------------
#
# Each row is ``(concept phrase, (objective, ...))``: when the phrase appears as a
# literal substring of the normalized (lowercased, TR-aware) request, EVERY listed
# objective is a candidate, in the listed order. The table is APPEND-ONLY and
# table-driven (no fuzzy match, no model). EN and TR phrases sit side by side so a
# Turkish student and an English team get the same understanding. More-specific
# phrases are listed before shorter ones they contain, so the specific reading
# wins a tie. Every objective on the right is a real ``available_objectives()``
# name (a test asserts this), so a concept can only ever name runnable work.
#
# This is the ONE source of truth: :func:`comprehend` ranks against it (and the
# objective NAMES) and ``objective_compiler.resolve_objective`` consults it as the
# fallback after its own hand-tuned synonym table — so deepening it here lifts the
# whole NL→objective hit-rate at both call sites at once.
CONCEPT_VOCAB: tuple[tuple[str, tuple[str, ...]], ...] = (
    # --- type hints / annotations ---------------------------------------------
    ("type hints", ("infer-type-hints", "annotate-self-returns", "pin-return-type",
                    "add-from-future-annotations")),
    ("type hint", ("infer-type-hints", "annotate-self-returns", "pin-return-type",
                   "add-from-future-annotations")),
    ("type annotation", ("infer-type-hints", "annotate-self-returns",
                         "pin-return-type", "add-from-future-annotations")),
    ("typing", ("infer-type-hints", "annotate-self-returns", "pin-return-type")),
    ("annotate", ("infer-type-hints", "annotate-self-returns", "pin-return-type")),
    ("add types", ("infer-type-hints", "pin-return-type")),
    ("tip belirteç", ("infer-type-hints", "annotate-self-returns", "pin-return-type")),
    ("tip ekle", ("infer-type-hints", "pin-return-type")),
    # --- docstrings / documentation -------------------------------------------
    ("docstrings", ("document-param", "document-returns", "document-attributes",
                    "document-raises", "document-yields", "document-signature",
                    "generate-usage-doc")),
    ("docstring", ("document-param", "document-returns", "document-attributes",
                   "document-raises", "document-yields", "document-signature",
                   "generate-usage-doc")),
    ("documentation", ("document-param", "document-returns", "document-signature",
                       "generate-usage-doc")),
    ("api docs", ("generate-usage-doc", "document-signature", "document-param")),
    ("usage doc", ("generate-usage-doc", "document-signature")),
    ("readme", ("generate-usage-doc", "document-signature")),
    ("doc comment", ("document-param", "document-returns", "document-signature")),
    ("document", ("document-param", "document-returns", "document-signature",
                  "generate-usage-doc")),
    ("dökümantasyon", ("document-param", "document-returns", "document-signature",
                       "generate-usage-doc")),
    ("dokümantasyon", ("document-param", "document-returns", "document-signature",
                       "generate-usage-doc")),
    ("belge", ("document-param", "document-returns", "document-signature")),
    ("açıklama ekle", ("document-param", "document-returns", "document-signature")),
    # --- tests / coverage -----------------------------------------------------
    ("unit test", ("cover-gaps", "strengthen-tests", "pin-doctest")),
    ("characterization", ("cover-gaps", "strengthen-tests")),
    ("coverage", ("cover-gaps", "strengthen-tests")),
    ("add tests", ("cover-gaps", "strengthen-tests", "pin-doctest")),
    ("add a test", ("cover-gaps", "strengthen-tests")),
    ("write tests", ("cover-gaps", "strengthen-tests", "pin-doctest")),
    ("more tests", ("strengthen-tests", "cover-gaps")),
    ("tests", ("cover-gaps", "strengthen-tests", "pin-doctest")),
    ("test ekle", ("cover-gaps", "strengthen-tests")),
    ("kapsam", ("cover-gaps", "strengthen-tests")),
    # --- implement / scaffold (concrete value) --------------------------------
    ("notimplementederror", ("implement-stub", "implement-from-doctest",
                             "tdd-implement")),
    ("not implemented", ("implement-stub", "implement-from-doctest", "tdd-implement")),
    ("implement", ("implement-stub", "implement-from-doctest", "tdd-implement",
                   "scaffold-from-protocol")),
    ("fill in", ("implement-stub", "implement-from-doctest")),
    ("scaffold", ("scaffold-from-protocol", "implement-stub")),
    ("todo", ("implement-stub", "implement-from-doctest")),
    ("stub", ("implement-stub", "tdd-implement", "scaffold-from-protocol")),
    ("hayata geçir", ("implement-stub", "implement-from-doctest")),
    # --- security -------------------------------------------------------------
    ("security", ("harden",)),
    ("secure", ("harden",)),
    ("vulnerab", ("harden",)),
    ("injection", ("harden",)),
    ("unsafe", ("harden",)),
    ("güvenlik", ("harden",)),
    ("zafiyet", ("harden",)),
    ("açık", ("harden",)),
    # --- modernize / idiom (the broad surface-tidy family) --------------------
    # Listed AFTER the specific families above so e.g. "simplify the type hints"
    # still leads with infer-type-hints. The family head (``modernize``) is first
    # so the broad ask leads with the broad lens, then the specific idiom fixers.
    ("modernize", ("modernize", "format-to-fstring", "fstring-convert",
                   "percent-to-fstring", "simplify-comprehension", "use-enumerate")),
    ("modernise", ("modernize", "format-to-fstring", "use-enumerate")),
    ("pythonic", ("modernize", "use-enumerate", "simplify-comprehension")),
    ("idiom", ("modernize", "use-enumerate", "simplify-comprehension")),
    ("cleaner", ("modernize", "simplify-bool-return")),
    ("f-string", ("format-to-fstring", "fstring-convert", "percent-to-fstring",
                  "remove-redundant-fstring")),
    ("fstring", ("format-to-fstring", "fstring-convert", "percent-to-fstring",
                 "remove-redundant-fstring")),
    ("comprehension", ("simplify-comprehension", "dict-comprehension")),
    ("lint", ("modernize", "remove-unused-imports", "sort-imports")),
    ("iyileştir", ("modernize", "simplify-bool-return")),
    # --- dataclass / immutability ---------------------------------------------
    ("dataclass", ("dataclassify", "freeze-dataclass", "add-slots",
                   "add-dataclass-order", "synthesize-dunders")),
    ("frozen", ("freeze-dataclass", "dataclassify")),
    ("immutable", ("freeze-dataclass", "add-slots")),
    ("slots", ("add-slots", "dataclassify")),
    ("veri sınıf", ("dataclassify", "freeze-dataclass", "add-slots")),
    # --- final / sealing ------------------------------------------------------
    ("final", ("add-final", "seal-final-method", "seal-hashable-eq",
               "seal-total-ordering")),
    ("seal", ("add-final", "seal-final-method", "seal-hashable-eq",
              "seal-total-ordering")),
    ("mühürle", ("add-final", "seal-final-method")),
    # --- exports / public API -------------------------------------------------
    ("public api", ("wire-exports", "wire-module-exports", "sort-dunder-all")),
    ("__all__", ("wire-exports", "wire-module-exports", "sort-dunder-all",
                 "dedup-dunder-all")),
    ("exports", ("wire-exports", "wire-module-exports", "sort-dunder-all")),
    ("dışa aktar", ("wire-exports", "wire-module-exports")),
    # --- exceptions / error handling ------------------------------------------
    ("error handling", ("raise-from", "document-raises")),
    ("exception", ("raise-from", "document-raises")),
    ("re-raise", ("raise-from",)),
    ("hata", ("raise-from", "document-raises")),
    # --- enum / match ---------------------------------------------------------
    ("match exhaustive", ("complete-match-exhaustiveness",)),
    ("exhaustive", ("complete-match-exhaustiveness",)),
    ("enum", ("enforce-enum-unique",)),
    # --- JS / TS --------------------------------------------------------------
    ("javascript", ("js-document-param-types", "js-implement-from-jsdoc",
                    "js-tdd-implement", "js-wire-exports")),
    ("typescript", ("js-document-param-types", "js-implement-from-jsdoc",
                    "js-tdd-implement", "js-wire-exports")),
    ("jsdoc", ("js-document-param-types", "document-export-jsdoc",
               "document-raises-jsdoc", "js-implement-from-jsdoc")),
    # --- Java -----------------------------------------------------------------
    ("java", ("java-document-throws", "java-finalize-field")),
    # --- restructure (long/sprawling code) ------------------------------------
    # "split this up", "break into smaller pieces", "this function is too long" —
    # the structural lenses. The synonym table already routes "split function"/
    # "shrink function"; these noun-light phrases broaden the reach to the concept.
    ("split", ("shrink-functions", "inline-helpers")),
    ("break up", ("shrink-functions", "inline-helpers")),
    ("break into", ("shrink-functions", "inline-helpers")),
    ("too long", ("shrink-functions",)),
    ("too big", ("shrink-functions",)),
    # --- imports (the noun) ---------------------------------------------------
    # The imports-management family, named by the noun so "sort my imports",
    # "fix the imports", "organize imports" all land here (the verb-specific
    # phrases like "sort import"/"unused import" stay in the compiler's synonym
    # table and rank the precise lens first). ``import`` covers both forms.
    ("imports", ("sort-imports", "remove-unused-imports", "merge-duplicate-imports")),
    ("import", ("sort-imports", "remove-unused-imports", "merge-duplicate-imports")),
    # --- broad "tidy / clean" generic asks ------------------------------------
    # The catch-all for "make it nicer / clean it up / kodu temizle": route to the
    # surface-tidy lens plus the cheap idiom fixers. These are GENERIC verbs (see
    # ``_GENERIC_PHRASES``) so they always score at the family tier — a specific
    # noun in the same request (e.g. "imports") outranks them, so "clean up the
    # imports" leads with sort-imports, not modernize.
    ("clean up", ("modernize", "remove-dead-code", "sort-imports")),
    ("cleanup", ("modernize", "remove-dead-code", "sort-imports")),
    ("clean code", ("modernize", "remove-dead-code")),
    ("tidy", ("modernize", "sort-imports", "remove-dead-code")),
    ("kodu temizle", ("modernize", "remove-dead-code", "sort-imports")),
    ("temizle", ("modernize", "remove-dead-code", "sort-imports")),
    ("refactor", ("modernize", "shrink-functions", "inline-helpers")),
)


# Broad/generic concept phrases that always rank at the FAMILY tier even though
# they are multiword — a "clean up"/"refactor" ask is a vague surface tidy, so a
# SPECIFIC noun in the same request (e.g. "imports", "tests") must outrank it.
# Everything here is also a key in ``CONCEPT_VOCAB`` above.
_GENERIC_PHRASES: frozenset[str] = frozenset({
    "clean up", "cleanup", "clean code", "tidy", "kodu temizle", "temizle",
    "refactor",
})


# --- Normalization & matching primitives -------------------------------------
#
# A request is normalized to lowercase with a single source of truth for the
# token alphabet (ASCII + the Turkish letters), so EN and TR requests tokenize
# identically and deterministically. ``_norm`` joins the tokens with single
# spaces for substring phrase matching; ``_tokens`` is the word list for opener
# detection.
_WORD = re.compile(r"[a-zçğıöşü]+")
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


def _norm(request: str) -> str:
    """Lowercase the request to its token alphabet (ASCII + TR), joined by single
    spaces, so phrase matching is whitespace- and punctuation-insensitive and
    TR-aware. Same normalization for every request → same matches every time."""
    return " ".join(_WORD.findall(request.lower()))


def _tokens(request: str) -> list[str]:
    """The request's word tokens (TR-aware), in order — for opener detection."""
    return _WORD.findall(request.lower())


def name_phrase_match(text: str, objectives: list[str]) -> list[str]:
    """Objectives whose NAME appears as a phrase in already-normalized ``text``.

    An objective name matches when its slug-with-hyphens-as-spaces is a substring
    of ``text`` (``sort imports`` for ``sort-imports``, ``infer type hints`` for
    ``infer-type-hints``); a single-token name (``modernize``, ``harden``) equals
    that phrase and so matches the same way. A bare hyphen-token is deliberately
    NOT matched on its own (``document`` heads ten objectives, ``simplify`` seven
    — a lone token would be hopelessly ambiguous and could mis-route a request
    that used to resolve precisely); only the full, specific name counts. Returns
    hits in declaration order of ``objectives``; deterministic, substring-only."""
    hits: list[str] = []
    for name in objectives:
        if name.replace("-", " ") in text:
            hits.append(name)
    return hits


def concept_matches(text: str) -> list[str]:
    """Objectives named by the CONCEPT_VOCAB for already-normalized ``text``.

    Every concept phrase that is a substring of ``text`` contributes its
    objectives, in vocab declaration order, dedup'd preserving first-seen. Pure,
    deterministic, substring-only — the shared concept fallback both
    :func:`comprehend` and ``resolve_objective`` consult."""
    out: list[str] = []
    for phrase, objs in CONCEPT_VOCAB:
        if phrase in text:
            for obj in objs:
                if obj not in out:
                    out.append(obj)
    return out


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
    token. Otherwise it is a develop command."""
    if request.rstrip().endswith("?"):
        return "question"
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
    objective-NAME phrases; (1) hand-tuned family synonyms. Pure, substring-only."""
    available_set = set(available)
    out: list[tuple[str, int]] = []
    if text in available_set:                                   # (3) exact slug
        out.append((text, _RANK_EXACT))
    for phrase, objs in CONCEPT_VOCAB:                          # (2)/(1) concepts
        if phrase in text:
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
                     scope: str | None) -> str:
    """A grounded, human one-liner explaining the understanding — no jargon, the
    same facts the report shows, so a buyer can sanity-check the routing."""
    if action == "question":
        focus = f" about {scope}" if scope else ""
        return (f"Understood a QUESTION{focus} → analyze/explain "
                f"(no changes; ask routes to a scan).")
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
    if objectives is not None:
        # Constrain to the caller's allow-list, preserving the computed rank.
        allow = set(objectives)
        ranked = [o for o in ranked if o in allow]
    confidence = "high" if ranked else "low"
    return Comprehension(
        request=request, action="develop", objectives=ranked, mode=mode,
        scope=scope, rationale=_build_rationale("develop", ranked, mode, scope),
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
