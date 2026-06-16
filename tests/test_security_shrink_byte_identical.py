"""Characterization test: prove ``_patch_weak_hash`` and ``_patch_eval`` in
``app/execution/semantic/transforms/security.py`` stay BYTE-IDENTICAL after the
cx-shrinking refactor that decomposed each into small pure helpers.

The pristine pre-refactor source is embedded below as base64. It is loaded as a
SUBMODULE of the real ``app.execution.semantic.transforms`` package so its
relative imports (``..result``, ``.base``) resolve, then for a corpus of
convertible AND must-NOT-convert snippets we run BOTH the original and the live
(refactored) entry points and assert the full result matches exactly. We compare
through three surfaces per function: the direct ``_patch_*`` helper and the
public ``apply`` dispatch (which routes by title keyword). Zero mismatch is the
proof. Self-contained — no /tmp dependency, stdlib-only.
"""

from __future__ import annotations

import ast
import base64
import importlib.util
import sys

from app.execution.semantic.transforms import security as live


_ORIG_SECURITY_B64 = (
    "ZnJvbSBfX2Z1dHVyZV9fIGltcG9ydCBhbm5vdGF0aW9ucwoKaW1wb3J0IGFzdAoKZnJvbSAuLnJl"
    "c3VsdCBpbXBvcnQgU2VtYW50aWNQYXRjaFJlc3VsdApmcm9tIC5iYXNlIGltcG9ydCBfZ2V0X2lu"
    "ZGVudCwgaW1wb3J0X2luc2VydF9pbmRleAoKCmRlZiBfc2VsZWN0X3BhdGNoZXIoaXNzdWU6IHN0"
    "cik6CiAgICAiIiJSZXR1cm4gdGhlIHBhdGNoIGZ1bmN0aW9uIHdob3NlIGtleXdvcmQgbWF0Y2hl"
    "cyBgYGlzc3VlYGAsIGVsc2UgTm9uZS4KCiAgICBPcmRlciBtYXR0ZXJzIGFuZCBtaXJyb3JzIHRo"
    "ZSBvcmlnaW5hbCBpZi1jaGFpbiBleGFjdGx5OiB0aGUgZmlyc3Qga2V5d29yZAogICAgZ3JvdXAg"
    "dGhhdCBtYXRjaGVzIHdpbnMuCiAgICAiIiIKICAgIGZvciBrZXl3b3JkcywgcGF0Y2hlciBpbiBf"
    "RElTUEFUQ0g6CiAgICAgICAgaWYgYW55KGtleXdvcmQgaW4gaXNzdWUgZm9yIGtleXdvcmQgaW4g"
    "a2V5d29yZHMpOgogICAgICAgICAgICByZXR1cm4gcGF0Y2hlcgogICAgcmV0dXJuIE5vbmUKCgpk"
    "ZWYgYXBwbHkocmVsX3BhdGg6IHN0ciwgc291cmNlOiBzdHIsIHRpdGxlOiBzdHIpIC0+IFNlbWFu"
    "dGljUGF0Y2hSZXN1bHQgfCBOb25lOgogICAgdHJ5OgogICAgICAgIHRyZWUgPSBhc3QucGFyc2Uo"
    "c291cmNlKQogICAgZXhjZXB0IFN5bnRheEVycm9yOgogICAgICAgIHJldHVybiBOb25lCgogICAg"
    "cGF0Y2hlciA9IF9zZWxlY3RfcGF0Y2hlcih0aXRsZS5sb3dlcigpKQogICAgaWYgcGF0Y2hlciBp"
    "cyBOb25lOgogICAgICAgIHJldHVybiBOb25lCiAgICByZXR1cm4gcGF0Y2hlcihyZWxfcGF0aCwg"
    "c291cmNlLCB0cmVlKQoKCmRlZiBfcGF0Y2hfd2Vha19oYXNoKHJlbF9wYXRoOiBzdHIsIHNvdXJj"
    "ZTogc3RyLCB0cmVlOiBhc3QuTW9kdWxlKSAtPiBTZW1hbnRpY1BhdGNoUmVzdWx0IHwgTm9uZToK"
    "ICAgICIiIkZsYWcgYSB3ZWFrIGBgaGFzaGxpYi5tZDUoKWBgL2Bgc2hhMSgpYGAgdXNlZCBmb3Ig"
    "c2VjdXJpdHkgd2l0aCBhIGNvbW1lbnQuCgogICAgVGhlcmUgaXMgbm8gc2FmZSBhdXRvbWF0aWMg"
    "cmV3cml0ZTogc3dpdGNoaW5nIHRvIHNoYTI1NiBjaGFuZ2VzIHRoZSBkaWdlc3QKICAgIChicmVh"
    "a2luZyBhbnkgc3RvcmVkL2NvbXBhcmVkIGhhc2gpLCBhbmQgYWRkaW5nIGBgdXNlZGZvcnNlY3Vy"
    "aXR5PUZhbHNlYGAgaXMKICAgIG9ubHkgY29ycmVjdCB3aGVuIHRoZSBjYWxsZXIgcmVhbGx5IGlz"
    "bid0IHVzaW5nIGl0IGZvciBzZWN1cml0eSDigJQgYSBqdWRnbWVudAogICAgdGhlIHRvb2wgY2Fu"
    "J3QgbWFrZS4gU28gd2UgYW5ub3RhdGUgdGhlIGNhbGwgc2l0ZSwgbGlrZSB0aGUgcGlja2xlL1NR"
    "TCBmbGFncy4KICAgICIiIgogICAgZm9yIG5vZGUgaW4gYXN0LndhbGsodHJlZSk6CiAgICAgICAg"
    "aWYgbm90IGlzaW5zdGFuY2Uobm9kZSwgYXN0LkNhbGwpOgogICAgICAgICAgICBjb250aW51ZQog"
    "ICAgICAgIGZ1bmMgPSBub2RlLmZ1bmMKICAgICAgICBpZiBub3QgKGlzaW5zdGFuY2UoZnVuYywg"
    "YXN0LkF0dHJpYnV0ZSkgYW5kIGZ1bmMuYXR0ciBpbiAoIm1kNSIsICJzaGExIikpOgogICAgICAg"
    "ICAgICBjb250aW51ZQogICAgICAgIGlmIG5vdCAoaXNpbnN0YW5jZShmdW5jLnZhbHVlLCBhc3Qu"
    "TmFtZSkgYW5kIGZ1bmMudmFsdWUuaWQgPT0gImhhc2hsaWIiKToKICAgICAgICAgICAgY29udGlu"
    "dWUKICAgICAgICBpZiBhbnkoa3cuYXJnID09ICJ1c2VkZm9yc2VjdXJpdHkiIGFuZCBpc2luc3Rh"
    "bmNlKGt3LnZhbHVlLCBhc3QuQ29uc3RhbnQpCiAgICAgICAgICAgICAgIGFuZCBrdy52YWx1ZS52"
    "YWx1ZSBpcyBGYWxzZSBmb3Iga3cgaW4gbm9kZS5rZXl3b3Jkcyk6CiAgICAgICAgICAgIGNvbnRp"
    "bnVlICAjIGNhbGxlciBhbHJlYWR5IGRlY2xhcmVkIHRoaXMgbm9uLXNlY3VyaXR5CgogICAgICAg"
    "IGxpbmVubyA9IG5vZGUubGluZW5vCiAgICAgICAgbGluZXMgPSBzb3VyY2Uuc3BsaXRsaW5lcyhr"
    "ZWVwZW5kcz1UcnVlKQogICAgICAgIGlmIGxpbmVubyA+IGxlbihsaW5lcyk6CiAgICAgICAgICAg"
    "IGNvbnRpbnVlCiAgICAgICAgbGluZV9jb250ZW50ID0gbGluZXNbbGluZW5vIC0gMV0KICAgICAg"
    "ICBwcmV2X2xpbmUgPSBsaW5lc1tsaW5lbm8gLSAyXSBpZiBsaW5lbm8gPj0gMiBlbHNlICIiCiAg"
    "ICAgICAgaWYgIkFwZXg6IHdlYWsgaGFzaCIgaW4gbGluZV9jb250ZW50IG9yICJBcGV4OiB3ZWFr"
    "IGhhc2giIGluIHByZXZfbGluZToKICAgICAgICAgICAgY29udGludWUgICMgYWxyZWFkeSBmbGFn"
    "Z2VkCiAgICAgICAgaW5kZW50ID0gbGluZV9jb250ZW50WzogbGVuKGxpbmVfY29udGVudCkgLSBs"
    "ZW4obGluZV9jb250ZW50LmxzdHJpcCgpKV0KICAgICAgICB3YXJuaW5nID0gKAogICAgICAgICAg"
    "ICBmIntpbmRlbnR9IyBTRUNVUklUWSAoQXBleDogd2VhayBoYXNoIGZvciBzZWN1cml0eSDigJQg"
    "dXNlIGhhc2hsaWIuc2hhMjU2KCksICIKICAgICAgICAgICAgZiJvciBwYXNzIHVzZWRmb3JzZWN1"
    "cml0eT1GYWxzZSBpZiB0aGlzIGlzbid0IHNlY3VyaXR5LXJlbGF0ZWQpXG4iCiAgICAgICAgKQog"
    "ICAgICAgIG5ld19saW5lcyA9IGxpc3QobGluZXMpCiAgICAgICAgbmV3X2xpbmVzLmluc2VydChs"
    "aW5lbm8gLSAxLCB3YXJuaW5nKQogICAgICAgIHJldHVybiBTZW1hbnRpY1BhdGNoUmVzdWx0KAog"
    "ICAgICAgICAgICBwYXRjaF9yZXF1ZXN0cz1bewogICAgICAgICAgICAgICAgInBhdGgiOiByZWxf"
    "cGF0aCwKICAgICAgICAgICAgICAgICJuZXdfY29udGVudCI6ICIiLmpvaW4obmV3X2xpbmVzKSwK"
    "ICAgICAgICAgICAgICAgICJleHBlY3RlZF9vbGRfY29udGVudCI6IHNvdXJjZSwKICAgICAgICAg"
    "ICAgfV0sCiAgICAgICAgICAgIHRyYW5zZm9ybV90eXBlPSJmbGFnX3dlYWtfaGFzaCIsCiAgICAg"
    "ICAgICAgIHJhdGlvbmFsZT1bZiJGbGFnZ2VkIHdlYWsgaGFzaGxpYi5tZDUoKS9zaGExKCkgd2l0"
    "aCBhIHNlY3VyaXR5IHdhcm5pbmcgaW4ge3JlbF9wYXRofS4iXSwKICAgICAgICApCiAgICByZXR1"
    "cm4gTm9uZQoKCmRlZiBfcGF0Y2hfbWt0ZW1wKHJlbF9wYXRoOiBzdHIsIHNvdXJjZTogc3RyLCB0"
    "cmVlOiBhc3QuTW9kdWxlKSAtPiBTZW1hbnRpY1BhdGNoUmVzdWx0IHwgTm9uZToKICAgICIiIkZs"
    "YWcgYGB0ZW1wZmlsZS5ta3RlbXAoKWBgIHdpdGggYSBzZWN1cml0eSB3YXJuaW5nIGNvbW1lbnQu"
    "CgogICAgbWt0ZW1wIG9ubHkgcmV0dXJucyBhICpuYW1lKjsgd2hhdGV2ZXIgb3BlbnMgaXQgYWZ0"
    "ZXJ3YXJkcyBpcyBhIFRPQ1RPVSByYWNlLgogICAgVGhlIHNhZmUgcmVwbGFjZW1lbnRzIChta3N0"
    "ZW1wIHJldHVybnMgYW4gb3BlbiBmZDsgTmFtZWRUZW1wb3JhcnlGaWxlIHJldHVybnMKICAgIGEg"
    "ZmlsZSBvYmplY3QpIGhhdmUgZGlmZmVyZW50IHJldHVybiBjb250cmFjdHMsIHNvIHRoZXJlIGlz"
    "IG5vIHNhZmUgZHJvcC1pbgogICAgcmV3cml0ZSDigJQgd2UgYW5ub3RhdGUgdGhlIGNhbGwgc2l0"
    "ZSByYXRoZXIgdGhhbiBzaWxlbnRseSBjaGFuZ2UgYmVoYXZpb3IsCiAgICBleGFjdGx5IGxpa2Ug"
    "dGhlIHBpY2tsZS9TUUwgZmxhZ3MuCiAgICAiIiIKICAgIGZvciBub2RlIGluIGFzdC53YWxrKHRy"
    "ZWUpOgogICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKG5vZGUsIGFzdC5DYWxsKToKICAgICAgICAg"
    "ICAgY29udGludWUKICAgICAgICBmdW5jID0gbm9kZS5mdW5jCiAgICAgICAgaWYgbm90IChpc2lu"
    "c3RhbmNlKGZ1bmMsIGFzdC5BdHRyaWJ1dGUpIGFuZCBmdW5jLmF0dHIgPT0gIm1rdGVtcCIpOgog"
    "ICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlmIG5vdCAoaXNpbnN0YW5jZShmdW5jLnZhbHVl"
    "LCBhc3QuTmFtZSkgYW5kIGZ1bmMudmFsdWUuaWQgPT0gInRlbXBmaWxlIik6CiAgICAgICAgICAg"
    "IGNvbnRpbnVlCgogICAgICAgIGxpbmVubyA9IG5vZGUubGluZW5vCiAgICAgICAgbGluZXMgPSBz"
    "b3VyY2Uuc3BsaXRsaW5lcyhrZWVwZW5kcz1UcnVlKQogICAgICAgIGlmIGxpbmVubyA+IGxlbihs"
    "aW5lcyk6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgbGluZV9jb250ZW50ID0gbGluZXNb"
    "bGluZW5vIC0gMV0KICAgICAgICBwcmV2X2xpbmUgPSBsaW5lc1tsaW5lbm8gLSAyXSBpZiBsaW5l"
    "bm8gPj0gMiBlbHNlICIiCiAgICAgICAgaWYgIkFwZXg6IGluc2VjdXJlIHRlbXAgZmlsZSIgaW4g"
    "bGluZV9jb250ZW50IG9yICJBcGV4OiBpbnNlY3VyZSB0ZW1wIGZpbGUiIGluIHByZXZfbGluZToK"
    "ICAgICAgICAgICAgY29udGludWUgICMgYWxyZWFkeSBmbGFnZ2VkIChjb21tZW50IHNpdHMgb24g"
    "dGhlIHByZWNlZGluZyBsaW5lKQogICAgICAgIGluZGVudCA9IGxpbmVfY29udGVudFs6IGxlbihs"
    "aW5lX2NvbnRlbnQpIC0gbGVuKGxpbmVfY29udGVudC5sc3RyaXAoKSldCiAgICAgICAgd2Fybmlu"
    "ZyA9ICgKICAgICAgICAgICAgZiJ7aW5kZW50fSMgU0VDVVJJVFkgKEFwZXg6IGluc2VjdXJlIHRl"
    "bXAgZmlsZSDigJQgdGVtcGZpbGUubWt0ZW1wKCkgaXMgYSBUT0NUT1UgIgogICAgICAgICAgICBm"
    "InJhY2U7IHVzZSB0ZW1wZmlsZS5ta3N0ZW1wKCkgb3IgTmFtZWRUZW1wb3JhcnlGaWxlKVxuIgog"
    "ICAgICAgICkKICAgICAgICBuZXdfbGluZXMgPSBsaXN0KGxpbmVzKQogICAgICAgIG5ld19saW5l"
    "cy5pbnNlcnQobGluZW5vIC0gMSwgd2FybmluZykKICAgICAgICByZXR1cm4gU2VtYW50aWNQYXRj"
    "aFJlc3VsdCgKICAgICAgICAgICAgcGF0Y2hfcmVxdWVzdHM9W3sKICAgICAgICAgICAgICAgICJw"
    "YXRoIjogcmVsX3BhdGgsCiAgICAgICAgICAgICAgICAibmV3X2NvbnRlbnQiOiAiIi5qb2luKG5l"
    "d19saW5lcyksCiAgICAgICAgICAgICAgICAiZXhwZWN0ZWRfb2xkX2NvbnRlbnQiOiBzb3VyY2Us"
    "CiAgICAgICAgICAgIH1dLAogICAgICAgICAgICB0cmFuc2Zvcm1fdHlwZT0iZmxhZ19pbnNlY3Vy"
    "ZV90ZW1wZmlsZSIsCiAgICAgICAgICAgIHJhdGlvbmFsZT1bZiJGbGFnZ2VkIGluc2VjdXJlIHRl"
    "bXBmaWxlLm1rdGVtcCgpIHdpdGggYSBzZWN1cml0eSB3YXJuaW5nIGluIHtyZWxfcGF0aH0uIl0s"
    "CiAgICAgICAgKQogICAgcmV0dXJuIE5vbmUKCgpkZWYgX3BhdGNoX3lhbWxfbG9hZChyZWxfcGF0"
    "aDogc3RyLCBzb3VyY2U6IHN0ciwgdHJlZTogYXN0Lk1vZHVsZSkgLT4gU2VtYW50aWNQYXRjaFJl"
    "c3VsdCB8IE5vbmU6CiAgICAiIiJSZXdyaXRlIGFuIHVuc2FmZSBgYHlhbWwubG9hZCh4KWBgIGNh"
    "bGwgdG8gYGB5YW1sLnNhZmVfbG9hZCh4KWBgLgoKICAgIFVubGlrZSBwaWNrbGUvU1FMLCB0aGlz"
    "IGhhcyBhIHNhZmUsIHNlbWFudGljYWxseS1lcXVpdmFsZW50IGRyb3AtaW4gZm9yIHRoZQogICAg"
    "Y29tbW9uIGNhc2UgKGxvYWRpbmcgdW50cnVzdGVkIFlBTUwgd2l0aG91dCBjdXN0b20gdGFncyks"
    "IHNvIHdlIHJld3JpdGUgaXQuCiAgICBBIGNhbGwgdGhhdCBhbHJlYWR5IHBhc3NlcyBhbiBleHBs"
    "aWNpdCBgYExvYWRlcj1gYCBpcyBsZWZ0IHVudG91Y2hlZC4KICAgICIiIgogICAgZm9yIG5vZGUg"
    "aW4gYXN0LndhbGsodHJlZSk6CiAgICAgICAgaWYgbm90IGlzaW5zdGFuY2Uobm9kZSwgYXN0LkNh"
    "bGwpOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGZ1bmMgPSBub2RlLmZ1bmMKICAgICAg"
    "ICBpZiBub3QgKGlzaW5zdGFuY2UoZnVuYywgYXN0LkF0dHJpYnV0ZSkgYW5kIGZ1bmMuYXR0ciA9"
    "PSAibG9hZCIpOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlmIG5vdCAoaXNpbnN0YW5j"
    "ZShmdW5jLnZhbHVlLCBhc3QuTmFtZSkgYW5kIGZ1bmMudmFsdWUuaWQgPT0gInlhbWwiKToKICAg"
    "ICAgICAgICAgY29udGludWUKICAgICAgICAjIFJlc3BlY3QgYW4gZXhwbGljaXQgTG9hZGVyPS4u"
    "LiAoY2FsbGVyIGFscmVhZHkgY2hvc2UgYSBsb2FkZXIpLgogICAgICAgIGlmIGFueShrdy5hcmcg"
    "PT0gIkxvYWRlciIgZm9yIGt3IGluIG5vZGUua2V5d29yZHMpOgogICAgICAgICAgICBjb250aW51"
    "ZQoKICAgICAgICBsaW5lbm8gPSBub2RlLmxpbmVubwogICAgICAgIGxpbmVzID0gc291cmNlLnNw"
    "bGl0bGluZXMoa2VlcGVuZHM9VHJ1ZSkKICAgICAgICBpZiBsaW5lbm8gPiBsZW4obGluZXMpOgog"
    "ICAgICAgICAgICBjb250aW51ZQogICAgICAgIGxpbmVfY29udGVudCA9IGxpbmVzW2xpbmVubyAt"
    "IDFdCiAgICAgICAgbmV3X2xpbmUgPSBsaW5lX2NvbnRlbnQucmVwbGFjZSgieWFtbC5sb2FkKCIs"
    "ICJ5YW1sLnNhZmVfbG9hZCgiKQogICAgICAgIGlmIG5ld19saW5lID09IGxpbmVfY29udGVudDoK"
    "ICAgICAgICAgICAgY29udGludWUKICAgICAgICBuZXdfbGluZXMgPSBsaXN0KGxpbmVzKQogICAg"
    "ICAgIG5ld19saW5lc1tsaW5lbm8gLSAxXSA9IG5ld19saW5lCiAgICAgICAgcmV0dXJuIFNlbWFu"
    "dGljUGF0Y2hSZXN1bHQoCiAgICAgICAgICAgIHBhdGNoX3JlcXVlc3RzPVt7CiAgICAgICAgICAg"
    "ICAgICAicGF0aCI6IHJlbF9wYXRoLAogICAgICAgICAgICAgICAgIm5ld19jb250ZW50IjogIiIu"
    "am9pbihuZXdfbGluZXMpLAogICAgICAgICAgICAgICAgImV4cGVjdGVkX29sZF9jb250ZW50Ijog"
    "c291cmNlLAogICAgICAgICAgICB9XSwKICAgICAgICAgICAgdHJhbnNmb3JtX3R5cGU9InlhbWxf"
    "bG9hZF90b19zYWZlX2xvYWQiLAogICAgICAgICAgICByYXRpb25hbGU9W2YiUmVwbGFjZWQgdW5z"
    "YWZlIHlhbWwubG9hZCgpIHdpdGggeWFtbC5zYWZlX2xvYWQoKSBpbiB7cmVsX3BhdGh9LiJdLAog"
    "ICAgICAgICkKICAgIHJldHVybiBOb25lCgoKZGVmIF9wYXRjaF9zcWxfaW5qZWN0aW9uKHJlbF9w"
    "YXRoOiBzdHIsIHNvdXJjZTogc3RyLCB0cmVlOiBhc3QuTW9kdWxlKSAtPiBTZW1hbnRpY1BhdGNo"
    "UmVzdWx0IHwgTm9uZToKICAgICIiIkZsYWcgYW4gZi1zdHJpbmcgcGFzc2VkIHRvIC5leGVjdXRl"
    "KCkvLmN1cnNvcigpIGFzIGEgU1FMLWluamVjdGlvbiByaXNrLgoKICAgIEEgY29ycmVjdCByZXdy"
    "aXRlIG5lZWRzIHRvIGV4dHJhY3QgdGhlIGludGVycG9sYXRlZCB2YWx1ZXMgaW50byBib3VuZAog"
    "ICAgcGFyYW1ldGVycywgd2hpY2ggY2FuJ3QgYmUgZG9uZSBzYWZlbHkgd2l0aG91dCB1bmRlcnN0"
    "YW5kaW5nIHRoZSBxdWVyeSwgc28KICAgIHdlIGFubm90YXRlIHRoZSBjYWxsIHNpdGUgcmF0aGVy"
    "IHRoYW4gcmV3cml0ZSBpdC4KICAgICIiIgogICAgZm9yIG5vZGUgaW4gYXN0LndhbGsodHJlZSk6"
    "CiAgICAgICAgaWYgbm90IGlzaW5zdGFuY2Uobm9kZSwgYXN0LkNhbGwpOgogICAgICAgICAgICBj"
    "b250aW51ZQogICAgICAgIGZ1bmMgPSBub2RlLmZ1bmMKICAgICAgICBuYW1lID0gZnVuYy5hdHRy"
    "IGlmIGlzaW5zdGFuY2UoZnVuYywgYXN0LkF0dHJpYnV0ZSkgZWxzZSBnZXRhdHRyKGZ1bmMsICJp"
    "ZCIsICIiKQogICAgICAgIGlmIG5hbWUgbm90IGluICgiZXhlY3V0ZSIsICJjdXJzb3IiLCAiZXhl"
    "Y3V0ZW1hbnkiKToKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpZiBub3QgYW55KGlzaW5z"
    "dGFuY2UoYSwgYXN0LkpvaW5lZFN0cikgZm9yIGEgaW4gbm9kZS5hcmdzKToKICAgICAgICAgICAg"
    "Y29udGludWUKCiAgICAgICAgbGluZW5vID0gbm9kZS5saW5lbm8KICAgICAgICBsaW5lcyA9IHNv"
    "dXJjZS5zcGxpdGxpbmVzKGtlZXBlbmRzPVRydWUpCiAgICAgICAgaWYgbGluZW5vID4gbGVuKGxp"
    "bmVzKToKICAgICAgICAgICAgY29udGludWUKICAgICAgICBsaW5lX2NvbnRlbnQgPSBsaW5lc1ts"
    "aW5lbm8gLSAxXQogICAgICAgIHByZXZfbGluZSA9IGxpbmVzW2xpbmVubyAtIDJdIGlmIGxpbmVu"
    "byA+PSAyIGVsc2UgIiIKICAgICAgICBpZiAiQXBleDogU1FMIGluamVjdGlvbiIgaW4gbGluZV9j"
    "b250ZW50IG9yICJBcGV4OiBTUUwgaW5qZWN0aW9uIiBpbiBwcmV2X2xpbmU6CiAgICAgICAgICAg"
    "IGNvbnRpbnVlICAjIGFscmVhZHkgZmxhZ2dlZCAoY29tbWVudCBzaXRzIG9uIHRoZSBwcmVjZWRp"
    "bmcgbGluZSkKICAgICAgICBpbmRlbnQgPSBsaW5lX2NvbnRlbnRbOiBsZW4obGluZV9jb250ZW50"
    "KSAtIGxlbihsaW5lX2NvbnRlbnQubHN0cmlwKCkpXQogICAgICAgIHdhcm5pbmcgPSAoCiAgICAg"
    "ICAgICAgIGYie2luZGVudH0jIFNFQ1VSSVRZIChBcGV4OiBTUUwgaW5qZWN0aW9uIOKAlCBwYXNz"
    "IHZhbHVlcyBhcyBxdWVyeSAiCiAgICAgICAgICAgIGYicGFyYW1ldGVycywgZS5nLiBleGVjdXRl"
    "KHNxbCwgKGEsIGIpKSwgbm90IGFuIGYtc3RyaW5nKVxuIgogICAgICAgICkKICAgICAgICBuZXdf"
    "bGluZXMgPSBsaXN0KGxpbmVzKQogICAgICAgIG5ld19saW5lcy5pbnNlcnQobGluZW5vIC0gMSwg"
    "d2FybmluZykKICAgICAgICByZXR1cm4gU2VtYW50aWNQYXRjaFJlc3VsdCgKICAgICAgICAgICAg"
    "cGF0Y2hfcmVxdWVzdHM9W3sKICAgICAgICAgICAgICAgICJwYXRoIjogcmVsX3BhdGgsCiAgICAg"
    "ICAgICAgICAgICAibmV3X2NvbnRlbnQiOiAiIi5qb2luKG5ld19saW5lcyksCiAgICAgICAgICAg"
    "ICAgICAiZXhwZWN0ZWRfb2xkX2NvbnRlbnQiOiBzb3VyY2UsCiAgICAgICAgICAgIH1dLAogICAg"
    "ICAgICAgICB0cmFuc2Zvcm1fdHlwZT0iZmxhZ19zcWxfaW5qZWN0aW9uIiwKICAgICAgICAgICAg"
    "cmF0aW9uYWxlPVtmIkZsYWdnZWQgZi1zdHJpbmcgU1FMIHF1ZXJ5IHdpdGggYSBzZWN1cml0eSB3"
    "YXJuaW5nIGluIHtyZWxfcGF0aH0uIl0sCiAgICAgICAgKQogICAgcmV0dXJuIE5vbmUKCgpkZWYg"
    "X3BhdGNoX3BpY2tsZShyZWxfcGF0aDogc3RyLCBzb3VyY2U6IHN0ciwgdHJlZTogYXN0Lk1vZHVs"
    "ZSkgLT4gU2VtYW50aWNQYXRjaFJlc3VsdCB8IE5vbmU6CiAgICAiIiJGbGFnIHBpY2tsZS5sb2Fk"
    "cygpIHdpdGggYSBzZWN1cml0eSB3YXJuaW5nIGNvbW1lbnQuCgogICAgVW5saWtlIGV2YWwvb3Mu"
    "c3lzdGVtLCB0aGVyZSBpcyBubyBzYWZlIGRyb3AtaW4gcmVwbGFjZW1lbnQgKHBpY2tsZSBjYW4K"
    "ICAgIGV4ZWN1dGUgYXJiaXRyYXJ5IGNvZGUgb24gbG9hZCwgYW5kIGpzb24vbXNncGFjayBhcmUg"
    "bm90IHNlbWFudGljYWxseQogICAgZXF1aXZhbGVudCksIHNvIHdlIGFubm90YXRlIHRoZSBjYWxs"
    "IHNpdGUgcmF0aGVyIHRoYW4gc2lsZW50bHkgcmV3cml0aW5nIGl0LgogICAgIiIiCiAgICBmb3Ig"
    "bm9kZSBpbiBhc3Qud2Fsayh0cmVlKToKICAgICAgICBpZiBub3QgaXNpbnN0YW5jZShub2RlLCBh"
    "c3QuQ2FsbCk6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgZnVuYyA9IG5vZGUuZnVuYwog"
    "ICAgICAgIGlmIG5vdCAoaXNpbnN0YW5jZShmdW5jLCBhc3QuQXR0cmlidXRlKSBhbmQgZnVuYy5h"
    "dHRyID09ICJsb2FkcyIpOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlmIG5vdCAoaXNp"
    "bnN0YW5jZShmdW5jLnZhbHVlLCBhc3QuTmFtZSkgYW5kIGZ1bmMudmFsdWUuaWQgPT0gInBpY2ts"
    "ZSIpOgogICAgICAgICAgICBjb250aW51ZQoKICAgICAgICBsaW5lbm8gPSBub2RlLmxpbmVubwog"
    "ICAgICAgIGxpbmVzID0gc291cmNlLnNwbGl0bGluZXMoa2VlcGVuZHM9VHJ1ZSkKICAgICAgICBp"
    "ZiBsaW5lbm8gPiBsZW4obGluZXMpOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGxpbmVf"
    "Y29udGVudCA9IGxpbmVzW2xpbmVubyAtIDFdCiAgICAgICAgcHJldl9saW5lID0gbGluZXNbbGlu"
    "ZW5vIC0gMl0gaWYgbGluZW5vID49IDIgZWxzZSAiIgogICAgICAgIGlmICJBcGV4OiB1bnRydXN0"
    "ZWQgcGlja2xlIiBpbiBsaW5lX2NvbnRlbnQgb3IgIkFwZXg6IHVudHJ1c3RlZCBwaWNrbGUiIGlu"
    "IHByZXZfbGluZToKICAgICAgICAgICAgY29udGludWUgICMgYWxyZWFkeSBmbGFnZ2VkIChjb21t"
    "ZW50IHNpdHMgb24gdGhlIHByZWNlZGluZyBsaW5lKQogICAgICAgIGluZGVudCA9IGxpbmVfY29u"
    "dGVudFs6IGxlbihsaW5lX2NvbnRlbnQpIC0gbGVuKGxpbmVfY29udGVudC5sc3RyaXAoKSldCiAg"
    "ICAgICAgd2FybmluZyA9ICgKICAgICAgICAgICAgZiJ7aW5kZW50fSMgU0VDVVJJVFkgKEFwZXg6"
    "IHVudHJ1c3RlZCBwaWNrbGUubG9hZHMgY2FuIGV4ZWN1dGUgIgogICAgICAgICAgICBmImFyYml0"
    "cmFyeSBjb2RlOyB2YWxpZGF0ZSB0aGUgc291cmNlIG9yIHVzZSBqc29uL21zZ3BhY2spXG4iCiAg"
    "ICAgICAgKQogICAgICAgIG5ld19saW5lcyA9IGxpc3QobGluZXMpCiAgICAgICAgbmV3X2xpbmVz"
    "Lmluc2VydChsaW5lbm8gLSAxLCB3YXJuaW5nKQogICAgICAgIHJldHVybiBTZW1hbnRpY1BhdGNo"
    "UmVzdWx0KAogICAgICAgICAgICBwYXRjaF9yZXF1ZXN0cz1bewogICAgICAgICAgICAgICAgInBh"
    "dGgiOiByZWxfcGF0aCwKICAgICAgICAgICAgICAgICJuZXdfY29udGVudCI6ICIiLmpvaW4obmV3"
    "X2xpbmVzKSwKICAgICAgICAgICAgICAgICJleHBlY3RlZF9vbGRfY29udGVudCI6IHNvdXJjZSwK"
    "ICAgICAgICAgICAgfV0sCiAgICAgICAgICAgIHRyYW5zZm9ybV90eXBlPSJmbGFnX3BpY2tsZV9s"
    "b2FkcyIsCiAgICAgICAgICAgIHJhdGlvbmFsZT1bZiJGbGFnZ2VkIHVuc2FmZSBwaWNrbGUubG9h"
    "ZHMoKSB3aXRoIGEgc2VjdXJpdHkgd2FybmluZyBpbiB7cmVsX3BhdGh9LiJdLAogICAgICAgICkK"
    "ICAgIHJldHVybiBOb25lCgoKZGVmIF9wYXRjaF9ldmFsKHJlbF9wYXRoOiBzdHIsIHNvdXJjZTog"
    "c3RyLCB0cmVlOiBhc3QuTW9kdWxlKSAtPiBTZW1hbnRpY1BhdGNoUmVzdWx0IHwgTm9uZToKICAg"
    "IGZvciBub2RlIGluIGFzdC53YWxrKHRyZWUpOgogICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKG5v"
    "ZGUsIGFzdC5DYWxsKToKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpZiBub3QgaXNpbnN0"
    "YW5jZShub2RlLmZ1bmMsIGFzdC5OYW1lKToKICAgICAgICAgICAgY29udGludWUKICAgICAgICBp"
    "ZiBub2RlLmZ1bmMuaWQgIT0gImV2YWwiOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlm"
    "IG5vdCBub2RlLmFyZ3M6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgYXJnX25vZGUgPSBu"
    "b2RlLmFyZ3NbMF0KICAgICAgICAjIEFuIGYtc3RyaW5nIGFyZ3VtZW50IGlzIG5ldmVyIGEgUHl0"
    "aG9uIGxpdGVyYWwsIHNvIG5hcnJvd2luZwogICAgICAgICMgZXZhbChmIi4uLiIpIHRvIGFzdC5s"
    "aXRlcmFsX2V2YWwoZiIuLi4iKSB3b3VsZCBhbHdheXMgY3Jhc2gg4oCUIGRlY2xpbmUuCiAgICAg"
    "ICAgaWYgaXNpbnN0YW5jZShhcmdfbm9kZSwgYXN0LkpvaW5lZFN0cik6CiAgICAgICAgICAgIGNv"
    "bnRpbnVlCiAgICAgICAgIyBBIHN0cmluZy1saXRlcmFsIGFyZ3VtZW50IGlzIG9ubHkgc2FmZSB0"
    "byBuYXJyb3cgdG8gYXN0LmxpdGVyYWxfZXZhbAogICAgICAgICMgaWYgdGhlIHN0cmluZyBpdHNl"
    "bGYgaXMgYSBQeXRob24gbGl0ZXJhbC4gZXZhbCgiYSAqIGIiKSAvCiAgICAgICAgIyBldmFsKCJh"
    "Y2NbJ3gnXSIpIGFyZSBydW50aW1lICpleHByZXNzaW9ucyogdGhhdCBsaXRlcmFsX2V2YWwgcmFp"
    "c2VzIG9uLAogICAgICAgICMgc28gcmV3cml0aW5nIHRoZW0gd291bGQgc2hpcCBjb2RlIHRoYXQg"
    "Y3Jhc2hlcyDigJQgbGVhdmUgdGhlbSBmb3IgYSBodW1hbi4KICAgICAgICBpZiBpc2luc3RhbmNl"
    "KGFyZ19ub2RlLCBhc3QuQ29uc3RhbnQpIGFuZCBpc2luc3RhbmNlKGFyZ19ub2RlLnZhbHVlLCBz"
    "dHIpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBhc3QubGl0ZXJhbF9ldmFsKGFy"
    "Z19ub2RlLnZhbHVlKQogICAgICAgICAgICBleGNlcHQgKFZhbHVlRXJyb3IsIFN5bnRheEVycm9y"
    "LCBUeXBlRXJyb3IpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICBhcmdfc291cmNl"
    "ID0gX2dldF9hcmdfc291cmNlKGFyZ19ub2RlLCBzb3VyY2UpCiAgICAgICAgaWYgbm90IGFyZ19z"
    "b3VyY2U6CiAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgIGxpbmVubyA9IG5vZGUubGluZW5v"
    "CiAgICAgICAgbGluZXMgPSBzb3VyY2Uuc3BsaXRsaW5lcyhrZWVwZW5kcz1UcnVlKQogICAgICAg"
    "IGxpbmVfY29udGVudCA9IGxpbmVzW2xpbmVubyAtIDFdIGlmIGxpbmVubyA8PSBsZW4obGluZXMp"
    "IGVsc2UgIiIKICAgICAgICBfZ2V0X2luZGVudChsaW5lX2NvbnRlbnQpCgogICAgICAgIGlmIGFy"
    "Z19zb3VyY2Uuc3RhcnRzd2l0aCgoImFzdC5saXRlcmFsX2V2YWwoIiwgImpzb24ubG9hZHMoIikp"
    "OgogICAgICAgICAgICByZXR1cm4gTm9uZQoKICAgICAgICBuZXdfbGluZSA9IGxpbmVfY29udGVu"
    "dC5yZXBsYWNlKGYiZXZhbCh7YXJnX3NvdXJjZX0pIiwgZiJhc3QubGl0ZXJhbF9ldmFsKHthcmdf"
    "c291cmNlfSkiKQogICAgICAgIGlmIG5ld19saW5lID09IGxpbmVfY29udGVudDoKICAgICAgICAg"
    "ICAgIyBUaGUgYXJndW1lbnQgc291cmNlIGRpZG4ndCBtYXRjaCB0aGUgbGluZSB2ZXJiYXRpbSAo"
    "ZS5nLiBhIHN0cmluZwogICAgICAgICAgICAjIGxpdGVyYWwgdGhhdCBpc24ndCBhIFB5dGhvbiBs"
    "aXRlcmFsKS4gRG9uJ3QgZW1pdCBhIG5vLW9wIHBhdGNoIHRoYXQKICAgICAgICAgICAgIyB3b3Vs"
    "ZCBhZGQgYSBzcHVyaW91cywgdW51c2VkIGBpbXBvcnQgYXN0YDsgdHJ5IHRoZSBuZXh0IGV2YWwu"
    "CiAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgIG5ld19saW5lcyA9IGxpc3QobGluZXMpCiAg"
    "ICAgICAgbmV3X2xpbmVzW2xpbmVubyAtIDFdID0gbmV3X2xpbmUKCiAgICAgICAgaW1wb3J0X25l"
    "ZWRlZCA9ICJpbXBvcnQgYXN0IiBub3QgaW4gc291cmNlCiAgICAgICAgaWYgaW1wb3J0X25lZWRl"
    "ZDoKICAgICAgICAgICAgbmV3X2xpbmVzLmluc2VydChpbXBvcnRfaW5zZXJ0X2luZGV4KHRyZWUp"
    "LCAiaW1wb3J0IGFzdFxuIikKCiAgICAgICAgcmV0dXJuIFNlbWFudGljUGF0Y2hSZXN1bHQoCiAg"
    "ICAgICAgICAgIHBhdGNoX3JlcXVlc3RzPVt7CiAgICAgICAgICAgICAgICAicGF0aCI6IHJlbF9w"
    "YXRoLAogICAgICAgICAgICAgICAgIm5ld19jb250ZW50IjogIiIuam9pbihuZXdfbGluZXMpLAog"
    "ICAgICAgICAgICAgICAgImV4cGVjdGVkX29sZF9jb250ZW50Ijogc291cmNlLAogICAgICAgICAg"
    "ICB9XSwKICAgICAgICAgICAgdHJhbnNmb3JtX3R5cGU9ImV2YWxfdG9fbGl0ZXJhbF9ldmFsIiwK"
    "ICAgICAgICAgICAgcmF0aW9uYWxlPVtmIlJlcGxhY2VkIGV2YWwoKSB3aXRoIGFzdC5saXRlcmFs"
    "X2V2YWwoKSBmb3Igc2FmZXR5IGluIHtyZWxfcGF0aH0uIl0sCiAgICAgICAgKQoKICAgIHJldHVy"
    "biBOb25lCgoKZGVmIF9wYXRjaF9vc19zeXN0ZW0ocmVsX3BhdGg6IHN0ciwgc291cmNlOiBzdHIs"
    "IHRyZWU6IGFzdC5Nb2R1bGUpIC0+IFNlbWFudGljUGF0Y2hSZXN1bHQgfCBOb25lOgogICAgZm9y"
    "IG5vZGUgaW4gYXN0LndhbGsodHJlZSk6CiAgICAgICAgaWYgbm90IGlzaW5zdGFuY2Uobm9kZSwg"
    "YXN0LkNhbGwpOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlmIG5vdCBpc2luc3RhbmNl"
    "KG5vZGUuZnVuYywgYXN0LkF0dHJpYnV0ZSk6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAg"
    "aWYgbm90IGlzaW5zdGFuY2Uobm9kZS5mdW5jLnZhbHVlLCBhc3QuTmFtZSk6CiAgICAgICAgICAg"
    "IGNvbnRpbnVlCiAgICAgICAgaWYgbm9kZS5mdW5jLnZhbHVlLmlkICE9ICJvcyI6CiAgICAgICAg"
    "ICAgIGNvbnRpbnVlCiAgICAgICAgaWYgbm9kZS5mdW5jLmF0dHIgIT0gInN5c3RlbSI6CiAgICAg"
    "ICAgICAgIGNvbnRpbnVlCgogICAgICAgIGlmIG5vdCBub2RlLmFyZ3M6CiAgICAgICAgICAgIGNv"
    "bnRpbnVlCiAgICAgICAgYXJnX3NvdXJjZSA9IF9nZXRfYXJnX3NvdXJjZShub2RlLmFyZ3NbMF0s"
    "IHNvdXJjZSkKICAgICAgICBpZiBub3QgYXJnX3NvdXJjZToKICAgICAgICAgICAgY29udGludWUK"
    "CiAgICAgICAgbGluZW5vID0gbm9kZS5saW5lbm8KICAgICAgICBsaW5lcyA9IHNvdXJjZS5zcGxp"
    "dGxpbmVzKGtlZXBlbmRzPVRydWUpCiAgICAgICAgbGluZV9jb250ZW50ID0gbGluZXNbbGluZW5v"
    "IC0gMV0gaWYgbGluZW5vIDw9IGxlbihsaW5lcykgZWxzZSAiIgogICAgICAgIF9nZXRfaW5kZW50"
    "KGxpbmVfY29udGVudCkKCiAgICAgICAgIyBvcy5zeXN0ZW0gcnVucyBpdHMgYXJndW1lbnQgdGhy"
    "b3VnaCBhIHNoZWxsLCB3aGljaCBUT0tFTklTRVMgaXQuIFRoZQogICAgICAgICMgZXF1aXZhbGVu"
    "dCBzaGVsbC1mcmVlIGNhbGwgbXVzdCBzcGxpdCB0aGUgY29tbWFuZCB0aGUgc2FtZSB3YXksIHNv"
    "IHdlCiAgICAgICAgIyB1c2Ugc2hsZXguc3BsaXQg4oCUIHdyYXBwaW5nIHRoZSB3aG9sZSBzdHJp"
    "bmcgaW4gYSBvbmUtZWxlbWVudCBsaXN0CiAgICAgICAgIyAoc3VicHJvY2Vzcy5ydW4oW2NtZF0s"
    "IHNoZWxsPUZhbHNlKSkgd291bGQgc2VlayBhIHNpbmdsZSBleGVjdXRhYmxlCiAgICAgICAgIyBs"
    "aXRlcmFsbHkgbmFtZWQgZS5nLiAibHMgLWxhIiBhbmQgZmFpbCBhdCBydW50aW1lLgogICAgICAg"
    "IG5ld19saW5lID0gbGluZV9jb250ZW50LnJlcGxhY2UoCiAgICAgICAgICAgIGYib3Muc3lzdGVt"
    "KHthcmdfc291cmNlfSkiLAogICAgICAgICAgICBmInN1YnByb2Nlc3MucnVuKHNobGV4LnNwbGl0"
    "KHthcmdfc291cmNlfSksIGNoZWNrPVRydWUpIgogICAgICAgICkKCiAgICAgICAgbmV3X2xpbmVz"
    "ID0gbGlzdChsaW5lcykKICAgICAgICBuZXdfbGluZXNbbGluZW5vIC0gMV0gPSBuZXdfbGluZQoK"
    "ICAgICAgICBuZWVkc19zdWJwcm9jZXNzID0gImltcG9ydCBzdWJwcm9jZXNzIiBub3QgaW4gc291"
    "cmNlCiAgICAgICAgbmVlZHNfc2hsZXggPSAiaW1wb3J0IHNobGV4IiBub3QgaW4gc291cmNlCiAg"
    "ICAgICAgYXQgPSBpbXBvcnRfaW5zZXJ0X2luZGV4KHRyZWUpCiAgICAgICAgaWYgbmVlZHNfc2hs"
    "ZXg6CiAgICAgICAgICAgIG5ld19saW5lcy5pbnNlcnQoYXQsICJpbXBvcnQgc2hsZXhcbiIpCiAg"
    "ICAgICAgaWYgbmVlZHNfc3VicHJvY2VzczoKICAgICAgICAgICAgbmV3X2xpbmVzLmluc2VydChh"
    "dCwgImltcG9ydCBzdWJwcm9jZXNzXG4iKQoKICAgICAgICByZXR1cm4gU2VtYW50aWNQYXRjaFJl"
    "c3VsdCgKICAgICAgICAgICAgcGF0Y2hfcmVxdWVzdHM9W3sKICAgICAgICAgICAgICAgICJwYXRo"
    "IjogcmVsX3BhdGgsCiAgICAgICAgICAgICAgICAibmV3X2NvbnRlbnQiOiAiIi5qb2luKG5ld19s"
    "aW5lcyksCiAgICAgICAgICAgICAgICAiZXhwZWN0ZWRfb2xkX2NvbnRlbnQiOiBzb3VyY2UsCiAg"
    "ICAgICAgICAgIH1dLAogICAgICAgICAgICB0cmFuc2Zvcm1fdHlwZT0ib3Nfc3lzdGVtX3RvX3N1"
    "YnByb2Nlc3MiLAogICAgICAgICAgICByYXRpb25hbGU9W2YiUmVwbGFjZWQgb3Muc3lzdGVtKCkg"
    "d2l0aCBzdWJwcm9jZXNzLnJ1bigpIGZvciBzYWZldHkgaW4ge3JlbF9wYXRofS4iXSwKICAgICAg"
    "ICApCgogICAgcmV0dXJuIE5vbmUKCgpkZWYgX3BhdGNoX2Jhc2VfZXhjZXB0aW9uKHJlbF9wYXRo"
    "OiBzdHIsIHNvdXJjZTogc3RyLCB0cmVlOiBhc3QuTW9kdWxlKSAtPiBTZW1hbnRpY1BhdGNoUmVz"
    "dWx0IHwgTm9uZToKICAgICIiIk5hcnJvdyBgYGV4Y2VwdCBCYXNlRXhjZXB0aW9uOmBgIHRvIGBg"
    "ZXhjZXB0IEV4Y2VwdGlvbjpgYC4KCiAgICBPbmx5IGhhbmRsZXJzIHRoYXQgZG9uJ3QgcmUtcmFp"
    "c2UgYXJlIHJld3JpdHRlbiAoYSBiYXJlIGBgcmFpc2VgYCBtZWFucyB0aGUKICAgIGJyb2FkIGNh"
    "dGNoIGlzIHRoZSBpbnRlbnRpb25hbCBjbGVhbnVwIHBhdHRlcm4pIOKAlCBtaXJyb3JpbmcgdGhl"
    "IGRldGVjdG9yLgogICAgIiIiCiAgICBmcm9tIGFwcC5lbmdpbmUuZGV0ZWN0b3JzIGltcG9ydCBf"
    "ZXhjX25hbWVzLCBfcmVyYWlzZXMKCiAgICBmb3Igbm9kZSBpbiBhc3Qud2Fsayh0cmVlKToKICAg"
    "ICAgICBpZiBub3QgaXNpbnN0YW5jZShub2RlLCBhc3QuRXhjZXB0SGFuZGxlcikgb3Igbm9kZS50"
    "eXBlIGlzIE5vbmU6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgaWYgIkJhc2VFeGNlcHRp"
    "b24iIG5vdCBpbiBfZXhjX25hbWVzKG5vZGUudHlwZSkgb3IgX3JlcmFpc2VzKG5vZGUuYm9keSk6"
    "CiAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgIGxpbmVubyA9IG5vZGUubGluZW5vCiAgICAg"
    "ICAgbGluZXMgPSBzb3VyY2Uuc3BsaXRsaW5lcyhrZWVwZW5kcz1UcnVlKQogICAgICAgIGxpbmVf"
    "Y29udGVudCA9IGxpbmVzW2xpbmVubyAtIDFdIGlmIGxpbmVubyA8PSBsZW4obGluZXMpIGVsc2Ug"
    "IiIKCiAgICAgICAgbmV3X2xpbmUgPSBsaW5lX2NvbnRlbnQucmVwbGFjZSgiQmFzZUV4Y2VwdGlv"
    "biIsICJFeGNlcHRpb24iLCAxKQogICAgICAgIGlmIG5ld19saW5lID09IGxpbmVfY29udGVudDoK"
    "ICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgbmV3X2xpbmVzID0gbGlzdChsaW5lcykKICAg"
    "ICAgICBuZXdfbGluZXNbbGluZW5vIC0gMV0gPSBuZXdfbGluZQoKICAgICAgICByZXR1cm4gU2Vt"
    "YW50aWNQYXRjaFJlc3VsdCgKICAgICAgICAgICAgcGF0Y2hfcmVxdWVzdHM9W3sKICAgICAgICAg"
    "ICAgICAgICJwYXRoIjogcmVsX3BhdGgsCiAgICAgICAgICAgICAgICAibmV3X2NvbnRlbnQiOiAi"
    "Ii5qb2luKG5ld19saW5lcyksCiAgICAgICAgICAgICAgICAiZXhwZWN0ZWRfb2xkX2NvbnRlbnQi"
    "OiBzb3VyY2UsCiAgICAgICAgICAgIH1dLAogICAgICAgICAgICB0cmFuc2Zvcm1fdHlwZT0iYmFz"
    "ZV9leGNlcHRpb25fdG9fZXhjZXB0aW9uIiwKICAgICAgICAgICAgcmF0aW9uYWxlPVsKICAgICAg"
    "ICAgICAgICAgIGYiTmFycm93ZWQgZXhjZXB0IEJhc2VFeGNlcHRpb24gdG8gZXhjZXB0IEV4Y2Vw"
    "dGlvbiBpbiB7cmVsX3BhdGh9ICIKICAgICAgICAgICAgICAgICIod2FzIHN3YWxsb3dpbmcgS2V5"
    "Ym9hcmRJbnRlcnJ1cHQvU3lzdGVtRXhpdCkuIgogICAgICAgICAgICBdLAogICAgICAgICkKCiAg"
    "ICByZXR1cm4gTm9uZQoKCmRlZiBfcGF0Y2hfYmFyZV9leGNlcHQocmVsX3BhdGg6IHN0ciwgc291"
    "cmNlOiBzdHIsIHRyZWU6IGFzdC5Nb2R1bGUpIC0+IFNlbWFudGljUGF0Y2hSZXN1bHQgfCBOb25l"
    "OgogICAgZm9yIG5vZGUgaW4gYXN0LndhbGsodHJlZSk6CiAgICAgICAgaWYgbm90IGlzaW5zdGFu"
    "Y2Uobm9kZSwgYXN0LkV4Y2VwdEhhbmRsZXIpOgogICAgICAgICAgICBjb250aW51ZQogICAgICAg"
    "IGlmIG5vZGUudHlwZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgY29udGludWUKCiAgICAgICAg"
    "bGluZW5vID0gbm9kZS5saW5lbm8KICAgICAgICBsaW5lcyA9IHNvdXJjZS5zcGxpdGxpbmVzKGtl"
    "ZXBlbmRzPVRydWUpCiAgICAgICAgbGluZV9jb250ZW50ID0gbGluZXNbbGluZW5vIC0gMV0gaWYg"
    "bGluZW5vIDw9IGxlbihsaW5lcykgZWxzZSAiIgoKICAgICAgICBuZXdfbGluZSA9IGxpbmVfY29u"
    "dGVudC5yZXBsYWNlKCJleGNlcHQ6IiwgImV4Y2VwdCBFeGNlcHRpb246IikKICAgICAgICBpZiBu"
    "ZXdfbGluZSA9PSBsaW5lX2NvbnRlbnQ6CiAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgIG5l"
    "d19saW5lcyA9IGxpc3QobGluZXMpCiAgICAgICAgbmV3X2xpbmVzW2xpbmVubyAtIDFdID0gbmV3"
    "X2xpbmUKCiAgICAgICAgcmV0dXJuIFNlbWFudGljUGF0Y2hSZXN1bHQoCiAgICAgICAgICAgIHBh"
    "dGNoX3JlcXVlc3RzPVt7CiAgICAgICAgICAgICAgICAicGF0aCI6IHJlbF9wYXRoLAogICAgICAg"
    "ICAgICAgICAgIm5ld19jb250ZW50IjogIiIuam9pbihuZXdfbGluZXMpLAogICAgICAgICAgICAg"
    "ICAgImV4cGVjdGVkX29sZF9jb250ZW50Ijogc291cmNlLAogICAgICAgICAgICB9XSwKICAgICAg"
    "ICAgICAgdHJhbnNmb3JtX3R5cGU9ImJhcmVfZXhjZXB0X3RvX2V4Y2VwdGlvbiIsCiAgICAgICAg"
    "ICAgIHJhdGlvbmFsZT1bZiJSZXBsYWNlZCBiYXJlIGV4Y2VwdCB3aXRoIGV4Y2VwdCBFeGNlcHRp"
    "b24gaW4ge3JlbF9wYXRofS4iXSwKICAgICAgICApCgogICAgcmV0dXJuIE5vbmUKCgpkZWYgX2dl"
    "dF9hcmdfc291cmNlKGFyZ19ub2RlOiBhc3QuZXhwciwgc291cmNlOiBzdHIpIC0+IHN0cjoKICAg"
    "IGlmIGlzaW5zdGFuY2UoYXJnX25vZGUsIGFzdC5OYW1lKToKICAgICAgICByZXR1cm4gYXJnX25v"
    "ZGUuaWQKICAgIGlmIGlzaW5zdGFuY2UoYXJnX25vZGUsIGFzdC5BdHRyaWJ1dGUpOgogICAgICAg"
    "IHJldHVybiBfZ2V0X2FyZ19zb3VyY2UoYXJnX25vZGUudmFsdWUsIHNvdXJjZSkKICAgIGlmIGlz"
    "aW5zdGFuY2UoYXJnX25vZGUsIGFzdC5DYWxsKToKICAgICAgICBzb3VyY2Uuc3BsaXRsaW5lcygp"
    "W2FyZ19ub2RlLmxpbmVubyAtIDFdIGlmIGFyZ19ub2RlLmxpbmVubyA8PSBsZW4oc291cmNlLnNw"
    "bGl0bGluZXMoKSkgZWxzZSAiIgogICAgICAgIHN0YXJ0ID0gYXJnX25vZGUuY29sX29mZnNldAog"
    "ICAgICAgIHN0YXJ0ICsgbGVuKGFzdC51bnBhcnNlKGFyZ19ub2RlKSkKICAgICAgICByZXR1cm4g"
    "YXN0LnVucGFyc2UoYXJnX25vZGUpCiAgICBpZiBpc2luc3RhbmNlKGFyZ19ub2RlLCBhc3QuSm9p"
    "bmVkU3RyKToKICAgICAgICAjIGYtc3RyaW5nOiBleHRyYWN0IHRoZSBleGFjdCBzb3VyY2Ugc28g"
    "dGhlIGxpbmUgcmVwbGFjZW1lbnQgbWF0Y2hlcwogICAgICAgICMgdmVyYmF0aW0gKHJlY29uc3Ry"
    "dWN0aW5nIGl0IGNvdWxkIGNoYW5nZSBxdW90ZS9zcGFjZSBzdHlsZSkuCiAgICAgICAgcmV0dXJu"
    "IGFzdC5nZXRfc291cmNlX3NlZ21lbnQoc291cmNlLCBhcmdfbm9kZSkgb3IgIiIKICAgIGlmIGlz"
    "aW5zdGFuY2UoYXJnX25vZGUsIChhc3QuU3RyLCBhc3QuQ29uc3RhbnQpKToKICAgICAgICBpZiBp"
    "c2luc3RhbmNlKGFyZ19ub2RlLCBhc3QuU3RyKToKICAgICAgICAgICAgcmV0dXJuIHJlcHIoYXJn"
    "X25vZGUucykKICAgICAgICBpZiBpc2luc3RhbmNlKGFyZ19ub2RlLCBhc3QuQ29uc3RhbnQpIGFu"
    "ZCBpc2luc3RhbmNlKGFyZ19ub2RlLnZhbHVlLCBzdHIpOgogICAgICAgICAgICByZXR1cm4gcmVw"
    "cihhcmdfbm9kZS52YWx1ZSkKICAgIHJldHVybiAiIgoKCiMgSXNzdWUta2V5d29yZCAtPiBwYXRj"
    "aGVyIGRpc3BhdGNoLCBpbiB0aGUgU0FNRSBwcmVjZWRlbmNlIG9yZGVyIGFzIHRoZQojIG9yaWdp"
    "bmFsIGlmLWNoYWluIGluIGBgYXBwbHlgYC4gVGhlIGZpcnN0IGdyb3VwIHdob3NlIGtleXdvcmQg"
    "YXBwZWFycyBpbiB0aGUKIyBsb3dlcmNhc2VkIHRpdGxlIHdpbnMuCl9ESVNQQVRDSCA9ICgKICAg"
    "ICgoImV2YWwiLCksIF9wYXRjaF9ldmFsKSwKICAgICgoIm9zLnN5c3RlbSIsKSwgX3BhdGNoX29z"
    "X3N5c3RlbSksCiAgICAoKCJiYXJlIGV4Y2VwdCIsICJiYXJlZXhjZXB0IiksIF9wYXRjaF9iYXJl"
    "X2V4Y2VwdCksCiAgICAoKCJiYXNlLWV4Y2VwdGlvbiIsICJiYXNlZXhjZXB0aW9uIiksIF9wYXRj"
    "aF9iYXNlX2V4Y2VwdGlvbiksCiAgICAoKCJwaWNrbGUiLCksIF9wYXRjaF9waWNrbGUpLAogICAg"
    "KCgic3FsIiwgImluamVjdGlvbiIpLCBfcGF0Y2hfc3FsX2luamVjdGlvbiksCiAgICAoKCJ5YW1s"
    "IiwpLCBfcGF0Y2hfeWFtbF9sb2FkKSwKICAgICgoInRlbXBmaWxlIiwgIm1rdGVtcCIpLCBfcGF0"
    "Y2hfbWt0ZW1wKSwKICAgICgoIndlYWstaGFzaCIsICJoYXNobGliIiksIF9wYXRjaF93ZWFrX2hh"
    "c2gpLAopCg=="
)


def _load_original():
    """Load the pristine snapshot as a submodule so its relative imports work."""
    name = "app.execution.semantic.transforms._orig_security_snapshot"
    code = base64.b64decode(_ORIG_SECURITY_B64.encode()).decode()
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "app.execution.semantic.transforms"
    sys.modules[name] = mod
    exec(compile(code, name.replace(".", "/") + ".py", "exec"), mod.__dict__)
    return mod


_orig = _load_original()


def _result_tuple(result):
    """Normalize a ``SemanticPatchResult | None`` to a comparable tuple."""
    if result is None:
        return None
    return (
        [dict(pr) for pr in result.patch_requests],
        result.transform_type,
        list(result.rationale),
    )


def _direct(patch_fn, source: str):
    tree = ast.parse(source)
    return _result_tuple(patch_fn("app/m.py", source, tree))


# --------------------------------------------------------------------------- #
# Corpus for weak-hash: convertible (flag) + must-NOT-flag.
# --------------------------------------------------------------------------- #

_WEAK_HASH_CORPUS = [
    # canonical flag
    "import hashlib\nh = hashlib.md5(b'x')\n",
    "import hashlib\nh = hashlib.sha1(b'x')\n",
    # indented call site
    "import hashlib\n\n\ndef f(b):\n    return hashlib.md5(b)\n",
    # already flagged on the SAME line
    "import hashlib\nh = hashlib.md5(b'x')  # Apex: weak hash\n",
    # already flagged on the PRECEDING line
    "import hashlib\n# Apex: weak hash here\nh = hashlib.md5(b'x')\n",
    # ---- must NOT flag ----
    # explicit usedforsecurity=False
    "import hashlib\nh = hashlib.md5(b'x', usedforsecurity=False)\n",
    # usedforsecurity=True (a different constant) still flags
    "import hashlib\nh = hashlib.md5(b'x', usedforsecurity=True)\n",
    # not hashlib
    "import other\nh = other.md5(b'x')\n",
    # sha256 (not weak)
    "import hashlib\nh = hashlib.sha256(b'x')\n",
    # bare md5 name, no hashlib attr
    "from hashlib import md5\nh = md5(b'x')\n",
    # no call at all
    "x = 1\ndef f():\n    return x\n",
    # multiple md5 calls (first wins)
    "import hashlib\na = hashlib.md5(b'a')\nb = hashlib.md5(b'b')\n",
    # md5 on first line where lineno >= 2 path for prev_line is ""
    "import hashlib\nhashlib.md5(b'x')\n",
]


# --------------------------------------------------------------------------- #
# Corpus for eval: convertible (rewrite) + must-NOT-rewrite.
# --------------------------------------------------------------------------- #

_EVAL_CORPUS = [
    # name arg
    "x = eval(data)\n",
    # attribute-chain arg
    "x = eval(obj.attr)\n",
    # string literal that IS a python literal
    "x = eval('[1, 2, 3]')\n",
    "x = eval(\"{'a': 1}\")\n",
    "x = eval('42')\n",
    # call arg
    "x = eval(get_data())\n",
    # already ast.literal_eval -> apply returns None (declines whole)
    "import ast\nx = eval(ast.literal_eval(s))\n",
    # already json.loads -> declines
    "import json\nx = eval(json.loads(s))\n",
    # import ast already present (no extra import inserted)
    "import ast\nx = eval(data)\n",
    # ---- must NOT rewrite ----
    # f-string arg
    "x = eval(f'{a}')\n",
    # string literal that is a runtime EXPRESSION, not a literal
    "x = eval('a * b')\n",
    "x = eval(\"acc['x']\")\n",
    # no args
    "x = eval()\n",
    # not a bare eval (attribute)
    "x = mod.eval(data)\n",
    # not eval at all
    "x = compute(data)\n",
    # eval used as a name, not called
    "f = eval\n",
    # multiple evals: first rewritable wins; first is f-string (skip), second name
    "a = eval(f'{x}')\nb = eval(data)\n",
    # eval with file docstring + future import (import insert index path)
    '"""doc."""\nfrom __future__ import annotations\nx = eval(data)\n',
    # nested eval inside expression
    "y = [eval(item) for item in items]\n",
    # no match
    "def f():\n    return 1\n",
]


def test_weak_hash_direct_byte_identical():
    for src in _WEAK_HASH_CORPUS:
        assert _direct(_orig._patch_weak_hash, src) == \
            _direct(live._patch_weak_hash, src), src


def test_weak_hash_apply_byte_identical():
    for src in _WEAK_HASH_CORPUS:
        assert _result_tuple(_orig.apply("app/m.py", src, "weak-hash")) == \
            _result_tuple(live.apply("app/m.py", src, "weak-hash")), src


def test_eval_direct_byte_identical():
    for src in _EVAL_CORPUS:
        assert _direct(_orig._patch_eval, src) == \
            _direct(live._patch_eval, src), src


def test_eval_apply_byte_identical():
    for src in _EVAL_CORPUS:
        assert _result_tuple(_orig.apply("app/m.py", src, "eval")) == \
            _result_tuple(live.apply("app/m.py", src, "eval")), src


def test_snapshot_loaded_distinctly():
    # The embedded snapshot must be the pristine pre-refactor source: it has the
    # monolithic helpers and lacks the new pure helpers introduced by the refactor.
    assert not hasattr(_orig, "_flag_call_site")
    assert not hasattr(_orig, "_eval_arg")
    assert hasattr(live, "_flag_call_site")
    assert hasattr(live, "_eval_arg")
