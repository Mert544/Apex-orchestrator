from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")

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
        self.keywords = self._keywords(self.objective)

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
        terms = self._keywords(text)
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
