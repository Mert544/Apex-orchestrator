"""JS driver<->Python splice offset seam — astral-char (emoji) correctness.

The ts_driver emits ``getStart``/``getEnd`` / ``insertOffset`` as UTF-16 CODE-UNIT
indices (the SourceFile text's native index). The Python side decodes the file via
``read_text(encoding="utf-8")`` into a CODE-POINT-indexed ``str`` and splices with
``str`` slicing. They agree on the BMP (and on a leading BOM) but diverge by +1 per
astral character (emoji, U+10000+) BEFORE the splice site, so a raw splice on the
code-unit offset lands one position early per astral char. The re-parse oracles
CATCH the corrupt result and REFUSE, so today the symptom is a SILENT FALSE-REFUSAL
(lost capability) on every emoji-bearing file across all six JS objectives — not
landed corruption.

The fix re-indexes each driver offset with :func:`_u16_to_codepoint` BEFORE slicing
at the three Python splice sites (``_splice_body`` — also the adapter ``apply``
path; ``splice_jsdoc``; ``_splice_export``). The driver stays UTF-16 (its in-process
``cmdFill`` slices the same code-unit string self-consistently). ``encoding="utf-8"``
is kept (NEVER ``utf-8-sig``) so the BOM stays one unit / one code point on both
sides. An out-of-range or surrogate-splitting offset maps to ``None`` -> refuse,
never corrupt.

Covers: the ``_u16_to_codepoint`` / ``_is_low_surrogate`` helpers (BMP identity,
1-astral off-by-one, multi-astral, BOM identity, CJK/CRLF identity, out-of-range ->
None, surrogate-split -> None, negative -> None); the three headline false-refusal
regressions (a leading-emoji comment before an exported fn / a throw-stub now LANDS
correctly on js-wire-exports / document-export-jsdoc / js-tdd's body splice instead
of refusing); the driver-grounded seam parity (the Python re-splice matches the
driver's own ``fill`` byte-for-byte on BMP/CJK/CRLF/BOM/astral files); and that BOM
survives byte-for-byte in the landed contents. The node-backed arms skip cleanly
when node + global ``typescript`` are unavailable; the pure helper tests always run.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.execution.lang.js_adapter import (
    Edit,
    JavaScriptAdapter,
    JsStub,
    TargetQuery,
    _is_low_surrogate,
    _splice_body,
    _u16_to_codepoint,
)

_EMOJI = "\U0001F600"  # 😀 : 1 code point, 2 UTF-16 code units, 4 UTF-8 bytes


# --- environment guard (the node-backed arms are opt-in by availability) -------

def _node_ok() -> bool:
    """True when ``node`` is on PATH and the global ``typescript`` resolves — the
    minimum for the LLM-free driver (scan / wire-targets / doc-targets) to run."""
    from app.execution.js.js_tool import global_node_modules

    if shutil.which("node") is None:
        return False
    nm = global_node_modules()
    return bool(nm) and (Path(nm) / "typescript").is_dir()


_needs_node = pytest.mark.skipif(not _node_ok(),
                                 reason="node + global typescript not available")


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


def _with_package_json(root: Path) -> Path:
    (root / "package.json").write_text(
        '{ "name": "d", "version": "1.0.0" }\n', encoding="utf-8")
    return root


# --- the helper: _u16_to_codepoint / _is_low_surrogate (pure, always run) ------

def test_u16_identity_on_bmp_ascii():
    # On pure ASCII/BMP, UTF-16 code units == code points -> identity remap.
    assert _u16_to_codepoint("abc", 0) == 0
    assert _u16_to_codepoint("abc", 2) == 2
    assert _u16_to_codepoint("abc", 3) == 3  # end-of-string offset is in range


def test_u16_one_leading_astral_is_off_by_one():
    # 😀x : the emoji is 2 code units / 1 code point, so the code-unit offset of `x`
    # is 2 but its code-point index is 1 (the +1 divergence the bug describes).
    s = _EMOJI + "x"
    assert _u16_to_codepoint(s, 2) == 1
    assert _u16_to_codepoint(s, 3) == 2  # past `x` (end) -> code-point 2


def test_u16_multi_astral_accumulates():
    # Two leading emoji: code-unit 4 -> code-point 2 (each astral char is +1 skew).
    s = _EMOJI + _EMOJI + "x"
    assert _u16_to_codepoint(s, 4) == 2
    assert _u16_to_codepoint(s, 5) == 3


def test_u16_bom_is_identity():
    # U+FEFF is ONE UTF-16 code unit AND ONE code point, so the remap is identity
    # through a leading BOM (and the read must stay utf-8, never utf-8-sig).
    s = "﻿" + "export"
    assert _u16_to_codepoint(s, 1) == 1
    assert _u16_to_codepoint(s, 7) == 7


def test_u16_cjk_and_crlf_are_identity():
    # CJK is BMP (1 unit = 1 code point) and CRLF is two BMP units; both remap to
    # identity -> we must NOT over-correct non-astral multibyte / line endings.
    assert _u16_to_codepoint("中文x", 2) == 2
    assert _u16_to_codepoint("a\r\nb", 3) == 3  # past the \r\n


def test_u16_out_of_range_is_none():
    # An offset past the end (a stale scan) refuses rather than slicing garbage.
    assert _u16_to_codepoint(_EMOJI + "x", 99) is None
    assert _u16_to_codepoint("abc", 4) is None


def test_u16_surrogate_split_is_none():
    # An offset landing BETWEEN the high and low half of an astral char would split
    # a surrogate pair -> refuse (never corrupt). For "😀", code-unit 1 is mid-pair.
    assert _u16_to_codepoint(_EMOJI, 1) is None
    assert _u16_to_codepoint(_EMOJI + _EMOJI, 3) is None  # mid second pair


def test_u16_negative_is_none():
    assert _u16_to_codepoint("abc", -1) is None


def test_is_low_surrogate_flags_only_the_pair_middle():
    # The guard is byte-precise: only the SECOND code unit of a surrogate pair (the
    # low half) is flagged; the high half and BMP units are not.
    buf = _EMOJI.encode("utf-16-le")  # [high, low]
    assert _is_low_surrogate(buf, 0) is False  # high surrogate
    assert _is_low_surrogate(buf, 2) is True   # low surrogate (mid-pair byte_pos)
    ascii_buf = "ab".encode("utf-16-le")
    assert _is_low_surrogate(ascii_buf, 0) is False
    assert _is_low_surrogate(ascii_buf, 4) is False  # past end


# --- _splice_body: the js-tdd / implement-from-jsdoc splice (pure + node) -------

def test_splice_body_remaps_astral_offset_pure():
    # The headline js-tdd regression at the splice locus: a stub whose body block
    # follows a leading emoji. The driver's body span is in UTF-16 code units; with
    # the remap the body `{ ... }` is replaced exactly, NOT one char early.
    src = "// " + _EMOJI + " b\nfunction s(a) {\n  throw new Error('x');\n}\n"
    # code-UNIT offsets of the body block (what the driver emits): find via utf-16.
    brace_cu = len(src[:src.index("{")].encode("utf-16-le")) // 2
    end_cu = len(src[:src.index("}") + 1].encode("utf-16-le")) // 2
    stub = JsStub(name="s", params=("a",), body_start=brace_cu, body_end=end_cu)
    out = _splice_body(src, stub, "return a;")
    assert out == "// " + _EMOJI + " b\nfunction s(a) { return a; }\n"


def test_splice_body_refuses_out_of_range_and_surrogate_split():
    src = _EMOJI + "fn"
    # past end -> None (stale span)
    assert _splice_body(src, JsStub("s", (), 99, 100), "x") is None
    # surrogate-split start -> None (never corrupt)
    assert _splice_body(src, JsStub("s", (), 1, 3), "x") is None


@_needs_node
def test_splice_body_matches_driver_fill_on_astral_file(tmp_path: Path):
    # Driver-grounded: scan a REAL emoji file for its (code-unit) stub span, splice
    # it in Python via _splice_body, and assert it equals the driver's OWN in-process
    # fill byte-for-byte — the seam now agrees on an astral file.
    from app.execution.js.js_tool import fill_body, scan_stubs

    src = "// " + _EMOJI + " banner\nfunction s(a) {\n  throw new Error('x');\n}\n"
    root = _project(tmp_path, "src/m.js", src)
    stub = scan_stubs(root, "src/m.js")[0]
    py = _splice_body(src, stub, "return a;")
    assert fill_body(root, "src/m.js", "s", "return a;")
    driver = (root / "src" / "m.js").read_text(encoding="utf-8")
    assert py == driver
    assert py == "// " + _EMOJI + " banner\nfunction s(a) { return a; }\n"


@_needs_node
@pytest.mark.parametrize("label,raw", [
    ("bmp", b"function s(a) {\n  throw new Error('x');\n}\n"),
    ("cjk", "// 中文 b\nfunction s(a) {\n  throw new Error('x');\n}\n".encode()),
    ("crlf", b"// hi\r\nfunction s(a) {\r\n  throw new Error('x');\r\n}\r\n"),
    ("bom", "﻿function s(a) {\n  throw new Error('x');\n}\n".encode()),
    ("astral", ("// " + _EMOJI + " b\nfunction s(a) {\n  throw new Error('x');\n}\n").encode()),
])
def test_splice_body_seam_parity_across_encodings(tmp_path: Path, label: str, raw: bytes):
    # BMP/CJK/CRLF/BOM stay correct (and astral is now correct): the Python re-splice
    # matches the driver's own fill byte-for-byte. Compare RAW bytes so the harness'
    # universal-newline read does not mask a CRLF round-trip.
    from app.execution.js.js_tool import fill_body, scan_stubs

    src = raw.decode("utf-8")
    root = tmp_path / label
    (root / "src").mkdir(parents=True)
    (root / "src" / "m.js").write_bytes(raw)  # exact bytes (preserve CRLF/BOM)
    stub = scan_stubs(root, "src/m.js")[0]
    py = _splice_body(src, stub, "return a;")
    assert fill_body(root, "src/m.js", "s", "return a;")
    driver = (root / "src" / "m.js").read_bytes().decode("utf-8")
    assert py == driver, f"{label}: python re-splice diverged from driver fill"


@_needs_node
def test_adapter_apply_lands_astral_stub_correctly(tmp_path: Path):
    # The SECOND entry into the body span — JavaScriptAdapter.locate -> apply (the
    # js-tdd _land_body path) — also lands correctly on an emoji file (apply routes
    # through _splice_body, so the remap covers it too; this guards that linkage).
    from app.execution.js.js_tool import scan_stubs

    src = "// " + _EMOJI + " b\nfunction s(a) {\n  throw new Error('x');\n}\n"
    root = _project(tmp_path, "src/m.js", src)
    stub = scan_stubs(root, "src/m.js")[0]
    adapter = JavaScriptAdapter()
    located = adapter.locate(adapter.parse(src), src,
                             TargetQuery(name="s", extra={"stub": stub}))
    assert located is not None
    out = adapter.apply(src, located, Edit(body="return a;"))
    assert out == "// " + _EMOJI + " b\nfunction s(a) { return a; }\n"


# --- end-to-end false-refusal regressions (need node; no jest needed) ----------

@_needs_node
def test_js_wire_exports_lands_on_emoji_file_not_refused(tmp_path: Path):
    # js-wire-exports: a leading emoji comment before an un-exported public function.
    # Pre-fix the splice landed one char early -> the superset oracle refused. Now it
    # prepends `export ` at the correct statement start and the oracle accepts it.
    from app.execution.objectives.js_wire_exports import (
        plan_js_wire_exports,
        wireable_targets,
    )

    src = "// " + _EMOJI + " banner\nfunction pub(a) { return a; }\n"
    root = _with_package_json(tmp_path)
    _project(root, "src/w.ts", src)
    assert [t.name for t in wireable_targets(root, "src/w.ts")] == ["pub"]
    landed = plan_js_wire_exports(str(root), "src/w.ts").new_contents.get("src/w.ts")
    assert landed == "// " + _EMOJI + " banner\nexport function pub(a) { return a; }\n"


@_needs_node
def test_document_export_jsdoc_lands_on_emoji_file_not_refused(tmp_path: Path):
    # document-export-jsdoc: a leading emoji comment before an exported, return-typed
    # function. The JSDoc must splice in as leading trivia at the STATEMENT start
    # (after the emoji comment), not one char early -> the re-parse oracle accepts it.
    from app.execution.objectives.document_export_jsdoc import (
        plan_document_export_jsdoc,
    )

    src = "// " + _EMOJI + " banner\nexport function g(a: number): number {\n  return a;\n}\n"
    root = _with_package_json(tmp_path)
    _project(root, "src/g.ts", src)
    landed = plan_document_export_jsdoc(str(root), "src/g.ts").new_contents.get("src/g.ts")
    assert landed is not None  # NOT a false-refusal
    assert landed.startswith("// " + _EMOJI + " banner\n/**")
    assert "@param a" in landed and "@returns {number}" in landed
    # the original function body and signature survive untouched after the JSDoc
    assert landed.endswith("export function g(a: number): number {\n  return a;\n}\n")


@_needs_node
def test_js_tdd_body_splice_lands_on_emoji_file(tmp_path: Path):
    # js-tdd's body splice (the _land_body locate->apply path on a synthesised body):
    # a leading emoji comment before a throw-stub. We drive the splice directly with
    # the driver-located span (no jest install needed) and assert the body block is
    # replaced exactly, the surrounding emoji comment intact.
    from app.execution.js.js_tool import scan_stubs

    src = "// " + _EMOJI + " hdr\nfunction add(a, b) {\n  throw new Error('x');\n}\n"
    root = _project(tmp_path, "src/math.js", src)
    stub = scan_stubs(root, "src/math.js")[0]
    assert stub.name == "add"
    out = _splice_body(src, stub, "return a + b;")
    assert out == "// " + _EMOJI + " hdr\nfunction add(a, b) { return a + b; }\n"


@_needs_node
def test_bom_survives_byte_for_byte_in_wired_contents(tmp_path: Path):
    # BOM safety end-to-end: a file whose first code point is U+FEFF, read with
    # encoding="utf-8" (NOT utf-8-sig), keeps the BOM as one unit/one code point on
    # both sides; the wired contents preserve it byte-for-byte. A future switch to
    # utf-8-sig (which drops the BOM and shifts every offset) trips this.
    from app.execution.objectives.js_wire_exports import plan_js_wire_exports

    src = "﻿// hi\nfunction pub(a) { return a; }\n"
    root = _with_package_json(tmp_path)
    _project(root, "src/w.ts", src)
    landed = plan_js_wire_exports(str(root), "src/w.ts").new_contents.get("src/w.ts")
    assert landed is not None
    assert landed.startswith("﻿")  # BOM intact (not dropped)
    assert landed == "﻿// hi\nexport function pub(a) { return a; }\n"
