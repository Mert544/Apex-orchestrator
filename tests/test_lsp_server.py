from __future__ import annotations

from app.lsp.server import LSPServer


def test_lsp_analyze_eval():
    server = LSPServer()
    diagnostics = server._analyze("file:///test.py", "def f(x):\n    return eval(x)\n")
    assert len(diagnostics) >= 1
    assert any("eval()" in d["message"] for d in diagnostics)


def test_lsp_analyze_bare_except():
    server = LSPServer()
    diagnostics = server._analyze("file:///test.py", "try:\n    pass\nexcept:\n    pass\n")
    assert any("bare except" in d["message"] for d in diagnostics)


def test_lsp_analyze_missing_docstring():
    server = LSPServer()
    diagnostics = server._analyze("file:///test.py", "def hello():\n    pass\n")
    assert any("missing docstring" in d["message"] for d in diagnostics)


def test_lsp_hover_info():
    server = LSPServer()
    info = server._get_hover_info("eval")
    assert "eval()" in info


def test_lsp_extract_symbols():
    server = LSPServer()
    symbols = server._extract_symbols("def foo():\n    pass\nclass Bar:\n    pass\n")
    assert len(symbols) == 2
    assert symbols[0]["name"] == "foo"
    assert symbols[1]["name"] == "Bar"


def test_lsp_analyze_os_system():
    from app.lsp.server import LSPServer
    diags = LSPServer()._analyze("file:///t.py", "import os\nos.system('ls')\n")
    assert any("os.system" in d["message"] for d in diags)


def test_lsp_analyze_syntax_error():
    from app.lsp.server import LSPServer
    diags = LSPServer()._analyze("file:///t.py", "def broken(:\n")
    assert any("SyntaxError" in d["message"] for d in diags)
    assert diags[0]["severity"] == 1


def test_lsp_extract_word():
    s = __import__("app.lsp.server", fromlist=["LSPServer"]).LSPServer()
    assert s._extract_word("    return eval(x)", 12) == "eval"
    assert s._extract_word("   ", 1) == ""


def test_lsp_hover_unknown_word():
    from app.lsp.server import LSPServer
    info = LSPServer()._get_hover_info("totally_unknown")
    assert "No specific Apex info" in info


def test_lsp_extract_symbols_kinds():
    from app.lsp.server import LSPServer
    syms = LSPServer()._extract_symbols("def foo():\n    pass\nclass Bar:\n    pass\n")
    names = {s["name"] for s in syms}
    assert "foo" in names and "Bar" in names


def test_lsp_handle_initialize_sends_capabilities():
    import io
    from app.lsp.server import LSPServer
    s = LSPServer()
    s.stdout = io.BytesIO()
    # _send_message writes to sys.stdout.buffer; patch the writer instead.
    sent = {}
    s._send_response = lambda id, result=None, error=None: sent.update({"id": id, "result": result})
    s._handle_initialize(1, {})
    assert sent["id"] == 1
    assert "capabilities" in sent["result"]


def test_lsp_didopen_didchange_track_documents():
    from app.lsp.server import LSPServer
    s = LSPServer()
    s._send_notification = lambda method, params: None  # swallow publishDiagnostics
    s._handle_textDocument_didOpen({"textDocument": {"uri": "file:///x.py", "text": "x=1\n"}})
    assert "file:///x.py" in s._documents
    s._handle_textDocument_didChange({
        "textDocument": {"uri": "file:///x.py"},
        "contentChanges": [{"text": "y=2\n"}],
    })
    assert s._documents["file:///x.py"] == "y=2\n"


# --- Full stdio run() loop, end-to-end over fake stdin/stdout -----------------

import io
import json


class _FakeStdout:
    """Mimics sys.stdout: _send_message writes framed bytes to .buffer."""

    def __init__(self):
        self.buffer = io.BytesIO()


def _frame(msg: dict) -> str:
    body = json.dumps(msg)
    return f"Content-Length: {len(body.encode())}\r\n\r\n{body}"


def _parse_frames(raw: bytes) -> list[dict]:
    """Split a Content-Length framed byte stream into JSON messages."""
    out = []
    text = raw.decode("utf-8")
    while "Content-Length:" in text:
        header, _, rest = text.partition("\r\n\r\n")
        length = int(header.split("Content-Length:")[1].strip().splitlines()[0])
        out.append(json.loads(rest[:length]))
        text = rest[length:]
    return out


def _drive(monkeypatch, messages: list[dict]) -> list[dict]:
    from app.lsp.server import LSPServer

    stream = "".join(_frame(m) for m in messages)
    fake_out = _FakeStdout()
    monkeypatch.setattr("sys.stdin", io.StringIO(stream))
    monkeypatch.setattr("sys.stdout", fake_out)
    LSPServer().run()
    return _parse_frames(fake_out.buffer.getvalue())


def test_lsp_run_initialize_and_shutdown(monkeypatch):
    replies = _drive(monkeypatch, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "shutdown"},
        {"jsonrpc": "2.0", "method": "exit"},
    ])
    init = next(r for r in replies if r.get("id") == 1)
    assert "capabilities" in init["result"]
    assert any(r.get("id") == 2 for r in replies)


def test_lsp_run_didopen_publishes_diagnostics(monkeypatch):
    replies = _drive(monkeypatch, [
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": "file:///r.py", "text": "x = eval(y)\n"}}},
        {"jsonrpc": "2.0", "method": "exit"},
    ])
    diag = next(r for r in replies if r.get("method") == "textDocument/publishDiagnostics")
    assert any("eval()" in d["message"] for d in diag["params"]["diagnostics"])


def test_lsp_run_hover_and_symbols(monkeypatch):
    src = "def foo():\n    return eval(x)\n"
    replies = _drive(monkeypatch, [
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": "file:///h.py", "text": src}}},
        {"jsonrpc": "2.0", "id": 10, "method": "textDocument/hover", "params": {
            "textDocument": {"uri": "file:///h.py"},
            "position": {"line": 1, "character": 11}}},
        {"jsonrpc": "2.0", "id": 11, "method": "textDocument/documentSymbol", "params": {
            "textDocument": {"uri": "file:///h.py"}}},
        {"jsonrpc": "2.0", "method": "exit"},
    ])
    hover = next(r for r in replies if r.get("id") == 10)
    assert "eval" in hover["result"]["contents"]["value"]
    symbols = next(r for r in replies if r.get("id") == 11)
    assert any(s["name"] == "foo" for s in symbols["result"])


def test_lsp_run_unknown_method_returns_error(monkeypatch):
    replies = _drive(monkeypatch, [
        {"jsonrpc": "2.0", "id": 7, "method": "textDocument/nonsense", "params": {}},
        {"jsonrpc": "2.0", "method": "exit"},
    ])
    err = next(r for r in replies if r.get("id") == 7)
    assert err["error"]["code"] == -32601


def test_lsp_run_didclose_drops_document(monkeypatch):
    replies = _drive(monkeypatch, [
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": "file:///c.py", "text": "x=1\n"}}},
        {"jsonrpc": "2.0", "method": "textDocument/didClose", "params": {
            "textDocument": {"uri": "file:///c.py"}}},
        {"jsonrpc": "2.0", "id": 99, "method": "textDocument/documentSymbol", "params": {
            "textDocument": {"uri": "file:///c.py"}}},
        {"jsonrpc": "2.0", "method": "exit"},
    ])
    # After close the doc is gone, so symbols come back empty. (An empty list
    # is normalized to {} by _send_response's `result or {}` default.)
    syms = next(r for r in replies if r.get("id") == 99)
    assert not syms["result"]


def test_lsp_hover_out_of_range_line(monkeypatch):
    replies = _drive(monkeypatch, [
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": "file:///o.py", "text": "x=1\n"}}},
        {"jsonrpc": "2.0", "id": 5, "method": "textDocument/hover", "params": {
            "textDocument": {"uri": "file:///o.py"},
            "position": {"line": 999, "character": 0}}},
        {"jsonrpc": "2.0", "method": "exit"},
    ])
    hover = next(r for r in replies if r.get("id") == 5)
    assert hover["result"]["contents"] == ""
