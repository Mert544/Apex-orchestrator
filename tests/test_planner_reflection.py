import os
import shutil
import tempfile

from app.engine.planner import Planner, Plan
from app.engine.feedback_loop import FeedbackLoop


class TestPlannerReflection:
    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.tmp_dir)

    def teardown_method(self):
        os.chdir(self.original_dir)
        try:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        except:
            pass

    def test_extract_issue_type_simple(self):
        planner = Planner()
        assert planner._extract_issue_type("eval usage") == "eval usage"
        assert planner._extract_issue_type("bare except") == "bare except"

    def test_extract_issue_type_with_prefix(self):
        planner = Planner()
        assert planner._extract_issue_type("security: eval usage") == "security"
        assert planner._extract_issue_type("test: missing docstring") == "test"

    def test_plan_uses_feedback_to_skip(self):
        feedback = FeedbackLoop(log_dir=self.tmp_dir)
        node_key = "eval usage:foo.py:10"
        for _ in range(3):
            feedback.update(node_key, 0.5, -0.8, "patch")

        planner = Planner(feedback=feedback)
        plan = planner.plan({"issue": "eval usage", "file": "foo.py", "line": 10})
        assert plan.primary == "escalate", f"Expected escalate but got {plan.primary}"

    def test_record_action_result(self):
        feedback = FeedbackLoop(log_dir=self.tmp_dir)
        planner = Planner(feedback=feedback)
        finding = {"issue": "eval usage", "file": "foo.py", "line": 10}
        planner.record_action_result(finding, success=True)
        assert len(feedback.entries) >= 2
