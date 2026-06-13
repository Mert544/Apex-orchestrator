"""The bucketed duplication detector must match a brute-force reference exactly.

``find_duplicates`` was rewritten to group candidate statement-blocks by a
normalized fingerprint (a dict bucket) and to dump each statement once instead of
re-dumping it for every overlapping window. These tests pin the contract that the
optimization is behaviour-preserving: on the same project the bucketed result is
byte-for-byte identical to an independent O(n²)-style brute-force computation that
encodes the SAME equivalence (structural ``ast.dump`` with positions stripped,
identifier names kept). They also guard the determinism and ordering invariants
and the near-duplicate boundary (renamed locals must NOT collapse together).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.dedup import DuplicateBlock, find_duplicates


# --- brute-force reference ----------------------------------------------------
# A deliberately naive re-derivation of the SAME equivalence the detector uses:
# every window's fingerprint is the "\n"-joined ``ast.dump`` (no positions) of its
# statements, compared by quadratic pairwise scan, location-deduped, then sorted
# exactly as the real implementation sorts. If the bucketed code ever drifts in
# what it considers "the same block", this reference disagrees and the test fails.

def _is_fixture(rel: str) -> bool:
    p = rel.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


def _reference_find(
    root: Path, min_statements: int = 5, min_occurrences: int = 2
) -> list[DuplicateBlock]:
    """Brute-force, pairwise duplication scan — the trusted oracle.

    Collects every window as ``(fingerprint, location)`` first, then forms groups
    by pairwise fingerprint comparison (O(n²)) rather than a dict, to prove the
    fast bucketing reproduces the same equivalence classes.
    """
    windows: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if _is_fixture(rel):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = node.body
            limit = len(body) - min_statements + 1
            if limit <= 0:
                continue
            for start in range(limit):
                win = body[start:start + min_statements]
                fp = "\n".join(
                    ast.dump(s, annotate_fields=False) for s in win
                )
                windows.append((fp, f"{rel}:{win[0].lineno}"))

    # Pairwise grouping: build equivalence classes by comparing fingerprints.
    fingerprints: list[str] = []
    locations_by_fp: dict[str, list[str]] = {}
    for fp, loc in windows:
        match = None
        for known in fingerprints:  # the explicit O(n²) comparison
            if known == fp:
                match = known
                break
        if match is None:
            fingerprints.append(fp)
            locations_by_fp[fp] = []
            match = fp
        if loc not in locations_by_fp[match]:
            locations_by_fp[match].append(loc)

    blocks = [
        DuplicateBlock(
            fingerprint=fp,
            lines=min_statements,
            occurrences=sorted(locs),
        )
        for fp, locs in locations_by_fp.items()
        if len(locs) >= min_occurrences
    ]
    blocks.sort(key=lambda b: (-b.lines, b.fingerprint))
    return blocks


def _write(root: Path, rel: str, src: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(src, encoding="utf-8")


_DUP = (
    "    total = 0\n"
    "    total += 1\n"
    "    total += 2\n"
    "    total += 3\n"
    "    return total\n"
)


def test_bucketed_matches_bruteforce_on_duplicates(tmp_path: Path) -> None:
    # Two genuine copies of the same 5-statement block in distinct modules.
    _write(tmp_path, "app/a.py", f"def alpha():\n{_DUP}")
    _write(tmp_path, "app/b.py", f"def beta():\n{_DUP}")
    # A near-duplicate: same structure but renamed locals -> NOT a match, because
    # identifier names are part of the fingerprint.
    near = _DUP.replace("total", "count")
    _write(tmp_path, "app/c.py", f"def gamma():\n{near}")

    got = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    ref = _reference_find(tmp_path, min_statements=5, min_occurrences=2)

    assert [b.to_dict() for b in got] == [b.to_dict() for b in ref]
    # Sanity: exactly one block (alpha+beta), and the renamed copy is excluded.
    assert len(got) == 1
    locs = got[0].occurrences
    assert locs == ["app/a.py:2", "app/b.py:2"]
    assert all("c.py" not in loc for loc in locs)


def test_bucketed_matches_bruteforce_overlapping_and_unique(tmp_path: Path) -> None:
    # A longer body so overlapping windows exercise the per-statement dump cache;
    # plus a unique function that produces buckets of size 1 (filtered out).
    long_body = "".join(f"    a = a + {i}\n" for i in range(10))
    _write(tmp_path, "app/x.py", f"def f():\n    a = 0\n{long_body}    return a\n")
    _write(tmp_path, "app/y.py", f"def g():\n    a = 0\n{long_body}    return a\n")
    _write(
        tmp_path,
        "app/z.py",
        "def h():\n    p = 1\n    q = 2\n    r = 3\n    s = 4\n    return p\n",
    )

    for min_stmts in (3, 5, 7):
        got = find_duplicates(tmp_path, min_statements=min_stmts, min_occurrences=2)
        ref = _reference_find(tmp_path, min_statements=min_stmts, min_occurrences=2)
        assert [b.to_dict() for b in got] == [b.to_dict() for b in ref], min_stmts
        # The shared block must surface; the unique h() must never appear.
        assert got, min_stmts
        assert all("z.py" not in loc for b in got for loc in b.occurrences)


def test_bucketed_matches_bruteforce_on_self_repeat(tmp_path: Path) -> None:
    # The same run pasted back-to-back inside one function: two distinct linenos,
    # one bucket, no location double-counted. Reference and impl must agree.
    repeated = "def f():\n" + _DUP + _DUP
    _write(tmp_path, "app/a.py", repeated)

    got = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    ref = _reference_find(tmp_path, min_statements=5, min_occurrences=2)
    assert [b.to_dict() for b in got] == [b.to_dict() for b in ref]
    assert len(got) == 1
    assert len(got[0].occurrences) == len(set(got[0].occurrences)) == 2


def test_empty_project_returns_empty(tmp_path: Path) -> None:
    # No modules at all, and an unparseable module: both contribute nothing.
    got = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert got == []
    _write(tmp_path, "app/broken.py", "def f(:\n    pass\n")  # SyntaxError
    got = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    ref = _reference_find(tmp_path, min_statements=5, min_occurrences=2)
    assert got == [] == ref


def test_min_occurrences_three_matches_reference(tmp_path: Path) -> None:
    # Three copies; with min_occurrences=3 the block survives, with =4 it does not.
    for name in ("a", "b", "c"):
        _write(tmp_path, f"app/{name}.py", f"def {name}():\n{_DUP}")

    got3 = find_duplicates(tmp_path, min_statements=5, min_occurrences=3)
    ref3 = _reference_find(tmp_path, min_statements=5, min_occurrences=3)
    assert [b.to_dict() for b in got3] == [b.to_dict() for b in ref3]
    assert len(got3) == 1 and len(got3[0].occurrences) == 3

    got4 = find_duplicates(tmp_path, min_statements=5, min_occurrences=4)
    assert got4 == []
