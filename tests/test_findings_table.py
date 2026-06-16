"""Tests for the fixed-width ASCII findings table."""

from __future__ import annotations

from dataclasses import dataclass

from app.reporting.findings_table import findings_to_table


@dataclass
class F:
    file: str
    line: int
    category: str
    severity: str
    message: str


def _sample() -> list[F]:
    return [
        F("app/b.py", 12, "security", "high", "eval() — code injection risk"),
        F("app/a.py", 3, "style", "low", "compare to None with `is`"),
        F("app/a.py", 1, "bug", "medium", "mutable default argument"),
    ]


def test_empty_returns_sentinel():
    assert findings_to_table([]) == "No findings."


def test_header_and_rows_present():
    out = findings_to_table(_sample())
    for header in ("Severity", "File:Line", "Category", "Message"):
        assert header in out
    assert "app/b.py:12" in out
    assert "eval()" in out
    assert "mutable default argument" in out


def test_each_line_same_width():
    out = findings_to_table(_sample())
    lines = out.splitlines()
    assert len(lines) > 4  # rules + header + 3 rows
    widths = {len(line) for line in lines}
    assert len(widths) == 1  # every line aligned to the same width


def test_total_width_within_max():
    out = findings_to_table(_sample(), max_width=80)
    for line in out.splitlines():
        assert len(line) <= 80


def test_long_message_truncated_with_ellipsis():
    long = F("x.py", 1, "bug", "high", "M" * 500)
    out = findings_to_table([long], max_width=60)
    for line in out.splitlines():
        assert len(line) <= 60
    assert "..." in out
    # The full untruncated message must not survive.
    assert "M" * 500 not in out


def test_short_message_not_truncated():
    out = findings_to_table([F("x.py", 1, "bug", "high", "tiny")], max_width=120)
    assert "tiny" in out
    assert "..." not in out


def test_severity_ordering_high_first():
    out = findings_to_table([
        F("z.py", 1, "style", "low", "low one"),
        F("z.py", 2, "bug", "high", "high one"),
        F("z.py", 3, "bug", "medium", "medium one"),
    ])
    body = [ln for ln in out.splitlines() if "one" in ln]
    assert body[0].index("high one") >= 0
    # Order of appearance: high, medium, low.
    text = "\n".join(body)
    assert text.index("high one") < text.index("medium one") < text.index("low one")


def test_sort_by_path_then_line_within_severity():
    out = findings_to_table([
        F("b.py", 1, "bug", "high", "B1"),
        F("a.py", 9, "bug", "high", "A9"),
        F("a.py", 2, "bug", "high", "A2"),
    ])
    text = out
    assert text.index("A2") < text.index("A9") < text.index("B1")


def test_deterministic_same_input_same_output():
    sample = _sample()
    assert findings_to_table(sample) == findings_to_table(list(reversed(sample)))


def test_accepts_dict_findings():
    out = findings_to_table([
        {"file": "d.py", "line": 7, "category": "security", "severity": "high",
         "message": "os.system() — prefer subprocess.run()"},
    ])
    assert "d.py:7" in out
    assert "os.system()" in out


def test_truncation_with_tiny_message_budget():
    # A very narrow max_width forces the message column to the minimum; must
    # still produce aligned, in-spirit output without crashing.
    out = findings_to_table([F("some/long/path.py", 100, "security", "high", "x" * 50)])
    lines = out.splitlines()
    assert len({len(ln) for ln in lines}) == 1
