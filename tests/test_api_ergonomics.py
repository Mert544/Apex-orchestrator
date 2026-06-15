from __future__ import annotations

from app.tools.api_ergonomics import ApiErgonomics, analyze_api_ergonomics


def _write(tmp_path, name: str, src: str):
    p = tmp_path / name
    p.write_text(src, encoding="utf-8")
    return p


def test_long_parameter_list_is_flagged(tmp_path):
    _write(
        tmp_path,
        "m.py",
        "def wide(a, b, c, d, e, f):\n"
        "    return a\n",
    )
    rep = analyze_api_ergonomics(tmp_path)
    assert isinstance(rep, ApiErgonomics)
    assert rep.long_param_count == 1
    assert rep.offenders[0]["function"] == "wide"
    assert rep.offenders[0]["params"] == 6
    assert rep.offenders[0]["module"] == "m"
    assert "long parameter list" in rep.offenders[0]["reason"]


def test_boolean_trap_is_flagged(tmp_path):
    # Two bool params (one annotated, one bool-default) — a call-site riddle.
    _write(
        tmp_path,
        "b.py",
        "def render(text, bold: bool, italic=False):\n"
        "    return text\n",
    )
    rep = analyze_api_ergonomics(tmp_path)
    assert rep.boolean_trap_count == 1
    assert rep.long_param_count == 0  # only 3 params — not long
    off = rep.offenders[0]
    assert off["bool_params"] == 2
    assert "boolean trap" in off["reason"]


def test_single_bool_param_not_flagged(tmp_path):
    _write(
        tmp_path,
        "s.py",
        "def toggle(x, enabled: bool):\n"
        "    return x\n",
    )
    rep = analyze_api_ergonomics(tmp_path)
    assert rep.boolean_trap_count == 0
    assert rep.offenders == []


def test_clean_three_param_function_not_flagged(tmp_path):
    _write(
        tmp_path,
        "c.py",
        "def add(a, b, c):\n"
        "    return a + b + c\n",
    )
    rep = analyze_api_ergonomics(tmp_path)
    assert rep.functions_analyzed == 1
    assert rep.long_param_count == 0
    assert rep.boolean_trap_count == 0
    assert rep.positional_overload_count == 0
    assert rep.offenders == []


def test_dunders_excluded(tmp_path):
    # __init__ with many params is framework-shaped — never a target.
    _write(
        tmp_path,
        "d.py",
        "class C:\n"
        "    def __init__(self, a, b, c, d, e, f, g):\n"
        "        self.a = a\n",
    )
    rep = analyze_api_ergonomics(tmp_path)
    assert rep.long_param_count == 0
    assert rep.offenders == []


def test_self_and_cls_not_counted(tmp_path):
    # 5 real params after self => not > 5, so not flagged.
    _write(
        tmp_path,
        "r.py",
        "class C:\n"
        "    def method(self, a, b, c, d, e):\n"
        "        return a\n"
        "    @classmethod\n"
        "    def make(cls, a, b, c, d, e):\n"
        "        return cls\n",
    )
    rep = analyze_api_ergonomics(tmp_path)
    assert rep.long_param_count == 0
    assert rep.offenders == []


def test_args_kwargs_only_not_flagged(tmp_path):
    _write(
        tmp_path,
        "v.py",
        "def variadic(*args, **kwargs):\n"
        "    return args\n",
    )
    rep = analyze_api_ergonomics(tmp_path)
    assert rep.functions_analyzed == 1
    assert rep.offenders == []
    assert rep.positional_overload_count == 0


def test_positional_overload_vs_keyword_only_marker(tmp_path):
    # All-positional and long -> positional overload (and long list).
    _write(
        tmp_path,
        "p.py",
        "def loose(a, b, c, d, e, f):\n"
        "    return a\n",
    )
    rep = analyze_api_ergonomics(tmp_path)
    assert rep.positional_overload_count == 1
    off = rep.offenders[0]
    assert "positional overload" in off["reason"]

    # Same arity but a `*` marker protects the tail -> still long, NOT overload.
    _write(
        tmp_path,
        "p.py",
        "def guarded(a, b, c, *, d, e, f):\n"
        "    return a\n",
    )
    rep2 = analyze_api_ergonomics(tmp_path)
    assert rep2.positional_overload_count == 0
    assert rep2.long_param_count == 1  # 6 counted params is still a long list


def test_keyword_only_bool_counts_toward_trap(tmp_path):
    _write(
        tmp_path,
        "k.py",
        "def cfg(x, *, verbose: bool = False, dry_run: bool = False):\n"
        "    return x\n",
    )
    rep = analyze_api_ergonomics(tmp_path)
    assert rep.boolean_trap_count == 1
    assert rep.offenders[0]["bool_params"] == 2


def test_max_params_threshold_configurable(tmp_path):
    _write(
        tmp_path,
        "t.py",
        "def four(a, b, c, d):\n"
        "    return a\n",
    )
    assert analyze_api_ergonomics(tmp_path).long_param_count == 0
    # Lower the ceiling: 4 params now exceeds max_params=3.
    rep = analyze_api_ergonomics(tmp_path, max_params=3)
    assert rep.long_param_count == 1


def test_empty_tree_is_safe(tmp_path):
    rep = analyze_api_ergonomics(tmp_path)
    assert rep.files_analyzed == 0
    assert rep.functions_analyzed == 0
    assert rep.offenders == []
    assert rep.to_dict()["offenders"] == []


def test_unparseable_file_skipped(tmp_path):
    _write(tmp_path, "broken.py", "def oops(:\n    pass\n")
    _write(tmp_path, "ok.py", "def ok(a):\n    return a\n")
    rep = analyze_api_ergonomics(tmp_path)
    assert rep.files_analyzed == 1  # only ok.py parsed
    assert rep.functions_analyzed == 1


def test_offenders_capped_and_deterministic(tmp_path):
    # 20 distinct wide functions -> capped at 15, identical ordering each run.
    lines = []
    for i in range(20):
        params = ", ".join(f"p{j}" for j in range(6 + (i % 3)))
        lines.append(f"def fn{i:02d}({params}):\n    return p0\n")
    _write(tmp_path, "many.py", "\n".join(lines))

    rep_a = analyze_api_ergonomics(tmp_path)
    rep_b = analyze_api_ergonomics(tmp_path)
    assert len(rep_a.offenders) == 15
    assert rep_a.long_param_count == 20  # count reflects ALL offenders, not the cap
    assert rep_a.to_dict() == rep_b.to_dict()
    # Worst (most params) first.
    params_seq = [o["params"] for o in rep_a.offenders]
    assert params_seq == sorted(params_seq, reverse=True)


def test_skip_dirs_are_excluded(tmp_path):
    # A wide function inside a worktree copy must NOT be analyzed.
    nested = tmp_path / ".claude" / "worktrees" / "w" / "app"
    nested.mkdir(parents=True)
    (nested / "copy.py").write_text(
        "def wide(a, b, c, d, e, f):\n    return a\n", encoding="utf-8"
    )
    _write(tmp_path, "real.py", "def ok(a):\n    return a\n")
    rep = analyze_api_ergonomics(tmp_path)
    assert rep.files_analyzed == 1
    assert rep.long_param_count == 0
