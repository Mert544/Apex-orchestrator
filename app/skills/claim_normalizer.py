from __future__ import annotations

import re


class ClaimNormalizer:
    QUESTION_PATTERNS = [
        (
            re.compile(r"^What critical information is missing to validate this claim:\s*(.+?)\?*$", re.IGNORECASE),
            "Missing-information claim: the project still lacks critical evidence, constraints, or implementation detail needed to validate {claim}.",
        ),
        (
            re.compile(r"^What evidence would directly contradict this claim:\s*(.+?)\?*$", re.IGNORECASE),
            "Contradiction claim: direct counter-evidence should be sought against {claim}.",
        ),
        (
            re.compile(r"^What are the consequences if this claim is wrong:\s*(.+?)\?*$", re.IGNORECASE),
            "Risk claim: if {claim} is wrong, downstream project decisions may become brittle, unsafe, or low quality.",
        ),
        (
            re.compile(r"^What sub-factors or causal components explain this claim:\s*(.+?)\?\s*Assumption anchor:\s*(.+)$", re.IGNORECASE),
            "Deepening claim: the underlying sub-factors and causal components behind {claim} should be decomposed further. Assumption anchor: {anchor}.",
        ),
        (
            re.compile(r"^What sub-factors or causal components explain this claim:\s*(.+?)\?*$", re.IGNORECASE),
            "Deepening claim: the underlying sub-factors and causal components behind {claim} should be decomposed further.",
        ),
    ]

    NORMALIZED_PATTERNS = [
        re.compile(r"^Missing-information claim: .*? needed to validate (.+?)(?:\.)?$", re.IGNORECASE),
        re.compile(r"^Contradiction claim: direct counter-evidence should be sought against (.+?)(?:\.)?$", re.IGNORECASE),
        re.compile(r"^Risk claim: if (.+?) is wrong, .*", re.IGNORECASE),
        re.compile(r"^Deepening claim: .*? behind (.+?) should be decomposed further(?:\. Assumption anchor: .+)?(?:\.)?$", re.IGNORECASE),
        re.compile(r"^Investigation claim: (.+?)(?:\.)?$", re.IGNORECASE),
    ]

    def normalize(self, text: str) -> str | None:
        cleaned = self._clean(text)
        if not cleaned:
            return None

        for pattern, template in self.QUESTION_PATTERNS:
            match = pattern.match(cleaned)
            if not match:
                continue
            groups = match.groups()
            claim = self._clean_claim(groups[0])
            anchor = self._clean_claim(groups[1]) if len(groups) > 1 else None
            normalized = template.format(claim=claim, anchor=anchor)
            return self._finalize(normalized)

        if self._looks_like_question(cleaned):
            return self._finalize(f"Investigation claim: {cleaned.rstrip(' ?')}.")

        return self._finalize(self._clean_claim(cleaned))

    def split_sentences(self, text: str, limit: int = 5) -> list[str]:
        cleaned = self._clean(text)
        if not cleaned:
            return []
        parts = re.split(r"(?<=[!?])\s+|(?<=[A-Za-z0-9])\.\s+", cleaned)
        claims: list[str] = []
        for part in parts:
            normalized = self.normalize(part)
            if self.is_viable(normalized):
                claims.append(normalized)
        return list(dict.fromkeys(claims))[:limit]

    def is_viable(self, claim: str | None) -> bool:
        if not claim:
            return False
        lowered = claim.lower().strip()
        if len(lowered) < 24:
            return False
        if lowered.startswith("what "):
            return False
        if lowered in {"py.", "py", "js.", "js", "ts.", "ts", "md.", "md"}:
            return False
        if lowered.count("?") > 0:
            return False
        punctuation_only = re.sub(r"[a-z0-9_/.-]", "", lowered)
        return not (len(punctuation_only) > len(lowered) * 0.4)

    def _looks_like_question(self, text: str) -> bool:
        lowered = text.lower().strip()
        starters = ("what ", "which ", "why ", "how ", "where ", "when ")
        return lowered.endswith("?") or lowered.startswith(starters)

    def _clean(self, text: str) -> str:
        text = text.replace("\n", " ").strip()
        text = re.sub(r"\s+", " ", text)
        return text

    def _clean_claim(self, text: str) -> str:
        cleaned = self._clean(text)
        cleaned = re.sub(r"^(this claim|claim)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bAssumption anchor:.*$", "", cleaned, flags=re.IGNORECASE)
        previous = None
        while cleaned != previous:
            previous = cleaned
            for pattern in self.NORMALIZED_PATTERNS:
                match = pattern.match(cleaned)
                if match:
                    cleaned = self._clean(match.group(1))
                    break
        return cleaned.strip(" .?;:-")

    def _finalize(self, text: str) -> str | None:
        cleaned = self._clean(text)
        if not cleaned:
            return None
        cleaned = cleaned.strip(" -")
        if not cleaned.endswith("."):
            cleaned += "."
        return cleaned
