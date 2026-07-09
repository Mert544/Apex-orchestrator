"""The vault's EIGHTH section: the LIVING MANIFESTO (``app.engine.manifesto``).

``_manifesto_section`` mirrors ``derive_manifesto`` into the vault — but unlike
the raw-passthrough sections (``idea_memory``, ``dream_journal``, ...), the
manifesto has no store of its own: it is DERIVED from ``proof-of-fix.json`` +
``native-mind-experience.json`` on every load, the same "derived, not stored"
contract ``track_record`` already uses. Contracts pinned here:

* an empty project (no ``.apex`` history) → ``present: False`` and an honest
  "legislated no laws yet" markdown body — never raises;
* a project with real proof/native-landing history → ``present: True``, law
  COUNTS per kind, and the rendered markdown embeds the actual laws;
* malformed underlying artifacts degrade to an empty manifesto, never raise;
* deterministic — same ``.apex`` artifacts, same section, every time;
* ``write_vault`` stays byte-idempotent with the manifesto section included.

Fixture style mirrors ``tests/test_manifesto_eyml.py`` (fabricates
``proof-of-fix.json`` fixes + a native landing) so ``derive_manifesto`` returns
non-empty laws.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.native_proof_memory import record_native_landing
from app.engine.proof_of_fix import SCHEMA
from app.memory.vault import VAULT_REL, load_vault_view, render_vault_markdown, write_vault

_PROOF_REL = ".apex/proof-of-fix.json"
_NATIVE_EXPERIENCE_REL = ".apex/native-mind-experience.json"


def _proof(root: Path, fixes: list[dict]) -> None:
    apex = root / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    (apex / "proof-of-fix.json").write_text(
        json.dumps({"schema": SCHEMA, "generated_at": "2026-01-01", "fixes": fixes}),
        encoding="utf-8")


def _fix(action: str, module: str, outcome: str) -> dict:
    return {"outcome": outcome,
            "finding": {"action": action, "target": module},
            "changed_files": [module]}


def _learned_project(tmp_path: Path) -> Path:
    _proof(tmp_path, [
        *[_fix("risky-x", "app/bad.py", "rolled_back") for _ in range(4)],
        _fix("risky-x", "app/bad.py", "applied"),
        *[_fix("safe-y", "app/good.py", "applied") for _ in range(6)],
    ])
    record_native_landing(tmp_path, ["2:p0 + p1"])
    return tmp_path


def test_empty_project_is_honest_and_tolerant(tmp_path: Path):
    sec = load_vault_view(tmp_path)["sections"]["manifesto"]
    assert sec["present"] is False
    assert sec["readable"] is True
    assert (sec["avoid"], sec["trust"], sec["fragile"], sec["proven_idioms"]) == (0, 0, 0, 0)
    assert sec["derived_from"] == f"{_PROOF_REL} + {_NATIVE_EXPERIENCE_REL}"
    assert "legislated no laws" in sec["text"]


def test_learned_project_manifesto_section_has_expected_laws(tmp_path: Path):
    _learned_project(tmp_path)
    sec = load_vault_view(tmp_path)["sections"]["manifesto"]
    assert sec["present"] is True
    assert sec["readable"] is True
    assert sec["avoid"] == 1
    assert sec["fragile"] == 1
    assert sec["trust"] >= 1
    assert sec["proven_idioms"] == 1
    md = sec["text"]
    assert "AVOID" in md and "FRAGILE" in md and "TRUST" in md and "PROVEN" in md
    assert "app/bad.py" in md
    assert "p0 + p1 (2-arg)" in md


def test_manifesto_matches_derive_manifesto_directly(tmp_path: Path):
    """The vault section's law counts must agree with the same
    ``derive_manifesto`` call the manifesto CLI/markdown use directly — the
    vault is a mirror, never a second author of the laws."""
    from app.engine.manifesto import derive_manifesto

    _learned_project(tmp_path)
    direct = derive_manifesto(tmp_path)
    sec = load_vault_view(tmp_path)["sections"]["manifesto"]
    assert sec["avoid"] == len(direct["avoid"])
    assert sec["trust"] == len(direct["trust"])
    assert sec["fragile"] == len(direct["fragile"])
    assert sec["proven_idioms"] == len(direct["proven_idioms"])


def test_malformed_proof_history_degrades_to_empty_never_raises(tmp_path: Path):
    apex = tmp_path / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    (apex / "proof-of-fix.json").write_text("{ not valid json", encoding="utf-8")
    sec = load_vault_view(tmp_path)["sections"]["manifesto"]  # must not raise
    assert sec["present"] is False
    assert (sec["avoid"], sec["trust"], sec["fragile"], sec["proven_idioms"]) == (0, 0, 0, 0)


def test_is_deterministic(tmp_path: Path):
    _learned_project(tmp_path)
    first = load_vault_view(tmp_path)["sections"]["manifesto"]
    second = load_vault_view(tmp_path)["sections"]["manifesto"]
    assert first == second


def test_render_vault_markdown_shows_manifesto_law_counts(tmp_path: Path):
    _learned_project(tmp_path)
    md = render_vault_markdown(load_vault_view(tmp_path))
    assert "**manifesto** — 1 avoid / 1 fragile" in md
    assert f"`{_PROOF_REL} + {_NATIVE_EXPERIENCE_REL}`" in md


def test_render_vault_markdown_shows_absent_manifesto(tmp_path: Path):
    md = render_vault_markdown(load_vault_view(tmp_path))
    assert "**manifesto** — absent" in md


def test_write_vault_is_byte_idempotent_with_manifesto_section(tmp_path: Path):
    _learned_project(tmp_path)
    p1 = write_vault(tmp_path)
    first = p1.read_bytes()
    p2 = write_vault(tmp_path)
    assert p2.read_bytes() == first
    assert (tmp_path / VAULT_REL).exists()
    assert '"manifesto"' in first.decode("utf-8")
