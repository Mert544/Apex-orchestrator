"""The two "living-cell" dashboard cards: Memory (vault, L5) and JS/TS scope (L1).

Both self-gate: they render only when their data is present, and return "" (so
the page stays byte-identical) on a fresh / Python-only project. The JS card's
real-graph path is gated on node + global typescript, like the profiler's own
suite; the memory card is pure (artifact reads only).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.execution.js.js_tool import global_node_modules
from app.reporting.dashboard_sections import _js_scope_section, _memory_vault_section


def _seed_vault(root: Path) -> None:
    (root / ".apex").mkdir(parents=True, exist_ok=True)
    (root / ".apex" / "idea-memory.json").write_text(
        '{"most_reliable": [], "least_reliable": []}', encoding="utf-8")


# --- Memory / vault card (L5) -----------------------------------------------

def test_memory_card_renders_when_a_store_is_present(tmp_path):
    _seed_vault(tmp_path)
    html = _memory_vault_section(str(tmp_path))
    assert "Memory — vault stores" in html
    assert "stores present" in html
    # CONSCIOUS PIN MOVE: 7 -> 8-store roll-up (the derived "manifesto" section
    # joined the vault; see tests/test_vault_manifesto_eyml.py for its contract).
    assert "/8" in html  # the 8-store roll-up


def test_memory_card_empty_on_fresh_project(tmp_path):
    assert _memory_vault_section(str(tmp_path)) == ""


def test_memory_card_is_deterministic(tmp_path):
    _seed_vault(tmp_path)
    assert _memory_vault_section(str(tmp_path)) == _memory_vault_section(str(tmp_path))


# --- JS/TS scope card (L1) --------------------------------------------------

def test_js_scope_card_empty_on_python_only_project(tmp_path):
    (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
    assert _js_scope_section(str(tmp_path)) == ""


def _node_ok() -> bool:
    if shutil.which("node") is None:
        return False
    nm = global_node_modules()
    return bool(nm) and (Path(nm) / "typescript").is_dir()


@pytest.mark.skipif(not _node_ok(), reason="node + global typescript not available")
def test_js_scope_card_renders_for_a_js_project(tmp_path):
    (tmp_path / "package.json").write_text(
        '{ "name": "demo", "version": "1.0.0" }\n', encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "core.ts").write_text(
        "export function core(x: number): number { return x; }\n", encoding="utf-8")
    (src / "a.ts").write_text(
        'import { core } from "./core";\nexport const a = () => core(1);\n', encoding="utf-8")
    (src / "b.ts").write_text(
        'import { core } from "./core";\nexport const b = () => core(2);\n', encoding="utf-8")

    html = _js_scope_section(str(tmp_path))
    assert "JS/TS scope" in html
    assert "Dependency hubs" in html
    assert "modules" in html
