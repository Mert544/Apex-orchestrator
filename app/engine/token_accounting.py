from __future__ import annotations

from math import ceil


class TokenAccounting:
    APPROX_CHARS_PER_TOKEN = 4

    def estimate_text_tokens(self, text: str) -> int:
        cleaned = text.strip()
        if not cleaned:
            return 0
        return max(1, ceil(len(cleaned) / self.APPROX_CHARS_PER_TOKEN))

    def estimate_many(self, texts: list[str]) -> int:
        return sum(self.estimate_text_tokens(text) for text in texts if text)
