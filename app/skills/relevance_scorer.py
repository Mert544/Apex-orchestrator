from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Concept expansion: a domain word in the objective ("security") should match an
# idea grounded in a *related* term ("harden", "sensitive", "eval") even when the
# surface tokens differ. Each concept maps to the vocabulary treated as
# equivalent for relevance; when either side's tokens touch that vocabulary, the
# canonical concept token is added to both so they can overlap. Deterministic and
# offline — it only ever *adds* matches (raising recall for a related idea),
# never removes one, so it can't make an on-topic objective prune a relevant idea.
_CONCEPTS: dict[str, set[str]] = {
    "security": {
        "security", "secure", "harden", "hardening", "vulnerability", "vulnerable",
        "injection", "inject", "eval", "exec", "pickle", "auth", "authentication",
        "authorization", "secret", "secrets", "credential", "credentials",
        "sensitive", "exploit", "sanitize", "xss", "csrf", "payment", "token",
    },
    "testing": {
        "test", "testing", "tests", "coverage", "untested", "regression",
        "assertion", "assert", "verify", "verification", "fixture",
    },
    "performance": {
        "performance", "perf", "latency", "throughput", "speed", "optimize",
        "optimization", "optimise", "bottleneck", "cache", "caching", "index",
        "indexing",
    },
    "reliability": {
        "reliability", "reliable", "resilience", "resilient", "robust", "timeout",
        "retry", "failure", "fault", "crash", "exception", "rollback",
    },
    "architecture": {
        "architecture", "architectural", "coupling", "cohesion", "modularity",
        "refactor", "dependency", "dependencies", "cycle", "hub", "interface",
        "boundary",
    },
    "documentation": {
        "documentation", "docs", "document", "documented", "docstring", "readme",
        "comment", "comments", "contract",
    },
}


def _expand(tokens: set[str]) -> set[str]:
    """Add the canonical concept token for any concept the tokens touch."""
    out = set(tokens)
    for concept, vocab in _CONCEPTS.items():
        if tokens & vocab:
            out.add(concept)
    return out

# Small, dependency-free stopword list so generic words don't inflate overlap.
_STOPWORDS = {
    "the", "and", "for", "are", "was", "were", "with", "that", "this", "from",
    "into", "onto", "out", "over", "under", "than", "then", "them", "they",
    "you", "your", "our", "not", "but", "any", "all", "can", "could", "should",
    "would", "will", "shall", "may", "might", "must", "has", "have", "had",
    "its", "it's", "his", "her", "their", "what", "when", "where", "which",
    "who", "whom", "why", "how", "does", "did", "done", "doing", "being",
    "been", "more", "most", "some", "such", "only", "own", "same", "very",
    "via", "per", "about", "above", "below", "between", "because", "while",
}


class RelevanceScorer:
    """Score how relevant a text is to the run's objective (the "main idea").

    Fully deterministic and offline — no LLM, no dependencies. Uses
    stopword-filtered token overlap so branches that drift away from the
    objective score lower and can be deprioritised or pruned, keeping the
    reasoning tree focused on the main idea.

    score() returns a value in [0.0, 1.0]:
      1.0  -> no objective given (everything is on-topic)
      0.0  -> shares no meaningful term with the objective
    """

    def __init__(self, objective: str) -> None:
        self.objective = objective or ""
        self.keywords = _expand(self._keywords(self.objective))

    @staticmethod
    def _keywords(text: str) -> set[str]:
        return {
            tok
            for tok in _TOKEN_RE.findall(text.lower())
            if len(tok) > 2 and tok not in _STOPWORDS
        }

    def score(self, text: str) -> float:
        if not self.keywords:
            return 1.0
        terms = _expand(self._keywords(text))
        if not terms:
            return 0.0
        overlap = self.keywords & terms
        if not overlap:
            return 0.0
        # Recall against the objective (how much of the main idea is covered)
        # blended with precision (how on-topic the text is overall).
        recall = len(overlap) / len(self.keywords)
        precision = len(overlap) / len(terms)
        return round(min(1.0, 0.6 * recall + 0.4 * precision), 4)
