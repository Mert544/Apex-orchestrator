from __future__ import annotations

from pathlib import Path

from app.tools.async_safety import AsyncSafety, analyze_async_safety


def _write(tmp_path: Path, name: str, body: str) -> Path:
    f = tmp_path / name
    f.write_text(body, encoding="utf-8")
    return f


def test_time_sleep_in_async_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "mod.py",
        "import time\n"
        "async def handler():\n"
        "    await go()\n"
        "    time.sleep(1)\n",
    )
    result = analyze_async_safety(tmp_path)
    calls = {(b["function"], b["call"]) for b in result.blocking_calls}
    assert ("handler", "time.sleep") in calls
    assert result.blocking_call_count >= 1


def test_requests_get_in_async_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "mod.py",
        "import requests\n"
        "async def fetch():\n"
        "    await prep()\n"
        "    return requests.get('http://x')\n",
    )
    result = analyze_async_safety(tmp_path)
    calls = {b["call"] for b in result.blocking_calls}
    assert "requests.get" in calls


def test_subprocess_and_os_system_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "mod.py",
        "import subprocess, os\n"
        "async def run_it():\n"
        "    await prep()\n"
        "    subprocess.run(['ls'])\n"
        "    os.system('ls')\n",
    )
    result = analyze_async_safety(tmp_path)
    calls = {b["call"] for b in result.blocking_calls}
    assert "subprocess.run" in calls
    assert "os.system" in calls


def test_bare_open_in_async_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "mod.py",
        "async def load():\n"
        "    await prep()\n"
        "    with open('f') as fh:\n"
        "        return fh.read()\n",
    )
    result = analyze_async_safety(tmp_path)
    assert any(b["call"] == "open" for b in result.blocking_calls)


def test_awaitless_async_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "mod.py",
        "async def pointless():\n"
        "    return 42\n",
    )
    result = analyze_async_safety(tmp_path)
    awaitless = {(a["module"], a["function"]) for a in result.awaitless_async}
    assert ("mod", "pointless") in awaitless
    assert result.awaitless_async_count == 1


def test_clean_async_with_await_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "mod.py",
        "async def good():\n"
        "    return await compute()\n",
    )
    result = analyze_async_safety(tmp_path)
    assert result.blocking_calls == []
    assert result.awaitless_async == []


def test_sync_def_with_sleep_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "mod.py",
        "import time\n"
        "def sync_handler():\n"
        "    time.sleep(1)\n",
    )
    result = analyze_async_safety(tmp_path)
    assert result.blocking_calls == []
    assert result.awaitless_async == []


def test_async_for_counts_as_await(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "mod.py",
        "async def stream():\n"
        "    async for item in source():\n"
        "        handle(item)\n",
    )
    result = analyze_async_safety(tmp_path)
    assert result.awaitless_async == []


def test_nested_sync_def_sleep_not_attributed_to_coroutine(tmp_path: Path) -> None:
    # time.sleep lives in a NESTED sync function; the coroutine itself awaits,
    # so neither a blocking call nor an awaitless finding should appear.
    _write(
        tmp_path,
        "mod.py",
        "import time\n"
        "async def outer():\n"
        "    def inner():\n"
        "        time.sleep(1)\n"
        "    await go()\n",
    )
    result = analyze_async_safety(tmp_path)
    assert result.blocking_calls == []
    assert result.awaitless_async == []


def test_test_files_excluded(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_thing.py",
        "import time\n"
        "async def handler():\n"
        "    time.sleep(1)\n",
    )
    result = analyze_async_safety(tmp_path)
    assert result.blocking_calls == []
    assert result.awaitless_async == []


def test_empty_tree_is_safe(tmp_path: Path) -> None:
    result = analyze_async_safety(tmp_path)
    assert isinstance(result, AsyncSafety)
    assert result.blocking_calls == []
    assert result.awaitless_async == []
    assert result.blocking_call_count == 0
    assert result.awaitless_async_count == 0


def test_determinism(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.py",
        "import time, requests\n"
        "async def h():\n"
        "    time.sleep(1)\n"
        "    requests.post('x')\n"
        "async def silent():\n"
        "    return 1\n",
    )
    first = analyze_async_safety(tmp_path)
    second = analyze_async_safety(tmp_path)
    assert first == second
    assert first.blocking_calls == second.blocking_calls
    assert first.awaitless_async == second.awaitless_async
