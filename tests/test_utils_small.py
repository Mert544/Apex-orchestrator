from app.memory.dedup import ExactQuestionDeduplicator
from app.utils.ids import make_child_id


def test_make_child_id_format():
    assert make_child_id("x.a", 0, 1) == "x.a-0-1"
    assert make_child_id("root", 2, 3) == "root-2-3"


def test_deduplicator_normalize():
    d = ExactQuestionDeduplicator()
    assert d.normalize("  Hello World  ") == "hello world"
    assert d.normalize("SAME") == d.normalize("same")
