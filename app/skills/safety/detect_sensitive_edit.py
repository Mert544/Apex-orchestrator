from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SensitiveEditResult:
    touched_sensitive_paths: list[str]
    detected_hints: dict[str, list[str]]

    @property
    def ok(self) -> bool:
        return not self.touched_sensitive_paths


class DetectSensitiveEditSkill:
    DEFAULT_HINTS = {
        "auth": ["auth", "login", "session"],
        "payments": ["payment", "billing", "invoice"],
        "secrets": ["secret", "token", "credential", "key"],
        "workflows": [".github/workflows"],
    }

    def run(self, changed_files: list[str], hints: dict[str, list[str]] | None = None) -> SensitiveEditResult:
        mapping = hints or self.DEFAULT_HINTS
        touched: list[str] = []
        detected: dict[str, list[str]] = {}

        for path in changed_files:
            lowered = path.lower()
            matched_categories = [
                category
                for category, values in mapping.items()
                if any(value in lowered for value in values)
            ]
            if matched_categories:
                touched.append(path)
                detected[path] = matched_categories

        return SensitiveEditResult(
            touched_sensitive_paths=touched,
            detected_hints=detected,
        )
