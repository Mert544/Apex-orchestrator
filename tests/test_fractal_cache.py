from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.fractal_cache import FractalCache
from app.engine.fractal_5whys import FractalNode


class TestFractalCache:
    def test_cache_miss(self, tmp_path: Path):
        cache = FractalCache(cache_dir=str(tmp_path / "cache"))
        finding = {"issue": "eval() usage", "file": "a.py", "line": 5}
        assert cache.get(finding) is None

    def test_cache_hit(self, tmp_path: Path):
        cache = FractalCache(cache_dir=str(tmp_path / "cache"))
        finding = {"issue": "eval() usage", "file": "a.py", "line": 5}
        tree = FractalNode(level=1, question="Q?", answer="A.", confidence=0.9)
        cache.put(finding, tree)
        retrieved = cache.get(finding)
        assert retrieved is not None
        assert retrieved.level == 1
        assert retrieved.question == "Q?"

    def test_cache_invalidation(self, tmp_path: Path):
        cache = FractalCache(cache_dir=str(tmp_path / "cache"))
        finding = {"issue": "eval() usage", "file": "a.py", "line": 5}
        tree = FractalNode(level=1, question="Q?", answer="A.", confidence=0.9)
        cache.put(finding, tree)
        cache.invalidate(finding)
        assert cache.get(finding) is None

    def test_cache_clear(self, tmp_path: Path):
        cache = FractalCache(cache_dir=str(tmp_path / "cache"))
        for i in range(3):
            cache.put({"issue": f"x{i}", "file": "a.py", "line": i}, FractalNode(level=1, question="Q", answer="A", confidence=0.5))
        cache.clear()
        assert not list(cache.cache_dir.glob("*.json"))

    def test_cache_persistence(self, tmp_path: Path):
        cache = FractalCache(cache_dir=str(tmp_path / "cache"))
        finding = {"issue": "eval() usage", "file": "a.py", "line": 5}
        tree = FractalNode(level=1, question="Q?", answer="A.", confidence=0.9, children=[
            FractalNode(level=2, question="Q2?", answer="A2.", confidence=0.8),
        ])
        cache.put(finding, tree)
        # Fresh cache instance
        cache2 = FractalCache(cache_dir=str(tmp_path / "cache"))
        retrieved = cache2.get(finding)
        assert retrieved is not None
        assert len(retrieved.children) == 1
        assert retrieved.children[0].level == 2
