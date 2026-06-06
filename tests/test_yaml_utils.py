import pytest

from app.utils.yaml_utils import load_yaml


def test_loads_mapping_from_file(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("name: apex\nvalue: 3\n", encoding="utf-8")
    data = load_yaml(p)
    assert data == {"name": "apex", "value": 3}


def test_accepts_str_path(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("k: v\n", encoding="utf-8")
    assert load_yaml(str(p)) == {"k": "v"}


def test_empty_file_yields_empty_dict(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    assert load_yaml(p) == {}


def test_non_mapping_top_level_is_rejected(tmp_path):
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_yaml(p)


def test_missing_file_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        load_yaml(tmp_path / "nope.yaml")
