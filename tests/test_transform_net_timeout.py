from __future__ import annotations

from app.engine.detectors import has_network_call_without_timeout
from app.execution.semantic.transforms.net_timeout import apply as net_timeout_apply

_MARKER = "RELIABILITY (Apex: add a timeout="


def _new_content(source: str) -> str | None:
    result = net_timeout_apply("test.py", source, "Add request timeouts in test.py")
    return None if result is None else result.patch_requests[0]["new_content"]


def test_requests_get_without_timeout_is_flagged():
    source = "import requests\nr = requests.get(url)\n"
    out = _new_content(source)
    assert out is not None
    assert _MARKER in out
    assert "requests.get(url)" in out  # call preserved, only annotated


def test_requests_get_with_timeout_is_not_flagged():
    source = "import requests\nr = requests.get(url, timeout=5)\n"
    assert _new_content(source) is None


def test_requests_post_with_kwargs_splat_is_not_flagged():
    # A **kwargs could smuggle in timeout — stay conservative and skip.
    source = "import requests\nr = requests.post(url, **opts)\n"
    assert _new_content(source) is None


def test_urllib_urlopen_is_flagged():
    source = "import urllib.request\nr = urllib.request.urlopen(url)\n"
    out = _new_content(source)
    assert out is not None
    assert _MARKER in out


def test_bare_urlopen_is_flagged():
    source = "from urllib.request import urlopen\nr = urlopen(url)\n"
    out = _new_content(source)
    assert out is not None
    assert _MARKER in out


def test_httpx_get_is_flagged():
    source = "import httpx\nr = httpx.get(url)\n"
    out = _new_content(source)
    assert out is not None
    assert _MARKER in out


def test_non_network_call_is_not_flagged():
    # An ambiguous owner like a session/object is out of scope.
    source = "def f(foo, x):\n    return foo.get(x)\n"
    assert _new_content(source) is None


def test_session_get_is_out_of_scope():
    source = "def f(session, url):\n    return session.get(url)\n"
    assert _new_content(source) is None


def test_idempotent_running_twice_does_not_double_comment():
    source = "import requests\nr = requests.get(url)\n"
    once = _new_content(source)
    assert once is not None
    twice = net_timeout_apply("test.py", once, "Add request timeouts in test.py")
    assert twice is None  # already flagged on the preceding line
    assert once.count(_MARKER) == 1


def test_syntax_error_returns_none():
    assert _new_content("def (:\n") is None


def test_detector_agrees_with_transform():
    flagged = "import requests\nr = requests.get(url)\n"
    safe = "import requests\nr = requests.get(url, timeout=5)\n"
    assert has_network_call_without_timeout(flagged) is True
    assert (_new_content(flagged) is not None) is True
    assert has_network_call_without_timeout(safe) is False
    assert _new_content(safe) is None
