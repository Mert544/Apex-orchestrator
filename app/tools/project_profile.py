from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProjectProfile:
    root: str
    total_files: int = 0
    extension_counts: dict[str, int] = field(default_factory=dict)
    top_directories: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    ci_files: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)
    sensitive_paths: list[str] = field(default_factory=list)


class ProjectProfiler:
    ENTRYPOINT_NAMES = {
        "main.py",
        "__main__.py",
        "server.py",
        "app.py",
        "cli.py",
        "index.ts",
        "index.js",
    }
    CONFIG_NAMES = {
        "pyproject.toml",
        "package.json",
        "requirements.txt",
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        ".env.example",
    }
    SENSITIVE_HINTS = {
        "auth",
        "payment",
        "token",
        "secret",
        "billing",
        "api",
        "credential",
    }

    def __init__(self, root: str | Path, max_files: int = 2000) -> None:
        self.root = Path(root)
        self.max_files = max_files

    def profile(self) -> ProjectProfile:
        profile = ProjectProfile(root=str(self.root))
        if not self.root.exists():
            return profile

        ext_counter: Counter[str] = Counter()
        dir_counter: Counter[str] = Counter()

        scanned = 0
        for path in self.root.rglob("*"):
            if scanned >= self.max_files:
                break
            if not path.is_file():
                continue
            scanned += 1
            profile.total_files += 1

            rel = path.relative_to(self.root)
            rel_str = str(rel)
            ext = path.suffix.lower() or "<no_ext>"
            ext_counter[ext] += 1

            if rel.parts:
                dir_counter[rel.parts[0]] += 1

            name_lower = path.name.lower()
            rel_lower = rel_str.lower()

            if name_lower in self.ENTRYPOINT_NAMES:
                profile.entrypoints.append(rel_str)
            if name_lower.startswith("test_") or "/tests/" in f"/{rel_lower}/" or rel_lower.startswith("tests/"):
                profile.test_files.append(rel_str)
            if ".github/workflows/" in rel_lower:
                profile.ci_files.append(rel_str)
            if name_lower in self.CONFIG_NAMES:
                profile.config_files.append(rel_str)
            if any(hint in rel_lower for hint in self.SENSITIVE_HINTS):
                profile.sensitive_paths.append(rel_str)

        profile.extension_counts = dict(ext_counter.most_common())
        profile.top_directories = [name for name, _count in dir_counter.most_common(5)]
        profile.entrypoints = sorted(dict.fromkeys(profile.entrypoints))
        profile.test_files = sorted(dict.fromkeys(profile.test_files))
        profile.ci_files = sorted(dict.fromkeys(profile.ci_files))
        profile.config_files = sorted(dict.fromkeys(profile.config_files))
        profile.sensitive_paths = sorted(dict.fromkeys(profile.sensitive_paths))
        return profile
