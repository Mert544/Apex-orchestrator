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
    import json
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
