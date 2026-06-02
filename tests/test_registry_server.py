import io
import json

from app.registry_server import RegistryHandler


class _Handler(RegistryHandler):
    """Drive RegistryHandler.do_GET without a real socket."""

    def __init__(self, path, plugin_dir):
        self.path = path
        self.__class__.plugin_dir = plugin_dir
        self.wfile = io.BytesIO()
        self._status = None
        self._headers = {}

    def send_response(self, status):
        self._status = status

    def send_header(self, k, v):
        self._headers[k] = v

    def end_headers(self):
        pass


def _run(path, tmp_path):
    h = _Handler(path, tmp_path)
    h.do_GET()
    body = h.wfile.getvalue().decode("utf-8")
    return h._status, body


def _plugins(tmp_path):
    (tmp_path / "alpha.py").write_text("def register(p):\n    pass\n")
    (tmp_path / "beta.py").write_text("def register(p):\n    pass\n")
    return tmp_path


def test_list_plugins(tmp_path):
    _plugins(tmp_path)
    status, body = _run("/plugins", tmp_path)
    assert status == 200
    data = json.loads(body)
    names = {p["name"] for p in data["plugins"]}
    assert {"alpha", "beta"} <= names


def test_plugin_detail_found(tmp_path):
    _plugins(tmp_path)
    status, body = _run("/plugins/alpha", tmp_path)
    assert status == 200
    assert json.loads(body)["download_url"] == "/download/alpha.py"


def test_plugin_detail_not_found(tmp_path):
    _plugins(tmp_path)
    status, body = _run("/plugins/missing", tmp_path)
    assert status == 404


def test_download_plugin(tmp_path):
    _plugins(tmp_path)
    status, body = _run("/download/alpha.py", tmp_path)
    assert status == 200
    assert "def register" in body


def test_download_missing(tmp_path):
    _plugins(tmp_path)
    status, _ = _run("/download/nope.py", tmp_path)
    assert status == 404


def test_unknown_path(tmp_path):
    status, body = _run("/whatever", tmp_path)
    assert status == 404
    assert "Not found" in body
