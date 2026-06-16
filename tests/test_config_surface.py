from __future__ import annotations

from app.tools.config_surface import (
    DYNAMIC_KEY,
    ConfigSurface,
    analyze_config_surface,
)


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _key(surface, name):
    for entry in surface.keys:
        if entry["key"] == name:
            return entry
    return None


def test_getenv_constant_key_detected(tmp_path):
    _write(tmp_path, "a.py", "import os\nKEY = os.getenv('API_KEY')\n")
    surface = analyze_config_surface(tmp_path)
    assert isinstance(surface, ConfigSurface)
    assert surface.total_reads == 1
    assert surface.reader_modules == 1
    entry = _key(surface, "API_KEY")
    assert entry == {"key": "API_KEY", "count": 1, "modules": 1}


def test_environ_subscript_detected(tmp_path):
    _write(tmp_path, "a.py", "import os\nX = os.environ['X']\n")
    surface = analyze_config_surface(tmp_path)
    assert surface.total_reads == 1
    assert _key(surface, "X") == {"key": "X", "count": 1, "modules": 1}


def test_environ_get_constant_detected(tmp_path):
    _write(tmp_path, "a.py", "import os\nDB = os.environ.get('DB_URL', 'sqlite')\n")
    surface = analyze_config_surface(tmp_path)
    assert surface.total_reads == 1
    assert _key(surface, "DB_URL")["count"] == 1


def test_non_constant_key_recorded_as_dynamic(tmp_path):
    _write(
        tmp_path,
        "a.py",
        "import os\n"
        "var = 'NAME'\n"
        "v1 = os.environ.get(var)\n"      # dynamic
        "v2 = os.getenv(var)\n"           # dynamic
        "v3 = os.environ[var]\n",         # dynamic
    )
    surface = analyze_config_surface(tmp_path)
    assert surface.total_reads == 3
    entry = _key(surface, DYNAMIC_KEY)
    assert entry is not None
    assert entry["count"] == 3
    # No constant key leaked in.
    assert {e["key"] for e in surface.keys} == {DYNAMIC_KEY}


def test_imported_from_os_forms_detected(tmp_path):
    _write(
        tmp_path,
        "a.py",
        "from os import getenv, environ\n"
        "a = getenv('A')\n"
        "b = environ['B']\n"
        "c = environ.get('C')\n",
    )
    surface = analyze_config_surface(tmp_path)
    assert surface.total_reads == 3
    assert {e["key"] for e in surface.keys} == {"A", "B", "C"}


def test_cross_module_aggregation(tmp_path):
    _write(tmp_path, "pkg/x.py", "import os\nv = os.getenv('SHARED')\n")
    _write(tmp_path, "pkg/y.py", "import os\nv = os.environ['SHARED']\n")
    _write(tmp_path, "pkg/z.py", "import os\nv = os.environ.get('OTHER')\n")
    surface = analyze_config_surface(tmp_path)
    assert surface.total_reads == 3
    assert surface.reader_modules == 3
    shared = _key(surface, "SHARED")
    assert shared["count"] == 2
    assert shared["modules"] == 2
    other = _key(surface, "OTHER")
    assert other["modules"] == 1


def test_scattered_flag_and_score(tmp_path):
    # One read each across four modules → spread thinly → scattered.
    for i in range(4):
        _write(tmp_path, f"m{i}.py", f"import os\nv = os.getenv('K{i}')\n")
    surface = analyze_config_surface(tmp_path)
    assert surface.reader_modules == 4
    assert surface.total_reads == 4
    assert surface.scattered is True
    assert surface.scatter_score == 1.0


def test_centralized_not_scattered(tmp_path):
    # All reads funnel through a single settings module → not scattered.
    body = "import os\n" + "".join(f"k{i} = os.getenv('K{i}')\n" for i in range(6))
    _write(tmp_path, "settings.py", body)
    surface = analyze_config_surface(tmp_path)
    assert surface.reader_modules == 1
    assert surface.total_reads == 6
    assert surface.scattered is False
    assert 0.0 < surface.scatter_score < 1.0


def test_unrelated_attributes_not_matched(tmp_path):
    _write(
        tmp_path,
        "a.py",
        "import os\n"
        "os.path.join('a', 'b')\n"        # not a config read
        "d = {'environ': 1}\n"
        "x = d['environ']\n"              # subscript of a dict, not os.environ
        "obj.getenv('NOPE')\n",           # getenv on some other object
    )
    surface = analyze_config_surface(tmp_path)
    assert surface.total_reads == 0
    assert surface.keys == []


def test_empty_tree_is_safe(tmp_path):
    surface = analyze_config_surface(tmp_path)
    assert surface.total_reads == 0
    assert surface.reader_modules == 0
    assert surface.keys == []
    assert surface.scattered is False
    assert surface.scatter_score == 0.0
    assert surface.to_dict() == {
        "keys": [],
        "total_reads": 0,
        "reader_modules": 0,
        "scattered": False,
        "scatter_score": 0.0,
    }


def test_tests_and_fixtures_excluded(tmp_path):
    _write(tmp_path, "app/real.py", "import os\nv = os.getenv('REAL')\n")
    _write(tmp_path, "tests/test_x.py", "import os\nv = os.getenv('TESTONLY')\n")
    _write(tmp_path, "pkg/conftest.py", "import os\nv = os.getenv('CONF')\n")
    _write(tmp_path, "fixtures/data.py", "import os\nv = os.getenv('FIX')\n")
    surface = analyze_config_surface(tmp_path)
    assert surface.total_reads == 1
    assert {e["key"] for e in surface.keys} == {"REAL"}


def test_determinism(tmp_path):
    _write(tmp_path, "pkg/x.py", "import os\nv = os.getenv('SHARED')\n")
    _write(tmp_path, "pkg/y.py", "import os\nv = os.environ['SHARED']\nw = os.getenv('B')\n")
    first = analyze_config_surface(tmp_path).to_dict()
    second = analyze_config_surface(tmp_path).to_dict()
    assert first == second
    # Ordering: SHARED (count 2) precedes B (count 1).
    order = [e["key"] for e in first["keys"]]
    assert order == ["SHARED", "B"]


def test_syntax_error_file_skipped(tmp_path):
    _write(tmp_path, "bad.py", "import os\ndef (:\n")            # unparseable
    _write(tmp_path, "good.py", "import os\nv = os.getenv('OK')\n")
    surface = analyze_config_surface(tmp_path)
    assert surface.total_reads == 1
    assert _key(surface, "OK") is not None
