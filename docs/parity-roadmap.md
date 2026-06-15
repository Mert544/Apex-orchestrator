# Apex — Feature-Parity Gap Analysis & Commercial Roadmap

> **Purpose.** An honest, code-grounded answer to one question: *what do mature
> competitors (SonarQube/SonarCloud, Snyk, Semgrep, CodeClimate, Codacy, Codecov,
> GitHub code scanning / Dependabot) do that Apex does NOT yet do* — and which of
> those gaps are worth closing, in what order, to **surpass** them on Apex's own
> terms.
>
> **Method.** Every "Apex has / partial / not yet" verdict below was cross-checked
> against the actual code in this repository (grep + file reads), not against
> marketing. Where this analysis contradicts an earlier internal note, the code
> wins and the contradiction is called out.
>
> **The wedge (do not break it).** Apex's defensible position is *deterministic,
> offline, zero-token, test-verified-with-rollback* development assistance — see
> `docs/market-positioning.md`. A "gap" that can only be closed by adding an LLM,
> a hosted multi-tenant backend, or a paid third-party data feed is flagged
> explicitly, and in most cases the recommendation is **a deterministic
> alternative** rather than chasing parity by breaking the wedge.

---

## 0. What Apex already has (verified — do not re-list as "missing")

Confirmed present in the codebase (file evidence in parentheses):

- **Health grade** A–F with a numeric score (`app/engine/health_score.py`,
  surfaced by `apex grade` / `apex pulse`).
- **Security findings** — line-level AST detectors: `eval`/`exec`, `os.system`,
  `pickle.loads`, `yaml.load`, `subprocess(shell=True)`, SQL built from f-strings,
  weak hashes, hardcoded-secret heuristics, missing network timeouts, `open`
  without encoding, bare/broad `except`, mutable defaults, identity-literal, etc.
  (`app/engine/detectors.py`).
- **Security-in-context** — `exposure.py` adds **age** (git-blame age of the
  flagged line) and **reach** (can a project entrypoint transitively call the
  enclosing function, via the call graph). This is *reachability*, not taint
  (see §3).
- **Quality/bug findings, duplication, cognitive complexity, dead code**
  (`apex duplication`, `apex deadcode --confirm` with stdlib `trace` runtime
  confirmation, `app/tools/cognitive_complexity.py`).
- **Idea Permutation Engine + roadmap reasoning** — the unique asset: a
  deterministic tree of grounded, traceable development ideas, sequenced into a
  Stabilize→Secure→Evolve→Refine roadmap (`app/engine/idea_permutation.py`,
  `idea_roadmap.py`, `apex ideate` / `apex develop`).
- **Deterministic auto-fix with verification** — ~20+ AST transforms, risk-tiered,
  applied only if the full test suite passes, with automatic rollback and a
  `proof-of-fix.json` evidence artifact (`app/execution/`, `app/engine/proof_of_fix.py`).
- **Coverage linkage & verification strength** — does the green suite actually
  *name the changed function* (`app/engine/verification_strength.py`,
  `app/tools/test_linker.py`); false-green refusal.
- **Dependency analysis** — declared-vs-imported: possibly-unused, undeclared,
  unpinned (`app/engine/dependency_audit.py`, `apex deps`). **Heuristic only — no
  CVE data** in the core path (see §6). (One *optional, non-core* agent limb,
  `DependencyLimb._check_security_issues`, shells out to external `pip audit`
  — `app/agents/limbs/__init__.py:425` — but it is not wired into `apex deps`,
  depends on a third-party tool, and makes a network call, so it is not part of
  the deterministic/offline core.)
- **Dependency/cycle/coupling analysis** — call graph, import cycles, blast
  radius, cross-language co-change (`app/engine/call_graph.py`, `blast_radius.py`,
  `cross_language_coupling.py`).
- **SARIF export** for GitHub code scanning (`app/engine/sarif_export.py`,
  `apex review --sarif`). Plus JSON / Markdown / HTML report output and
  Canvas/Mermaid/reasoning-graph visual exports.
- **Static HTML dashboard** with historical trend panels (`app/reporting/dashboard.py`,
  `city_dashboard.py`).
- **Run-over-run history** persisted as local JSON under `.apex/` (`dev_history.py`,
  `signal_trends.py`, `roadmap_history.py`, `run_comparison.py`, `idea_memory.py`).
- **Deterministic CI quality gate** — `apex gate` with `--min-score`,
  `--max-security`, `--max-bugs`, `--max-out-of-scope`, and a baseline/regression
  mode (`--save-baseline` / `--baseline` / `--tolerance`) (`app/cli_reporting.py`).
- **A minimal LSP server** that *does* exist and emits live diagnostics
  (`app/lsp/server.py`: `initialize`, `didOpen`/`didChange` →
  `textDocument/publishDiagnostics`, `hover`, `documentSymbol`).
- **A composite GitHub Action** + CI workflows that post a sticky PR summary
  comment and upload SARIF to the Security tab (`action.yml`,
  `.github/workflows/apex-ci.yml`, `apex-review.yml`).

### Accuracy corrections to prior internal notes

Two claims circulating in task framing did **not** survive a code check, and the
document treats the code as ground truth:

1. **"New CodeClimate / JUnit / SonarQube exporters" — NOT present.** A repo-wide
   grep finds no CodeClimate JSON, JUnit XML, or SonarQube-format exporter. The
   only finding/report exporters that exist are **SARIF, JSON, Markdown, HTML**
   (plus Canvas/Mermaid visual exports). These three formats are listed below as
   real gaps (§4), not as things Apex already does.
2. **"GitHub exporter" — partially overstated.** Apex integrates with GitHub via
   SARIF upload + a sticky summary comment; it does **not** post per-line inline
   review comments on the diff, and there is no GitHub *App*/bot with installation
   UX. Treated as a partial (§3).

---

## 1. Capability-area scorecard (Apex vs. mature competitors)

Legend: **Yes** = real, shipped, code-backed · **Partial** = exists but shallow or
narrow · **No** = absent.

| Capability area | Apex | Evidence / nuance |
|---|---|---|
| **Multi-language analysis breadth** | **Partial** | Deep AST analysis (detectors, transforms, grade) is **Python-only**. Other languages get *awareness only* — file name, LOC, git churn, convention-based test-presence flag, debt-marker count, py↔non-py co-change (`app/tools/polyglot_facts.py`, `cross_language_coupling.py`). **No issue detection in any non-Python language.** Competitors (Sonar 30+, Semgrep, Snyk Code) analyze many languages with real rules. |
| **Web dashboard** | **Partial** | Self-contained **static HTML** export, generated on demand (`app/reporting/dashboard.py`). No hosted/served web app, no login, no multi-project org view, no shareable persistent URL. Competitors (SonarCloud, Snyk, Codacy) ship a hosted dashboard. |
| **Historical trends** | **Yes** | Run-over-run history in local `.apex/*.json`; trajectory + sparkline panels in the dashboard (`signal_trends.py`, `roadmap_history.py`, `run_comparison.py`). Local-only; no hosted time-series across a team. |
| **PR bot UX** | **Partial** | Sticky PR *summary* comment + SARIF→Security-tab (inline on diff via GitHub's native scanner). **No native per-line review comments** Apex posts itself; no installable GitHub App; no "request changes"/check-run gating beyond the Action's exit code. |
| **IDE plugins** | **Partial** | A real minimal **LSP server exists** (`app/lsp/server.py`, publishes diagnostics + hover). **But** the VS Code extension is a thin CLI wrapper (`vscode-extension/`) with **no LanguageClient wiring** — so today there are **no live in-editor squiggles** for a user. The pieces exist but aren't connected. No JetBrains plugin. |
| **Security rule depth (taint / dataflow)** | **No** (taint) / **Partial** (depth) | All detectors are **single-node / line-level AST patterns**. Grep for `taint`/`dataflow`/`reaching`/`interprocedural` → **zero hits**. `exposure.py` gives call-graph *reachability* (is the sink reachable from an entrypoint), which is valuable but is **not** source→sink taint of untrusted input. Semgrep/Sonar/Snyk Code do interprocedural taint. |
| **Dependency CVE scanning** | **No** (core) | `apex deps` does declared-vs-imported heuristics (unused / undeclared / unpinned) only. Grep for `cve`/`osv`/`ghsa`/`advisory`/`vulnerab` in `dependency_audit.py` → **no vulnerability database**. (An optional agent limb shells out to external `pip audit` — `app/agents/limbs/__init__.py:425` — but it is off the main path, non-deterministic, and network-dependent.) Snyk/Dependabot match installed versions against CVE feeds as a first-class feature. This is the single biggest category Apex lacks in its core. |
| **Quality gates / policy-as-code** | **Partial** | `apex gate` is a real deterministic gate with baseline/regression. **But thresholds are CLI flags only** — there is **no project policy *config file*** that `gate` reads (a `config/policies.yaml` exists but governs the autonomy constitution, not gate conditions). No Sonar-style composable conditions ("fail if new_bugs>0 AND coverage_on_new_code<80%"). |
| **Team analytics** | **No** | No per-developer attribution, no ownership model, no CODEOWNERS parsing, no per-author trend, no cross-repo/org rollup. Git is used only for churn/blame-age signals feeding the idea engine (`git_history.py`, `git_rule_miner.py`). Competitors sell exactly this (Sonar "new code by author", Codacy/Codecov team views). |
| **Integrations marketplace** | **Partial** | A plugin/operator seam + a local marketplace/registry server exist (`app/plugins/marketplace_server.py`, `registry.py`, `apex plugin` / `apex marketplace`). But it's a local registry of Apex operators, **not** a published ecosystem of third-party integrations (Jira, Slack, GitLab, Bitbucket, Azure DevOps connectors) the way mature vendors offer. |

---

## 2. Reading the scorecard: where the real gaps are

Strip the partials down to what *actually blocks a buyer*:

- **Hard "No"s:** taint/dataflow, dependency CVE scanning, team/people analytics,
  CodeClimate/JUnit/SonarQube export formats.
- **"Partial" that hurts at evaluation time:** multi-language depth (Python-only),
  no live IDE squiggles (the LSP isn't wired to the editor), no inline PR review
  comments, gate thresholds not declarable as policy-as-code, dashboard is
  static-export not hosted.
- **"Partial" that is fine to leave as-is:** the static dashboard and the local
  plugin registry are *consistent with the offline wedge* and shouldn't be traded
  for a hosted SaaS unless the company deliberately decides to.

Crucially, **most of the highest-value gaps can be closed deterministically** —
they don't require breaking the LLM-free, offline principle. The few that do
(or that pull toward a hosted multi-tenant SaaS) are flagged in §7.

---

## 3. Detail: security rule depth (taint / dataflow)

**What competitors do:** Semgrep, SonarQube, and Snyk Code track *taint* —
untrusted input (a request param, `argv`, an env var, file/network read) flowing
**through** assignments and function calls **into** a dangerous sink (`eval`,
`subprocess`, SQL `execute`, `os.path` traversal). This is interprocedural and is
what lets them claim "real" vuln detection with lower false positives.

**What Apex does:** purely **local, single-node** pattern detection
(`detectors.py`) — "there is an f-string inside `.execute()`" — plus call-graph
**reachability** in `exposure.py` ("an entrypoint can reach this function in N
calls"). Reachability answers *"does this code run?"*; taint answers *"does
attacker-controlled data reach this sink?"*. They are complementary, and Apex has
the first, not the second.

**Can it stay deterministic?** **Yes — fully.** Taint/dataflow is a classic
*static* analysis; it needs no LLM. Apex already has the call graph and an AST
visitor framework. A **bounded, intraprocedural-first taint pass** (track a small
set of known sources to known sinks within a function, then extend across the
existing call graph) is squarely in the deterministic wedge and would be a
*headline* differentiator: "taint analysis you can replay, offline, zero-token."

---

## 4. Detail: export formats (CodeClimate / JUnit / SonarQube / GitLab)

Confirmed **absent**. These are mechanical, deterministic serializers of findings
Apex already computes — the same shape as the existing `sarif_export.py`:

- **CodeClimate JSON** → unlocks **GitLab Code Quality** (GitLab renders this
  format natively in MR widgets). High leverage for the GitLab half of the market.
- **JUnit XML** → unlocks generic CI test-report panels (Jenkins, GitLab, Azure
  DevOps, CircleCI) so Apex findings show up as "tests".
- **SonarQube generic issue import JSON** → lets Sonar shops ingest Apex findings
  without adopting Apex's UI.

All three are pure functions of `ReviewResult` and stay 100% deterministic/offline.

---

## 5. Detail: IDE plugins (the pieces exist but aren't connected)

This is the cheapest "wow" on the board because **the hard part is already built**:
`app/lsp/server.py` is a working LSP server that returns live diagnostics. The gap
is purely **wiring**: the VS Code extension shells out to the CLI instead of
launching the LSP server over stdio as a `LanguageClient`. Closing this turns
"run a command and read a notification" into "red squiggles as you type" — the
demo every competitor leads with — with **no LLM and no new analysis**.

---

## 6. Detail: dependency CVE scanning (the honest hard case)

**What competitors do:** match the dependency tree against a vulnerability feed
(NVD/CVE, GitHub Advisory/GHSA, OSV) and report "you have `requests 2.19.0`, which
has CVE-XXXX". This is Snyk's and Dependabot's whole pitch.

**What Apex does today:** declared-vs-imported heuristics only in the core
(`apex deps`). The lone CVE touch-point is an *optional* agent limb that shells
out to external `pip audit` (`app/agents/limbs/__init__.py:425`) — not wired into
`apex deps`, dependent on a third-party tool, and network-bound, so it is not part
of the deterministic/offline guarantee and cannot be the answer here.

**Why it's awkward for the wedge:** a *fresh, current* CVE check structurally needs
an **external advisory database**, which means either a network call or shipping a
snapshot that goes stale. Either way it dents "stdlib-only, offline, zero
marginal cost".

**Deterministic alternative (recommended):** ship an **offline, pinned OSV/GHSA
snapshot** that Apex matches against locally. The *match* stays deterministic and
offline (same snapshot → same result, replayable, CI-safe, zero token); only the
*snapshot refresh* touches the network, and it's an explicit, versioned,
opt-in step (`apex deps --refresh-advisories`), clearly dated in output
("advisories as of 2026-05-01"). This preserves the wedge's spirit — reproducible
and air-gappable for a given snapshot — while closing the category buyers ask about
most. Do **not** add a live per-run API call to a SaaS feed as the default; that
breaks air-gappability.

---

## 7. Gaps that conflict with the LLM-free / offline wedge — flagged

| Gap | Why it tempts a wedge violation | Recommendation |
|---|---|---|
| **Dependency CVE scanning** | Fresh advisories want a network/SaaS feed | **Pursue via the deterministic alternative** in §6 (pinned offline snapshot + explicit opt-in refresh). Never a default live API call. |
| **Hosted web dashboard / org SaaS** | A multi-tenant served app implies accounts, a backend, data leaving the machine | **Do NOT pursue as the core.** Keep the static-HTML export (it *is* the offline feature). If hosting is ever wanted, make it an *optional self-hosted* server over local artifacts, off by default. |
| **Team/people analytics across repos** | Pulls toward a central server aggregating many repos | Pursue only the **single-repo, deterministic slice** (author attribution from local `git blame`/`git log`, CODEOWNERS mapping) — that's offline and replayable. Cross-org rollup is a SaaS feature; defer it / keep it self-hosted. |
| **"Creative" security rules / NL fix explanations** | Tempts adding an LLM to phrase findings or invent fixes | **Do NOT.** Deepen *deterministic* taint instead (§3). LLM-drafted text is explicitly deferred in the positioning doc. |
| **Auto-fixing high-risk logic bugs (to match flashy competitor demos)** | Tempts loosening the test-verified-apply guarantee | **Do NOT.** Keep proposal-only for Tier-2; the safety guarantee *is* the product. |

Everything else in the roadmap below is achievable **without touching the wedge**.

---

## 8. Prioritized roadmap (P0 / P1 / P2)

Priority = commercial leverage ÷ wedge risk, with effort as a tiebreaker.
Effort is rough: **S** ≈ days, **M** ≈ 1–2 weeks, **L** ≈ multiple weeks.

### P0 — close first (high commercial leverage, low/zero wedge risk)

| # | Gap to close | Why it matters commercially | Effort | LLM-free / deterministic? |
|---|---|---|---|---|
| P0-1 | **Wire the existing LSP server into the VS Code extension** (live diagnostics as you type) | The single cheapest credibility win — every competitor leads with in-editor squiggles, and Apex already has the server. Removes the "it's just a CLI" objection. | **S–M** | **Yes** — wiring only, no new analysis. |
| P0-2 | **CodeClimate-JSON + JUnit-XML exporters** (and SonarQube generic JSON) | Unlocks the entire **GitLab** market (native Code Quality widget) and generic CI panels with near-zero engineering. Pure serializers of data Apex already has. | **S** | **Yes** — deterministic, like SARIF. |
| P0-3 | **Bounded deterministic taint/dataflow pass** (intraprocedural first, then over the existing call graph) | Moves Apex from "pattern linter" to "real SAST" — and uniquely as a *replayable, offline, zero-token* one. Directly attacks the SQL-injection / command-injection demo that sells competitors. | **L** | **Yes** — classic static analysis; *this is the headline deterministic differentiator.* |
| P0-4 | **Policy-as-code: a `apex gate` config file** (`.apex/gate.yaml`) with composable conditions | "Quality Gate" is the phrase enterprise buyers shop for. Apex has the gate logic; it lacks the declarative, version-controlled policy file that lands in the repo and reviews like code. | **S–M** | **Yes** — reads a local YAML; fully deterministic. |

### P1 — close next (strong leverage, modest wedge nuance)

| # | Gap to close | Why it matters commercially | Effort | LLM-free / deterministic? |
|---|---|---|---|---|
| P1-1 | **Dependency CVE scanning via pinned offline OSV/GHSA snapshot** | The most-requested missing category (Snyk/Dependabot parity), delivered the *air-gappable* way no SaaS scanner can match. | **M–L** | **Yes for the match** — snapshot refresh is explicit/opt-in (see §6). Flagged: keep refresh non-default. |
| P1-2 | **Inline PR review comments** (per-line, via GitHub review API) + a real GitHub App | Turns the PR bot from "summary comment" into the line-level reviewer buyers expect; an installable App removes setup friction. | **M** | **Yes** — posting existing findings; deterministic content. |
| P1-3 | **Single-repo team/author analytics** (attribution via `git blame`/`git log`, CODEOWNERS map; "findings on new code by author") | Sonar's "new code" framing is a top enterprise selling point; the offline single-repo slice is fully in-wedge. | **M** | **Yes** — local git only. (Cross-org rollup deferred — §7.) |
| P1-4 | **Second-language *detectors*** (JS/TS first, regex/structural then tree-sitter), advisory-only, behind the language-plugin seam | Roughly doubles addressable market without diluting the Python safety story (no transforms initially). | **L** | **Yes** — static detectors, no LLM. tree-sitter is an optional dep, not a network/SaaS one. |

### P2 — later (real but lower leverage, or higher wedge tension)

| # | Gap to close | Why it matters commercially | Effort | LLM-free / deterministic? |
|---|---|---|---|---|
| P2-1 | **Optional self-hosted dashboard server** over local artifacts (off by default) | Some teams want a shareable URL; doing it self-hosted preserves the offline guarantee. | **M** | **Yes if self-hosted only** — do not build a multi-tenant SaaS (§7). |
| P2-2 | **Published third-party integrations** (Jira/Slack/GitLab/Azure DevOps connectors) → a real marketplace | Broadens the ecosystem story beyond the local operator registry. | **L** | **Yes** — connectors push existing deterministic output. |
| P2-3 | **JetBrains / IntelliJ plugin** (reuse the LSP server) | Covers the non-VS-Code IDE share once P0-1 proves the LSP path. | **M** | **Yes** — LSP reuse. |
| P2-4 | **Cross-repo / org-level rollup** | Enterprise "portfolio" view. | **L** | **Conflicts** — implies a central server; keep self-hosted, defer (§7). |

---

## 9. The one-paragraph strategy

Do **not** try to out-feature Sonar/Snyk on their turf by adding an LLM or a SaaS
backend — that trades away the only thing they can't copy. Instead, close the gaps
that are *both* commercially expected *and* expressible deterministically:
**wire the IDE (P0-1)**, **emit the export formats the CI ecosystem already speaks
(P0-2)**, **ship the deterministic taint analysis that turns Apex into replayable
SAST (P0-3)**, and **make the quality gate declarative policy-as-code (P0-4)**.
Then close dependency CVEs the air-gappable way (P1-1) and add the inline PR
reviewer + single-repo author analytics (P1-2/3). Each of these makes Apex *look*
like a mature competitor at evaluation time while staying offline, zero-token, and
replayable — i.e. it surpasses them *on the axis only Apex can win on*.
