"""Characterization tests for the shared finding-export helpers.

:mod:`app.reporting.codeclimate_export` and
:mod:`app.reporting.gitlab_sast_export` were de-duplicated by hoisting their
byte-identical ``_field`` / ``_path_of`` / ``_relative_path`` cores into
:mod:`app.reporting._finding_export_common`. These tests pin that the two
exporters still consume those helpers under their existing private aliases and,
critically, that the helpers behave identically to the inlined originals across
the dict/object and path-normalisation edge cases the formatters relied on.
"""

from __future__ import annotations

from app.reporting import _finding_export_common as common
from app.reporting import codeclimate_export as cc
from app.reporting import gitlab_sast_export as gl


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_exporters_reuse_shared_helpers_under_aliases():
    # Both formatters must route through the single shared implementation.
    assert cc._field is common.field
    assert gl._field is common.field
    assert cc._path_of is common.path_of
    assert gl._path_of is common.path_of
    assert cc._relative_path is common.relative_path
    assert gl._relative_path is common.relative_path


def test_field_reads_dict_object_and_default():
    assert common.field({"x": 1}, "x", 9) == 1
    assert common.field(_Obj(x=2), "x", 9) == 2
    assert common.field({}, "missing", "d") == "d"
    assert common.field(_Obj(), "missing", "d") == "d"
    # None present -> falls back to default (the partial-finding contract).
    assert common.field({"x": None}, "x", "d") == "d"
    assert common.field(_Obj(x=None), "x", "d") == "d"


def test_path_of_prefers_file_then_path_then_empty():
    assert common.path_of({"file": "a.py"}) == "a.py"
    assert common.path_of({"path": "b.py"}) == "b.py"
    assert common.path_of(_Obj(file="c.py", path="ignored.py")) == "c.py"
    assert common.path_of({}) == ""
    # file=None falls through to path; non-strings are stringified.
    assert common.path_of({"file": None, "path": "d.py"}) == "d.py"
    assert common.path_of({"file": 5}) == "5"


def test_relative_path_strips_root_and_is_a_noop_otherwise():
    assert common.relative_path("p.py", "") == "p.py"
    assert common.relative_path("/repo/p.py", "/repo") == "p.py"
    assert common.relative_path("/repo/p.py", "/repo/") == "p.py"
    # Backslash paths are normalised to forward slashes for the prefix test.
    assert common.relative_path("C:\\win\\d.py", "C:\\win") == "d.py"
    # Path not under root -> returned unchanged.
    assert common.relative_path("/other/p.py", "/repo") == "/other/p.py"


def test_helpers_drive_identical_path_resolution_in_both_exporters():
    finding = {"file": "/repo/sub/x.py", "line": 7, "severity": "high", "message": "m"}
    cc_out = cc.to_codeclimate_json([finding], project_root="/repo")
    gl_out = gl.to_gitlab_sast_json([finding], project_root="/repo")
    # Same repo-relative path lands in each format's location block.
    assert '"sub/x.py"' in cc_out
    assert '"sub/x.py"' in gl_out
