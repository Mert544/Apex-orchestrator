"""Edge/error paths for `app.engine.completeness` not covered by the main suite.

Targets the conservative-detection corners the canonical tests skip:

  - ``_decorator_leaf`` unwrapping a CALL decorator (``@dataclass(frozen=True)``,
    ``@dataclasses.dataclass(slots=True)``) — the guard must still recognise the
    auto-hash framework through the call args.
  - ``_decorator_leaf`` falling through to ``""`` for an exotic decorator node
    (``@registry[0]``) — an unrecognised decorator does NOT suppress the gap.
  - the ``OSError`` read path in :func:`incomplete_protocols` (an unreadable
    file is skipped, not raised) and the multi-gap / multi-file ordering.

Pure AST, deterministic (sorted output, no time/random), tmp_path-hermetic —
matching the style of ``tests/test_completeness.py``.
"""

from pathlib import Path

from app.engine import completeness
from app.engine.completeness import (
    _decorator_leaf,
    incomplete_protocols,
    render_completeness_markdown,
)


def _write(tmp_path: Path, rel: str, body: str) -> None:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


# --- _decorator_leaf: the CALL-unwrap branch (line 69) ----------------------

def test_call_dataclass_decorator_is_not_flagged(tmp_path: Path):
    # @dataclass(frozen=True) is an ast.Call wrapping a Name -> leaf "dataclass".
    # The auto-hash guard must see through the call args, so no gap.
    _write(tmp_path, "app/d.py",
           "from dataclasses import dataclass\n\n"
           "@dataclass(frozen=True)\nclass D:\n"
           "    x: int\n"
           "    def __eq__(self, o):\n        return self.x == o.x\n")
    assert incomplete_protocols(str(tmp_path)) == []


def test_call_dotted_dataclass_decorator_is_not_flagged(tmp_path: Path):
    # @dataclasses.dataclass(slots=True) is a Call wrapping an Attribute.
    _write(tmp_path, "app/d.py",
           "import dataclasses\n\n"
           "@dataclasses.dataclass(slots=True)\nclass D:\n"
           "    x: int\n"
           "    def __eq__(self, o):\n        return self.x == o.x\n")
    assert incomplete_protocols(str(tmp_path)) == []


def test_call_attrs_define_decorator_is_not_flagged(tmp_path: Path):
    # @attrs.define() — a Call wrapping an Attribute whose leaf is "define".
    _write(tmp_path, "app/a.py",
           "import attrs\n\n"
           "@attrs.define()\nclass A:\n"
           "    def __eq__(self, o):\n        return True\n")
    assert incomplete_protocols(str(tmp_path)) == []


def test_decorator_leaf_unwraps_call_directly():
    # Direct unit pin on the Call-unwrap (line 69): @attr.s(slots=True) -> "s".
    import ast

    tree = ast.parse("@attr.s(slots=True)\nclass C:\n    pass\n")
    cls = tree.body[0]
    assert _decorator_leaf(cls.decorator_list[0]) == "s"


# --- _decorator_leaf: the fall-through "" branch (line 74) ------------------

def test_subscript_decorator_falls_through_and_class_is_flagged(tmp_path: Path):
    # @registry[0] is an ast.Subscript — neither Call/Attribute/Name, so the
    # leaf is "" (not an auto-hash decorator) and the eq/hash gap still fires.
    _write(tmp_path, "app/s.py",
           "@registry[0]\nclass C:\n"
           "    def __eq__(self, o):\n        return True\n")
    items = incomplete_protocols(str(tmp_path))
    assert len(items) == 1
    assert items[0]["class"] == "C"
    assert items[0]["protocol"] == "equality/hash"


def test_decorator_leaf_returns_empty_for_exotic_node():
    # Direct unit pin on the "" fall-through (line 74).
    import ast

    tree = ast.parse("@registry[0]\nclass C:\n    pass\n")
    cls = tree.body[0]
    assert _decorator_leaf(cls.decorator_list[0]) == ""


# --- incomplete_protocols: the OSError read path (lines 194-195) -------------

def test_unreadable_file_is_skipped_not_raised(tmp_path: Path, monkeypatch):
    # A file whose read raises OSError is silently skipped; a sibling that reads
    # fine is still flagged. Deterministic: we fail ONLY the named file.
    _write(tmp_path, "app/bad.py",
           "class Bad:\n    def __eq__(self, o):\n        return True\n")
    _write(tmp_path, "app/good.py",
           "class Good:\n    def __eq__(self, o):\n        return True\n")

    real_read_text = Path.read_text

    def fake_read_text(self, *args, **kwargs):
        if self.name == "bad.py":
            raise OSError("simulated unreadable file")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    items = incomplete_protocols(str(tmp_path))
    classes = [it["class"] for it in items]
    assert classes == ["Good"]


def test_all_files_unreadable_yields_empty(tmp_path: Path, monkeypatch):
    _write(tmp_path, "app/x.py",
           "class X:\n    def __eq__(self, o):\n        return True\n")

    def boom(self, *args, **kwargs):
        raise OSError("nope")

    monkeypatch.setattr(Path, "read_text", boom)
    assert incomplete_protocols(str(tmp_path)) == []


# --- multi-gap ordering / determinism corners --------------------------------

def test_multiple_classes_same_file_sorted_by_line(tmp_path: Path):
    _write(tmp_path, "app/multi.py",
           "class First:\n    def __enter__(self):\n        return self\n\n"
           "class Second:\n    def __eq__(self, o):\n        return True\n")
    items = incomplete_protocols(str(tmp_path))
    assert [it["class"] for it in items] == ["First", "Second"]
    assert [it["line"] for it in items] == sorted(it["line"] for it in items)


def test_async_exit_without_enter_is_flagged(tmp_path: Path):
    # The reverse async pair: __aexit__ present, __aenter__ missing.
    _write(tmp_path, "app/acm.py",
           "class ACM:\n"
           "    async def __aexit__(self, *a):\n        return False\n")
    items = incomplete_protocols(str(tmp_path))
    assert len(items) == 1
    assert items[0]["protocol"] == "async-context-manager"
    assert items[0]["have"] == "__aexit__"
    assert items[0]["missing"] == "__aenter__"


def test_render_joins_multiple_items_with_semicolons():
    items = [
        {"module": "app/a.py", "class": "A", "line": 1,
         "protocol": "equality/hash", "have": "__eq__", "missing": "__hash__"},
        {"module": "app/b.py", "class": "B", "line": 2,
         "protocol": "context-manager", "have": "__enter__", "missing": "__exit__"},
    ]
    md = render_completeness_markdown(items)
    assert md.startswith("Incomplete protocols (finish what you started): ")
    assert md.endswith(".")
    assert "; " in md
    assert "`A`" in md and "`B`" in md


def test_module_exports_only_public_api():
    assert completeness.__all__ == [
        "incomplete_protocols", "render_completeness_markdown"
    ]
