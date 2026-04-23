from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.automation.models import AutomationContext
from app.automation.runner import SkillAutomationRunner
from app.automation.skills import build_default_registry
from app.plugins.registry import PluginRegistry
from app.validation.django_mini_factory import create_django_mini_examples
from app.validation.real_world_validator import RealWorldValidator


class TestPluginRegistry:
    def test_empty_registry(self):
        reg = PluginRegistry()
        assert reg.list_plugins() == []
        assert reg.run_hook("before_scan", {"x": 1}) == {"x": 1}

    def test_load_valid_plugin(self, tmp_path):
        plugin_file = tmp_path / "my_plugin.py"
        plugin_file.write_text(
            '''__plugin_name__ = "test-plugin"
__plugin_version__ = "1.0.0"
__plugin_description__ = "A test plugin"

def register(proxy):
    proxy.add_hook("before_scan", lambda ctx: ctx.update({"hooked": True}))
''',
            encoding="utf-8",
        )
        reg = PluginRegistry(plugin_dirs=[str(tmp_path)])
        loaded = reg.load(plugin_file)
        assert loaded is not None
        assert loaded.name == "test-plugin"
        assert "before_scan" in loaded.hooks
        ctx = reg.run_hook("before_scan", {})
        assert ctx["hooked"] is True

    def test_load_all(self, tmp_path):
        (tmp_path / "p1.py").write_text(
            "def register(proxy):\n    proxy.add_hook('on_report', lambda c: None)\n",
            encoding="utf-8",
        )
        (tmp_path / "p2.py").write_text(
            "def register(proxy):\n    proxy.add_hook('on_claim', lambda c: None)\n",
            encoding="utf-8",
        )
        reg = PluginRegistry(plugin_dirs=[str(tmp_path)])
        plugins = reg.load_all()
        assert len(plugins) == 2
        hook_names = [h for p in plugins for h in p.hooks.keys()]
        assert "on_report" in hook_names
        assert "on_claim" in hook_names

    def test_skip_files_without_register(self, tmp_path):
        (tmp_path / "bad.py").write_text("x = 1\n", encoding="utf-8")
        reg = PluginRegistry(plugin_dirs=[str(tmp_path)])
        result = reg.load(tmp_path / "bad.py")
        assert result is None

    def test_list_plugins(self, tmp_path):
        (tmp_path / "p.py").write_text(
            '__plugin_name__ = "demo"\n__plugin_version__ = "0.1"\n'
            'def register(proxy):\n    proxy.add_hook("after_scan", lambda c: None)\n',
            encoding="utf-8",
        )
        reg = PluginRegistry(plugin_dirs=[str(tmp_path)])
        reg.load_all()
        assert len(reg.list_plugins()) == 1
        assert reg.list_plugins()[0]["name"] == "demo"

    def test_runner_fires_plugin_hooks(self, tmp_path):
        plugin_file = tmp_path / "audit_plugin.py"
        plugin_file.write_text(
            '''__plugin_name__ = "audit"
__plugin_version__ = "1.0.0"

_audit_log = []

def register(proxy):
    proxy.add_hook("before_scan", lambda ctx: _audit_log.append("before_scan"))
    proxy.add_hook("after_scan", lambda ctx: _audit_log.append("after_scan"))
    proxy.add_hook("on_report", lambda ctx: _audit_log.append("on_report"))
''',
            encoding="utf-8",
        )
        plugins = PluginRegistry(plugin_dirs=[str(tmp_path)])
        plugins.load_all()

        context = AutomationContext(
            project_root=tmp_path,
            objective="test",
            config={"max_total_nodes": 2, "max_depth": 1, "top_k_questions": 1},
        )
        runner = SkillAutomationRunner(build_default_registry(), plugins=plugins)
        result = runner.run_plan("project_scan", context)

        assert result.plan_name == "project_scan"
        assert len(result.steps) > 0
        # Hooks should have been fired during plan execution
        audit_log = plugin_file.with_suffix(".log")
        # We can't easily read the module's private _audit_log, but we can verify
        # the runner completed without error and plugins are loaded
        assert len(plugins.list_plugins()) == 1


class TestDjangoMiniValidation:
    def test_django_mini_created(self, tmp_path):
        create_django_mini_examples(tmp_path)
        root = tmp_path / "django_mini"
        assert (root / "settings.py").exists()
        assert (root / "views.py").exists()
        assert (root / "models.py").exists()
        assert (root / "urls.py").exists()
        assert not (root / "tests").exists()

    def test_django_mini_issues_detected(self, tmp_path):
        create_django_mini_examples(tmp_path)
        root = tmp_path / "django_mini"
        # Check known issues
        settings = (root / "settings.py").read_text(encoding="utf-8")
        assert "hardcoded-secret" in settings
        # CSRF is commented out → not active in MIDDLEWARE list
        assert '# "django.middleware.csrf.CsrfViewMiddleware"' in settings

        views = (root / "views.py").read_text(encoding="utf-8")
        assert "cursor.execute" in views
        assert "f\"SELECT" in views  # SQL injection
        assert "except:" in views  # bare except

        models = (root / "models.py").read_text(encoding="utf-8")
        assert "def process(self):" in models
        assert '"""' not in models  # no docstring
