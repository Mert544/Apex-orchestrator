from __future__ import annotations

import math
from collections import Counter
from typing import Any


class VectorStore:
    """Simple in-memory vector store for claim similarity search.

    Uses bag-of-words vectors with cosine similarity.
    No external ML dependencies — pure stdlib.

    Usage:
        store = VectorStore()
        store.add("eval() in auth.py", {"severity": "high"})
        store.add("os.system() in utils.py", {"severity": "critical"})
        results = store.search("eval usage detected", top_k=2)
    """

    def __init__(self) -> None:
        self._vectors: list[tuple[list[float], dict[str, Any], str]] = []
        self._vocab: list[str] = []
        self._dirty = True

    def _tokenize(self, text: str) -> list[str]:
        return text.lower().replace("(", " ").replace(")", " ").replace(".", " ").split()

    def _build_vocab(self) -> None:
        vocab_set: set[str] = set()
        for _vec, _, text in self._vectors:
            vocab_set.update(self._tokenize(text))
        self._vocab = sorted(vocab_set)
        self._dirty = False

    def _vectorize(self, text: str) -> list[float]:
        if self._dirty:
            self._build_vocab()
        tokens = self._tokenize(text)
        counts = Counter(tokens)
        return [counts.get(word, 0) for word in self._vocab]

    def add(self, text: str, metadata: dict[str, Any]) -> None:
        self._vectors.append(([], metadata, text))
        self._dirty = True

    def _cosine(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        if not self._vectors:
            return []
        q_vec = self._vectorize(query)
        scored: list[tuple[float, dict[str, Any], str]] = []
        for _, metadata, text in self._vectors:
            vec = self._vectorize(text)
            score = self._cosine(q_vec, vec)
            scored.append((score, metadata, text))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"text": text, "metadata": meta, "score": round(score, 3)}
            for score, meta, text in scored[:top_k]
        ]

    def stats(self) -> dict[str, Any]:
        if self._dirty:
            self._build_vocab()
        return {
            "entries": len(self._vectors),
            "vocab_size": len(self._vocab),
        }
