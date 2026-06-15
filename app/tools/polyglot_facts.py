"""Language-agnostic facts layer — make Apex's "X% out of analysis scope" line
ACTIONABLE.

``project_profile`` already reports, honestly, that on a polyglot repo Apex's
Python-only analysis covers a subset (``out_of_scope_ratio``,
``language_breakdown``). But it stops at counts: it says nothing CONCRETE about
that out-of-scope remainder, so on a JS/HTML-heavy repo Apex silently abandons
the non-Python part of the very project it claims to develop.

This module closes that gap one factual step: it names the biggest / most-churned
NON-Python source files — the place the non-Python risk actually concentrates —
without pretending to deep-analyse them. It is deliberately neutral and pure:

  - the canonical ``app.engine.skip_dirs.is_skipped`` predicate is the ONLY skip
    set (no rolled-own exclusions), so it stays consistent with every other walk;
  - LOC is non-blank line count (read locally);
  - churn is git commit count, computed in a SINGLE ``git log`` pass (never one
    subprocess per file) that is memoised per ``(repo, HEAD)`` for the process —
    so the several entry points that scan one build's repo state pay the full
    walk once, gated by a cheap ``git rev-parse HEAD`` — degrading to 0 on any
    error (non-git dir, timeout, …) rather than raising;
  - ranking is deterministic: ``(-churn, -loc, path)`` — same input, same output,
    no time/random anywhere.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.engine.skip_dirs import is_skipped

__all__ = ["FileFact", "scan_polyglot_facts", "render_polyglot_attention"]

# Non-Python source extension -> normalised language name. Mirrors the
# extension/language map ``ProjectProfiler._SCOPE_LANGUAGE_BY_EXT`` uses for the
# scope breakdown, minus the Python entries (those are the IN-scope subset and
# never appear here). An explicit allow-list: only these extensions are treated
# as deep-analysable-elsewhere source worth naming.
_LANGUAGE_BY_EXT: dict[str, str] = {
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C", ".h": "C",
    ".cc": "C++", ".cpp": "C++", ".cxx": "C++", ".hpp": "C++", ".hh": "C++",
    ".cs": "C#",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".swift": "Swift",
    ".sh": "Shell", ".bash": "Shell",
    ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "CSS", ".sass": "CSS",
    ".sql": "SQL",
    ".vue": "Vue",
}

# Python is the IN-scope subset Apex already deep-analyses — never named here.
_PYTHON_EXTENSIONS = {".py", ".pyi"}

# Language-agnostic technical-debt markers. Word-boundary, case-insensitive, so
# ``TODO`` matches but ``TODOLIST`` does not; works on ANY text file regardless
# of comment syntax. A precompiled, deterministic regex — no time/random.
_DEBT_MARKER_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)

# Sanity cap: a pathological generated file shouldn't report an absurd count.
_DEBT_MARKER_CAP = 9999

# Explicit deny set: lockfiles / generated manifests whose extension might map to
# a language but whose CONTENT is machine-written, so naming them as "files worth
# attention" would be noise. Matched on the full lowercased basename.
_DENY_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock",
    "cargo.lock", "gemfile.lock", "poetry.lock",
}


@dataclass(frozen=True)
class FileFact:
    """One non-Python source file Apex can name but not deep-analyse yet.

    ``has_test`` is a conservative, convention-based, NO-execution guess at
    whether the file is covered by a test (see ``_build_test_index`` /
    ``_file_has_test``). It is additive and defaults to ``False`` so existing
    facts/rankings keep their shape; an untested big active file is the
    highest-leverage non-Python risk, so it is surfaced first on ties.

    ``debt_markers`` is a language-agnostic count of ``TODO``/``FIXME``/``HACK``/
    ``XXX`` occurrences (case-insensitive, word-boundary) found in the file's
    text. It is additive and defaults to ``0``; it is purely informational and
    does NOT affect ranking. Counted in the SAME local read used for LOC.
    """

    path: str
    language: str
    loc: int
    churn: int
    has_test: bool = False
    debt_markers: int = 0


# Test-directory convention names: a file living under (or beside) one of these
# directories, whose stem references the source stem, counts as a test.
_TEST_DIR_NAMES = {"__tests__", "tests", "test", "spec"}

# Sibling-name test conventions, as stem suffixes/prefixes (joined to the source
# stem with the SAME extension): foo.test.ext, foo.spec.ext, foo_test.ext,
# test_foo.ext, foo_spec.ext.
def _conventional_test_stems(stem: str) -> set[str]:
    """The stems a test file for source ``stem`` would conventionally carry.

    Language-agnostic, name-only — never reads or executes anything. Returned as
    lowercased stems (the extension is appended by the caller / handled by the
    membership test on full names).
    """
    s = stem.lower()
    return {
        f"{s}.test", f"{s}.spec",
        f"{s}_test", f"{s}_spec", f"test_{s}",
    }


def _build_test_index(
    files: list[tuple[str, str]],
) -> tuple[set[str], list[tuple[frozenset[str], str]]]:
    """Build, in ONE pass over the already-collected file set, the lookup
    structures used to answer "does source X have a test?" without re-walking.

    ``files`` is ``(rel_posix, name_lower)`` for every non-skipped repo file
    (test files included). Returns:

      - ``test_names``: the set of lowercased basenames that match a sibling
        naming convention for SOME stem (e.g. ``app.test.js``). A source's test
        existence is then a single set lookup against the convention names its
        own stem would produce.
      - ``test_dir_files``: per file that lives under a recognised test
        directory, the set of "reference tokens" its name/path contributes,
        paired with the file's own stem — so a source can be matched if a
        test-dir file's stem references the source stem.

    Deterministic: derived purely from the sorted file set, no time/random.
    """
    test_names: set[str] = set()
    test_dir_files: list[tuple[frozenset[str], str]] = []
    for rel, name in files:
        test_names.add(name)
        parts = rel.split("/")
        if any(part in _TEST_DIR_NAMES for part in parts[:-1]):
            stem = name.rsplit(".", 1)[0] if "." in name else name
            # Tokens this test-dir file's stem could reference a source by:
            # the whole stem, and convention-stripped variants.
            tokens = {stem}
            for marker in ("_test", "_spec", ".test", ".spec"):
                if stem.endswith(marker):
                    tokens.add(stem[: -len(marker)])
            for marker in ("test_", "spec_"):
                if stem.startswith(marker):
                    tokens.add(stem[len(marker):])
            test_dir_files.append((frozenset(tokens), stem))
    return test_names, test_dir_files


def _file_has_test(
    rel: str,
    test_names: set[str],
    test_dir_files: list[tuple[frozenset[str], str]],
) -> bool:
    """Conservative convention-based test-presence check for source ``rel``.

    A test is deemed to exist when EITHER a sibling/anywhere file matches a
    naming convention for this stem (``foo.test.ext`` etc.), OR a file under a
    recognised test directory references this stem. When unsure, returns False
    (a false "untested" is an acceptable prompt; a false "tested" would hide
    risk). Pure: only set/list lookups, no I/O.
    """
    name = rel.rsplit("/", 1)[-1]
    if "." in name:
        stem, ext = name.rsplit(".", 1)
        ext = "." + ext
    else:
        stem, ext = name, ""
    stem_l = stem.lower()
    # Sibling naming conventions: foo.test.ext, foo_test.ext, test_foo.ext, ...
    for conv_stem in _conventional_test_stems(stem_l):
        if f"{conv_stem}{ext}".lower() in test_names:
            return True
    # Test-directory convention: a file under tests/ __tests__/ … whose stem
    # references this source's stem. Require the source stem to be a non-trivial
    # token (len >= 2) so a 1-char stem can't match everything.
    if len(stem_l) >= 2:
        for tokens, t_stem in test_dir_files:
            if stem_l == t_stem.lower():
                return True
            if stem_l in {t.lower() for t in tokens}:
                return True
    return False


def _loc_and_debt(path: Path) -> tuple[int, int]:
    """Non-blank LOC and debt-marker count from a SINGLE local read.

    Returns ``(loc, debt_markers)``. ``loc`` is the non-blank line count;
    ``debt_markers`` is the capped count of ``TODO``/``FIXME``/``HACK``/``XXX``
    matches (case-insensitive, word-boundary). Degrades to ``(0, 0)`` on any
    read error (never raises). No second read or walk is performed.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0, 0
    loc = sum(1 for line in text.splitlines() if line.strip())
    debt = min(len(_DEBT_MARKER_RE.findall(text)), _DEBT_MARKER_CAP)
    return loc, debt


# Process-level memo of the FULL repo churn map, keyed by ``(resolved_root,
# head_oid)``. A single ideate build calls ``scan_polyglot_facts`` from several
# entry points (project_profile, dashboard, cli_*), each of which would otherwise
# re-run the expensive full-history ``git log --name-only`` walk over the SAME
# repo state. Keying on the HEAD object id makes the cache safe: the moment HEAD
# moves (new commit), the key changes and the map is recomputed, so the churn /
# hotspots output stays IDENTICAL to a non-cached run for any given repo state.
# Purely a within-process speedup; no time/random, so determinism is unaffected.
_CHURN_CACHE: dict[tuple[str, str], dict[str, int]] = {}


def _git_head_oid(root: Path) -> str | None:
    """The current HEAD object id via ONE cheap ``git rev-parse HEAD`` call.

    ``git rev-parse`` resolves HEAD without walking history, so it is orders of
    magnitude cheaper than the ``git log`` churn pass it gates. Returns ``None``
    on any failure (non-git dir, missing git, timeout, empty repo with no
    commits) — the caller then degrades to the same empty churn map as today.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    oid = out.stdout.strip()
    return oid or None


def _compute_full_churn_map(root: Path) -> dict[str, int] | None:
    """The commit count for EVERY repo path, from a SINGLE ``git log`` pass.

    One ``git log --name-only`` invocation lists every file touched per commit;
    we tally how many commits touch each path. Never one subprocess per file.
    Returns ``None`` on any failure (missing git, timeout, non-zero exit) so the
    caller can distinguish "git failed" (degrade to empty, do NOT cache) from a
    genuinely empty map — preserving today's graceful behaviour exactly.
    """
    try:
        out = subprocess.run(
            ["git", "log", "--format=", "--name-only"],
            cwd=root, capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    counts: dict[str, int] = {}
    for raw in out.stdout.splitlines():
        rel = raw.strip()
        if rel:
            counts[rel] = counts.get(rel, 0) + 1
    return counts


def _git_churn(root: Path, candidates: set[str]) -> dict[str, int]:
    """Commit count per ``root``-relative candidate path, churn-cached per HEAD.

    The expensive full-history ``git log --name-only`` walk is run AT MOST ONCE
    per ``(repo, HEAD)`` per process: a cheap ``git rev-parse HEAD`` yields the
    cache key, and a hit reuses the already-parsed full churn map instead of
    re-shelling-out. The returned mapping is then the full map filtered to the
    requested ``candidates`` — byte-for-byte identical to tallying only the
    candidates in a fresh pass. Any failure (non-git dir, missing git, timeout,
    non-zero exit) degrades to an empty mapping — callers read churn 0 — and
    never raises. No time/random anywhere, so the result is deterministic.
    """
    if not candidates:
        return {}
    head = _git_head_oid(root)
    if head is None:
        return {}
    key = (str(root.resolve()), head)
    full = _CHURN_CACHE.get(key)
    if full is None:
        full = _compute_full_churn_map(root)
        if full is None:
            return {}
        _CHURN_CACHE[key] = full
    return {rel: full[rel] for rel in candidates if rel in full}


def scan_polyglot_facts(root: str, *, limit: int = 5) -> list[FileFact]:
    """The top ``limit`` non-Python source files worth attention, ranked.

    Walk ``root`` (skipping the canonical excluded directories via
    ``is_skipped`` — never a rolled-own skip set), keep every NON-Python source
    file whose extension is in the explicit language allow-list and whose
    basename is not a denied lockfile/manifest, then rank deterministically by
    ``(-churn, -loc, path)`` and return the strongest ``limit``.

    Pure and total: LOC is read locally; churn comes from one git pass that
    degrades to 0 on any error; the result is identical for a given repo state.
    """
    root_path = Path(root)
    if limit <= 0 or not root_path.exists():
        return []

    # SINGLE pass: collect both the non-Python source candidates AND the full
    # (rel, name) file set the convention-based test index is built from. We
    # never walk again per file and never shell out for test presence.
    all_files: list[tuple[str, str]] = []  # (rel_posix, name_lower)
    # (rel_posix, language, loc, debt_markers)
    candidates: list[tuple[str, str, int, int]] = []
    for path in root_path.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root_path)
        if is_skipped(rel):
            continue
        rel_posix = rel.as_posix()
        all_files.append((rel_posix, path.name.lower()))
        ext = path.suffix.lower()
        if ext in _PYTHON_EXTENSIONS:
            continue
        language = _LANGUAGE_BY_EXT.get(ext)
        if language is None:
            continue
        if path.name.lower() in _DENY_NAMES:
            continue
        loc, debt = _loc_and_debt(path)
        candidates.append((rel_posix, language, loc, debt))

    if not candidates:
        return []

    # Deterministic test index, derived from the sorted file set.
    all_files.sort()
    test_names, test_dir_files = _build_test_index(all_files)

    churn_by_path = _git_churn(
        root_path, {rel for rel, _lang, _loc, _debt in candidates}
    )
    facts = [
        FileFact(
            path=rel, language=language, loc=loc,
            churn=churn_by_path.get(rel, 0),
            has_test=_file_has_test(rel, test_names, test_dir_files),
            debt_markers=debt,
        )
        for rel, language, loc, debt in candidates
    ]
    # ``has_test`` is a LATER tiebreaker: primary ordering stays (-churn, -loc)
    # so the pinned ranking in tests/test_polyglot_facts.py is unchanged; among
    # otherwise-equal files, untested (False sorts before True) surfaces first.
    facts.sort(key=lambda f: (-f.churn, -f.loc, f.has_test, f.path))
    return facts[:limit]


def render_polyglot_attention(facts: list[FileFact]) -> str:
    """A short, calm clause naming the out-of-scope files worth attention.

    Empty string when there are none, so callers can append it unconditionally
    and an all-Python repo's output stays byte-identical.
    """
    if not facts:
        return ""
    # Only annotate test presence when the set actually carries the signal —
    # i.e. at least one file WAS found to have a test. On an all-untested set
    # (which includes hand-built facts with the default has_test=False) there is
    # nothing to contrast against, so the clause stays byte-identical to the
    # pre-test-presence output and existing pinned renders don't shift.
    annotate = any(f.has_test for f in facts)
    # Debt markers are annotated the same gated, additive way as test presence:
    # only when at least one file actually carries the signal, and per-file only
    # when that file's count is > 0. On a no-debt set this stays byte-identical
    # to the pre-debt output, so existing pinned renders don't shift.
    annotate_debt = any(f.debt_markers for f in facts)
    parts = []
    for fact in facts:
        commit_word = "commit" if fact.churn == 1 else "commits"
        suffix = " (no test found)" if annotate and not fact.has_test else ""
        debt_suffix = (
            f" ({fact.debt_markers} TODO/FIXME)"
            if annotate_debt and fact.debt_markers
            else ""
        )
        parts.append(
            f"`{fact.path}` ({fact.loc} LOC, {fact.churn} {commit_word})"
            f"{suffix}{debt_suffix}"
        )
    return (
        "Largest / most-active files outside analysis scope: "
        + ", ".join(parts)
        + " — Apex can't deep-analyse these yet, but they're where the "
        "non-Python risk concentrates."
    )
