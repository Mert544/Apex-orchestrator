import argparse

from app.cli import cmd_debug


def test_cli_debug_trace_writes_report(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("x = 1\n")
    args = argparse.Namespace(subcommand="trace", target=str(tmp_path), json=False)
    assert cmd_debug(args) == 0
    out = capsys.readouterr().out
    assert "APEX DEBUG TRACE" in out
    assert list((tmp_path / ".apex" / "debug").glob("debug-*.json"))


def test_cli_debug_analyze_identifies_cause(tmp_path, capsys):
    tb = (
        "Traceback (most recent call last):\n"
        "  File 'x.py', line 1, in <module>\n"
        "ImportError: No module named foo\n"
    )
    f = tmp_path / "tb.txt"
    f.write_text(tb)
    args = argparse.Namespace(
        subcommand="analyze", target=str(tmp_path), trace=str(f), file="", json=True
    )
    assert cmd_debug(args) == 0
    assert "ImportError" in capsys.readouterr().out


def test_cli_debug_analyze_human_output(tmp_path, capsys):
    args = argparse.Namespace(
        subcommand="analyze", target=str(tmp_path), trace="-", file="", json=False
    )
    import io
    import sys
    sys.stdin = io.StringIO("ImportError: No module named foo\n")
    try:
        assert cmd_debug(args) == 0
    finally:
        sys.stdin = sys.__stdin__
    out = capsys.readouterr().out
    assert "APEX DEBUG ANALYZE" in out
    assert "ImportError" in out
