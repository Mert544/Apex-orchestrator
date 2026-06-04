from __future__ import annotations

import ast
import urllib.request
from unittest.mock import patch

import pytest

from app.event_stream import ApexEventStreamServer, EventStream, StreamEvent
from app.execution.semantic.transforms.security import apply as security_apply
from app.execution.targeted_test_selector import TargetedTestSelector
from app.models.enums import QuestionType
from app.policies.constitution import (
    enforce_four_question_types,
    downgrade_if_unsupported,
    must_search_counter_evidence,
)


# ---------------------------------------------------------------------------
# security transform: still-missing rewrite / line-replacement edge cases.
# Every rewritten output is parsed with ast.parse() to guarantee valid Python,
# and flag transforms are checked for idempotency.
# ---------------------------------------------------------------------------


def _parse_ok(text: str) -> None:
    ast.parse(text)


class TestSecurityYamlLoad:
    def test_yaml_load_rewritten_to_safe_load(self):
        source = "import yaml\nx = yaml.load(data)\n"
        result = security_apply("t.py", source, "yaml.load is unsafe")
        assert result is not None
        out = result.patch_requests[0]["new_content"]
        assert result.transform_type == "yaml_load_to_safe_load"
        assert "yaml.safe_load(" in out
        _parse_ok(out)

    def test_yaml_load_with_explicit_loader_left_untouched(self):
        # An explicit Loader= means the caller already chose a loader (line 47-48).
        source = "import yaml\nx = yaml.load(data, Loader=yaml.SafeLoader)\n"
        result = security_apply("t.py", source, "yaml.load")
        assert result is None

    def test_yaml_other_load_attribute_ignored(self):
        # func.attr == 'load' but value is not the 'yaml' name (line 44-45).
        source = "x = config.load(data)\n"
        result = security_apply("t.py", source, "yaml")
        assert result is None

    def test_yaml_non_load_attribute_ignored(self):
        # An attribute call whose attr is not 'load' (line 42-43).
        source = "import yaml\nx = yaml.dump(data)\n"
        result = security_apply("t.py", source, "yaml")
        assert result is None

    def test_yaml_safe_load_is_idempotent(self):
        source = "import yaml\nx = yaml.load(data)\n"
        out = security_apply("t.py", source, "yaml").patch_requests[0]["new_content"]
        assert security_apply("t.py", out, "yaml") is None


class TestSecuritySqlInjection:
    def test_fstring_execute_flagged(self):
        source = 'cur.execute(f"select {x}")\n'
        result = security_apply("t.py", source, "sql injection")
        assert result is not None
        out = result.patch_requests[0]["new_content"]
        assert result.transform_type == "flag_sql_injection"
        assert "Apex: SQL injection" in out
        _parse_ok(out)

    def test_executemany_fstring_flagged(self):
        source = 'cur.executemany(f"insert {x}")\n'
        result = security_apply("t.py", source, "sql injection")
        assert result is not None
        assert "Apex: SQL injection" in result.patch_requests[0]["new_content"]

    def test_sql_unrelated_method_name_ignored(self):
        # Method name not in (execute, cursor, executemany) (line 84-85).
        source = 'cur.run(f"select {x}")\n'
        result = security_apply("t.py", source, "sql injection")
        assert result is None

    def test_sql_non_fstring_arg_ignored(self):
        # execute() but no JoinedStr arg (line 86-87).
        source = 'cur.execute("select 1")\n'
        result = security_apply("t.py", source, "sql injection")
        assert result is None

    def test_sql_flag_is_idempotent(self):
        source = 'cur.execute(f"select {x}")\n'
        out = security_apply("t.py", source, "sql").patch_requests[0]["new_content"]
        assert security_apply("t.py", out, "sql") is None


class TestSecurityPickle:
    def test_pickle_loads_flagged(self):
        source = "import pickle\nx = pickle.loads(data)\n"
        result = security_apply("t.py", source, "pickle deserialization")
        assert result is not None
        out = result.patch_requests[0]["new_content"]
        assert result.transform_type == "flag_pickle_loads"
        assert "Apex: untrusted pickle" in out
        _parse_ok(out)

    def test_pickle_non_loads_attribute_ignored(self):
        # attr != 'loads' (line 127-128).
        source = "import pickle\nx = pickle.load(fh)\n"
        result = security_apply("t.py", source, "pickle")
        assert result is None

    def test_pickle_other_object_loads_ignored(self):
        # attr == 'loads' but value is not the 'pickle' name (line 129-130).
        source = "x = json.loads(data)\n"
        result = security_apply("t.py", source, "pickle")
        assert result is None

    def test_pickle_flag_is_idempotent(self):
        source = "import pickle\nx = pickle.loads(data)\n"
        out = security_apply("t.py", source, "pickle").patch_requests[0]["new_content"]
        assert security_apply("t.py", out, "pickle") is None


class TestSecurityEvalEdges:
    def test_eval_non_name_func_ignored(self):
        # eval accessed as an attribute is not a bare eval() call (line 163-164).
        source = "x = mod.eval(data)\n"
        result = security_apply("t.py", source, "eval")
        assert result is None

    def test_eval_without_args_ignored(self):
        # eval() with no positional args (line 167-168).
        source = "x = eval()\n"
        result = security_apply("t.py", source, "eval")
        assert result is None

    def test_eval_already_literal_eval_arg_returns_none(self):
        # arg already starts with ast.literal_eval( (line 179-180).
        source = "import ast\nx = eval(ast.literal_eval(s))\n"
        result = security_apply("t.py", source, "eval")
        assert result is None

    def test_eval_already_json_loads_arg_returns_none(self):
        source = "import json\nx = eval(json.loads(s))\n"
        result = security_apply("t.py", source, "eval")
        assert result is None

    def test_eval_call_arg_rewritten_valid(self):
        # _get_arg_source Call branch (lines 292-296) -> unparsed call text.
        source = "x = eval(get_input())\n"
        result = security_apply("t.py", source, "eval")
        assert result is not None
        out = result.patch_requests[0]["new_content"]
        assert "ast.literal_eval(get_input())" in out
        _parse_ok(out)

    def test_eval_string_literal_arg_rewritten_valid(self):
        # _get_arg_source Constant str branch (lines 300-301).
        source = "x = eval('1+1')\n"
        result = security_apply("t.py", source, "eval")
        assert result is not None
        out = result.patch_requests[0]["new_content"]
        assert "ast.literal_eval('1+1')" in out
        _parse_ok(out)


class TestSecurityOsSystemEdges:
    def test_os_system_non_attribute_func_ignored(self):
        # bare system() call, func is a Name not Attribute (line 208-209).
        source = "system(cmd)\n"
        result = security_apply("t.py", source, "os.system")
        assert result is None

    def test_os_system_non_name_value_ignored(self):
        # attribute chain where value is not a plain Name (line 210-211).
        source = "self.os.system(cmd)\n"
        result = security_apply("t.py", source, "os.system")
        assert result is None

    def test_os_system_other_module_ignored(self):
        # value.id != 'os' (line 212-213).
        source = "shell.system(cmd)\n"
        result = security_apply("t.py", source, "os.system")
        assert result is None

    def test_os_other_attribute_ignored(self):
        # os.<attr> where attr != 'system' (line 214-215).
        source = "import os\nos.getpid()\n"
        result = security_apply("t.py", source, "os.system")
        assert result is None

    def test_os_system_no_args_ignored(self):
        # os.system() with no args (line 217-218).
        source = "import os\nos.system()\n"
        result = security_apply("t.py", source, "os.system")
        assert result is None

    def test_os_system_existing_imports_not_duplicated(self):
        # subprocess + shlex already imported -> no insertion (skipped).
        source = "import subprocess\nimport shlex\nos.system(cmd)\n"
        result = security_apply("t.py", source, "os.system")
        assert result is not None
        out = result.patch_requests[0]["new_content"]
        assert out.count("import subprocess") == 1
        assert out.count("import shlex") == 1
        # Correct rewrite tokenises with shlex.split, not a [cmd] one-element list.
        assert "subprocess.run(shlex.split(cmd)" in out
        _parse_ok(out)


class TestSecurityBareExceptEdges:
    def test_bare_except_with_type_ignored(self):
        # ExceptHandler that already has a type (line 260-261).
        source = "try:\n    x\nexcept ValueError:\n    pass\n"
        result = security_apply("t.py", source, "bare except")
        assert result is None


# ---------------------------------------------------------------------------
# targeted_test_selector: marker filtering + scan-failure exception paths.
# ---------------------------------------------------------------------------


def _project(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text(
        "def test_add():\n    assert 1 + 1 == 2\n"
    )
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    return tmp_path


class TestTargetedSelectorMarkers:
    def test_marker_filter_keeps_matching_test(self, tmp_path):
        _project(tmp_path)
        sel = TargetedTestSelector(project_root=str(tmp_path))

        class _Res:
            stdout = "@pytest.mark.slow: slow tests"
            stderr = ""

        with patch("subprocess.run", return_value=_Res()):
            tests = sel.select_tests(
                changed_files=["app/calc.py"], markers=["slow"]
            )
        assert any("test_calc.py" in t for t in tests)

    def test_marker_filter_no_match_falls_back_to_all(self, tmp_path):
        # When no test matches a marker, the filter returns the original list.
        _project(tmp_path)
        sel = TargetedTestSelector(project_root=str(tmp_path))

        class _Res:
            stdout = "no markers here"
            stderr = ""

        with patch("subprocess.run", return_value=_Res()):
            tests = sel.select_tests(
                changed_files=["app/calc.py"], markers=["nonexistent"]
            )
        assert any("test_calc.py" in t for t in tests)

    def test_marker_filter_subprocess_error_keeps_test(self, tmp_path):
        # subprocess raising -> the test is kept (except branch, line 141-142).
        _project(tmp_path)
        sel = TargetedTestSelector(project_root=str(tmp_path))
        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            tests = sel.select_tests(
                changed_files=["app/calc.py"], markers=["slow"]
            )
        assert any("test_calc.py" in t for t in tests)

    def test_unparseable_test_file_is_skipped(self, tmp_path):
        # Invalid Python in a test file hits the except in _find_test_names_in_dir.
        _project(tmp_path)
        (tmp_path / "tests" / "test_broken.py").write_text("def (:\n")
        sel = TargetedTestSelector(project_root=str(tmp_path))
        tests = sel.select_tests(changed_files=["app/calc.py"])
        assert any("test_calc.py" in t for t in tests)

    def test_find_tests_for_functions_no_tests_dir(self, tmp_path):
        # Early return when tests dir is absent (lines 106-107).
        sel = TargetedTestSelector(project_root=str(tmp_path))
        assert sel.select_tests(uncovered_functions=["whatever"]) == []

    def test_find_tests_for_functions_unreadable_file_skipped(self, tmp_path):
        # A file that fails to read is skipped (except branch, lines 117-118).
        _project(tmp_path)
        sel = TargetedTestSelector(project_root=str(tmp_path))
        orig = TargetedTestSelector._find_tests_for_functions
        with patch("pathlib.Path.read_text", side_effect=OSError("nope")):
            tests = orig(sel, ["test_add"])
        assert tests == []


# ---------------------------------------------------------------------------
# event_stream: HTTP handler routes (SSE, html, 404) over a live server.
# ---------------------------------------------------------------------------


class TestEventStreamServerRoutes:
    def test_unknown_path_returns_404(self):
        server = ApexEventStreamServer(host="127.0.0.1", port=18871)
        server.start()
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:18871/nope", method="GET"
            )
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(req, timeout=2)
            assert exc.value.code == 404
        finally:
            server.stop()

    def test_sse_endpoint_streams_emitted_event(self):
        server = ApexEventStreamServer(host="127.0.0.1", port=18872)
        server.start()
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:18872/events", method="GET"
            )
            resp = urllib.request.urlopen(req, timeout=2)
            assert resp.status == 200
            assert resp.headers["Content-Type"] == "text/event-stream"
            server.emit("security.alert", {"risk": "eval"})
            line = resp.readline()
            assert line.startswith(b"data: ")
            assert b"security.alert" in line
            resp.close()
        finally:
            server.stop()

    def test_sse_endpoint_times_out_with_no_events(self):
        # Subscribing then sending nothing exercises the queue.Empty path.
        server = ApexEventStreamServer(host="127.0.0.1", port=18873)
        server.start()
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:18873/events", method="GET"
            )
            resp = urllib.request.urlopen(req, timeout=3)
            assert resp.status == 200
            resp.close()
        finally:
            server.stop()

    def test_stop_without_start_is_safe(self):
        server = ApexEventStreamServer(host="127.0.0.1", port=18874)
        server.stop()  # _server is None -> no error
        assert server._server is None


def test_stream_event_defaults_node_local():
    ev = StreamEvent(timestamp=1.0, topic="t", payload={})
    assert ev.node_id == "local"


def test_subscribe_then_unsubscribe_removes_subscriber():
    es = EventStream()
    sq = es.subscribe()
    assert sq in es._subscribers
    es.unsubscribe(sq)
    assert sq not in es._subscribers


# ---------------------------------------------------------------------------
# policies.constitution: question enforcement + node downgrade rules.
# ---------------------------------------------------------------------------


class _Q:
    def __init__(self, qtype):
        self.qtype = qtype


class _Node:
    def __init__(self, evidence_for=None, evidence_against=None, confidence=0.9):
        self.evidence_for = evidence_for if evidence_for is not None else []
        self.evidence_against = (
            evidence_against if evidence_against is not None else []
        )
        self.confidence = confidence


class TestConstitution:
    def test_enforce_passes_with_all_four_types(self):
        questions = [
            _Q(QuestionType.MISSING),
            _Q(QuestionType.CONTRADICTION),
            _Q(QuestionType.RISK),
            _Q(QuestionType.DEEPENING),
        ]
        assert enforce_four_question_types(questions) is None

    def test_enforce_raises_when_a_type_is_missing(self):
        questions = [
            _Q(QuestionType.MISSING),
            _Q(QuestionType.CONTRADICTION),
            _Q(QuestionType.RISK),
        ]
        with pytest.raises(ValueError) as exc:
            enforce_four_question_types(questions)
        assert "Mandatory question classes missing" in str(exc.value)
        assert "DEEPENING" in str(exc.value)

    def test_downgrade_caps_confidence_without_evidence(self):
        node = _Node(evidence_for=[], confidence=0.95)
        result = downgrade_if_unsupported(node)
        assert result is node
        assert result.confidence == 0.30

    def test_downgrade_leaves_low_confidence_untouched(self):
        node = _Node(evidence_for=[], confidence=0.10)
        result = downgrade_if_unsupported(node)
        assert result.confidence == 0.10

    def test_downgrade_keeps_confidence_when_evidence_present(self):
        node = _Node(evidence_for=["proof"], confidence=0.95)
        result = downgrade_if_unsupported(node)
        assert result.confidence == 0.95

    def test_must_search_adds_placeholder_when_no_counter_evidence(self):
        node = _Node(evidence_against=[])
        result = must_search_counter_evidence(node)
        assert result is node
        assert len(result.evidence_against) == 1
        assert "search incomplete" in result.evidence_against[0]

    def test_must_search_preserves_existing_counter_evidence(self):
        node = _Node(evidence_against=["a real counterpoint"])
        result = must_search_counter_evidence(node)
        assert result.evidence_against == ["a real counterpoint"]
