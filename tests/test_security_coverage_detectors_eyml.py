"""New deterministic security detectors: os.popen, TLS verify=False, Zip-Slip.

Each capability is proven three ways: (a) the detector fires on the vulnerable
form with the correct severity, locus, and routing fix_kind; (b) it does NOT
fire on the clean/guarded form (zero false positives); (c) the label flows
through the canonical ``security_labels`` query the bridge consumes.

Deterministic, stdlib + pytest only.
"""

from __future__ import annotations

from app.engine.detectors import (
    detect,
    has_os_popen,
    has_tls_verify_disabled,
    has_zip_slip,
    security_labels,
)


def _security_findings(src: str):
    return [i for i in detect(src) if i.category == "security"]


class TestOsPopenDetector:
    def test_fires_on_os_popen(self) -> None:
        src = "import os\nos.popen('ls')\n"
        findings = _security_findings(src)
        assert len(findings) == 1
        f = findings[0]
        assert f.fix_kind == "os.popen"
        assert f.severity == "high"
        assert f.line == 2
        assert "os.popen" in f.message
        assert has_os_popen(src)
        assert "os.popen" in security_labels(src)

    def test_clean_subprocess_does_not_fire(self) -> None:
        src = "import subprocess\nsubprocess.run(['ls'])\n"
        assert not _security_findings(src)
        assert not has_os_popen(src)

    def test_unrelated_popen_method_not_fired(self) -> None:
        # A .popen on something that is not the os module is left alone.
        src = "conn.popen('ls')\n"
        assert not has_os_popen(src)


class TestTlsVerifyDetector:
    def test_fires_on_requests_verify_false(self) -> None:
        src = "import requests\nrequests.get(url, verify=False)\n"
        findings = _security_findings(src)
        assert len(findings) == 1
        f = findings[0]
        assert f.fix_kind == "tls-verify"
        assert f.severity == "high"
        assert f.line == 2
        assert "verify=False" in f.message
        assert has_tls_verify_disabled(src)
        assert "tls-verify" in security_labels(src)

    def test_fires_on_httpx_verify_false(self) -> None:
        src = "import httpx\nhttpx.post(url, json=d, verify=False)\n"
        assert has_tls_verify_disabled(src)

    def test_verify_true_does_not_fire(self) -> None:
        src = "import requests\nrequests.get(url, verify=True)\n"
        assert not has_tls_verify_disabled(src)

    def test_no_verify_kwarg_does_not_fire(self) -> None:
        src = "import requests\nrequests.get(url, timeout=5)\n"
        assert not has_tls_verify_disabled(src)

    def test_non_literal_verify_does_not_fire(self) -> None:
        # verify=flag (a variable) is not a provable disable — left alone.
        src = "import requests\nrequests.get(url, verify=flag)\n"
        assert not has_tls_verify_disabled(src)


class TestZipSlipDetector:
    def test_fires_on_unguarded_tar_extractall(self) -> None:
        src = "import tarfile\nt = tarfile.open(p)\nt.extractall(dest)\n"
        findings = _security_findings(src)
        assert len(findings) == 1
        f = findings[0]
        assert f.fix_kind == "zip-slip"
        assert f.severity == "high"
        assert f.line == 3
        assert "Zip-Slip" in f.message or "path traversal" in f.message
        assert has_zip_slip(src)
        assert "zip-slip" in security_labels(src)

    def test_fires_on_unguarded_zipfile_extractall(self) -> None:
        src = "import zipfile\nz = zipfile.ZipFile(p)\nz.extractall(dest)\n"
        assert has_zip_slip(src)

    def test_guarded_with_filter_does_not_fire(self) -> None:
        src = "import tarfile\nt = tarfile.open(p)\nt.extractall(dest, filter='data')\n"
        assert not has_zip_slip(src)

    def test_guarded_with_members_does_not_fire(self) -> None:
        src = "import zipfile\nz = zipfile.ZipFile(p)\nz.extractall(dest, members=safe)\n"
        assert not has_zip_slip(src)

    def test_kwargs_smuggle_treated_as_guarded(self) -> None:
        src = "import tarfile\nt = tarfile.open(p)\nt.extractall(dest, **opts)\n"
        assert not has_zip_slip(src)

    def test_unrelated_method_not_named_extractall(self) -> None:
        src = "obj.extract(name)\n"
        assert not has_zip_slip(src)
