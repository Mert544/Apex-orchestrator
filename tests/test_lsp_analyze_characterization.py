"""Byte-identical characterization harness for LSPServer._analyze.

Loads the pre-refactor ``app/lsp/server.py`` from ``git show HEAD:...`` as an
isolated module and compares its ``_analyze`` output against the current
implementation across a corpus covering every branch. Zero mismatches proves
the refactor is output-preserving.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types

import pytest

from app.lsp.server import LSPServer


def _load_original() -> type:
    src = subprocess.check_output(
        ["git", "show", "HEAD:app/lsp/server.py"], text=True
    )
    mod = types.ModuleType("_lsp_server_original")
    mod.__file__ = "<HEAD:app/lsp/server.py>"
    spec = importlib.util.spec_from_loader(mod.__name__, loader=None)
    mod.__spec__ = spec
    sys.modules[mod.__name__] = mod
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod.LSPServer


ORIGINAL = _load_original()


CORPUS = [
    "",
    "x = 1\n",
    "def f():\n    pass\n",
    "def f():\n    '''doc'''\n    pass\n",
    "class C:\n    pass\n",
    "class C:\n    '''doc'''\n    pass\n",
    "async def g():\n    return 1\n",
    "async def g():\n    '''d'''\n    return 1\n",
    "eval('1+1')\n",
    "import os\nos.system('ls')\n",
    "x = eval('2')\nos.system('echo hi')\n",
    "try:\n    pass\nexcept:\n    pass\n",
    "try:\n    pass\nexcept Exception:\n    pass\n",
    "def broken(:\n    pass\n",       # SyntaxError
    "this is not python !!!\n",        # SyntaxError
    "(\n",                            # SyntaxError, offset variants
    "\n\n\neval('x')\n",
    "def outer():\n    def inner():\n        eval('z')\n    return inner\n",
    "class A:\n    def m(self):\n        try:\n            os.system('x')\n        except:\n            eval('y')\n",
    "import os\nresult = os.system('cmd') + eval('1')\n",
    "notos.system('x')\n",            # attribute system but not os
    "os.path.join('a')\n",            # os attr but not system
    "evaluate('x')\n",                # name starts with eval but not eval
    "lambda: eval('1')\n",
    "def f(): pass  # no body docstring on one line\n",
    "@decorator\ndef d():\n    pass\n",
    "x = {'a': 1}\nfor i in range(3):\n    print(i)\n",
    "def f():\n    '''doc'''\n    eval('inner')\n    os.system('y')\n    try:\n        pass\n    except:\n        pass\n",
]


@pytest.mark.parametrize("source", CORPUS, ids=range(len(CORPUS)))
def test_analyze_byte_identical(source: str) -> None:
    orig = ORIGINAL()._analyze("file:///t.py", source)
    new = LSPServer()._analyze("file:///t.py", source)
    assert json.dumps(orig, sort_keys=True) == json.dumps(new, sort_keys=True)


def test_uri_argument_does_not_affect_output() -> None:
    for uri in ("", "file:///a", "untitled:1", "weird"):
        assert ORIGINAL()._analyze(uri, "eval('1')\n") == LSPServer()._analyze(
            uri, "eval('1')\n"
        )


def test_corpus_covers_all_branches() -> None:
    combined = "\n".join(
        json.dumps(LSPServer()._analyze("u", s)) for s in CORPUS
    )
    for marker in (
        "SyntaxError",
        "eval() detected",
        "os.system() detected",
        "bare except",
        "missing docstring",
    ):
        assert marker in combined
