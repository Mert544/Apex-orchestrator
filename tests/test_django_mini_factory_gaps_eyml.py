from __future__ import annotations

from pathlib import Path

from app.validation.django_mini_factory import create_django_mini_examples

# The module is already at 100% line coverage; these are characterization /
# regression tests locking in the synthetic-project contract other suites rely on.


def test_idempotent_recreation(tmp_path: Path):
    # mkdir(exist_ok=True) + overwrite means a second call must not raise and
    # must leave stable content.
    create_django_mini_examples(tmp_path)
    create_django_mini_examples(tmp_path)
    root = tmp_path / "django_mini"
    assert (root / "settings.py").exists()
    assert (root / "views.py").read_text(encoding="utf-8").count("def ") == 3


def test_init_is_empty_and_no_tests_dir(tmp_path: Path):
    create_django_mini_examples(tmp_path)
    root = tmp_path / "django_mini"
    assert (root / "__init__.py").read_text(encoding="utf-8") == ""
    # A missing tests directory is the whole point (untested core module).
    assert not (root / "tests").exists()


def test_urls_wire_all_three_views(tmp_path: Path):
    create_django_mini_examples(tmp_path)
    urls = (tmp_path / "django_mini" / "urls.py").read_text(encoding="utf-8")
    for view in ("views.user_detail", "views.process_payment", "views.admin_override"):
        assert view in urls
