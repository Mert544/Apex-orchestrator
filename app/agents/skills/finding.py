"""Self-contained Finding/Severity types.

Previously these came from an external `apex_debug` package, which made the
debug/self-healing agents unimportable (and untestable) without that dependency.
Apex now owns these types and derives findings from its own SecurityAgent /
SelfAuditAgent — zero external dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Severity(IntEnum):
    """Ordered severity so comparisons (`f.severity >= Severity.HIGH`) work."""

    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @classmethod
    def from_name(cls, name: str) -> "Severity":
        try:
            return cls[name.upper()]
        except KeyError:
            return cls.LOW


@dataclass
class Finding:
    """A single code issue, independent of any external analyzer."""

    title: str
    message: str = ""
    category: str = "correctness"
    severity: Severity = Severity.LOW
    file: str = ""
    line: int = 0
    confidence: float = 0.9

    def location_str(self) -> str:
        return f"{self.file}:{self.line}" if self.file else "?"

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "message": self.message,
            "category": self.category,
            "severity": self.severity.name,
            "file": self.file,
            "line": self.line,
            "confidence": self.confidence,
        }
