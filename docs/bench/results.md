# Apex external benchmark — the same rubric on known codebases

_Reproduce: `apex bench --manifest docs/bench/manifest.json` (pinned refs; deterministic engine)._

| Repo | Ref | Files | Grade | Security | Architecture | Testing | Code debt | Correctness |
|---|---|---:|---|---|---|---|---|---|
| click | `8a1b1a33` | 150 | **A+ (97)** | −0 | −0 | −0 | −3 | −0 |
| jinja | `5ef70112` | 107 | **B+ (89)** | −10 | −0 | −1 | −0 | −0 |
| attrs | `89fae830` | 131 | **A (94)** | −4 | −0 | −2 | −0 | −0 |
| httpx | `b5addb64` | 124 | **B- (81)** | −14 | −0 | −5 | −0 | −0 |

_Columns show points lost per component (0 = clean under this rubric)._
_No precision/recall is claimed: real repos carry no ground-truth labels._
