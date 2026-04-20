from __future__ import annotations

import re


class SpamGuard:
    META_PREFIXES = (
        "missing-information claim:",
        "contradiction claim:",
        "deepening claim:",
        "risk claim:",
        "investigation claim:",
    )

    GENERIC_QUESTION_PATTERNS = (
        re.compile(r"^What critical information is missing to validate this claim\??$", re.IGNORECASE),
        re.compile(r"^What evidence would directly contradict this claim\??$", re.IGNORECASE),
        re.compile(r"^What are the consequences if this claim is wrong\??$", re.IGNORECASE),
        re.compile(r"^What sub-factors or causal components explain this claim\??$", re.IGNORECASE),
    )

    def is_low_value_question(self, question_text: str, parent_claim: str) -> bool:
        q = self._clean(question_text)
        parent = self._clean(parent_claim)
        if len(q) < 24:
            return True
        if self._nested_meta_count(q) > 1:
            return True
        if q.lower() == parent.lower():
            return True
        if any(pattern.match(q) for pattern in self.GENERIC_QUESTION_PATTERNS):
            return True
        return False

    def is_low_value_claim(self, claim: str, parent_claim: str | None = None) -> bool:
        cleaned = self._clean(claim)
        if len(cleaned) < 24:
            return True
        if self._nested_meta_count(cleaned) > 1:
            return True
        if cleaned.count(":") >= 4:
            return True
        if parent_claim is not None and self._canonical(cleaned) == self._canonical(parent_claim):
            return True
        return False

    def filter_claims(self, claims: list[str], parent_claim: str | None = None) -> list[str]:
        filtered: list[str] = []
        seen: set[str] = set()
        for claim in claims:
            if self.is_low_value_claim(claim, parent_claim=parent_claim):
                continue
            key = self._canonical(claim)
            if key in seen:
                continue
            seen.add(key)
            filtered.append(claim)
        return filtered

    def _nested_meta_count(self, text: str) -> int:
        lowered = text.lower()
        return sum(lowered.count(prefix) for prefix in self.META_PREFIXES)

    def _canonical(self, text: str) -> str:
        lowered = self._clean(text).lower()
        previous = None
        while lowered != previous:
            previous = lowered
            for prefix in self.META_PREFIXES:
                if lowered.startswith(prefix):
                    lowered = lowered[len(prefix):].strip()
        lowered = re.sub(r"\s+", " ", lowered)
        lowered = lowered.strip(" .:-`\"'")
        return lowered

    def _clean(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
