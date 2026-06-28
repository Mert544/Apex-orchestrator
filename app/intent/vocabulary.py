"""Shared NL→objective VOCABULARY — the stdlib-only leaf both surfaces consult.

This is the dependency LEAF for Apex's deterministic comprehension: it holds the
concept vocabulary and the matching primitives that BOTH
:mod:`app.intent.comprehension` (``comprehend``) and
``app.engine.objective_compiler`` (``resolve_objective``) use, so the two agree
on what a request means — *without* an import cycle.

Why a separate leaf? ``comprehension`` needs the objective registry
(``available_objectives``/``_OBJECTIVE_SYNONYMS``) from ``objective_compiler``,
and ``objective_compiler`` needs these matchers. Putting the matchers HERE — with
the objectives list passed IN as a parameter (dependency injection), never
imported — keeps the edges one-directional:

    vocabulary  → (stdlib only)
    objective_compiler → vocabulary
    comprehension → {vocabulary, objective_compiler}

No cycle. This is Apex's own "extract a shared leaf to break a cycle" move,
applied to itself.

Everything here is pure, deterministic, substring/regex-only — no clock, no
random, no model, no network. Same input → same output.
"""

from __future__ import annotations

import re

__all__ = [
    "CONCEPT_VOCAB", "concept_matches", "name_phrase_match", "phrase_in",
    "is_removal_framed", "suppress_removal", "normalize", "tokenize",
]


# The token alphabet — ASCII + the Turkish letters — as ONE source of truth, so
# EN and TR requests tokenize identically and deterministically.
_WORD = re.compile(r"[a-zçğıöşü]+")


def normalize(request: str) -> str:
    """Lowercase the request to its token alphabet (ASCII + TR), joined by single
    spaces, so phrase matching is whitespace- and punctuation-insensitive and
    TR-aware. Same normalization for every request → same matches every time. This
    is the text :func:`phrase_in` / :func:`concept_matches` expect."""
    return " ".join(_WORD.findall(request.lower()))


def tokenize(request: str) -> list[str]:
    """The request's word tokens (TR-aware), in order — for lead/opener checks."""
    return _WORD.findall(request.lower())


# --- The shared concept vocabulary -------------------------------------------
#
# Each row is ``(concept phrase, (objective, ...))``: when the phrase appears
# (via :func:`phrase_in`) in the normalized request, EVERY listed objective is a
# candidate, in the listed order. The table is APPEND-ONLY and table-driven (no
# fuzzy match, no model). EN and TR phrases sit side by side so a Turkish student
# and an English team get the same understanding. More-specific phrases are
# listed before shorter ones they contain, so the specific reading wins a tie.
# Every objective on the right is a real ``available_objectives()`` name (a test
# asserts this), so a concept can only ever name runnable work.
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


# --- Removal / negation honesty guard (LEAD-ANCHORED) ------------------------
#
# Apex has ADD capabilities (document, type, test, …) but no "un-document" /
# "un-type" inverse. A naive concept match turns "remove docstrings" into
# document-param — HIGH confidence, the exact OPPOSITE of intent, and the
# additive edit passes the green gate so auto-rollback can't catch the inversion.
# The guard suppresses that ONLY when the request is removal-FRAMED at its LEAD
# (not "cue anywhere", which over-suppresses "add tests for the delete endpoint").
#
# Removal verbs that, AS THE FIRST meaningful token, frame the whole request as a
# deletion ("remove docstrings", "strip the type hints").
_REMOVAL_LEAD_VERBS: frozenset[str] = frozenset({
    "remove", "delete", "strip", "drop", "disable", "undo", "revert", "purge",
    "eliminate", "kill",
})
# Multi-token removal/negation LEADS — matched as the request's first tokens. Each
# inverts intent ("get rid of …", "don't add …", "do not document", "never add").
# ``don't`` tokenizes to ``don`` + ``t``, so both forms are listed.
_NEGATION_LEADS: tuple[tuple[str, ...], ...] = (
    ("get", "rid", "of"), ("get", "rid"),
    ("don", "t"), ("don",), ("do", "not"), ("dont",),
    ("never",), ("no",), ("without",), ("stop",), ("skip",), ("avoid",),
)
# Objectives that GENUINELY remove/reduce code — a removal-framed request that
# matches one of these is a legitimate removal (e.g. "remove dead code"), so the
# guard must NOT fire. Membership is by name prefix/family, computed once.
_REMOVAL_OBJECTIVE_PREFIXES: tuple[str, ...] = (
    "remove-", "dedup", "merge-", "inline-", "dead-params",
    "collapse-", "fold-", "combine-", "simplify-", "fix-not-in-is",
)

# --- Word-boundary matching for short/ambiguous concept keys -----------------
#
# Substring matching makes "important" → ``import`` → sort-imports, "final exam"
# → add-final, "documentary" → document-*, "typing speed" → infer-type-hints —
# all false. Two tiers fix this deterministically:
#
# (A) WORD-BOUNDARY keys — a distinctive token whose only problem is being a
#     substring of a longer word: require a real word boundary (with the sensible
#     inflections). ``\benum\b`` won't match "enumerate"; ``\bdocument…\b`` won't
#     match "documentary"; ``import`` won't match "important".
_BOUNDARY_KEY_PATTERNS: dict[str, re.Pattern[str]] = {
    "import": re.compile(r"\bimport(s|ing|ed)?\b"),
    "imports": re.compile(r"\bimports\b"),
    "enum": re.compile(r"\benum\b"),         # not "enumerate"
    "document": re.compile(r"\bdocument(s|ed|ing|ation)?\b"),  # not "documentary"
    "type hint": re.compile(r"\btype hints?\b"),
    "type hints": re.compile(r"\btype hints?\b"),
    "typing": re.compile(r"\btyping\b(?!\s+speed)"),  # the module, not keyboard typing
    "annotate": re.compile(r"\bannotate[ds]?\b"),
    "tests": re.compile(r"\btests?\b"),      # not "latest"/"testament"
    "stub": re.compile(r"\bstubs?\b"),
    "todo": re.compile(r"\btodos?\b"),
}
# (B) CONTEXT keys — a genuine common ENGLISH word (``final``, ``java``, ``slot``,
#     ``seal``) where even a word boundary isn't enough ("final exam", "java is my
#     favorite island", "slot machine", "seal the envelope"). These match only
#     when a CODE-CONTEXT companion co-occurs (an add/make/seal verb, or a domain
#     noun like method/class/throws/dataclass), so "make it final"/"add slots"/
#     "java throws" KEEP working while the unrelated noun phrases are killed.
_CONTEXT_KEY_PATTERNS: dict[str, re.Pattern[str]] = {
    "final": re.compile(
        r"\b(method|class|attribute|field|var|variable|constant)\b.{0,25}\bfinal\b"
        r"|\bfinal\b.{0,25}\b(method|class|attribute|field|var|variable|constant)\b"
        r"|\b(add|make|mark|set|seal|declare|keep)\b.{0,25}\bfinal\b"),
    "java": re.compile(
        r"\bjava\b.{0,25}\b(throw|throws|finalize|field|class|method|document|"
        r"interface|annotation)\b"
        r"|\b(document|finalize|seal|harden)\b.{0,25}\bjava\b"),
    "slots": re.compile(
        r"\b(add|use|with|give|generate|introduce)\b.{0,16}\bslots?\b"
        r"|\bslots?\b.{0,12}\b(to|on|for|dataclass|class)\b|\b__slots__\b"),
    "seal": re.compile(
        r"\bseal\b.{0,16}\b(method|class|final|hashable|ordering|eq|dunder)\b"
        r"|\b(make|mark)\b.{0,16}\bseal\b"),
}


def phrase_in(phrase: str, text: str) -> bool:
    """Is ``phrase`` present in already-normalized ``text``?

    Three tiers, in order: a WORD-BOUNDARY key (``import``, ``enum``, ``document``,
    ``type hints`` …) matches with boundaries + inflections, so "important" ↛
    ``import`` and "documentary" ↛ ``document``; a CONTEXT key (``final``,
    ``java``, ``slot``, ``seal`` — genuine common words) matches ONLY with a
    code-context companion, so "final exam"/"slot machine"/"java is my favorite
    island" are killed while "make it final"/"add slots"/"java throws" keep
    working; every other phrase keeps fast exact substring matching. Shared by the
    concept, name, and synonym scans so comprehend() and resolve_objective() agree
    on what "present" means. Deterministic."""
    pattern = _BOUNDARY_KEY_PATTERNS.get(phrase) or _CONTEXT_KEY_PATTERNS.get(phrase)
    if pattern is not None:
        return pattern.search(text) is not None
    return phrase in text


def name_phrase_match(text: str, objectives: list[str]) -> list[str]:
    """Objectives whose NAME appears as a phrase in already-normalized ``text``.

    An objective name matches when its slug-with-hyphens-as-spaces is present in
    ``text`` (``sort imports`` for ``sort-imports``, ``infer type hints`` for
    ``infer-type-hints``); a single-token name (``modernize``, ``harden``) equals
    that phrase and so matches the same way. A bare hyphen-token is deliberately
    NOT matched on its own (``document`` heads ten objectives, ``simplify`` seven
    — a lone token would be hopelessly ambiguous and could mis-route a request
    that used to resolve precisely); only the full, specific name counts.
    Presence uses :func:`phrase_in`, so an ambiguous short name is word-bounded.
    The objectives list is INJECTED (this leaf never imports the registry), which
    is exactly what keeps it cycle-free. Returns hits in declaration order of
    ``objectives``; deterministic."""
    hits: list[str] = []
    for name in objectives:
        if phrase_in(name.replace("-", " "), text):
            hits.append(name)
    return hits


def concept_matches(text: str) -> list[str]:
    """Objectives named by the CONCEPT_VOCAB for already-normalized ``text``.

    Every concept phrase PRESENT in ``text`` (via :func:`phrase_in`, so a short
    ambiguous key is word-bounded) contributes its objectives, in vocab
    declaration order, dedup'd preserving first-seen. Pure, deterministic — the
    shared concept fallback both :func:`~app.intent.comprehension.comprehend` and
    ``resolve_objective`` consult. Needs no objectives list (it reads the static
    vocab), so it imports nothing and adds no edge."""
    out: list[str] = []
    for phrase, objs in CONCEPT_VOCAB:
        if phrase_in(phrase, text):
            for obj in objs:
                if obj not in out:
                    out.append(obj)
    return out


def is_removal_framed(tokens: list[str]) -> bool:
    """Is the request framed as a REMOVAL/negation at its LEAD?

    True iff the FIRST meaningful token is a removal verb ({remove, delete, strip,
    drop, …}), OR the first 1–3 tokens are a negation/removal lead ({get rid of,
    don't → "don"/"dont", "do not", never, no, without, stop, skip, avoid}).
    LEAD-anchored on purpose: a cue buried later ("add tests for the delete
    endpoint", "document how to remove a user") does NOT frame the request as a
    removal, so those are unaffected. Deterministic."""
    if not tokens:
        return False
    if tokens[0] in _REMOVAL_LEAD_VERBS:
        return True
    head = tuple(tokens[:3])
    for lead in _NEGATION_LEADS:
        if head[:len(lead)] == lead:
            return True
    return False


def _is_removal_objective(name: str) -> bool:
    """Does ``name`` genuinely REMOVE/reduce code (so a removal-framed request can
    legitimately mean it — "remove dead code" → remove-dead-code)? Matched by the
    removal name families, with ``scaffold-from-protocol`` explicitly excluded (it
    only shares the ``fold`` letters, it does not remove code)."""
    if name == "scaffold-from-protocol":
        return False
    return any(name.startswith(p) or p in name for p in _REMOVAL_OBJECTIVE_PREFIXES)


def suppress_removal(tokens: list[str], objectives: list[str]) -> bool:
    """Should a removal-framed request's ADDITIVE matches be suppressed?

    True iff (1) the request is lead-anchored removal-framed, (2) at least one
    objective matched, and (3) EVERY matched objective is additive (none is a real
    removal capability). In that case the fallback inverted intent — Apex would
    ADD what the user asked to REMOVE — so the honest move is to drop the matches.
    A legitimate removal ("remove dead code") matches a removal objective and is
    NOT suppressed; a non-removal-framed request is never touched."""
    if not objectives or not is_removal_framed(tokens):
        return False
    return not any(_is_removal_objective(o) for o in objectives)
