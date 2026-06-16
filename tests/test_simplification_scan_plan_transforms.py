"""Scanner coverage for the four on-disk ``plan_*`` simplification transforms.

``nested_with`` / ``comprehension`` / ``use_enumerate`` / ``simplify_len_comparison``
live under ``app/execution/`` as ``plan_<name>(root, rel) -> RenamePlan`` rewrites
rather than in-memory ``apply``. ``plan_to_apply`` adapts each to the uniform
``apply(rel, source, title)`` dry-run shape, so the scanner detects them exactly
like every other safe transform: a positive sample yields the EXECUTABLE
fact-label the bridge routes to the real transform, a negative sample fabricates
nothing, and the whole scan stays deterministic and a superset.

``merge_isinstance`` is deliberately NOT among them (it duplicates the already
wired ``isinstance-merge`` in-memory transform).
"""

from app.tools.simplification_scan import plan_to_apply, scan_simplifications

# A positive sample per transform plus the exact fact-label the scanner emits.
_POSITIVES = {
    "nested-with": (
        "def f(a, b):\n"
        "    with open(a) as x:\n"
        "        with open(b) as y:\n"
        "            return x, y\n"
    ),
    "comprehension": (
        "def f(items):\n"
        "    out = []\n"
        "    for i in items:\n"
        "        out.append(i + 1)\n"
        "    return out\n"
    ),
    "use-enumerate": (
        "def f(seq):\n"
        "    for i in range(len(seq)):\n"
        "        print(seq[i])\n"
    ),
}

_NEGATIVE = "def f(x):\n    return x + 1\n"


def test_scanner_detects_each_plan_transform(tmp_path):
    # Each positive sample, in its own real source file, surfaces exactly its
    # executable fact-label with the matching module + transform fields.
    for i, (label, src) in enumerate(_POSITIVES.items()):
        d = tmp_path / f"case{i}"
        d.mkdir()
        (d / "m.py").write_text(src, encoding="utf-8")
        opps = scan_simplifications(d)
        labels = {o["fact_label"] for o in opps}
        assert label in labels, (label, labels)
        hit = next(o for o in opps if o["fact_label"] == label)
        assert hit["module"] == "m.py"
        # transform field is the underscore form of the fact-label.
        assert hit["transform"] == label.replace("-", "_")


def test_scanner_plan_transforms_skip_clean_file(tmp_path):
    # A file with none of the four shapes fabricates none of the new labels.
    (tmp_path / "clean.py").write_text(_NEGATIVE, encoding="utf-8")
    labels = {o["fact_label"] for o in scan_simplifications(tmp_path)}
    for label in ("nested-with", "comprehension", "use-enumerate", "len-comparison"):
        assert label not in labels


def test_plan_to_apply_refuses_on_clean_source(tmp_path):
    # The adapter itself returns None (refuse-on-unsafe) when the underlying
    # plan is a no-op — never a fabricated patch.
    from app.execution.nested_with import plan_combine_nested_with

    apply = plan_to_apply(plan_combine_nested_with)
    assert apply("m.py", _NEGATIVE, "t") is None


def test_plan_to_apply_emits_patch_request_on_positive():
    # A positive sample yields a SemanticPatchResult carrying the original as
    # expected_old_content and the rewritten text as new_content — the same
    # shape the in-memory transforms emit, so apply_step treats it identically.
    from app.execution.nested_with import plan_combine_nested_with

    src = _POSITIVES["nested-with"]
    apply = plan_to_apply(plan_combine_nested_with)
    result = apply("app/m.py", src, "t")
    assert result is not None
    pr = result.patch_requests[0]
    assert pr["path"] == "app/m.py"
    assert pr["expected_old_content"] == src
    assert "with open(a) as x, open(b) as y:" in pr["new_content"]
    assert pr["new_content"] != src


def test_plan_to_apply_swallows_a_raising_plan():
    # A plan callable that raises is treated as "would not safely act" (None) —
    # never a fabricated opportunity. This also guards the family against a
    # transiently-broken upstream transform module.
    def _boom(_root, _rel):
        raise RuntimeError("exotic input")

    apply = plan_to_apply(_boom)
    assert apply("m.py", "x = 1\n", "t") is None


def test_plan_to_apply_is_pure_no_tree_writes(tmp_path):
    # The adapter materialises source into a throwaway temp dir only — it must
    # not read or write the caller's project tree (it is handed source text).
    src = _POSITIVES["comprehension"]
    from app.execution.comprehension import plan_simplify_comprehension

    apply = plan_to_apply(plan_simplify_comprehension)
    before = set(tmp_path.rglob("*"))
    result = apply("app/sub/m.py", src, "t")
    after = set(tmp_path.rglob("*"))
    assert result is not None
    assert before == after  # nothing created under the caller's tree


def test_scanner_with_plan_positives_is_deterministic_superset(tmp_path):
    # Planting positives for the plan transforms keeps the scan deterministic
    # and the result a superset of what the prior labels would have produced
    # (the new labels only ADD rows; they never drop an existing one).
    (tmp_path / "w.py").write_text(_POSITIVES["nested-with"], encoding="utf-8")
    (tmp_path / "c.py").write_text(_POSITIVES["comprehension"], encoding="utf-8")
    first = scan_simplifications(tmp_path)
    second = scan_simplifications(tmp_path)
    assert first == second
    modules = [o["module"] for o in first]
    assert modules == sorted(modules)
    labels = {o["fact_label"] for o in first}
    assert {"nested-with", "comprehension"} <= labels
