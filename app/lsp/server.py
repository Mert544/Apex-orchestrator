from __future__ import annotations

import json
import sys
from typing import Any


class LSPServer:
    """Minimal Language Server Protocol (LSP) server for Apex diagnostics.

    Communicates over stdin/stdout using JSON-RPC 2.0.
    Supports:
      - textDocument/diagnostics (custom)
      - textDocument/hover
      - textDocument/documentSymbol

    Usage:
        python -m app.lsp.server
    """

    def __init__(self) -> None:
        self._running = True
        self._documents: dict[str, str] = {}

    def _read_message(self) -> dict[str, Any] | None:
        """Read a JSON-RPC message from stdin."""
        header = sys.stdin.readline()
        if not header:
            return None

        content_length = 0
        while header.strip():
            if header.lower().startswith("content-length:"):
                content_length = int(header.split(":")[1].strip())
            header = sys.stdin.readline()

        if content_length == 0:
            return None

        body = sys.stdin.read(content_length)
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None

    def _send_message(self, msg: dict[str, Any]) -> None:
        """Send a JSON-RPC message to stdout."""
        body = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        sys.stdout.buffer.write(header + body)
        sys.stdout.buffer.flush()

    def _send_response(self, id: Any, result: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": id}
        if error:
            msg["error"] = error
        else:
            msg["result"] = result or {}
        self._send_message(msg)

    def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        self._send_message({"jsonrpc": "2.0", "method": method, "params": params})

    def _handle_initialize(self, id: Any, params: dict[str, Any]) -> None:
        self._send_response(id, {
            "capabilities": {
                "textDocumentSync": {"openClose": True, "change": 1},
                "hoverProvider": True,
                "documentSymbolProvider": True,
            },
            "serverInfo": {"name": "apex-lsp", "version": "0.1.0"},
        })

    def _handle_textDocument_didOpen(self, params: dict[str, Any]) -> None:
        doc = params.get("textDocument", {})
        uri = doc.get("uri", "")
        text = doc.get("text", "")
        self._documents[uri] = text
        diagnostics = self._analyze(uri, text)
        self._send_notification("textDocument/publishDiagnostics", {
            "uri": uri,
            "diagnostics": diagnostics,
        })

    def _handle_textDocument_didChange(self, params: dict[str, Any]) -> None:
        doc = params.get("textDocument", {})
        uri = doc.get("uri", "")
        changes = params.get("contentChanges", [])
        if changes:
            self._documents[uri] = changes[-1].get("text", "")
            diagnostics = self._analyze(uri, self._documents[uri])
            self._send_notification("textDocument/publishDiagnostics", {
                "uri": uri,
                "diagnostics": diagnostics,
            })

    def _handle_textDocument_hover(self, id: Any, params: dict[str, Any]) -> None:
        doc = params.get("textDocument", {})
        uri = doc.get("uri", "")
        position = params.get("position", {})
        line = position.get("line", 0)
        char = position.get("character", 0)

        text = self._documents.get(uri, "")
        lines = text.splitlines()
        if line < len(lines):
            current_line = lines[line]
            word = self._extract_word(current_line, char)
            hover_text = self._get_hover_info(word)
            self._send_response(id, {
                "contents": {"kind": "markdown", "value": hover_text},
            })
        else:
            self._send_response(id, {"contents": ""})

    def _handle_textDocument_documentSymbol(self, id: Any, params: dict[str, Any]) -> None:
        doc = params.get("textDocument", {})
        uri = doc.get("uri", "")
        text = self._documents.get(uri, "")
        symbols = self._extract_symbols(text)
        self._send_response(id, symbols)

    @staticmethod
    def _diagnostic(line: int, start_char: int, end_char: int, severity: int, message: str) -> dict[str, Any]:
        """Build a single LSP diagnostic spanning one line."""
        return {
            "range": {
                "start": {"line": line, "character": start_char},
                "end": {"line": line, "character": end_char},
            },
            "severity": severity,
            "message": message,
            "source": "apex-lsp",
        }

    @classmethod
    def _syntax_diagnostic(cls, exc: SyntaxError) -> dict[str, Any]:
        """Build the diagnostic for an unparseable source."""
        line = exc.lineno - 1 if exc.lineno else 0
        char = exc.offset or 0
        return cls._diagnostic(line, char, char, 1, f"SyntaxError: {exc.msg}")

    @classmethod
    def _call_diagnostics(cls, node: Any) -> list[dict[str, Any]]:
        """Diagnostics for a Call node (eval and os.system)."""
        import ast

        diags: list[dict[str, Any]] = []
        func = node.func
        line = node.lineno - 1
        if isinstance(func, ast.Name) and func.id == "eval":
            diags.append(cls._diagnostic(line, node.col_offset, node.col_offset + 4, 1, "Apex: eval() detected — potential security risk"))
        if (isinstance(func, ast.Attribute)) and (func.attr == "system" and isinstance(func.value, ast.Name) and func.value.id == "os"):
            diags.append(cls._diagnostic(line, node.col_offset, node.col_offset + 10, 2, "Apex: os.system() detected — consider subprocess.run()"))
        return diags

    @classmethod
    def _node_diagnostics(cls, node: Any) -> list[dict[str, Any]]:
        """Collect all diagnostics emitted for a single AST node."""
        import ast

        diags: list[dict[str, Any]] = []
        if isinstance(node, ast.Call):
            diags.extend(cls._call_diagnostics(node))
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            diags.append(cls._diagnostic(node.lineno - 1, 0, 12, 2, "Apex: bare except — use except Exception:"))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and ast.get_docstring(node) is None:
            diags.append(cls._diagnostic(node.lineno - 1, 0, len(node.name), 3, f"Apex: missing docstring for {node.name}"))
        return diags

    def _analyze(self, uri: str, text: str) -> list[dict[str, Any]]:
        """Run Apex diagnostics on Python source."""
        import ast

        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            return [self._syntax_diagnostic(exc)]
        except (RecursionError, MemoryError):
            # A pathological source the parser can't handle (deeply-nested
            # expression / enormous file): report it at the top of the file
            # rather than crashing the language server.
            return [self._diagnostic(0, 0, 0, 1, "unparseable: file too complex")]

        diagnostics: list[dict[str, Any]] = []
        for node in ast.walk(tree):
            diagnostics.extend(self._node_diagnostics(node))
        return diagnostics

    def _extract_word(self, line: str, char: int) -> str:
        """Extract the word at the given character position."""
        import re
        for match in re.finditer(r"[a-zA-Z_][a-zA-Z0-9_]*", line):
            if match.start() <= char <= match.end():
                return match.group()
        return ""

    def _get_hover_info(self, word: str) -> str:
        """Return hover information for a symbol."""
        risk_keywords = {
            "eval": "**eval()** — Evaluates a string as Python code. High security risk.",
            "exec": "**exec()** — Executes arbitrary Python code. High security risk.",
            "system": "**os.system()** — Runs shell commands. Prefer `subprocess.run()`.",
        }
        return risk_keywords.get(word, f"**{word}** — No specific Apex info available.")

    def _extract_symbols(self, text: str) -> list[dict[str, Any]]:
        """Extract document symbols for LSP."""
        import ast

        symbols: list[dict[str, Any]] = []
        try:
            tree = ast.parse(text)
        except (SyntaxError, RecursionError, MemoryError):
            return symbols

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append({
                    "name": node.name,
                    "kind": 12,  # Function
                    "location": {
                        "uri": "",
                        "range": {
                            "start": {"line": node.lineno - 1, "character": node.col_offset},
                            "end": {"line": (node.end_lineno or node.lineno) - 1, "character": 0},
                        },
                    },
                })
            elif isinstance(node, ast.ClassDef):
                symbols.append({
                    "name": node.name,
                    "kind": 5,  # Class
                    "location": {
                        "uri": "",
                        "range": {
                            "start": {"line": node.lineno - 1, "character": node.col_offset},
                            "end": {"line": (node.end_lineno or node.lineno) - 1, "character": 0},
                        },
                    },
                })

        return symbols

    def run(self) -> None:
        print("Apex LSP server started (stdio transport)", file=sys.stderr)
        while self._running:
            msg = self._read_message()
            if msg is None:
                break

            method = msg.get("method")
            msg_id = msg.get("id")
            params = msg.get("params", {})

            if method == "initialize":
                self._handle_initialize(msg_id, params)
            elif method == "initialized":
                pass
            elif method == "shutdown":
                self._send_response(msg_id)
                self._running = False
            elif method == "exit":
                break
            elif method == "textDocument/didOpen":
                self._handle_textDocument_didOpen(params)
            elif method == "textDocument/didChange":
                self._handle_textDocument_didChange(params)
            elif method == "textDocument/didClose":
                uri = params.get("textDocument", {}).get("uri", "")
                self._documents.pop(uri, None)
            elif method == "textDocument/hover":
                self._handle_textDocument_hover(msg_id, params)
            elif method == "textDocument/documentSymbol":
                self._handle_textDocument_documentSymbol(msg_id, params)
            else:
                if msg_id is not None:
                    self._send_response(msg_id, error={"code": -32601, "message": f"Method not found: {method}"})


def main() -> int:
    server = LSPServer()
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
