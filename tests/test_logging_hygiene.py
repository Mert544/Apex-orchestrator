"""Tests for the deterministic logging-hygiene analyzer."""

from __future__ import annotations

from app.tools.logging_hygiene import (
    LoggingHygiene,
    _is_entrypoint_module,
    _is_excluded_path,
    analyze_logging_hygiene,
)


def _write(tmp_path, rel, source):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


# ── print() in library code ─────────────────────────────────────────────────

def test_print_in_library_flagged(tmp_path):
    _write(tmp_path, "lib.py", "def f():\n    print('hi')\n")
    res = analyze_logging_hygiene(tmp_path)
    assert res.print_calls == 1
    assert res.offenders == [{"module": "lib.py", "line": 2, "kind": "print"}]


def test_print_in_cli_module_not_flagged(tmp_path):
    _write(tmp_path, "cli_run.py", "def f():\n    print('hi')\n")
    _write(tmp_path, "main.py", "print('go')\n")
    _write(tmp_path, "tool_cli.py", "print('go')\n")
    res = analyze_logging_hygiene(tmp_path)
    assert res.print_calls == 0
    assert res.offenders == []


def test_print_under_main_guard_not_flagged(tmp_path):
    _write(
        tmp_path,
        "lib.py",
        "def f():\n"
        "    return 1\n"
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    print('go')\n",
    )
    res = analyze_logging_hygiene(tmp_path)
    assert res.print_calls == 0


# ── eager interpolation passed to a logging call ────────────────────────────

def test_eager_fstring_flagged(tmp_path):
    _write(
        tmp_path,
        "lib.py",
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def f(x):\n"
        '    logger.info(f"x={x}")\n',
    )
    res = analyze_logging_hygiene(tmp_path)
    assert res.eager_format_calls == 1
    assert any(o["kind"] == "eager_format" for o in res.offenders)


def test_lazy_logging_not_flagged(tmp_path):
    _write(
        tmp_path,
        "lib.py",
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def f(x):\n"
        '    logger.info("x=%s", x)\n',
    )
    res = analyze_logging_hygiene(tmp_path)
    assert res.eager_format_calls == 0


def test_percent_and_format_flagged(tmp_path):
    _write(
        tmp_path,
        "lib.py",
        "def f(x):\n"
        '    log.info("x=%s" % x)\n'
        '    log.debug("x={}".format(x))\n',
    )
    res = analyze_logging_hygiene(tmp_path)
    assert res.eager_format_calls == 2


def test_constant_fstring_not_flagged(tmp_path):
    # f-string with no replacement fields costs nothing.
    _write(
        tmp_path,
        "lib.py",
        "def f():\n"
        '    logger.info(f"done")\n',
    )
    res = analyze_logging_hygiene(tmp_path)
    assert res.eager_format_calls == 0


def test_non_logger_info_not_flagged(tmp_path):
    # ``.info`` on something that is not a logger-like name is ignored.
    _write(
        tmp_path,
        "lib.py",
        "def f(response, x):\n"
        '    response.info(f"x={x}")\n',
    )
    res = analyze_logging_hygiene(tmp_path)
    assert res.eager_format_calls == 0


def test_self_logger_flagged(tmp_path):
    _write(
        tmp_path,
        "lib.py",
        "class C:\n"
        "    def f(self, x):\n"
        '        self.logger.info(f"x={x}")\n',
    )
    res = analyze_logging_hygiene(tmp_path)
    assert res.eager_format_calls == 1


# ── error/exception outside an except block ─────────────────────────────────

def test_error_outside_except_flagged(tmp_path):
    _write(
        tmp_path,
        "lib.py",
        "def f():\n"
        '    logger.error("boom")\n',
    )
    res = analyze_logging_hygiene(tmp_path)
    assert res.error_outside_except == 1


def test_error_inside_except_not_flagged(tmp_path):
    _write(
        tmp_path,
        "lib.py",
        "def f():\n"
        "    try:\n"
        "        g()\n"
        "    except ValueError:\n"
        '        logger.exception("boom")\n',
    )
    res = analyze_logging_hygiene(tmp_path)
    assert res.error_outside_except == 0


def test_log_method_message_index(tmp_path):
    # logger.log(level, msg): message is the SECOND positional arg.
    _write(
        tmp_path,
        "lib.py",
        "import logging\n"
        "def f(x):\n"
        '    logger.log(logging.INFO, f"x={x}")\n',
    )
    res = analyze_logging_hygiene(tmp_path)
    assert res.eager_format_calls == 1


# ── exclusions ──────────────────────────────────────────────────────────────

def test_tests_excluded(tmp_path):
    _write(tmp_path, "tests/test_thing.py", "print('hi')\n")
    _write(tmp_path, "pkg/test_helper.py", "print('hi')\n")
    _write(tmp_path, "fixtures/data.py", "print('hi')\n")
    res = analyze_logging_hygiene(tmp_path)
    assert res.print_calls == 0
    assert res.offenders == []


# ── empty / determinism ─────────────────────────────────────────────────────

def test_empty_tree_is_safe(tmp_path):
    res = analyze_logging_hygiene(tmp_path)
    assert isinstance(res, LoggingHygiene)
    assert res.print_calls == 0
    assert res.eager_format_calls == 0
    assert res.error_outside_except == 0
    assert res.offenders == []


def test_missing_root_is_safe(tmp_path):
    res = analyze_logging_hygiene(tmp_path / "does_not_exist")
    assert res.offenders == []
    assert res.print_calls == 0


def test_deterministic(tmp_path):
    _write(tmp_path, "b.py", "print('a')\n")
    _write(tmp_path, "a.py", "def f():\n    logger.error('x')\n")
    first = analyze_logging_hygiene(tmp_path)
    second = analyze_logging_hygiene(tmp_path)
    assert first == second
    # Offenders are sorted by (module, line, kind).
    assert [o["module"] for o in first.offenders] == ["a.py", "b.py"]


def test_offender_cap(tmp_path):
    body = "".join(f"print('{i}')\n" for i in range(40))
    _write(tmp_path, "lib.py", body)
    res = analyze_logging_hygiene(tmp_path)
    assert res.print_calls == 40
    assert len(res.offenders) == 20


# ── predicate helpers ───────────────────────────────────────────────────────

def test_entrypoint_predicate():
    assert _is_entrypoint_module("main")
    assert _is_entrypoint_module("__main__")
    assert _is_entrypoint_module("cli")
    assert _is_entrypoint_module("cli_run")
    assert _is_entrypoint_module("tool_cli")
    assert not _is_entrypoint_module("library")


def test_excluded_path_predicate():
    assert _is_excluded_path("tests/test_x.py")
    assert _is_excluded_path("pkg/test_x.py")
    assert _is_excluded_path("examples/demo.py")
    assert not _is_excluded_path("app/tools/thing.py")
